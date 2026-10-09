"""story-to-video pipeline CLI (manifest-driven, resumable).

  python pipeline.py status  <slug>                      shots, tags, clip state, attempts
  python pipeline.py queue   <slug> [--min-score 0.8]    dynamic-shot ranking (importance x success prior x length boost)
  python pipeline.py estimate <slug> [--budget-min 240] [--fast]   expected GPU minutes for the queue (read-only; run before upgrade)
  python pipeline.py upgrade <slug> --budget-min 240 [--max-shots N] [--shots 3,5] [--fast] [--model 5b|a14b] [--unattended]
                                                         Wan2.2 image-to-video with watchdog, numeric QC, retry chain
  python pipeline.py review  <slug> <shot> ok|reject [--keep N] [--note "..."]
                                                         record the semantic (visual) verdict; updates priors
  python pipeline.py timeline <slug>                     rebuild timeline from audio + validate shot lengths
  python pipeline.py render  <slug> L1|L2 [out.mp4]
  python pipeline.py upscale <slug> [--shots 3,5]           SeedVR2 to 1080p for clips below it (A14B 480p); render then uses them
  python pipeline.py preview <slug> [out.mp4]             low-res labelled reel of every shot (clip or still) for the motion sign-off

Tail-frame chaining (opt-in): a shot may carry `continue_from: <shot id>`. Once that shot's clip is accepted (ok / ok_unreviewed)
this shot starts from the LAST KEPT FRAME of it instead of its own keyframe, so one continuous action can run past Wan's ~5 s.
Not decided yet -> the shot waits; source failed -> it falls back to its own keyframe. Keep chains short (drift accumulates).
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import comfy  # noqa: E402
import config  # noqa: E402
import graphs  # noqa: E402
import qc  # noqa: E402
import lint  # noqa: E402
import render  # noqa: E402

PRIORS_PATH = os.path.join(config.STATE, "priors.json")         # learned copy; seeded from engine/priors.json on first use
PRIORS_SEED = os.path.join(config.ENGINE, "priors.json")
WAN_W, WAN_H, WAN_FRAMES = 1280, 704, 121
FAST_PROFILE = (960, 544, 81, 16)       # width, height, frames, steps: the retry chain's reduced profile, measured 3.3-3.4 min/clip
FAST_DEFAULT_MIN = 3.4
# Wan2.2 I2V A14B (GGUF Q4 + lightx2v 4-step LoRAs, graphs.wan_a14b_i2v_graph): 16 fps, 81 frames = 5 s. Spike 2026-10-08
# (references/motion.md): 5.5 min/clip at 832x480 incl. model load, and people kept their identity and did what the prompt
# said where the 5B clip drifted. 480p -> render upscales (or SeedVR2). Opt in per shot (`wan_model`) or per run (--model).
A14B_PROFILE = (848, 480, 81, 4)        # width, height, max frames, steps (848x480 ~ 16:9)
A14B_DEFAULT_MIN = 5.5
UPSCALE_DEFAULT_MIN = 8.1                # SeedVR2 480p -> 1080p for an accepted A14B clip (pipeline.py upscale), measured once
MODELS = ("5b", "a14b")
PEOPLE_CLASSES = ("human_static", "human_motion", "crowd", "hands")


def choose_model(m, shot, model=None, fast=False):
    """Which Wan model a shot runs on, and why. Order: the shot's `wan_model` > --model > --fast (5B fast profile, for
    card-window-sized shots) > the manifest's `wan_model` (unless "auto") > automatic:
      a 5B attempt of this shot already failed (too static, or rejected in review)   -> a14b (escalate, do not retry 5B)
      people, hands, a crowd, or acting verbs in the motion prompt                    -> a14b (5B swapped faces, added acting)
      close objects                                                                   -> a14b (5B made things appear / morph)
      pure environment: sky, water, mist, light, distant views                        -> 5b   (native 1280x704 @24 fps, prior 0.9)
    Basis: references/motion.md (2026-10-08 comparison, 4 shots x 1 seed). An A14B clip plus upscale (~5 + 8 min) costs
    about the same as one 5B clip (~13.8 min)."""
    if shot.get("wan_model"):
        return shot["wan_model"], "shot wan_model"
    if model:
        return model, "--model"
    if fast:
        return "5b", "--fast"
    if m.get("wan_model") in MODELS:
        return m["wan_model"], "manifest wan_model"
    for a in (shot.get("clip") or {}).get("attempts", []):
        if a.get("model", "5b") == "5b" and (a.get("result") == "fail_numeric" or (a.get("review") or {}).get("verdict") == "reject"):
            return "a14b", "5B failed on this shot"
    if (shot.get("motion_tier") == "ai_action" or shot.get("motion_class") in PEOPLE_CLASSES
            or lint.ACTING.search(str(shot.get("motion_prompt", "")).lower())):
        return "a14b", "people / acting"
    if shot.get("motion_class") == "object":
        return "a14b", "close objects"
    return "5b", "environment"
BASE_NEG_EXTRA = {
    "atmosphere": "人物，行人，多余的人，现代服装",
    "object": "人物，多余的手，现代物品",
    "hands": "多余的手指，第三只手，现代物品",
    "human_static": "转头，回头，走动，多余的人物，现代服装",
    "human_motion": "现代服装，多余的人物",
    "crowd": "现代服装",
}
SAFE_MOTION = {   # attempt 2+: the most conservative motion the class can survive
    "human_static": "the person stays perfectly still, only subtle breathing and gentle light flicker, camera almost static",
    "human_motion": "slow gentle camera push-in, the scene stays calm, people barely move",
    "crowd": "slow gentle camera push-in, the scene stays calm",
    "atmosphere": "slow gentle camera push-in, mist and light drift slowly",
    "object": "very slow push-in, dust motes drift in the light",
    "hands": "very slow push-in, dust motes drift in the light",
}


# ------------------------------------------------------------------ priors
def load_priors():
    if not os.path.exists(PRIORS_PATH):
        os.makedirs(os.path.dirname(PRIORS_PATH), exist_ok=True)
        shutil.copy(PRIORS_SEED, PRIORS_PATH)
    return json.load(open(PRIORS_PATH, encoding="utf-8"))


def prior(pri, cls):
    p = pri[cls]
    return (p["ok"] + 2 * p["m0"]) / (p["n"] + 2)


def record_outcome(cls, credit, model="5b"):
    if model != "5b":            # priors.json describes Wan 5B; A14B outcomes would skew it (no A14B priors yet)
        return
    pri = load_priors()
    pri[cls]["n"] += 1
    pri[cls]["ok"] += credit
    json.dump(pri, open(PRIORS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ ranking
def rank(m, min_score=0.0):
    pri = load_priors()
    rows = []
    for s in m["shots"]:
        if s.get("reuse_of") is not None or s.get("motion_tier") in ("camera", "overlay") or not s.get("motion_prompt"):
            continue                                           # crops, and shots planned to move without Wan
        c = s.get("clip") or {}
        atts = c.get("attempts", [])
        retryable = c.get("status") == "failed" and atts and all(a["result"] == "fail_timeout" for a in atts) and len(atts) < 3
        if c.get("status") in ("ok", "ok_unreviewed", "needs_review", "failed") and not retryable:
            continue
        if chain_source(m, s)[0] == "blocked":
            continue                                           # waits for its source clip (continue_from)
        span = max((sp["end"] - sp["start"] for sp in s["spans"]), default=0)
        boost = 1 + 0.15 * max(0.0, min(span, 8.0) - 5.0)      # long, static-looking shots gain more from motion
        score = s["importance"] * prior(pri, s["motion_class"]) * boost
        if score >= min_score:
            rows.append((score, s["id"], s["motion_class"], s["importance"], round(span, 1)))
    return sorted(rows, reverse=True)


def est_minutes(m, fast=False, model=None):
    if model == "a14b":
        ys = sorted(a["minutes"] for s in m["shots"] for a in (s.get("clip") or {}).get("attempts", [])
                    if a.get("model") == "a14b" and a.get("minutes"))
        return ys[len(ys) // 2] if ys else A14B_DEFAULT_MIN
    if fast:                                       # only attempts that really ran the fast profile say anything about it
        ys = sorted(a["minutes"] for s in m["shots"] for a in (s.get("clip") or {}).get("attempts", [])
                    if a.get("res") == "960x544" and a.get("minutes"))
        return ys[len(ys) // 2] if ys else FAST_DEFAULT_MIN
    xs = [a["minutes"] for s in m["shots"] for a in (s.get("clip") or {}).get("attempts", [])
          if a.get("dtype") == "fp8" and a.get("minutes") and a.get("model", "5b") == "5b"]
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 14.0


# ------------------------------------------------------------------ estimate (read-only)
REDUCED_COST = 0.25      # attempt 3 (960x544, 81 frames, 16 steps) took 3.4 min vs ~13.5 min at the default profile: ONE clip, rough
ACCEPTED = ("ok", "ok_unreviewed")


def expected_minutes(p, per, fast=False):
    """Expected GPU minutes for one shot with per-attempt success probability p: attempt 1 always, attempt 2 with
    probability (1-p), attempt 3 with probability (1-p)^2 (at the reduced profile unless `fast`, where all three cost the same).
    Attempts treated as independent."""
    q = 1 - p
    if fast:
        return per * (1 + q + q * q)
    return per * (1 + q) + per * REDUCED_COST * q * q


def estimate(m, min_score=0.0, budget_min=240.0, fast=False, model=None):
    pri = load_priors()
    per = {"5b": est_minutes(m, fast), "a14b": est_minutes(m, False, "a14b")}
    rows, cum, up = [], 0.0, 0.0
    by_id = {s["id"]: s for s in m["shots"]}
    for score, sid, cls, imp, span in rank(m, min_score):
        mdl, why = choose_model(m, by_id[sid], model, fast)
        e = expected_minutes(prior(pri, cls), per[mdl], fast or mdl == "a14b")       # A14B retries run the same profile
        if mdl == "a14b":
            up += UPSCALE_DEFAULT_MIN                                              # finalising: SeedVR2 to 1080p
        cum += e
        rows.append({"shot": sid, "class": cls, "importance": imp, "score": round(score, 2), "model": mdl, "why": why,
                     "expected_min": round(e, 1), "cumulative_min": round(cum, 1)})
    fits = [r for r in rows if r["cumulative_min"] <= budget_min]
    return {"per_attempt_min": per, "rows": rows, "total_min": round(cum, 1), "upscale_min": round(up, 1), "fit_in_budget": len(fits),
            "blocked": [s["id"] for s in m["shots"] if chain_source(m, s)[0] == "blocked" and (s.get("clip") or {}).get("status") not in ACCEPTED]}


# ------------------------------------------------------------------ tail-frame chaining (opt-in)
def chain_source(m, shot):
    """How a shot with `continue_from` should start: (mode, source shot).
    none      no chaining requested
    blocked   the source clip is not decided yet (not run / running / waiting for review): do not run this shot yet
    chain     the source clip is accepted: start from its last kept frame
    fallback  the source clip failed (or does not exist): start from this shot's own keyframe like any other shot"""
    cf = shot.get("continue_from")
    if cf is None:
        return "none", None
    src = next((x for x in m["shots"] if x["id"] == cf), None)
    if src is None:
        return "fallback", None
    status = (src.get("clip") or {}).get("status")
    if status in ACCEPTED:
        return "chain", src
    return ("fallback" if status == "failed" else "blocked"), src


