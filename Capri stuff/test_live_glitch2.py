import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab, ImageChops

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

out = open(os.path.join(LOG, "live2_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "live2_err.log"), "w", encoding="utf-8")
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

def diffcount(diff, box, thr=12):
    g = diff.crop(box).convert("L")
    return sum(1 for v in g.get_flattened_data() if v > thr)

def mean(im, box):
    c = im.crop(box).resize((60, 32), 1)
    return sum(sum(px) for px in c.get_flattened_data()) / (60 * 32 * 3)

h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h:
        break
    time.sleep(0.1)
print("pet hwnd", h)

pre = None; pre_rect = None
bursts = []
last_vis = False
t0 = time.perf_counter()
try:
    while time.perf_counter() - t0 < 9.0:
        g = u.FindWindowW("CapriGlitchWindow", None)
        vis = bool(g) and bool(u.IsWindowVisible(g))
        pr = rect(h)
        im = ImageGrab.grab()
        if not vis:
            pre, pre_rect = im, pr
            if last_vis:
                bursts[-1]["post"] = im.copy()
        elif not last_vis or (bursts and "during" not in bursts[-1]):
            if pre is not None and pr == pre_rect:
                l, t, r, b = pr
                box = (l, t, r, b)
                diff = ImageChops.difference(im, pre)
                gr = rect(g)
                ring = (gr[0], gr[1], gr[2], gr[3])
                border = 4
                outside_ring = diff.copy()
                outside_ring.paste((0, 0, 0), (ring[0] + border, ring[1] + border, ring[2] - border, ring[3] - border))
                bursts.append({
                    "t": time.perf_counter() - t0, "pet": pr, "glitch": gr,
                    "mean_pet": mean(im, box), "changed_pet": diffcount(diff, box),
                    "changed_outside_overlay": sum(1 for v in outside_ring.convert("L").get_flattened_data() if v > 12),
                    "during": im.copy(),
                })
                idx = len(bursts) - 1
                im.crop(gr).save(os.path.join(LOG, f"live2_during_{idx}.png"))
                pre.crop(gr).save(os.path.join(LOG, f"live2_pre_{idx}.png"))
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

pad = 12
print("bursts captured:", len(bursts))
for i, b in enumerate(bursts):
    l, t, r, bb = b["pet"]
    gr = b["glitch"]
    expand_ok = gr == (l - pad, t - pad, r + pad, bb + pad)
    post = b.get("post")
    pm = mean(post, (l, t, r, bb)) if post else None
    print(f"[{i}] t={b['t']:.2f} pet={b['pet']} glitch={gr} pad_ok={expand_ok} "
          f"mean_pet={b['mean_pet']:.1f} changed_pet={b['changed_pet']} "
          f"changed_outside_overlay={b['changed_outside_overlay']} "
          f"post_mean={pm if pm is None else round(pm, 1)}")
print("exit", code)
print("stderr:", open(os.path.join(LOG, "live2_err.log"), encoding="utf-8").read().strip()[:800])
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
