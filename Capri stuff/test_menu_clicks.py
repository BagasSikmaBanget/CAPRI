import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil, re

APP = r"C:\Users\aab06\Documents\CAPRI"
CFG = os.path.join(APP, "capri_config.txt")
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
backup = open(CFG, encoding="utf-8-sig").read()

def setcfg(text, key, value):
    return re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", text)

test = backup
for k, v in [("IDLE_MIN", "30"), ("IDLE_MAX", "40"), ("IDLE2_CHANCE", "0"), ("GLITCH_ENABLED", "false")]:
    test = setcfg(test, k, v)
open(CFG, "w", encoding="utf-8").write(test)

out = open(os.path.join(LOG, "mc_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "mc_err.log"), "w", encoding="utf-8")
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

def click(x, y):
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.12)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    u.mouse_event(0x0004, 0, 0, 0, 0)

def menu():
    m = u.FindWindowW("#32768", None)
    return m if m and u.IsWindowVisible(m) else None

pt = wt.POINT(); u.GetCursorPos(ctypes.byref(pt)); orig = (pt.x, pt.y)
h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
pr = rect(h)
pet_pt = ((pr[0] + pr[2]) // 2 - 29, pr[3] - 19)
print("pet", pr)

try:
    click(*pet_pt); time.sleep(0.7)
    print("open1:", bool(menu()))
    click(*pet_pt); time.sleep(0.7)
    m = menu()
    print("after click on pet while menu open -> open:", bool(m), rect(m) if m else None)
    if m:
        click(rect(m)[0] + 20, rect(m)[1] + 10); time.sleep(0.5)
    print("closed:", not bool(menu()))
    time.sleep(1.2)
    print("still closed:", not bool(menu()))

    for i in range(3):
        click(*pet_pt)
        time.sleep(0.12)
    time.sleep(0.8)
    n = 0
    m = menu()
    print("after 3 fast pet clicks -> menu:", bool(m), "count:", 1 if m else 0)
    if m:
        click(rect(m)[0] + 20, rect(m)[1] + 10)
    time.sleep(1.2)
    print("after x -> menu:", bool(menu()), "alive:", p.poll() is None)
finally:
    u.SetCursorPos(orig[0], orig[1])
    open(CFG, "w", encoding="utf-8").write(backup)
    if p.poll() is None:
        u.PostMessageW(h, 0x0010, 0, 0)
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
    out.close(); err.close()

print("exit", p.returncode, "stderr", repr(open(os.path.join(LOG, "mc_err.log"), encoding="utf-8").read().strip()))