def last_frame_png(m, src, dst):
    """Write the last KEPT frame of the source clip (qc may have trimmed the tail) to dst."""
    c = src["clip"]
    k = max(0, int(c.get("keep_frames") or WAN_FRAMES) - 1)
    if os.path.exists(dst):
        os.remove(dst)
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-i", os.path.join(m["root"], c["raw"]),
                           "-vf", f"select=eq(n\\,{k})", "-vframes", "1", dst])
    if not os.path.exists(dst):
        raise RuntimeError(f"could not read frame {k} of {c['raw']}")
    return dst


# ------------------------------------------------------------------ Wan attempt state machine
def frames_for(m, shot, cap, fps=24):
    """Frames the shot needs at 1x speed (its longest span, or that of a crop reusing it, plus the crossfade margin),
    on Wan's 4n+1 grid, capped. Short shots no longer pay for 121 frames that render would cut anyway."""
    spans = [sp for s in m["shots"] if s["id"] == shot["id"] or s.get("reuse_of") == shot["id"] for sp in s.get("spans", [])]
    if not spans:
        return cap
    n = math.ceil((max(sp["end"] - sp["start"] for sp in spans) + render.XFADE_MARGIN) * fps)
    return max(33, min(cap, 4 * math.ceil((n - 1) / 4) + 1))


