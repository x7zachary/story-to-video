"""ASR round trip: transcribe the TTS audio back to text and diff against the script.

Lets us catch mispronunciations without listening (the agent cannot hear audio).
Usage: python asr_check.py <audio_dir> <segments.json> [--model small]
Prints per-segment character error rate and the differing spans; writes asr_report.json next to audio_dir.
"""
import difflib
import json
import os
import re
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import subprocess  # noqa: E402

import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

FFMPEG = config.FFMPEG


def load_audio(path):
    """Decode with our ffmpeg (faster-whisper's own PyAV decoding breaks with the newest av)."""
    raw = subprocess.check_output([FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype=np.float32)

audio_dir, seg_path = sys.argv[1], sys.argv[2]
model_name = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else config.WHISPER_MODEL
segs = json.load(open(seg_path, encoding="utf-8"))["segments"]
# Whisper is asked in Chinese with a simplified-Chinese prompt so it does not output traditional characters.
model = WhisperModel(model_name, device="cpu", compute_type="int8")     # a model name, or a local model folder
norm = lambda s: re.sub(r"[\s，。？！：；、「」（）,.?!:;\"'()·・　]", "", s)
report = []
for seg in segs:
    if not seg.get("speaker"):
        continue
    mp3 = os.path.join(audio_dir, seg["id"] + ".mp3")
    out, _ = model.transcribe(load_audio(mp3), language="zh", initial_prompt="以下是普通话的句子。", beam_size=5)
    hyp = norm("".join(s.text for s in out))
    ref = norm(seg["text"])
    sm = difflib.SequenceMatcher(None, ref, hyp)
    diffs = [(ref[i1:i2], hyp[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
    cer = 1 - sm.ratio()
    report.append({"id": seg["id"], "cer": round(cer, 3), "ref": ref, "hyp": hyp, "diffs": diffs})
    print(f"{seg['id']} cer={cer:.2f} diffs={diffs}", flush=True)
json.dump(report, open(os.path.join(os.path.dirname(audio_dir.rstrip('\\/')), "asr_report.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("mean cer", round(sum(r["cer"] for r in report) / len(report), 3))
