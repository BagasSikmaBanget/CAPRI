import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab
APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
backup = open(CFG, encoding="utf-8-sig").read()
out = open(os.path.join(LOG, "reload_glitch_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "reload_glitch_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)
u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
time.sleep(0.8)

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)
test = backup
for k, v in [("IDLE_MIN", "1"), ("IDLE_MAX", "1.2"), ("IDLE2_CHANCE", "0"),
             ("WALK_SPEED", "500"), ("WALK_MIN_DISTANCE", "120"), ("WALK_MAX_DISTANCE", "200")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)
try:
    print("reload", u.PostMessageW(h, 0x0312, 2, 0))
    time.sleep(1.0)
    dark = 0
    samples = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 4.5:
        im = ImageGrab.grab().resize((240,135), 1)
        b = im.tobytes(); m = sum(b)/len(b)
        samples.append((time.perf_counter()-t0, m))
        if m < 6.0: dark += 1
        time.sleep(0.02)
    runs=[]; inr=False
    for t,m in samples:
        d=m<6.0
        if d and not inr: a=t; inr=True
        elif not d and inr: runs.append((a,t)); inr=False
    if inr: runs.append((a,samples[-1][0]))
    print("dark samples", dark, "of", len(samples))
    print("dark runs:", [(round(a,2),round(b,2),round(b-a,2)) for a,b in runs])
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    u.PostMessageW(h, 0x0010, 0, 0)
    try: code = p.wait(timeout=10)
    except subprocess.TimeoutExpired: p.kill(); code = "timeout"
    out.close(); err.close()
print("exit", code)
print("stderr:", open(os.path.join(LOG,"reload_glitch_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG,"reload_glitch_out.log"), encoding="utf-8").read().strip())