def attempt_params(shot, m, n, prev=0, fast=False, model=None):
    cls = shot["motion_class"]
    style = m["style"]
    neg = style["wan_negative"] + "，" + BASE_NEG_EXTRA[cls]
    # attempts of this run so far; a timeout (decode/sampling stall) says nothing about the prompt, so only a bad result
    # (static / glitch) falls back to the conservative motion
    atts = (shot.get("clip") or {}).get("attempts", [])
    earlier = atts[len(atts) - (n - 1):] if n > 1 else []
    own = all(a.get("result") == "fail_timeout" for a in earlier)
    motion = shot["motion_prompt"] if own else SAFE_MOTION[cls]
    mdl, why = choose_model(m, shot, model, fast)
    if mdl == "a14b":
        (w, h, cap, steps), fps = A14B_PROFILE, 16
    else:
        (w, h, cap, steps), fps = ((WAN_W, WAN_H, WAN_FRAMES, 20) if (n < 3 and not fast) else FAST_PROFILE), 24
    frames = frames_for(m, shot, cap, fps)
    return {"seed": 500 + shot["id"] + 100 * (n - 1 + prev), "prompt": f"{motion}. {style['motion_suffix']}", "negative": neg,
            "w": w, "h": h, "frames": frames, "steps": steps, "model": mdl, "model_reason": why, "fps": fps}


