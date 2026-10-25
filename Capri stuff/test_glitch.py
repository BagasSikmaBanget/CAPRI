import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab

APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)
backup = open(CFG, encoding="utf-8-sig").read()

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)

test = backup
for k, v in [("IDLE_MIN", "1"), ("IDLE_MAX", "1.2"), ("IDLE2_CHANCE", "0"),
             ("WALK_SPEED", "500"), ("WALK_MIN_DISTANCE", "120"), ("WALK_MAX_DISTANCE", "200")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "glitch_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "glitch_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return (r.left, r.top, r.right, r.bottom)

h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
print("hwnd", h)

samples = []
try:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 9.0:
        t = time.perf_counter() - t0
        im = ImageGrab.grab().resize((240, 135), 1)
        px = list(im.getdata())
        mean = sum(sum(c) for c in px) / (len(px) * 3)
        samples.append((t, mean, rect(h)))
        time.sleep(0.02)
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    if h:
        u.PostMessageW(h, 0x0010, 0, 0)
    try:
        code = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill(); code = "timeout"
    out.close(); err.close()

print("exit", code)
print("stderr:", open(os.path.join(LOG,"glitch_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG,"glitch_out.log"), encoding="utf-8").read().strip())

# find dark runs (overlay)
runs = []
inrun = False
for t, m, r in samples:
    dark = m < 8.0
    if dark and not inrun:
        start = t; inrun = True
    elif not dark and inrun:
        runs.append((start, t)); inrun = False
if inrun:
    runs.append((start, samples[-1][0]))
print("samples", len(samples), "duration", samples[-1][0])
print("dark runs (s):")
for a, b in runs:
    print(f"  {a:.2f} -> {b:.2f}  ({b-a:.2f}s)")

# rect changes
print("rect changes:")
prev = None
for t, m, r in samples:
    if r != prev:
        print(f"  t={t:.2f} mean={m:.1f} rect={r}")
        prev = r

# save representative frames for the first two runs
for idx, (a, b) in enumerate(runs[:2]):
    for label, tt in (("start", a), ("mid", (a+b)/2), ("end", b)):
        im = ImageGrab.grab()
        im.save(os.path.join(LOG, f"glitch_{idx}_{label}.png"))
        print("saved", idx, label, "at", round(tt,2))
