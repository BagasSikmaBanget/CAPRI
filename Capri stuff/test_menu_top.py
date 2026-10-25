import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re

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

out = open(os.path.join(LOG, "mtop_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "mtop_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
u.GetWindowLongW.restype = ctypes.c_long
u.WindowFromPoint.argtypes = [wt.POINT]
u.WindowFromPoint.restype = wt.HWND
u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def crect(h):
    r = wt.RECT(); u.GetClientRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def cls(h):
    b = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, b, 64)
    return b.value

h = None
for _ in range(100):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
time.sleep(0.5)
pr = rect(h); cr = crect(h)
lp = ((cr[3] // 2) << 16) | (cr[2] // 2)
u.SendMessageW(h, 0x0201, 1, lp)
u.SendMessageW(h, 0x0202, 0, lp)
m = None
for _ in range(40):
    m = u.FindWindowW("#32768", None)
    if m and u.IsWindowVisible(m):
        break
    time.sleep(0.05)
mr = rect(m)
print("pet", pr, "menu", mr, "menu class", cls(m))
print("menu exstyle", hex(u.GetWindowLongW(m, -20)), "topmost", bool(u.GetWindowLongW(m, -20) & 0x8))
pt = wt.POINT(pr[0] + 120, pr[1] + 20)
w = u.WindowFromPoint(pt)
print("overlap point", (pt.x, pt.y), "->", cls(w), "is menu:", w == m, "is pet:", w == h)
time.sleep(1.6)
w2 = u.WindowFromPoint(pt)
print("after 1.6s ->", cls(w2), "is menu:", w2 == m, "is pet:", w2 == h)
u.PostMessageW(h, 0x0010, 0, 0)
try:
    code = p.wait(timeout=8)
except subprocess.TimeoutExpired:
    p.kill(); code = "timeout"
out.close(); err.close()
open(CFG, "w", encoding="utf-8").write(backup)
print("exit", code)
print("stderr:", open(os.path.join(LOG, "mtop_err.log"), encoding="utf-8").read().strip())
