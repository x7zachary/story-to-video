"""Keyframe generation with automatic pre-screening.

  python stills.py <slug> L1|L2 [--shots 1,2] [--review]
L1: 1 candidate per shot at 1344x768 (fast animatic).  L2: hero shots get 2 candidates at 1920x1088, others 1.
Candidates are ranked by a cheap numeric score (sharpness, exposure, contrast); the best becomes the keyframe.
--review writes contact sheets so the agent/human can override the automatic pick (record it in keyframe_pick).
Pre-screening does NOT detect anatomy errors, fake text or off-model faces - the review sheet exists for that.
"""
import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import comfy  # noqa: E402
import config  # noqa: E402
import graphs  # noqa: E402
import stylelock  # noqa: E402


def compose(m, shot):
    text = shot["image_prompt"]
    for cid, c in m["characters"].items():
        text = text.replace("{" + cid + "}", c["descriptor"])
    # style tail = image_style (or flashback_style) + the project's palette / hard constraints when the preset has them
    return f"{text}. {stylelock.style_text(m['style'], bool(shot.get('flashback')))}"


def prescreen(path):
    im = np.asarray(Image.open(path).convert("L").resize((480, 270)), dtype=np.float32)
    lap = im[1:-1, 1:-1] * 4 - im[:-2, 1:-1] - im[2:, 1:-1] - im[1:-1, :-2] - im[1:-1, 2:]
    sharp = min(float(lap.var()) / 200.0, 1.0)
    mean = float(im.mean())
    exposure = 1.0 - min(abs(mean - 95) / 95, 1.0)          # moody but not black / blown out
    contrast = min(float(im.std()) / 60.0, 1.0)
    return round(0.4 * sharp + 0.3 * exposure + 0.3 * contrast, 3)


def run(slug, level, only, review):
    m = config.load_manifest(slug)
    comfy.start(1.5)
    w, h = (1344, 768) if level == "L1" else (1920, 1088)
    cdir = os.path.join(m["root"], "images", "cands")
    os.makedirs(cdir, exist_ok=True)
    for s in m["shots"]:
        if only and s["id"] not in only:
            continue
        if s.get("reuse_of") is not None:
            continue                                     # crops of another keyframe need no image of their own
        n = 2 if (level == "L2" and s.get("hero")) else 1
        scored = []
        for c in range(n):
            dest = os.path.join(cdir, f"shot_{s['id']:02d}_{level}_c{c}.png")
            if not os.path.exists(dest):
                files = comfy.run(graphs.zimage_graph(compose(m, s), 1000 * (level == "L2") + 10 * s["id"] + c + 7, w, h,
                                                      f"engine/{slug}_{s['id']:02d}"))
                shutil.copy(files[0], dest)
            scored.append((prescreen(dest), dest))
        best = max(scored)
        os.makedirs(os.path.join(m["root"], "images"), exist_ok=True)
        key = os.path.join(m["root"], "images", f"shot_{s['id']:02d}.png")
        shutil.copy(best[1], key)
        s["keyframe"] = f"images/shot_{s['id']:02d}.png"
        s["keyframe_pick"] = {"auto": os.path.basename(best[1]), "scores": [x[0] for x in scored], "level": level}
        config.save_manifest(slug, m)
        print(f"shot {s['id']:2d} pick {os.path.basename(best[1])} scores {[x[0] for x in scored]}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("level", choices=["L1", "L2"])
    ap.add_argument("--shots", default="")
    ap.add_argument("--review", action="store_true")
    a = ap.parse_args()
    run(a.slug, a.level, [int(x) for x in a.shots.split(",")] if a.shots else [], a.review)
