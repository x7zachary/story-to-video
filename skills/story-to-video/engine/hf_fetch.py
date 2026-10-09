"""Resumable HuggingFace file downloader (stdlib only) with host rotation; the proxy here drops TLS often.

Usage: python hf_fetch.py <repo> <dest_dir> <file> [<file> ...]
Files already complete (size == remote size) are skipped.
Hosts are tried in order: ModelScope (direct, no proxy; 14-18 MB/s measured 2026-10-08, most popular HF repos are
mirrored under the same name), hf-mirror.com (since 2026-10 it 308-redirects to huggingface.co's US CDN, ~0.6 MB/s),
huggingface.co (through the env proxy).
"""
import os
import re
import sys
import time
import urllib.request

# (base, revision, direct): direct=True bypasses the env proxy (ModelScope is a domestic CDN)
HOSTS = [("https://modelscope.cn/models", "master", True),
         ("https://hf-mirror.com", "main", False),
         ("https://huggingface.co", "main", False)]
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROXIED = urllib.request.build_opener()


def remote_size(opener, url):
    """Total size from a 1-byte ranged GET (ModelScope's HEAD has no Content-Length)."""
    with opener.open(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=60) as r:
        m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
        return int(m.group(1)) if m else int(r.headers.get("Content-Length", 0))


def fetch(repo, rel, dest_dir, attempts=40):
    os.makedirs(os.path.join(dest_dir, os.path.dirname(rel)), exist_ok=True)
    dest = os.path.join(dest_dir, rel)
    part = dest + ".part"
    for attempt in range(attempts):
        base, rev, direct = HOSTS[attempt // 3 % len(HOSTS)]
        opener = DIRECT if direct else PROXIED
        url = f"{base}/{repo}/resolve/{rev}/{rel}"
        try:
            total = remote_size(opener, url)
            if total <= 1:
                raise IOError(f"no size from {base}")
            if os.path.exists(dest) and os.path.getsize(dest) == total:
                return dest
            have = os.path.getsize(part) if os.path.exists(part) else 0
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
            with opener.open(req, timeout=120) as r, open(part, "ab" if have else "wb") as f:
                if have and r.status != 206:
                    f.truncate(0)
                while chunk := r.read(4 * 1024 * 1024):
                    f.write(chunk)
            if os.path.getsize(part) == total:
                os.replace(part, dest)
                print(f"[done] {rel} {total/1e6:.0f} MB via {base}", flush=True)
                return dest
        except Exception as e:
            print(f"  attempt {attempt} {base} {rel}: {e}", flush=True)
            time.sleep(min(30, 3 + attempt))
    raise SystemExit(f"failed: {rel}")


if __name__ == "__main__":
    repo, dest_dir, *files = sys.argv[1:]
    for f in files:
        fetch(repo, f, dest_dir)
    print("OK")
