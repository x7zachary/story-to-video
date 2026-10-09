"""Manifest-driven timeline: TTS durations -> segment times, shot spans, subtitle lines, poem/title/endcard, bells.

Ported from the ad-hoc build_timeline.py of the first project (same algorithm, so results are reproducible), plus a
shot-length validator that flags shots which cannot be animated (> WAN_MAX_SECONDS) or drag as stills (> STILL_MAX).
Usage: python timeline.py <slug> [--check-only]
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

PUNCT = "，。？！：；、,.?!:;「」"
DEFAULT_BEFORE, DEFAULT_AFTER, MAX_LINE = 0.3, 0.45, 18


def duration(path):
    raw = subprocess.check_output([config.FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", "48000", "-f", "s16le", "-"])
    return len(raw) / 2 / 48000


def split_lines(text):
    parts = re.findall(r"[^，。？！：；、]+[，。？！：；、]?", text)
    lines = []
    for p in parts:
        if lines and (len(lines[-1].rstrip(PUNCT)) <= 3 or len(p.rstrip(PUNCT)) <= 2) and len(lines[-1]) + len(p) <= MAX_LINE:
            lines[-1] += p
        else:
            lines.append(p)
    return lines


def display(line):
    line = line.rstrip("，。：；、")
    return line.replace("，", "　").replace("、", "・").replace("：", "　").replace("；", "　").replace("。", "　")


def line_times(lines, words, offset):
    res, wi = [], 0
    for line in lines:
        need = len([c for c in line if c not in PUNCT])
        got, first, last = 0, None, None
        while wi < len(words) and got < need:
            w = words[wi]
            first = w["start"] if first is None else first
            last = w["end"]
            got += len([c for c in w["text"] if c not in PUNCT])
            wi += 1
        if first is None:
            first = res[-1][1] if res else 0.0
            last = first + 0.5
        res.append((offset + first, offset + last))
    return res


def build(m):
    root = m["root"]
    shot_by_id = {s["id"]: s for s in m["shots"]}
    t = 0.0
    segments, subtitles, spans, bells, poem, title, endcard = [], [], [], [], None, None, None
    for seg in m["segments"]:
        vis_start = t
        if seg.get("speaker"):
            mp3 = os.path.join(root, "audio", seg["id"] + ".mp3")
            words = json.load(open(os.path.join(root, "audio", seg["id"] + ".words.json"), encoding="utf-8"))
            dur = duration(mp3)
            start = t + seg.get("pause_before", DEFAULT_BEFORE)
            end = start + dur
            t = end + seg.get("pause_after", DEFAULT_AFTER)
            lines = split_lines(seg["text"])
            times = line_times(lines, words, start)
            for i, (line, (a, b)) in enumerate(zip(lines, times)):
                nxt = times[i + 1][0] if i + 1 < len(times) else min(end + 0.35, t)
                item = {"text": display(line), "start": round(a, 3), "end": round(max(b, nxt - 0.05), 3), "speaker": seg["speaker"]}
                if seg.get("poem"):
                    item["text"] = line.rstrip("，。")
                    poem = poem or {"lines": []}
                    poem["lines"].append(item)
                else:
                    subtitles.append(item)
            if seg.get("poem"):
                poem["start"], poem["end"] = vis_start, t
            segments.append({"id": seg["id"], "speaker": seg["speaker"], "file": seg["id"] + ".mp3",
                             "start": round(start, 3), "end": round(end, 3), "text": seg["text"]})
            n = len(seg["shots"])
            cuts = [vis_start]
            for k in range(1, n):
                target = start + dur * k / n
                cands = [a for a, _ in times[1:]] or [target]
                cuts.append(min(cands, key=lambda c: abs(c - target)) - 0.15)
            cuts.append(t)
        else:
            t += seg["hold"]
            cuts = [vis_start, t]
            if seg.get("title"):
                title = {"start": vis_start, "end": t, "title": seg["title"], "subtitle": seg.get("subtitle", "")}
            if seg.get("endcard"):
                endcard = {"start": vis_start, "end": t, "lines": seg["endcard"]}
        for k, sid in enumerate(seg["shots"]):
            a, b = cuts[k], cuts[k + 1]
            if spans and spans[-1]["shot"] == sid and abs(spans[-1]["end"] - a) < 1e-6:
                spans[-1]["end"] = b
            else:
                spans.append({"shot": sid, "start": a, "end": b})
        if seg.get("bell_after"):
            bells.append(round(t - seg.get("pause_after", DEFAULT_AFTER) + 0.1, 3))
    bells.insert(0, 0.4)
    for s in shot_by_id.values():
        s["spans"] = []
    for sp in spans:
        sp["start"], sp["end"] = round(sp["start"], 3), round(sp["end"], 3)
        shot_by_id[sp["shot"]]["spans"].append({"start": sp["start"], "end": sp["end"]})
    m["timeline"] = {"total": round(t, 3), "segments": segments, "subtitles": subtitles, "poem": poem, "title": title,
                     "endcard": endcard, "bells": bells}
    return m


def validate(m):
    """Return planning problems: shots too long to animate (Wan makes ~5 s) or too long as a still."""
    problems = []
    for s in m["shots"]:
        for sp in s["spans"]:
            d = sp["end"] - sp["start"]
            animatable = s["motion_class"] in ("atmosphere", "object", "hands")
            if d > config.STILL_MAX:
                problems.append((s["id"], round(d, 1), f"still too long (> {config.STILL_MAX}s): split into wide + punch-in crop (reuse_of)"))
            elif animatable and d > config.WAN_MAX_SECONDS + 1.0:
                problems.append((s["id"], round(d, 1), f"animatable but > {config.WAN_MAX_SECONDS + 1}s: clip would need 0.5x slow-down; split or shorten"))
    return problems


if __name__ == "__main__":
    slug = sys.argv[1]
    m = config.load_manifest(slug)
    old = json.loads(json.dumps(m["timeline"]))
    m = build(m)
    same = abs(m["timeline"]["total"] - old["total"]) < 0.01
    print(f"total {m['timeline']['total']}s (stored {old['total']}s) {'MATCH' if same else 'DIFFERS'}")
    for pid, d, msg in validate(m):
        print(f"  shot {pid:2d} {d:5.1f}s  {msg}")
    if "--check-only" not in sys.argv:
        config.save_manifest(slug, m)
        print("manifest updated")
