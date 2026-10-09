"""One-time setup and health check for story-to-video.

  python setup/stv_setup.py init  [--workspace DIR] [--comfy-dir DIR] [--ffmpeg EXE] [--python EXE] [--whisper-model NAME|DIR]
        writes ~/.story-to-video/config.json, creates the workspace, copies the Remotion template there and renders the
        film-grain tiles. Run `npm install` in <workspace>/remotion afterwards and add two fonts (see INSTALL.md).
  python setup/stv_setup.py check
        reports what is missing: ffmpeg, Python packages, ComfyUI + custom nodes, model files, Remotion, fonts.
  python setup/stv_setup.py models [--download] [--verify]
        lists the model files (setup/models.json, ~59 GB), downloads missing ones (ModelScope first, then HF mirrors,
        resumable), or checks sha256 of the ones present.
Nothing here installs system packages or changes security settings.
"""
import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "skills", "story-to-video", "engine")
sys.path.insert(0, ENGINE)
import config  # noqa: E402
import hf_fetch  # noqa: E402

MODELS = json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))
NODES = {"ComfyUI-GGUF": "https://github.com/city96/ComfyUI-GGUF",
         "ComfyUI-SeedVR2_VideoUpscaler": "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler"}
PY_MODULES = ["numpy", "PIL", "edge_tts", "faster_whisper", "pypinyin", "websocket"]


def model_path(entry):
    """Where the file is (first model root that has it), else where a download goes (ComfyUI's own models folder)."""
    for root in config.MODEL_DIRS:
        p = os.path.join(root, entry["comfy_subdir"], entry["file"])
        if os.path.exists(p):
            return p
    return os.path.join(config.MODEL_DIRS[0], entry["comfy_subdir"], entry["file"])


def init(a):
    cfg = json.load(open(config.USER_CONFIG, encoding="utf-8")) if os.path.exists(config.USER_CONFIG) else {}
    for key, val in (("workspace", a.workspace), ("comfy_dir", a.comfy_dir), ("ffmpeg", a.ffmpeg), ("python", a.python),
                     ("whisper_model", a.whisper_model)):
        if val:
            cfg[key] = os.path.abspath(val) if key != "whisper_model" or os.path.isdir(val) else val
    os.makedirs(os.path.dirname(config.USER_CONFIG), exist_ok=True)
    json.dump(cfg, open(config.USER_CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    importlib.reload(config)
    for d in (config.WORKSPACE, config.PROJECTS, config.STATE, config.LOGS):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(config.REMOTION):
        shutil.copytree(config.REMOTION_TEMPLATE, config.REMOTION)
        print("copied the Remotion template to", config.REMOTION)
    grain(os.path.join(config.REMOTION, "public", "grain"))
    os.makedirs(os.path.join(config.REMOTION, "public", "fonts"), exist_ok=True)
    print("config:", config.USER_CONFIG, json.dumps(cfg, ensure_ascii=False))
    print(f"next: cd \"{config.REMOTION}\" && npm install   then add fonts and run: python setup/stv_setup.py check")


def grain(out):
    """Film-grain tiles for the FilmLook layer (generated, so nothing binary is shipped)."""
    import numpy as np
    from PIL import Image, ImageFilter
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(3)
    for i in range(6):
        noise = rng.normal(128, 38, (540, 960)).clip(0, 255).astype(np.uint8)
        Image.fromarray(noise, "L").filter(ImageFilter.GaussianBlur(0.6)).resize((1920, 1080), Image.BILINEAR).save(
            os.path.join(out, f"grain_{i}.png"))
    print("grain tiles ->", out)


def check(_a):
    bad = 0

    def report(ok, what, hint=""):
        nonlocal bad
        bad += not ok
        print(("  OK    " if ok else "  MISS  ") + what + ("" if ok or not hint else f"   -> {hint}"))

    print("config file:", config.USER_CONFIG if os.path.exists(config.USER_CONFIG) else "(none, defaults in use)")
    try:
        subprocess.run([config.FFMPEG, "-version"], capture_output=True, check=True)
        report(True, f"ffmpeg ({config.FFMPEG})")
    except (OSError, subprocess.CalledProcessError):
        report(False, f"ffmpeg ({config.FFMPEG})", "install ffmpeg or set it with init --ffmpeg")
    for mod in PY_MODULES:
        try:
            importlib.import_module(mod)
            report(True, f"python module {mod}")
        except Exception as e:  # noqa: BLE001 - a blocked DLL raises OSError, not ImportError
            report(False, f"python module {mod} ({type(e).__name__})", "pip install -r setup/requirements.txt")
    report(os.path.exists(os.path.join(config.COMFY, "main.py")), f"ComfyUI ({config.COMFY})", "see INSTALL.md")
    report(os.path.exists(config.COMFY_PY), f"ComfyUI python ({config.COMFY_PY})", "init --comfy-dir, or set comfy_python")
    for name, url in NODES.items():
        report(os.path.isdir(os.path.join(config.COMFY, "custom_nodes", name)), f"custom node {name}", f"git clone {url}")
    for e in MODELS:
        p = model_path(e)
        ok = os.path.exists(p) and os.path.getsize(p) == e["size"]
        report(ok or e["optional"], f"model {e['comfy_subdir']}/{e['file']} ({e['size'] / 1e9:.1f} GB)", "setup/stv_setup.py models --download")
    report(os.path.isdir(os.path.join(config.REMOTION, "node_modules")), f"Remotion node_modules ({config.REMOTION})", "npm install")
    for f in ("kai.ttf", "title.ttf"):
        report(os.path.exists(os.path.join(config.REMOTION, "public", "fonts", f)), f"font public/fonts/{f}", "see INSTALL.md (fonts)")
    print("all good" if not bad else f"{bad} item(s) missing")
    return 1 if bad else 0


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(16 << 20):
            h.update(b)
    return h.hexdigest()


def models(a):
    for e in MODELS:
        p = model_path(e)
        have = os.path.exists(p) and os.path.getsize(p) == e["size"]
        state = "present" if have else "missing"
        if a.download and not have:
            tmp = os.path.join(config.COMFY, "models", "_download")
            got = hf_fetch.fetch(e["repo"], e["path"], tmp)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.replace(got, p)
            state = "downloaded"
        if a.verify and os.path.exists(p):
            state += ", sha256 " + ("OK" if sha256(p) == e["sha256"] else "MISMATCH")
        print(f"{e['size'] / 1e9:6.2f} GB  {e['comfy_subdir']}/{e['file']}  [{state}]  {e['purpose']}")
    print(f"total {sum(e['size'] for e in MODELS) / 1e9:.1f} GB into {os.path.join(config.COMFY, 'models')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    for flag in ("--workspace", "--comfy-dir", "--ffmpeg", "--python", "--whisper-model"):
        p.add_argument(flag)
    sub.add_parser("check")
    p = sub.add_parser("models")
    p.add_argument("--download", action="store_true")
    p.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    sys.exit({"init": init, "check": check, "models": models}[a.cmd](a) or 0)
