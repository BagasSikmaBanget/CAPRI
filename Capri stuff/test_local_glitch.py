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
for k, v in [("IDLE_MIN", "1"), ("IDLE_MAX", "1.2"), ("IDLE2_CHANCE", "0")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "local_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "local_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h:
        break
    time.sleep(0.1)
print("pet hwnd", h)

samples = []
mid_saved = False
try:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 8.0:
        t = time.perf_counter() - t0
        g = u.FindWindowW("CapriGlitchWindow", None)
        vis = bool(g) and bool(u.IsWindowVisible(g))
        gr = rect(g) if vis else None
        pr = rect(h)
        im = ImageGrab.grab()
        full = im.resize((240, 135), 1)
        fmean = sum(sum(c) for c in full.getdata()) / (240 * 135 * 3)
        pad = 40
        box = (max(0, pr[0] - pad), max(0, pr[1] - pad), min(im.width, pr[2] + pad), min(im.height, pr[3] + pad))
        crop = im.crop(box)
        cmean = sum(sum(c) for c in crop.resize((80, 45), 1).getdata()) / (80 * 45 * 3)
        corner = im.getpixel((im.width - 5, 5))
        cval = sum(corner) / 3
        samples.append((t, fmean, cmean, cval, pr, gr, vis))
        if vis and not mid_saved:
            im.save(os.path.join(LOG, "local_glitch_mid.png"))
            im.crop(box).save(os.path.join(LOG, "local_glitch_crop.png"))
            mid_saved = True
            print("overlay pet_rect", pr, "glitch_rect", gr)
        time.sleep(0.03)
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
print("stderr:", open(os.path.join(LOG, "local_err.log"), encoding="utf-8").read().strip())

runs = []
inrun = False
for t, fm, cm, cv, pr, gr, vis in samples:
    dark = cm < 8.0
    if dark and not inrun:
        start = t; inrun = True
    elif not dark and inrun:
        runs.append((start, t)); inrun = False
if inrun:
    runs.append((start, samples[-1][0]))
print("samples", len(samples))
print("dark pet-region runs:")
for a, b in runs:
    inside = [s for s in samples if a <= s[0] <= b]
    print(f"  {a:.2f}->{b:.2f} ({b-a:.2f}s) full_min={min(s[1] for s in inside):.1f} corner_min={min(s[3] for s in inside):.1f}")

vis = [s for s in samples if s[6]]
print("visible overlay samples:", len(vis))
if vis:
    sizes = {(s[5][2] - s[5][0], s[5][3] - s[5][1]) for s in vis}
    print("glitch sizes:", sizes)
    offs = {(s[5][0] - s[4][0], s[5][1] - s[4][1]) for s in vis}
    print("glitch offset from pet:", sorted(offs)[:8])
    print("glitch rects sample:", sorted({s[5] for s in vis})[:4])

print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
