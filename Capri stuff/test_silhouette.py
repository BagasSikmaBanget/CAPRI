import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab, ImageChops, ImageStat

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

out = open(os.path.join(LOG, "sil_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "sil_err.log"), "w", encoding="utf-8")
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
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
print("pet", h, rect(h))

frames = []
try:
    t0 = time.perf_counter()
    g = None
    while time.perf_counter() - t0 < 12.0:
        gg = u.FindWindowW("CapriGlitchWindow", None)
        if gg and u.IsWindowVisible(gg):
            g = gg
            break
        time.sleep(0.02)
    print("glitch hwnd", g, "rect", rect(g) if g else None, "pet rect", rect(h))
    if g:
        pr = rect(h)
        gr = rect(g)
        print("rect match:", pr == gr)
        base = ImageGrab.grab()
        base.save(os.path.join(LOG, "sil_0.png"))
        for i in range(1, 12):
            time.sleep(0.085)
            im = ImageGrab.grab()
            im.save(os.path.join(LOG, f"sil_{i}.png"))
            frames.append(im)
        crop0 = base.crop(pr)
        for i, im in enumerate(frames, 1):
            c = im.crop(pr)
            corner = ImageStat.Stat(ImageChops.difference(c.crop((2, 2, 12, 12)), crop0.crop((2, 2, 12, 12)))).mean
            body = ImageStat.Stat(ImageChops.difference(c.crop((40, 40, 120, 80)), crop0.crop((40, 40, 120, 80)))).mean
            print(f"frame {i}: corner_diff={max(corner):5.1f} body_diff={max(body):5.1f}")
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    if p.poll() is None:
        if h:
            u.PostMessageW(h, 0x0010, 0, 0)
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
    out.close(); err.close()

print("exit", p.returncode)
print("stderr:", repr(open(os.path.join(LOG, "sil_err.log"), encoding="utf-8").read().strip()))
print("stdout:")
print(open(os.path.join(LOG, "sil_out.log"), encoding="utf-8").read().strip())
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
