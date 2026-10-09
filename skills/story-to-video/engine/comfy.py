"""ComfyUI client with a watchdog: detects stalled sampling / hung VAE decode, interrupts, and can restart the server.

Why: on 2026-09-29 a Wan job stalled for 25 min (VRAM spill) and another hung 90 min in VAE decode; nobody noticed.
Stall rules (all tunable):
  * sampling: no progress event for max(STEP_FLOOR_S, STEP_FACTOR * median step time)  -> stall
  * decode/save phase (after last step): longer than DECODE_MAX_S                       -> stall
  * whole job: longer than total_max_s                                                  -> stall
"""
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402

try:
    import websocket  # websocket-client
except ImportError:  # progress events unavailable -> only phase/total limits apply
    websocket = None

STEP_FLOOR_S, STEP_FACTOR, DECODE_MAX_S, UNRESPONSIVE_S = 150, 4.0, 900, 60
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # local server: never via the proxy
PID_FILE = os.path.join(config.STATE, "comfy.pid")


class Stalled(RuntimeError):
    pass


def _req(path, data=None, timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(config.COMFY_HOST + path, data=body, headers={"Content-Type": "application/json"})
    with _opener.open(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def alive():
    try:
        _req("/system_stats", timeout=5)
        return True
    except Exception:
        return False


def start(reserve_vram=1.5, wait_s=240):
    """Start ComfyUI hidden (if not already up) and wait until the API answers."""
    if alive():
        return
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    logs = config.LOGS
    os.makedirs(logs, exist_ok=True)
    p = subprocess.Popen([config.COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch",
                          "--reserve-vram", str(reserve_vram)], cwd=config.COMFY,
                         stdout=open(os.path.join(logs, "comfy_out.log"), "ab"),
                         stderr=open(os.path.join(logs, "comfy_err.log"), "ab"),
                         creationflags=subprocess.CREATE_NO_WINDOW)
    open(PID_FILE, "w").write(str(p.pid))
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if alive():
            return
        time.sleep(3)
    raise RuntimeError("ComfyUI did not come up")


def stop():
    try:
        _req("/interrupt", {})
        _req("/queue", {"clear": True})
    except Exception:
        pass
    if os.path.exists(PID_FILE):
        pid = open(PID_FILE).read().strip()
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
        os.remove(PID_FILE)
    time.sleep(3)


def server_pid():
    """PID of the process actually listening on the ComfyUI port (the venv python.exe is only a launcher stub)."""
    out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ":8188" in line and "LISTENING" in line:
            return int(line.split()[-1])


def restart(reserve_vram=1.5):
    stop()
    start(reserve_vram)


def run(graph, total_max_s=5400, step_floor_s=STEP_FLOOR_S, decode_max_s=DECODE_MAX_S, on_event=None, first_step_max_s=900):
    """Queue a graph, wait for outputs. Raises Stalled (after interrupting the server) on a stall."""
    cid = str(uuid.uuid4())
    ws = None
    if websocket:
        ws = websocket.create_connection(config.COMFY_HOST.replace("http", "ws") + f"/ws?clientId={cid}", timeout=5,
                                         http_no_proxy=["127.0.0.1"])
    pid = _req("/prompt", {"prompt": graph, "client_id": cid})["prompt_id"]
    t0 = last_progress = time.time()
    steps, last_step_t, last_value, max_value, sampling_done = [], None, 0, 0, False
    unresponsive_since = None
    try:
        while True:
            now = time.time()
            if ws:
                try:
                    msg = ws.recv()
                    if isinstance(msg, str):
                        ev = json.loads(msg)
                        if ev.get("type") == "progress" and ev["data"].get("prompt_id", pid) == pid:
                            v, mx = ev["data"]["value"], ev["data"]["max"]
                            if v != last_value:
                                if last_step_t is not None and v > last_value:
                                    steps.append(now - last_step_t)
                                last_step_t, last_value, max_value, last_progress = now, v, mx, now
                            if v >= mx:
                                sampling_done, last_progress = True, now
                        if on_event:
                            on_event(ev)
                except websocket.WebSocketTimeoutException:
                    pass
            else:
                time.sleep(5)
            try:
                h = _req(f"/history/{pid}", timeout=10)
                unresponsive_since = None
            except (OSError, TimeoutError):          # a hung server does not answer HTTP either
                unresponsive_since = unresponsive_since or now
                h = {}
                if now - unresponsive_since > UNRESPONSIVE_S:
                    raise Stalled(f"server unresponsive for {now - unresponsive_since:.0f}s")
            if pid in h:
                st = h[pid].get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError("ComfyUI error: " + json.dumps(msgs, ensure_ascii=False)[:1500])
                files = []
                for out in h[pid].get("outputs", {}).values():
                    for key in ("images", "gifs", "videos"):
                        for f in out.get(key, []):
                            files.append(os.path.join(config.COMFY, f.get("type", "output"), f.get("subfolder", ""), f["filename"]))
                return files
            # ---- watchdog ----
            idle = now - last_progress
            if sampling_done:
                if idle > decode_max_s:
                    raise Stalled(f"decode/save phase > {decode_max_s}s")
            elif steps:
                limit = max(step_floor_s, STEP_FACTOR * statistics.median(steps))
                if idle > limit:
                    raise Stalled(f"sampling stalled: no step for {idle:.0f}s (limit {limit:.0f}s, median step {statistics.median(steps):.0f}s)")
            elif idle > first_step_max_s:        # never got a first step (model load) in 15 minutes
                raise Stalled(f"no sampling progress within {first_step_max_s}s")
            if now - t0 > total_max_s:
                raise Stalled(f"job exceeded {total_max_s}s")
    except Stalled:
        try:
            _req("/interrupt", {}, timeout=5)
            _req("/queue", {"clear": True}, timeout=5)
        except Exception:
            pass
        raise
    finally:
        if ws:
            ws.close()