def prep_image(m, shot, w, h, source=None):
    from PIL import Image
    im = Image.open(source or os.path.join(m["root"], shot["keyframe"])).convert("RGB")
    sc = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    name = f"eng_{m['slug']}_{shot['id']:02d}.png"
    im.crop((l, t, l + w, t + h)).save(os.path.join(config.COMFY, "input", name))
    return name


def run_attempt(m, shot, n, reserve, fast=False, model=None):
    p = attempt_params(shot, m, n, len((shot.get("clip") or {}).get("attempts", [])), fast, model)
    mode, src = chain_source(m, shot)
    start = last_frame_png(m, src, os.path.join(m["root"], "clips", "raw", f"chain_{shot['id']:02d}_from_{src['id']:02d}.png")) if mode == "chain" else None
    img = prep_image(m, shot, p["w"], p["h"], start)
    prefix = f"engine/{m['slug']}_{shot['id']:02d}"
    if p["model"] == "a14b":
        g = graphs.wan_a14b_i2v_graph(img, p["prompt"], p["negative"], p["seed"], p["w"], p["h"], p["frames"], prefix, steps=p["steps"])
        limits = {"step_floor_s": 600, "first_step_max_s": 1800}       # partial loading: the first steps are slow
    else:
        g = graphs.wan_i2v_graph(img, p["prompt"], p["negative"], p["seed"], p["w"], p["h"], p["frames"], prefix,
                                 steps=p["steps"], dtype="fp8_e4m3fn")
        limits = {}
    t0 = time.time()
    rec = {"n": n, "model": p["model"], "model_reason": p["model_reason"], "dtype": "gguf_q4" if p["model"] == "a14b" else "fp8", "seed": p["seed"],
           "res": f"{p['w']}x{p['h']}", "frames": p["frames"], "fps": p["fps"], "steps": p["steps"],
           "start": f"chain:{src['id']}" if start else "keyframe"}
    try:
        files = comfy.run(g, **limits)
    except comfy.Stalled as e:
        rec.update(result="fail_timeout", note=str(e), minutes=round((time.time() - t0) / 60, 1))
        comfy.restart(reserve + 0.5)                     # stalls were VRAM spills: give the driver more headroom
        return rec, None
    frames = sorted(f for f in files if f.lower().endswith(".png"))
    raw_dir = os.path.join(m["root"], "clips", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    tmp = os.path.join(raw_dir, f"frames_{shot['id']:02d}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for i, f in enumerate(frames):
        shutil.move(f, os.path.join(tmp, f"{i:04d}.png"))
    out = os.path.join(raw_dir, f"shot_{shot['id']:02d}_a{n}.mp4")
    subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-framerate", str(p["fps"]), "-i", os.path.join(tmp, "%04d.png"),
                           "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", out])
    shutil.rmtree(tmp)
    rec["minutes"] = round((time.time() - t0) / 60, 1)
    metrics = qc.analyze(out)
    verdict, reasons = qc.verdict(metrics)
    rec.update(result=verdict, reasons=reasons, motion=metrics["motion"], spike=metrics["spike"])
    if verdict == "partial":
        rec["keep"] = qc.suggest_keep(metrics)
    return rec, out


