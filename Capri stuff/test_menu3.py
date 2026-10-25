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

out = open(os.path.join(LOG, "menu3_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "menu3_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.SendMessageW.restype = ctypes.c_ssize_t

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def lparam(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)

def click(h, cx, cy, hover=False):
    if hover:
        u.SendMessageW(h, 0x0200, 0, lparam(cx, cy))
        time.sleep(0.15)
    u.SendMessageW(h, 0x0201, 1, lparam(cx, cy))
    time.sleep(0.08)
    u.SendMessageW(h, 0x0202, 0, lparam(cx, cy))

def find_menu():
    m = u.FindWindowW("#32768", None)
    return m if m and u.IsWindowVisible(m) else None

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
print("pet", h, rect(h))

try:
    click(h, 60, 70)
    time.sleep(0.7)
    m = find_menu()
    print("menu", m, rect(m) if m else None)
    if not m:
        raise SystemExit("menu did not open")
    mr = rect(m)
    mh = mr[3] - mr[1]
    print("menu client h", mh)

    click(m, 60, 30, hover=True)
    time.sleep(1.5)
    chat = u.FindWindowW("TkTopLevel", None)
    vis = bool(chat) and bool(u.IsWindowVisible(chat))
    print("chat visible after item 1:", vis)
    if not vis:
        for yy in (28, 32, 34):
            click(m, 60, yy, hover=True)
            time.sleep(1.0)
            vis = bool(chat) and bool(u.IsWindowVisible(chat))
            print("retry y", yy, "->", vis)
            if vis:
                break
    ImageGrab.grab().save(os.path.join(LOG, "menu3_chat.png"))

    click(h, 60, 70)
    time.sleep(0.7)
    m = find_menu()
    print("menu again", m, rect(m) if m else None)
    if m:
        click(m, 60, mh - 31, hover=True)
        time.sleep(1.6)
    print("still running:", p.poll() is None)
    ImageGrab.grab().save(os.path.join(LOG, "menu3_after_close.png"))
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
print("stderr:", open(os.path.join(LOG, "menu3_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG, "menu3_out.log"), encoding="utf-8").read().strip())
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))

