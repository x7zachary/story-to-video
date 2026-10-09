"""Shared paths and constants for the story-to-video engine.

Every path is configurable. First hit wins:
  1. environment variable STV_<KEY> (e.g. STV_COMFY_DIR)
  2. the user config file ~/.story-to-video/config.json (written by `python setup/stv_setup.py init`), or STV_CONFIG
  3. the defaults below (everything under one workspace folder)
Projects live under <projects>/<slug>/manifest.json. Heavy installs (ComfyUI, models, Remotion node_modules) are made once
and shared by all projects.
"""
import json
import os
import shutil
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.abspath(os.path.join(ENGINE, "..", "..", ".."))
USER_CONFIG = os.environ.get("STV_CONFIG", os.path.join(os.path.expanduser("~"), ".story-to-video", "config.json"))
_cfg = {}
if os.path.exists(USER_CONFIG):
    with open(USER_CONFIG, encoding="utf-8") as _f:
        _cfg = json.load(_f)


def _get(key, default):
    return os.environ.get("STV_" + key.upper(), _cfg.get(key, default))


_WIN = os.name == "nt"
WORKSPACE = _get("workspace", os.path.join(os.path.expanduser("~"), "story-to-video"))
PROJECTS = _get("projects", os.path.join(WORKSPACE, "projects"))
COMFY = _get("comfy_dir", os.path.join(WORKSPACE, "tools", "ComfyUI"))
COMFY_PY = _get("comfy_python", os.path.join(COMFY, "venv", "Scripts" if _WIN else "bin", "python.exe" if _WIN else "python"))
COMFY_HOST = _get("comfy_host", "http://127.0.0.1:8188")
_md = _get("model_dirs", [])                                         # extra model roots (as in ComfyUI's extra_model_paths.yaml)
MODEL_DIRS = [os.path.join(COMFY, "models")] + (_md.split(os.pathsep) if isinstance(_md, str) else list(_md))
FFMPEG = _get("ffmpeg", shutil.which("ffmpeg") or "ffmpeg")
PY = _get("python", sys.executable)                                  # edge-tts, numpy, pillow, faster-whisper, pypinyin
REMOTION = _get("remotion_dir", os.path.join(WORKSPACE, "remotion"))  # copy of <plugin>/remotion with node_modules installed
REMOTION_TEMPLATE = os.path.join(PLUGIN_ROOT, "remotion")
WHISPER_MODEL = _get("whisper_model", "small")                       # faster-whisper model name or a local model folder
STATE = _get("state_dir", os.path.join(WORKSPACE, "state"))          # comfy.pid, learned priors.json
LOGS = _get("logs_dir", os.path.join(WORKSPACE, "logs"))

# Wan2.2 TI2V-5B generates 121 frames @ 24 fps ~= 5.04 s; plan dynamic shots to fit.
WAN_MAX_SECONDS = 5.5
STILL_MIN, STILL_MAX = 4.0, 8.0


def project_dir(slug):
    return os.path.join(PROJECTS, slug)


def manifest_path(slug):
    return os.path.join(project_dir(slug), "manifest.json")


def load_manifest(slug):
    with open(manifest_path(slug), encoding="utf-8") as f:
        return json.load(f)


def save_manifest(slug, m):
    tmp = manifest_path(slug) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(tmp, manifest_path(slug))   # atomic: a crash never leaves a half-written manifest


def load_json(rel):
    with open(os.path.join(ENGINE, rel), encoding="utf-8") as f:
        return json.load(f)
