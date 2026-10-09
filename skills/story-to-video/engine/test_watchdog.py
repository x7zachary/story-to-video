"""Manual test of the ComfyUI watchdog with real jobs.
 [1] normal job completes and progress events arrive
 [2] decode-phase stall: decode_max_s is absurdly small, so the VAE-decode/save phase counts as hung
 [3] sampling stall: we SUSPEND the ComfyUI process mid-sampling (like the real VRAM-spill stall), watchdog must fire
 [4] after comfy.restart() a normal job completes again
"""
import ctypes
import time

import comfy
import graphs

ntdll = ctypes.WinDLL("ntdll")
k32 = ctypes.WinDLL("kernel32")
k32.OpenProcess.restype = ctypes.c_void_p


def suspend(pid):
    h = k32.OpenProcess(0x0800, False, pid)   # PROCESS_SUSPEND_RESUME
    ntdll.NtSuspendProcess(ctypes.c_void_p(h))


def job(seed, name):
    return graphs.zimage_graph("a stone bridge in morning fog, cinematic", seed, 1024, 576, f"engine_test/{name}")


comfy.start()
seen = []
t = time.time()
files = comfy.run(job(1, "n1"), on_event=lambda e: seen.append(e["type"]))
print(f"[1] normal job OK in {time.time()-t:.0f}s, progress events: {seen.count('progress')}")

t = time.time()
try:
    comfy.run(job(2, "n2"), decode_max_s=0.2)
    print("[2] FAIL: expected Stalled")
except comfy.Stalled as e:
    print(f"[2] OK decode stall detected after {time.time()-t:.0f}s: {e}")
time.sleep(10)   # let the (uninterrupted) job finish

pid = comfy.server_pid()
print("    server pid", pid)
count = {"n": 0}


def cut_power(ev):
    if ev["type"] == "progress":
        count["n"] += 1
        if count["n"] == 3:
            suspend(pid)


t = time.time()
try:
    comfy.run(job(3, "n3"), step_floor_s=4, on_event=cut_power)
    print("[3] FAIL: expected Stalled")
except comfy.Stalled as e:
    print(f"[3] OK sampling stall detected after {time.time()-t:.0f}s: {e}")

comfy.restart()
t = time.time()
files = comfy.run(job(4, "n4"))
print(f"[4] after restart, job OK in {time.time()-t:.0f}s")