def upgrade(slug, budget_min, max_shots, only, unattended, fast=False, model=None):
    m = config.load_manifest(slug)
    comfy.start(1.5)
    t_start, per = time.time(), est_minutes(m, fast, model)
    static = [r[1] for r in rank(m)] if not only else list(only)
    dynamic = not only and any(s.get("continue_from") is not None for s in m["shots"])    # a finished clip can unlock a chained shot
    tried = set()
    done = 0

    def next_sid():
        cand = [r[1] for r in rank(config.load_manifest(slug))] if dynamic else static
        return next((x for x in cand if x not in tried), None)

    while True:
        sid = next_sid()
        if sid is None:
            break
        tried.add(sid)
        if (time.time() - t_start) / 60 + per > budget_min or (max_shots and done >= max_shots):
            print(f"budget/limit reached after {done} shots", flush=True)
            break
        m = config.load_manifest(slug)
        shot = next(s for s in m["shots"] if s["id"] == sid)
        if chain_source(m, shot)[0] == "blocked":
            print(f"shot {sid}: continues from shot {shot['continue_from']}, which has no accepted clip yet; skipped", flush=True)
            continue
        clip = shot.setdefault("clip", {"attempts": []})
        clip.setdefault("attempts", [])
        clip["status"] = "running"
        config.save_manifest(slug, m)
        accepted = None
        for n in (1, 2, 3):
            rec, path = run_attempt(m, shot, n, 1.5, fast, model)
            clip["attempts"].append(rec)
            print(f"shot {sid} attempt {n}: {rec['result']} {rec.get('reasons', '')} {rec.get('note', '')} ({rec['minutes']} min)", flush=True)
            if rec["result"] in ("needs_review", "partial"):
                accepted = (rec, path)
                break
            record_outcome(shot["motion_class"], 0.0, rec.get("model", "5b"))
            config.save_manifest(slug, m)
        if accepted:
            rec, path = accepted
            final = os.path.join(m["root"], "clips", "raw", f"shot_{sid:02d}.mp4")
            shutil.copy(path, final)
            tile = qc.tile(final, os.path.join(m["root"], "clips", "raw", f"shot_{sid:02d}_review.jpg"))
            clip.update(raw=f"clips/raw/shot_{sid:02d}.mp4", keep_frames=rec.get("keep", rec["frames"]), fps=rec.get("fps", 24), review_tile=tile,
                        status="ok_unreviewed" if unattended else "needs_review")
        else:
            clip["status"] = "failed"          # falls back to the Ken Burns still; reason is in attempts
        config.save_manifest(slug, m)
        done += 1
    print("upgrade finished:", {s["id"]: s["clip"]["status"] for s in config.load_manifest(slug)["shots"] if s.get("clip", {}).get("status") not in (None, "none")})


