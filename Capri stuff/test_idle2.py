import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab
APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
backup = open(CFG, encoding="utf-8-sig").read()
out = open(os.path.join(LOG, "idle2_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "idle2_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)
u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
time.sleep(0.8)

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)
test = backup
for k, v in [("IDLE_MIN", "1"), ("IDLE_MAX", "1.2"), ("IDLE2_CHANCE", "1"), ("IDLE2_DURATION", "2")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)
try:
    u.PostMessageW(h, 0x0312, 2, 0)
    time.sleep(1.0)
    t0=time.perf_counter(); prev=None; seen=set()
    while time.perf_counter()-t0 < 9.0:
        r=wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        size=(r.right-r.left, r.bottom-r.top)
        if size!=prev:
            seen.add(size)
            print(f"t={time.perf_counter()-t0:.2f} size={size} rect=({r.left},{r.top},{r.right},{r.bottom})")
            prev=size
        time.sleep(0.03)
    print("sizes seen:", sorted(seen))
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    u.PostMessageW(h, 0x0010, 0, 0)
    try: code = p.wait(timeout=10)
    except subprocess.TimeoutExpired: p.kill(); code = "timeout"
    out.close(); err.close()
print("exit", code)
print("stderr:", open(os.path.join(LOG,"idle2_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG,"idle2_out.log"), encoding="utf-8").read().strip())
