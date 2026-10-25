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

out = open(os.path.join(LOG, "live_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "live_err.log"), "w", encoding="utf-8")
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

def mean(im, box):
    c = im.crop(box).resize((60, 32), 1)
    return sum(sum(px) for px in c.getdata()) / (60 * 32 * 3)

def changed(diff, box, thr=12):
    g = diff.crop(box).convert("L")
    return sum(1 for v in g.getdata() if v > thr)

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
                corners = [
                    (l + 3, t + 3, l + 15, t + 15), (r - 15, t + 3, r - 3, t + 15),
                    (l + 3, b - 15, l + 15, b - 3), (r - 15, b - 15, r - 3, b - 3),
                ]
                inside = changed(diff, box)
                out_im = diff.copy(); out_im.paste((0, 0, 0), box)
                bursts.append({
                    "t": time.perf_counter() - t0, "pet": pr, "glitch": gr,
                    "mean_pet": mean(im, box), "changed_inside": inside,
                    "changed_outside": sum(1 for v in out_im.convert("L").getdata() if v > 12),
                    "corner_changed": sum(changed(diff, c) for c in corners),
                    "during": im.copy(), "pre": pre.copy(),
                })
                idx = len(bursts) - 1
                im.crop(box).save(os.path.join(LOG, f"live_during_{idx}.png"))
                pre.crop(box).save(os.path.join(LOG, f"live_pre_{idx}.png"))
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

print("bursts captured:", len(bursts))
for i, b in enumerate(bursts):
    l, t, r, bb = b["pet"]
    box = (l, t, r, bb)
    post = b.get("post")
    print(f"[{i}] t={b['t']:.2f} pet={b['pet']} glitch={b['glitch']} "
          f"mean_pet={b['mean_pet']:.1f} changed_in={b['changed_inside']} "
          f"changed_out={b['changed_outside']} corners={b['corner_changed']} "
          f"post_mean={mean(post, box):.1f}" if post else
          f"[{i}] t={b['t']:.2f} pet={b['pet']} glitch={b['glitch']} "
          f"mean_pet={b['mean_pet']:.1f} changed_in={b['changed_inside']} "
          f"changed_out={b['changed_outside']} corners={b['corner_changed']} post=None")
print("exit", code)
print("stderr:", open(os.path.join(LOG, "live_err.log"), encoding="utf-8").read().strip()[:800])
print("stdout tail:", open(os.path.join(LOG, "live_out.log"), encoding="utf-8").read().strip().splitlines()[-8:])
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