def upscale(slug, only, resolution=1080):
    """SeedVR2 3B fp8 upscale (graphs.seedvr2_upscale_graph) of clips shorter than `resolution` (the A14B 480p ones), or of
    the listed shots. Writes clips/raw/shot_XX_up.mp4 and clip["upscaled"]; render prefers it over clip["raw"].
    Measured 2026-10-08: 81 frames 832x480 -> 1872x1080 in 8.1 min, visibly sharper than lanczos, no flicker at the
    5-frame batch joins. Batch 21 ran out of memory on 8 GB; batch 5 + 384 px VAE tiles works."""
    comfy.start(1.5)
    for sid in [s["id"] for s in config.load_manifest(slug)["shots"]]:
        m = config.load_manifest(slug)
        s = next(x for x in m["shots"] if x["id"] == sid)
        c = s.get("clip") or {}
        if (only and sid not in only) or c.get("status") not in ("ok", "ok_unreviewed", "needs_review") or not c.get("raw"):
            continue
        res = next((a.get("res") for a in reversed(c.get("attempts", [])) if a.get("res")), "")
        if not only and res and int(res.split("x")[1]) >= resolution * 0.9:
            continue
        name = f"eng_{slug}_{sid:02d}_up.mp4"
        shutil.copy(os.path.join(m["root"], c["raw"]), os.path.join(config.COMFY, "input", name))
        comfy._req("/free", {"unload_models": True, "free_memory": True})          # cached Wan weights -> SeedVR2 OOM
        t0 = time.time()
        files = comfy.run(graphs.seedvr2_upscale_graph(name, f"engine/{slug}_{sid:02d}_up", resolution),
                          step_floor_s=1800, decode_max_s=1800, first_step_max_s=3600)
        rel = f"clips/raw/shot_{sid:02d}_up.mp4"
        tmp = os.path.join(m["root"], "clips", "raw", f"frames_up_{sid:02d}")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for i, f in enumerate(sorted(x for x in files if x.lower().endswith(".png"))):
            shutil.move(f, os.path.join(tmp, f"{i:04d}.png"))
        subprocess.check_call([config.FFMPEG, "-y", "-v", "error", "-framerate", str(c.get("fps", 24)), "-i", os.path.join(tmp, "%04d.png"),
                               "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", os.path.join(m["root"], rel)])
        shutil.rmtree(tmp)
        m = config.load_manifest(slug)                     # merge: a review may have been recorded meanwhile
        c = next(x for x in m["shots"] if x["id"] == sid)["clip"]
        c.update(upscaled=rel, upscale_minutes=round((time.time() - t0) / 60, 1))
        config.save_manifest(slug, m)
        print(f"shot {sid} upscaled -> {rel} ({c['upscale_minutes']} min)", flush=True)


def review(slug, sid, verdict, keep, note):
    m = config.load_manifest(slug)
    shot = next(s for s in m["shots"] if s["id"] == sid)
    clip = shot["clip"]
    if verdict == "ok":
        clip["status"] = "ok"
        if keep:
            clip["keep_frames"] = keep
        record_outcome(shot["motion_class"], 0.5 if keep and keep < 100 else 1.0, clip["attempts"][-1].get("model", "5b"))
    else:
        clip["status"] = "failed"
        record_outcome(shot["motion_class"], 0.0, clip["attempts"][-1].get("model", "5b"))
    clip["attempts"][-1]["review"] = {"verdict": verdict, "note": note, "keep": keep}
    config.save_manifest(slug, m)
    print(f"shot {sid} -> {clip['status']}")


