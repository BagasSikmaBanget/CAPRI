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

out = open(os.path.join(LOG, "diag_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "diag_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def info(h):
    cls = ctypes.create_unicode_buffer(256)
    txt = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, cls, 256)
    u.GetWindowTextW(h, txt, 256)
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return cls.value, txt.value, pid.value, rect(h), bool(u.IsWindowVisible(h))

def windows_of(pid):
    found = []
    @EnumProc
    def cb(h, _l):
        if info(h)[2] == pid:
            found.append((h, info(h)))
        return True
    u.EnumWindows(cb, 0)
    return found

def lparam(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
print("pet", h, rect(h))

try:
    r = u.SendMessageW(h, 0x0201, 1, lparam(60, 70))
    print("send down ->", r, "err", ctypes.get_last_error())
    r = u.SendMessageW(h, 0x0202, 0, lparam(60, 70))
    print("send up ->", r, "err", ctypes.get_last_error())
    time.sleep(1.0)
    ImageGrab.grab().save(os.path.join(LOG, "diag_menu.png"))
    for wh, wi in windows_of(p.pid):
        print("win", wh, wi)
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
print("stderr:", open(os.path.join(LOG, "diag_err.log"), encoding="utf-8").read().strip())
print("stdout:", open(os.path.join(LOG, "diag_out.log"), encoding="utf-8").read().strip())
