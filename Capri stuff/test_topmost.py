import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re
from PIL import ImageGrab
import tkinter as tk

APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)
backup = open(CFG, encoding="utf-8-sig").read()

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)

test = backup
for k, v in [("IDLE_MIN", "30"), ("IDLE_MAX", "40"), ("IDLE2_CHANCE", "0")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "top_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "top_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
u.GetWindowLongW.restype = ctypes.c_long

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

h = None
for _ in range(100):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
time.sleep(0.6)
pr = rect(h)
print("pet", h, pr)
ex = u.GetWindowLongW(h, -20)
print("WS_EX_TOPMOST set:", bool(ex & 0x00000008))

cx = (pr[0] + pr[2]) // 2
cy = pr[1] + (pr[3] - pr[1]) // 5
def sample():
    im = ImageGrab.grab(bbox=(cx - 2, cy - 2, cx + 3, cy + 3))
    px = list(im.get_flattened_data())
    return tuple(sum(c[i] for c in px) // len(px) for i in range(3))

base = sample()
print("baseline color at", (cx, cy), base)

w, hgt = pr[2] - pr[0], pr[3] - pr[1]
root = tk.Tk()
root.overrideredirect(True)
root.geometry(f"{w}x{hgt}+{pr[0]}+{pr[1]}")
root.configure(bg="#ff0000")
root.update()
time.sleep(0.4)
root.update()
normal = sample()
print("normal window over pet -> sample", normal)

root.attributes("-topmost", True)
root.update()
time.sleep(0.4)
root.update()
top = sample()
print("topmost window over pet -> sample", top)

t = time.time()
while time.time() - t < 1.8:
    root.update()
    time.sleep(0.1)
after = sample()
print("after re-assert -> sample", after)

root.destroy()
time.sleep(0.2)
restored = sample()
print("after close -> sample", restored)

u.PostMessageW(h, 0x0010, 0, 0)
try:
    code = p.wait(timeout=8)
except subprocess.TimeoutExpired:
    p.kill(); code = "timeout"
out.close(); err.close()
open(CFG, "w", encoding="utf-8").write(backup)
print("exit", code)
print("stderr:", open(os.path.join(LOG, "top_err.log"), encoding="utf-8").read().strip())
