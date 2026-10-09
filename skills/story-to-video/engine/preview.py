"""Low-res review reel of the whole film with every shot labelled, for the "motion preview" sign-off.

  python preview.py <slug> [out.mp4] [--height 540]

Each span shows the shot's clip if it has one that is not rejected (ok / ok_unreviewed / needs_review), else its keyframe;
a crop (reuse_of) shows its source. Top-left label: shot id, name, clip status, playback speed. ffmpeg only (no Remotion,
no minterpolate), ~1-2 min for a 4-minute film, so the user can watch the motion in context and answer
"shot 12 makes no sense" before anything is finalised. Speed matches render.fit_clip (no slower than MIN_SPEED,
then the last frame holds), so slow-motion problems show up here too.
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import render  # noqa: E402

SHOW = ("ok", "ok_unreviewed", "needs_review")
FONT = r"C\:/Windows/Fonts/msyh.ttc"


def segment(m, s, sp, out, h, tmp):
    root = m["root"]
    src = next(x for x in m["shots"] if x["id"] == s["reuse_of"]) if s.get("reuse_of") is not None else s
    c = src.get("clip") or {}
    dur = sp["end"] - sp["start"]
    w = round(h * m.get("width", 1920) / m.get("height", 1080) / 2) * 2
    fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    label = f"#{s['id']} {s.get('name', '')}"
    if c.get("status") in SHOW and c.get("raw"):
        keep = c.get("keep_frames") or 121
        fps = c.get("fps", render.WAN_FPS)
        speed = max(render.MIN_SPEED, min(1.0, keep / fps / (dur + render.XFADE_MARGIN)))
        label += f"  [{c['status']}  {speed:.2f}x]"
        inp = ["-i", os.path.join(root, c["raw"])]
        vf = f"trim=end_frame={keep},setpts=PTS-STARTPTS,setpts=PTS/{speed:.4f},fps=30,{fit},tpad=stop_mode=clone:stop_duration={dur:.2f}"
    else:
        label += "  [still]" + (f"  clip {c['status']}" if c.get("status") else "")
        inp = ["-loop", "1", "-framerate", "30", "-i", os.path.join(root, src["keyframe"])]
        vf = fit
    if s.get("reuse_of") is not None:
        label += f"  crop of #{s['reuse_of']}"
    txt = os.path.join(tmp, f"label_{s['id']}_{sp['start']:.2f}.txt")
    lyric = s.get("lyric") or ""
    open(txt, "w", encoding="utf-8").write(label + ("\n" + lyric if lyric else ""))
    tf = txt.replace("\\", "/").replace(":", "\\:")
    vf += (f",drawtext=fontfile='{FONT}':textfile='{tf}':fontsize={h // 24}:fontcolor=white:box=1:boxcolor=black@0.55:"
           f"boxborderw=6:x=12:y=12,trim=duration={dur:.3f},setpts=PTS-STARTPTS,format=yuv420p")
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", *inp, "-vf", vf, "-t", f"{dur:.3f}", "-an", "-r", "30",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", out])


def black(m, dur, out, h):
    w = round(h * m.get("width", 1920) / m.get("height", 1080) / 2) * 2
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=30:d={dur:.3f}",
                           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])


def audio_path(m):
    for rel in (m.get("song"), os.path.join("audio", "mix.wav")):
        if rel and os.path.exists(os.path.join(m["root"], rel)):
            return os.path.join(m["root"], rel)
    return None


def preview(slug, out=None, h=540):
    m = config.load_manifest(slug)
    out = out or os.path.join(m["root"], "output", f"{slug}_preview.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = os.path.join(m["root"], ".preview")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    spans = sorted(((sp, s) for s in m["shots"] for sp in s.get("spans", [])), key=lambda x: x[0]["start"])
    parts, t = [], 0.0
    for i, (sp, s) in enumerate(spans):
        if sp["start"] - t > 0.04:
            parts.append(os.path.join(tmp, f"{i:03d}_gap.mp4"))
            black(m, sp["start"] - t, parts[-1], h)
        parts.append(os.path.join(tmp, f"{i:03d}.mp4"))
        segment(m, s, {"start": max(sp["start"], t), "end": sp["end"]}, parts[-1], h, tmp)
        t = sp["end"]
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w", encoding="utf-8").write("".join(f"file '{p}'\n" for p in parts))
    au = audio_path(m)
    cmd = [config.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst]
    cmd += (["-i", au, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k", "-shortest"] if au else [])
    subprocess.check_call(cmd + ["-c:v", "copy", "-movflags", "+faststart", out])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"preview: {out} ({len(spans)} spans, audio: {os.path.basename(au) if au else 'none'})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--height", type=int, default=540)
    a = ap.parse_args()
    preview(a.slug, a.out, a.height)
