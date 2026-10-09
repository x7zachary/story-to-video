"""Song MV (route B): lyric timing from the song itself.

  python lyrics.py <slug> transcribe     faster-whisper word timestamps of the song -> audio/whisper.json
  python lyrics.py <slug> align          known lyrics (lyrics.txt) matched to those words -> audio/lyrics_aligned.json
  python lyrics.py <slug> subtitles      aligned lyrics -> manifest timeline.subtitles, timeline.total = song length

Inputs in the project folder: the song (manifest "song", relative to the project root) and lyrics.txt (one sung line per
line; "[Verse 1]" style section headers allowed). Whisper on a sung mix mishears characters, but the syllables mostly
survive, so matching is done on toneless pinyin (difflib), not on characters. Lines nothing matched are interpolated
between their neighbours and marked "interp" -- check those by ear. Tempo / beats / sections: run music.py on the song.
"""
import difflib
import json
import os
import re
import subprocess
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

HAN = re.compile(r"[一-鿿]")


def read_lyrics(root):
    sec, out = None, []
    for raw in open(os.path.join(root, "lyrics.txt"), encoding="utf-8"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            sec = line.strip("[]")
            continue
        out.append({"section": sec, "text": line})
    return out


def transcribe(m):
    # faster-whisper imports PyAV only to decode files; we decode with ffmpeg, so a blocked / missing av wheel is fine
    sys.modules.setdefault("av", types.ModuleType("av"))
    from faster_whisper import WhisperModel
    root = m["root"]
    raw = subprocess.check_output([config.FFMPEG, "-v", "error", "-i", os.path.join(root, m["song"]), "-ac", "1", "-ar", "16000",
                                   "-f", "f32le", "-"])
    audio = np.frombuffer(raw, dtype=np.float32)
    first = "".join(l["text"] for l in read_lyrics(root)[:2])
    model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language="zh", initial_prompt=f"以下是普通话歌词。{first}", beam_size=5,
                               word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    res = []
    for s in segs:
        res.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text,
                    "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "text": w.word} for w in s.words]})
        print(f"{s.start:7.2f} {s.end:7.2f} {s.text}", flush=True)
    os.makedirs(os.path.join(root, "audio"), exist_ok=True)
    json.dump(res, open(os.path.join(root, "audio", "whisper.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def whisper_chars(root):
    chars = []
    for seg in json.load(open(os.path.join(root, "audio", "whisper.json"), encoding="utf-8")):
        for w in seg["words"]:
            hz = HAN.findall(w["text"])
            for k, ch in enumerate(hz):        # spread a word's span evenly over its characters
                a = w["start"] + (w["end"] - w["start"]) * k / len(hz)
                b = w["start"] + (w["end"] - w["start"]) * (k + 1) / len(hz)
                chars.append((ch, a, b))
    return chars


def align(m):
    from pypinyin import lazy_pinyin
    root = m["root"]
    lines = read_lyrics(root)
    ref, owner = [], []
    for i, l in enumerate(lines):
        for ch in HAN.findall(l["text"]):
            ref.append(ch)
            owner.append(i)
    hyp = whisper_chars(root)
    sm = difflib.SequenceMatcher(None, lazy_pinyin(ref), lazy_pinyin([c for c, _, _ in hyp]), autojunk=False)
    t = [None] * len(ref)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            t[a + k] = (hyp[b + k][1], hyp[b + k][2])
    for i, l in enumerate(lines):
        idx = [k for k, o in enumerate(owner) if o == i]
        got = [t[k] for k in idx if t[k]]
        l["matched"] = f"{len(got)}/{len(idx)}"
        l["start"] = round(got[0][0], 2) if got else None
        l["end"] = round(got[-1][1], 2) if got else None
    for i, l in enumerate(lines):                  # fill unmatched lines between their neighbours
        if l["start"] is None:
            prev = next((lines[j]["end"] for j in range(i - 1, -1, -1) if lines[j]["end"]), 0)
            nxt = next((lines[j]["start"] for j in range(i + 1, len(lines)) if lines[j]["start"]), prev + 2)
            l["start"], l["end"], l["matched"] = round(prev + 0.1, 2), round(nxt - 0.1, 2), "interp"
    json.dump(lines, open(os.path.join(root, "audio", "lyrics_aligned.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for l in lines:
        print(f"{l['start']:7.2f} {l['end']:7.2f} {l['matched']:>6} [{l['section']}] {l['text']}")
    return lines


def subtitles(m):
    """Aligned lyrics -> manifest timeline (subtitles + total length = the song), for the shared StoryVideo template.
    Shot spans are the storyboard's job (Claude writes them against these times)."""
    root = m["root"]
    lines = json.load(open(os.path.join(root, "audio", "lyrics_aligned.json"), encoding="utf-8"))
    err = subprocess.run([config.FFMPEG, "-i", os.path.join(root, m["song"])], capture_output=True, text=True, errors="replace").stderr
    hh, mm, ss = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    tl = m.setdefault("timeline", {})
    tl["total"] = round(int(hh) * 3600 + int(mm) * 60 + float(ss), 3)
    tl["subtitles"] = [{"text": l["text"], "start": l["start"], "end": l["end"], "speaker": "lyrics"} for l in lines]
    config.save_manifest(m["slug"], m)
    print(f"timeline: {tl['total']} s, {len(lines)} lyric lines ({sum(l['matched'] == 'interp' for l in lines)} interpolated)")


if __name__ == "__main__":
    slug, cmd = sys.argv[1], sys.argv[2]
    man = config.load_manifest(slug)
    {"transcribe": transcribe, "align": align, "subtitles": subtitles}[cmd](man)
