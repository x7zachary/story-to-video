"""Stage assets and render a manifest project with the shared Remotion project.

  python render.py <slug> L1|L2 [out.mp4]
L1: keyframes only (Ken Burns).  L2: approved Wan clips are fitted to their shot spans and used where available.
Assets are staged into <root>/.stage/public so the Remotion bundle only contains this project (--public-dir).
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

# MIN_SPEED was 0.55 until 2026-10-08: in a song-MV project 22 of 59 clips ran slower than 0.8x and people laughing / walking
# read as dream-like slow motion, with minterpolate warping big motions on top. Plan shot lengths instead (lint warns).
MIN_SPEED, XFADE_MARGIN, WAN_FPS = 0.8, 0.8, 24


def fit_clip(shot, raw, out, keep, fps=WAN_FPS, min_speed=MIN_SPEED):
    """Slow the kept frames to fill the longest span (>= min_speed), interpolate to 30 fps, upscale to 1080p, hold the tail.
    fps: the clip's native rate (Wan 5B 24, A14B 16)."""
    need = max(sp["end"] - sp["start"] for sp in shot["spans"]) + XFADE_MARGIN
    raw_dur = keep / fps
    speed = max(min_speed, min(1.0, raw_dur / need))
    hold = max(0.0, need - raw_dur / speed)
    vf = (f"trim=end_frame={keep},setpts=PTS-STARTPTS,setpts=PTS/{speed:.4f},"
          "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
          f"scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,tpad=stop_mode=clone:stop_duration={hold + 0.5:.2f},"
          f"trim=duration={need:.3f},setpts=PTS-STARTPTS")
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-i", raw, "-vf", vf, "-an", "-c:v", "libx264", "-crf", "16",
                           "-pix_fmt", "yuv420p", "-r", "30", out])
    return {"speed": round(speed, 2), "hold": round(hold, 2)}


def stage(m, level):
    root = m["root"]
    pub = os.path.join(root, ".stage", "public")
    for sub in ("images", "clips", "audio"):
        shutil.rmtree(os.path.join(pub, sub), ignore_errors=True)
        os.makedirs(os.path.join(pub, sub), exist_ok=True)
    for sub in ("fonts", "grain"):                                  # shared, copied once
        dst = os.path.join(pub, sub)
        if not os.path.isdir(dst):
            shutil.copytree(os.path.join(config.REMOTION, "public", sub), dst)
    song = os.path.join(root, m["song"]) if m.get("song") else None          # route B: the song itself
    audio_src = song if song and os.path.exists(song) else os.path.join(root, "audio", "mix.wav")
    audio_rel = "audio/" + ("song" + os.path.splitext(audio_src)[1] if audio_src == song else "mix.wav")
    shutil.copy(audio_src, os.path.join(pub, *audio_rel.split("/")))
    tl = m["timeline"]
    shots, used = [], []
    for s in m["shots"]:
        src = s.get("reuse_of")
        key = os.path.join(root, next(x for x in m["shots"] if x["id"] == src)["keyframe"] if src is not None else s["keyframe"])
        dst_name = f"images/shot_{(src if src is not None else s['id']):02d}.png"
        if not os.path.exists(os.path.join(pub, dst_name)):
            shutil.copy(key, os.path.join(pub, dst_name))
        clip = None
        c = s.get("clip") or {}
        if level == "L2" and c.get("status") == "ok" and c.get("use", c.get("used_in_final", True)) and c.get("raw"):
            out = os.path.join(pub, "clips", f"shot_{s['id']:02d}.mp4")
            info = fit_clip(s, os.path.join(root, c.get("upscaled") or c["raw"]), out, c.get("keep_frames") or 121, c.get("fps", WAN_FPS))
            clip = f"clips/shot_{s['id']:02d}.mp4"
            used.append((s["id"], info))
        for sp in s["spans"]:
            d = {"shot": s["id"], "name": s["name"], "start": sp["start"], "end": sp["end"], "image": dst_name}
            if clip:
                d["clip"] = clip
            if s.get("zoom"):
                d["zoom"], d["focus"] = s["zoom"], s.get("focus", [0.5, 0.5])
            if s.get("overlay"):
                d["overlay"] = s["overlay"]              # code-drawn ambient motion, remotion/src/Ambient.tsx
            if s.get("move"):
                d["move"] = s["move"]                    # Ken Burns move: in / out / left / right / up / still
            if s.get("flashback"):
                d["flashback"] = True                    # sepia wash
            shots.append(d)
    shots.sort(key=lambda d: d["start"])
    out = {"fps": m["fps"], "width": m["width"], "height": m["height"], "total": tl["total"], "audio": audio_rel,
           "shots": shots, **{k: tl.get(k, [] if k in ("segments", "subtitles", "bells") else None)
                              for k in ("segments", "subtitles", "poem", "title", "endcard", "bells")}}
    json.dump(out, open(os.path.join(config.REMOTION, "src", "timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return pub, used


def render(slug, level, out_path=None):
    m = config.load_manifest(slug)
    pub, used = stage(m, level)
    out_path = out_path or os.path.join(m["root"], "output", f"{m['title']}_{level}.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    props = os.path.join(m["root"], ".stage", "props.json")
    json.dump({"useClips": level == "L2"}, open(props, "w"))
    cmd = ["npx", "remotion", "render", "StoryVideo", out_path, f"--public-dir={pub}", f"--props={props}", "--codec=h264",
           "--crf=18", "--concurrency=4", "--audio-codec=aac", "--audio-bitrate=192k"]
    subprocess.check_call(cmd, cwd=config.REMOTION, shell=True)
    print("rendered", out_path, "clips used:", used)
    return out_path


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
