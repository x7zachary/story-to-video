"""Try to map each DLL/PYD so Code Integrity (Smart App Control) evaluates it.
winerror 4551 = blocked by application control policy; 126/127 = only missing deps (i.e. allowed)."""
import ctypes, glob, os, sys
root = sys.argv[1]
os.add_dll_directory(os.path.join(root, "lib"))
files = sorted(glob.glob(os.path.join(root, "*.pyd")) + glob.glob(os.path.join(root, "lib", "*.dll")))
blocked, ok = [], []
for f in files:
    try:
        ctypes.WinDLL(f)
        ok.append(os.path.basename(f))
    except OSError as e:
        (blocked if e.winerror == 4551 else ok).append(os.path.basename(f) + ("" if e.winerror != 4551 else ""))
        if e.winerror not in (4551,):
            ok[-1] += f" (err {e.winerror})"
print("BLOCKED:", blocked)
print("ALLOWED:", ok)
