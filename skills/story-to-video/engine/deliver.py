"""Delivery check + normalisation for a finished video. One command instead of hand-run ffmpeg lines.

  python deliver.py <video.mp4> --out <final.mp4> [--sheet overview.jpg] [--frames N | t1,t2,...]
                    [--expect-duration S] [--expect-size 1920x1080] [--target-lufs -16] [--force]

1. probe       duration / resolution / fps / codecs / pixel format / colour range   (this ffmpeg build has no ffprobe)
2. normalise   Remotion writes full-range yuvj420p, which many players show washed out or too contrasty.
               Re-encode to limited-range yuv420p + faststart when needed, otherwise just re-mux.
3. loudness    EBU R128 integrated loudness, loudness range, true peak of the FINAL file
4. sheet       labelled overview of evenly spaced (or chosen) frames, to read the film at a glance
5. report      <out>.report.json next to the file; exit code 1 when any check is an ERROR

Checks: audio stream present; yuv420p limited range after normalising; duration vs --expect-duration (+-0.25 s);
size vs --expect-size; true peak above -1.0 dBFS (ERROR above -0.1); integrated loudness more than 3 LU from --target-lufs (WARN).

Refuses to overwrite --out unless --force. Idea (not code) borrowed from OpenMontage's post-render self-review.
Not checked on purpose: "does the caption fit the frame". Reading that off rendered pixels gives too many false alarms;
caption length is linted at the source instead (lint.py, timeline subtitles).
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

FF = config.FFMPEG


def run_ff(args):
    return subprocess.run([FF, "-hide_banner", "-nostats", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(path):
    """Parse `ffmpeg -i` stderr."""
    out = run_ff(["-i", path]).stderr
    info = {"path": path, "bytes": os.path.getsize(path)}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", out)
    info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    v = re.search(r"Stream #\S+: Video: (\w+)[^\n]*?, (yuv\w+)(?:\(([^)]*)\))?[^\n]*?, (\d{2,5})x(\d{2,5})[^\n]*?(\d+(?:\.\d+)?) fps", out)
    if v:
        tags = (v[3] or "").split(",")
        info.update(vcodec=v[1], pix_fmt=v[2], range=("tv" if "tv" in tags else "pc" if "pc" in tags else None),
                    width=int(v[4]), height=int(v[5]), fps=float(v[6]))
    a = re.search(r"Stream #\S+: Audio: (\w+)[^\n]*?, (\d+) Hz, (\w+)", out)
    info["audio"] = {"codec": a[1], "hz": int(a[2]), "layout": a[3]} if a else None
    return info


def needs_range_fix(info):
    return info.get("pix_fmt") == "yuvj420p" or info.get("range") == "pc" or info.get("pix_fmt") not in ("yuv420p", None)


def normalise(src, dst, info):
    if needs_range_fix(info):
        args = ["-y", "-v", "error", "-i", src, "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p", "-c:v", "libx264",
                "-crf", "17", "-preset", "slow", "-profile:v", "high", "-movflags", "+faststart"]
        mode = "re-encoded (full range -> limited range yuv420p)"
    else:
        args = ["-y", "-v", "error", "-i", src, "-c:v", "copy", "-movflags", "+faststart"]
        mode = "re-muxed (video already limited-range yuv420p)"
    args += ["-c:a", "copy" if (info.get("audio") or {}).get("codec") == "aac" else "aac", dst] if info.get("audio") else [dst]
    r = run_ff(args)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-400:])
    return mode


def loudness(path):
    err = run_ff(["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err[-1500:]
    pick = lambda rx: (lambda m: float(m[1]) if m else None)(re.search(rx, tail))   # noqa: E731
    return {"lufs": pick(r"I:\s+(-?[\d.]+) LUFS"), "lra": pick(r"LRA:\s+(-?[\d.]+) LU"), "true_peak": pick(r"Peak:\s+(-?[\d.]+) dBFS")}


def grab(path, t, width):
    b = subprocess.run([FF, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    from PIL import Image
    return Image.open(io.BytesIO(b)).convert("RGB")


def contact_sheet(path, out, times, width=480, cols=4):
    """Frames at `times` (seconds), each stamped with its time, tiled into one JPEG."""
    from PIL import Image, ImageDraw, ImageFont
    ims = [grab(path, t, width) for t in times]
    h = ims[0].height
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, rows * h), "black")
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for i, (t, im) in enumerate(zip(times, ims)):
        x, y = (i % cols) * width, (i // cols) * h
        sheet.paste(im, (x, y))
        d.rectangle([x, y, x + 84, y + 28], fill=(0, 0, 0))
        d.text((x + 6, y + 2), f"{t:.1f}s", fill=(255, 255, 0), font=font)
    sheet.save(out, quality=88)
    return out


def sheet_times(spec, duration):
    if spec and "," in spec:
        return [float(x) for x in spec.split(",")]
    n = int(spec) if spec else 24
    return [round(duration * (i + 0.5) / n, 2) for i in range(n)]


def check(info, loud, expect_duration, expect_size, target_lufs):
    f = []
    if not info.get("audio"):
        f.append(("ERROR", "no audio stream"))
    if info.get("pix_fmt") != "yuv420p" or info.get("range") == "pc":
        f.append(("ERROR", f"pixel format is {info.get('pix_fmt')} / range {info.get('range')}, expected limited-range yuv420p"))
    if expect_duration is not None and info.get("duration") is not None and abs(info["duration"] - expect_duration) > 0.25:
        f.append(("ERROR", f"duration {info['duration']:.2f}s, expected {expect_duration:.2f}s"))
    if expect_size and (f"{info.get('width')}x{info.get('height')}" != expect_size):
        f.append(("ERROR", f"size {info.get('width')}x{info.get('height')}, expected {expect_size}"))
    tp = loud.get("true_peak")
    if tp is not None and tp > -0.1:
        f.append(("ERROR", f"true peak {tp} dBFS: clipping"))
    elif tp is not None and tp > -1.0:
        f.append(("WARN", f"true peak {tp} dBFS is above -1.0 (lossy encoders can overshoot)"))
    if loud.get("lufs") is not None and target_lufs is not None and abs(loud["lufs"] - target_lufs) > 3:
        f.append(("WARN", f"integrated loudness {loud['lufs']} LUFS, target {target_lufs} +-3"))
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet")
    ap.add_argument("--frames", default="")
    ap.add_argument("--expect-duration", type=float)
    ap.add_argument("--expect-size")
    ap.add_argument("--target-lufs", type=float, default=-16.0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(a.video):
        sys.exit(f"deliver: no such file {a.video}")
    if os.path.exists(a.out) and not a.force:
        sys.exit(f"deliver: {a.out} exists; pass --force to overwrite")
    if os.path.abspath(a.out) == os.path.abspath(a.video):
        sys.exit("deliver: --out must differ from the input")
    src = probe(a.video)
    mode = normalise(a.video, a.out, src)
    info = probe(a.out)
    loud = loudness(a.out)
    findings = check(info, loud, a.expect_duration, a.expect_size, a.target_lufs)
    sheet = contact_sheet(a.out, a.sheet, sheet_times(a.frames, info["duration"])) if a.sheet else None
    rep = {"input": src, "output": info, "normalise": mode, "loudness": loud, "sheet": sheet,
           "findings": [{"level": lv, "msg": m} for lv, m in findings]}
    json.dump(rep, open(a.out + ".report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{a.out}\n  {info.get('width')}x{info.get('height')} @ {info.get('fps')} fps, {info['duration']:.2f}s, {info['bytes'] / 1e6:.1f} MB, "
          f"{info.get('pix_fmt')} ({info.get('range')}), audio {info['audio']}\n  {mode}\n  loudness {loud['lufs']} LUFS, LRA {loud['lra']} LU, "
          f"true peak {loud['true_peak']} dBFS")
    if sheet:
        print(f"  overview sheet: {sheet}")
    for lv, m in findings:
        print(f"  {lv}: {m}")
    print("  OK" if not [x for x in findings if x[0] == "ERROR"] else "  FAILED")
    sys.exit(1 if [x for x in findings if x[0] == "ERROR"] else 0)


if __name__ == "__main__":
    main()
