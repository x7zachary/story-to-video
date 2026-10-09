"""Numeric QC for generated Wan clips (no extra model downloads, numpy only).

Signals (on 64x36 RGB thumbnails of every frame):
  motion   median frame-to-frame mean abs diff      -> too low = static clip, wasted budget
  spike    max jump / median jump                   -> temporal glitch / cut / flicker
  drift    mean abs diff between frame i and frame 0 (per frame) -> composition change; also the point where
           the clip has changed "too much" from its keyframe (auto-trim candidate)
  local    largest 8x8-cell change vs frame 0 (max over cells of the cell's mean abs diff) -> something new appears
Layer 2 (semantic) is a 6-frame tile that a reviewer (Claude/human) judges; verdicts are recorded in the manifest.
"""
import json
import math
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

W, H = 64, 36
# Calibrated on 8 clips from 2026-09-29 (good: 0,4,13,17,21; bad: 5 new person, 11 head turn, 6 distortion after ~f90).
# Finding: numeric signals CANNOT catch gradual semantic failures (5, 11) and level-based change metrics
# false-alarm on legitimately fast clips (13, 21). Only a sudden frame-to-frame jump (shot 6: 8.8x median, all
# good clips <= 3.6x) and "clip is static" are reliable, so those are the only automatic rejections/trims.
LIMITS = {"motion_min": 0.25, "trim_ratio": 5.0}   # good clips peaked at 4.0x, the distorted one at 8.8x


def thumbs(mp4):
    raw = subprocess.check_output([config.FFMPEG, "-v", "error", "-i", mp4, "-vf", f"scale={W}:{H}:flags=area",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W, 3).astype(np.float32)


def analyze(mp4):
    t = thumbs(mp4)
    n = len(t)
    step = np.abs(np.diff(t, axis=0)).mean(axis=(1, 2, 3))
    drift = np.abs(t - t[0]).mean(axis=(1, 2, 3))
    # local change: 4x4 grid of cells (9x16 px), largest mean abs diff vs frame 0
    cells = np.abs(t - t[0]).reshape(n, 4, H // 4, 4, W // 4, 3).mean(axis=(2, 4, 5)).reshape(n, 16)
    local = cells.max(axis=1)
    med = float(np.median(step)) + 1e-6
    ratio = step / med
    bad = np.nonzero(ratio > LIMITS["trim_ratio"])[0]
    return {"frames": n, "motion": round(med, 3), "spike": round(float(ratio.max()), 2),
            "glitch_frame": int(bad[0]) + 1 if len(bad) else None,
            "drift_end": round(float(drift[-1]), 2), "local_end": round(float(local[-1]), 2),
            "drift": [round(float(x), 2) for x in drift[::8]], "local": [round(float(x), 2) for x in local[::8]]}





def verdict(m):
    """Layer 1 result: 'fail_numeric' (static), 'partial' (auto-trim at a glitch) or 'needs_review'.
    Every non-failed clip still needs the semantic tile review (layer 2) before it goes into a cut."""
    if m["motion"] < LIMITS["motion_min"]:
        return "fail_numeric", ["too_static"]
    if m["glitch_frame"] is not None:
        return "partial", [f"glitch@{m['glitch_frame']}"]
    return "needs_review", []


def tile(mp4, out_jpg, n=12, cols=4):
    """12 evenly spaced frames in a 4x3 sheet for the semantic review layer. Was 6 until 2026-10-08: with 6 frames
    (~1 s apart) things that pop in or vanish between two samples, and actions that make no sense, were missed."""
    total = len(thumbs(mp4))
    idx = np.linspace(0, total - 1, n).astype(int)
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    subprocess.check_call([config.FFMPEG, "-v", "error", "-y", "-i", mp4, "-vf",
                           f"select='{sel}',scale=480:-1,tile={cols}x{math.ceil(n / cols)}", "-frames:v", "1", out_jpg])
    return out_jpg


def suggest_keep(m, margin=10):
    """Frames to keep: everything before the first sudden jump (minus a safety margin), at least 24."""
    if m["glitch_frame"] is None:
        return m["frames"]
    return max(24, m["glitch_frame"] - margin)


if __name__ == "__main__":
    # python qc.py calibrate <dir-with-mp4s>
    if sys.argv[1] == "calibrate":
        d = sys.argv[2]
        for f in sorted(os.listdir(d)):
            if f.endswith(".mp4"):
                m = analyze(os.path.join(d, f))
                v, r = verdict(m)
                print(f"{f:26s} motion={m['motion']:6.3f} spike={m['spike']:5.1f} drift_end={m['drift_end']:5.1f} "
                      f"local_end={m['local_end']:5.1f} keep~{suggest_keep(m)} -> {v} {r}")
                print("    local:", m["local"])