def status(slug):
    m = config.load_manifest(slug)
    print(f"{m['title']}  total {m['timeline']['total']}s  {len(m['shots'])} shots  root={m['root']}")
    for s in m["shots"]:
        c = s.get("clip") or {}
        span = max((sp["end"] - sp["start"] for sp in s["spans"]), default=0)
        print(f" {s['id']:2d} {s['name']:20s} {s['motion_class']:13s} imp={s['importance']} span={span:5.1f}s "
              f"clip={c.get('status', 'none'):14s} attempts={[a['result'] for a in c.get('attempts', [])]}"
              + (f" continue_from={s['continue_from']}" if s.get("continue_from") is not None else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("slug")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--budget-min", type=float, default=240)
    ap.add_argument("--max-shots", type=int, default=0)
    ap.add_argument("--shots", default="")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--keep", type=int, default=0)
    ap.add_argument("--note", default="")
    ap.add_argument("--unattended", action="store_true", help="accept numerically-clean clips without a visual review")
    ap.add_argument("--model", choices=MODELS, default=None,
                    help="force a Wan model for shots without their own `wan_model` (default: automatic, see choose_model)")
    ap.add_argument("--fast", action="store_true", help="use the fast Wan profile (960x544, 81 frames, 16 steps; ~3.4 min/clip) for every attempt")
    a = ap.parse_args()
    if a.cmd == "status":
        status(a.slug)
    elif a.cmd == "queue":
        m = config.load_manifest(a.slug)
        print(f"median Wan attempt: 5B ~{est_minutes(m)} min, A14B ~{est_minutes(m, False, 'a14b')} min")
        by_id = {s["id"]: s for s in m["shots"]}
        for score, sid, cls, imp, span in rank(m, a.min_score):
            mdl, why = choose_model(m, by_id[sid], a.model, a.fast)
            print(f"  shot {sid:2d} score={score:4.2f} class={cls:13s} importance={imp} span={span}s  model={mdl} ({why})")
    elif a.cmd == "estimate":
        e = estimate(config.load_manifest(a.slug), a.min_score, a.budget_min, a.fast, a.model)
        pm = e["per_attempt_min"]
        print(f"per attempt: 5B ~{pm['5b']} min " + ("(fast profile 960x544, 81 frames, 16 steps)" if a.fast else
              f"(median of recorded attempts, default 14; reduced-profile retry counted as {REDUCED_COST}x)")
              + f", A14B ~{pm['a14b']} min (848x480, 4 steps; default 5.5)")
        print("shot  class          model  why                     imp  score  expected_min  cumulative_min")
        for r in e["rows"]:
            mark = "" if r["cumulative_min"] <= a.budget_min else "   (over budget)"
            print(f"{r['shot']:4d}  {r['class']:13s}  {r['model']:5s}  {r['why']:22s}  {r['importance']:3d}  {r['score']:5.2f}  "
                  f"{r['expected_min']:12.1f}  {r['cumulative_min']:14.1f}{mark}")
        h = e["total_min"] / 60
        print(f"queue: {len(e['rows'])} shots, expected {e['total_min']} min (~{h:.1f} h) if all run; {e['fit_in_budget']} shots fit in --budget-min {a.budget_min:g}")
        if e["upscale_min"]:
            print(f"plus ~{e['upscale_min']} min of SeedVR2 upscaling for the A14B clips when finalising (pipeline.py upscale)")
        if e["blocked"]:
            print(f"waiting for a chain source: shots {e['blocked']}")
        print("attempts are treated as independent with the class prior as success rate; Remotion rendering at the same time slows Wan down")
    elif a.cmd == "upgrade":
        upgrade(a.slug, a.budget_min, a.max_shots, [int(x) for x in a.shots.split(",")] if a.shots else [], a.unattended, a.fast, a.model)
    elif a.cmd == "review":
        review(a.slug, int(a.args[0]), a.args[1], a.keep, a.note)
    elif a.cmd == "timeline":
        subprocess.check_call([config.PY, os.path.join(config.ENGINE, "timeline.py"), a.slug])
    elif a.cmd == "render":
        import render
        render.render(a.slug, a.args[0], a.args[1] if len(a.args) > 1 else None)
    elif a.cmd == "upscale":
        upscale(a.slug, [int(x) for x in a.shots.split(",")] if a.shots else [])
    elif a.cmd == "preview":
        import preview
        preview.preview(a.slug, a.args[0] if a.args else None)
