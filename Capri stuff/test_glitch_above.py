import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import Image, ImageChops, ImageGrab

APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)
backup = open(CFG, encoding="utf-8-sig").read()

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)

test = backup
for k, v in [("IDLE_MIN", "1"), ("IDLE_MAX", "1.2"), ("IDLE2_CHANCE", "0.9"), ("IDLE2_DURATION", "1.2")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "above_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "above_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.GetWindow.argtypes = [wt.HWND, ctypes.c_uint]
u.GetWindow.restype = wt.HWND
u.GetTopWindow.argtypes = [wt.HWND]
u.GetTopWindow.restype = wt.HWND
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def zindex(target):
    w = u.GetTopWindow(None)
    i = 0
    while w:
        if int(w) == int(target):
            return i
        w = u.GetWindow(w, 2)
        i += 1
    return None

def art_alpha(w, h):
    for name, scale in (("Idle2.png", 0.38), ("walk1.png", 0.38), ("eyeline.png", 0.38)):
        path = os.path.join(APP, "action", name)
        if not os.path.isfile(path):
            continue
        im = Image.open(path).convert("RGBA")
        sw, sh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
        if (sw, sh) == (w, h):
            return im.getchannel("A")
    return None

h = None
for _ in range(100):
    h = u.FindWindowW("CapriPetWindow", None)
    if h:
        break
    time.sleep(0.1)

pre = None; pre_rect = None
res = []
last_vis = False
t0 = time.perf_counter()
try:
    while time.perf_counter() - t0 < 8.0:
        g = u.FindWindowW("CapriGlitchWindow", None)
        vis = bool(g) and bool(u.IsWindowVisible(g))
        pr = rect(h)
        im = ImageGrab.grab()
        if not vis:
            pre, pre_rect = im, pr
        elif not last_vis:
            if pre is not None and pr == pre_rect:
                z_pet = zindex(h); z_gl = zindex(g)
                diff = ImageChops.difference(im, pre)
                l, t, r, b = pr
                mask = art_alpha(r - l, b - t)
                inside = outside = 0
                if mask is not None:
                    dm = diff.crop(pr).convert("L")
                    for v, a in zip(dm.get_flattened_data(), mask.get_flattened_data()):
                        if v > 12:
                            if a > 128:
                                inside += 1
                            else:
                                outside += 1
                res.append((z_pet, z_gl, inside, outside, pr))
                im.crop(pr).save(os.path.join(LOG, f"above_during_{len(res)-1}.png"))
                pre.crop(pr).save(os.path.join(LOG, f"above_pre_{len(res)-1}.png"))
        last_vis = vis
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

print("bursts:", len(res))
for i, (zp, zg, ins, outs, pr) in enumerate(res):
    print(f"[{i}] pet_z={zp} glitch_z={zg} glitch_above={zg < zp} "
          f"changed_inside_body={ins} changed_outside_body={outs} rect={pr}")
print("exit", code)
print("stderr:", open(os.path.join(LOG, "above_err.log"), encoding="utf-8").read().strip()[:500])
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
