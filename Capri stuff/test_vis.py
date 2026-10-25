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

out = open(os.path.join(LOG, "vis_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "vis_err.log"), "w", encoding="utf-8")
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

saved = 0
prev_dark = False
t0 = time.perf_counter()
try:
    while time.perf_counter() - t0 < 5.5 and saved < 8:
        im = ImageGrab.grab()
        small = im.resize((240, 135), 1)
        px = small.tobytes()
        mean = sum(px) / len(px)
        t = time.perf_counter() - t0
        dark = mean < 6.0
        if dark != prev_dark:
            name = f"vis_{'dark' if dark else 'lit'}_{saved}.png"
            im.save(os.path.join(LOG, name))
            # corner samples
            print(f"t={t:.2f} mean={mean:.2f} -> {name} corners=",
                  [im.getpixel(xy) for xy in [(5,5),(1910,5),(5,1070),(1910,1070)]])
            saved += 1
            prev_dark = dark
        time.sleep(0.01)
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    if h: u.PostMessageW(h, 0x0010, 0, 0)
    try: code = p.wait(timeout=10)
    except subprocess.TimeoutExpired: p.kill(); code = "timeout"
    out.close(); err.close()
print("exit", code)
print("stderr:", open(os.path.join(LOG,"vis_err.log"), encoding="utf-8").read().strip())
print("stdout:", open(os.path.join(LOG,"vis_out.log"), encoding="utf-8").read().strip())
