"""Fetch Remotion's tested Chrome Headless Shell (resumable) into node_modules/.remotion layout (Windows x64).

Only needed when Remotion's own downloader stalls behind a slow proxy:  python get_headless_shell.py
"""
import os
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "story-to-video", "engine"))
import config  # noqa: E402

VERSION = "149.0.7790.0"
URL = f"https://storage.googleapis.com/chrome-for-testing-public/{VERSION}/win64/chrome-headless-shell-win64.zip"
DEST = os.path.join(config.REMOTION, "node_modules", ".remotion", "chrome-headless-shell")
os.makedirs(DEST, exist_ok=True)
zip_path = os.path.join(DEST, "chrome-headless-shell-win64.zip")
part = zip_path + ".part"

for attempt in range(40):
    try:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(URL, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            total = have + int(r.headers.get("Content-Length", 0))
            if have and r.status != 206:
                have, total = 0, int(r.headers.get("Content-Length", 0))
            with open(part, "ab" if have else "wb") as f:
                while chunk := r.read(1024 * 1024):
                    f.write(chunk)
        if os.path.getsize(part) == total:
            os.replace(part, zip_path)
            break
    except Exception as e:
        print("retry", attempt, e, flush=True)
        time.sleep(5)

with zipfile.ZipFile(zip_path) as z:
    z.extractall(os.path.join(DEST, "win64"))
os.remove(zip_path)
open(os.path.join(DEST, "VERSION"), "w").write(VERSION)
exe = os.path.join(DEST, "win64", "chrome-headless-shell-win64", "chrome-headless-shell.exe")
print("ready" if os.path.exists(exe) else "MISSING", exe)
