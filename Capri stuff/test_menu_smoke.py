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

out = open(os.path.join(LOG, "msmoke_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "msmoke_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def crect(h):
    r = wt.RECT(); u.GetClientRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
pr = rect(h); cr = crect(h)
print("pet", h, pr, "client", cr)

lp = ((cr[3] // 2) << 16) | (cr[2] // 2)
try:
    u.SendMessageW(h, 0x0201, 1, lp)
    u.SendMessageW(h, 0x0202, 0, lp)
    m = None
    for _ in range(40):
        m = u.FindWindowW("#32768", None)
        if m and u.IsWindowVisible(m):
            break
        time.sleep(0.05)
    print("menu open:", bool(m and u.IsWindowVisible(m)), rect(m) if m else None)
    print("chat open:", bool(u.FindWindowW("TkTopLevel", None)))
    u.PostMessageW(h, 0x0010, 0, 0)
    try:
        code = p.wait(timeout=8)
    except subprocess.TimeoutExpired:
        p.kill(); code = "timeout"
finally:
    open(CFG, "w", encoding="utf-8").write(backup)
    out.close(); err.close()

time.sleep(0.3)
print("exit", code)
print("stderr:", open(os.path.join(LOG, "msmoke_err.log"), encoding="utf-8").read().strip())
print("leftover menu:", bool(u.FindWindowW("#32768", None)))
print("leftover tk:", bool(u.FindWindowW("TkTopLevel", None)))
print("leftover pet:", bool(u.FindWindowW("CapriPetWindow", None)))
print("leftover glitch:", bool(u.FindWindowW("CapriGlitchWindow", None)))
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
