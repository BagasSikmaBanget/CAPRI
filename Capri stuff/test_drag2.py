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
for k, v in [("IDLE_MIN", "30"), ("IDLE_MAX", "40"), ("IDLE2_CHANCE", "0"), ("GLITCH_ENABLED", "false")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "drag2_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "drag2_err.log"), "w", encoding="utf-8")
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

def find_menu():
    m = u.FindWindowW("#32768", None)
    return m if m and u.IsWindowVisible(m) else None

pt = wt.POINT()
u.GetCursorPos(ctypes.byref(pt))
orig = (pt.x, pt.y)

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
before = rect(h)
print("pet", h, before)

try:
    x0 = (before[0] + before[2]) // 2 - 29
    y0 = before[3] - 19
    u.SetCursorPos(x0, y0)
    time.sleep(0.2)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    for i in range(1, 11):
        u.SetCursorPos(x0 + 15 * i, y0 - 8 * i)
        time.sleep(0.03)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.6)
    after = rect(h)
    print("after drag", after, "delta", (after[0] - before[0], after[1] - before[1]))
    print("menu visible after drag:", bool(find_menu()))
    ImageGrab.grab().save(os.path.join(LOG, "drag2_after.png"))

    u.SetCursorPos(after[2] - 60, after[3] - 19)
    time.sleep(0.2)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.8)
    print("menu visible after click:", bool(find_menu()))
    ImageGrab.grab().save(os.path.join(LOG, "drag2_menu.png"))

    u.PostMessageW(h, 0x0312, 2, 0)
    time.sleep(1.2)
    print("after reload menu:", bool(find_menu()), "rect", rect(h))
    ImageGrab.grab().save(os.path.join(LOG, "drag2_reload.png"))
finally:
    u.SetCursorPos(orig[0], orig[1])
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
print("stderr:", open(os.path.join(LOG, "drag2_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG, "drag2_out.log"), encoding="utf-8").read().strip())
