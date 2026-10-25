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

out = open(os.path.join(LOG, "menu2_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "menu2_err.log"), "w", encoding="utf-8")
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

def lparam(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)

def post_click(h, cx, cy):
    u.PostMessageW(h, 0x0201, 1, lparam(cx, cy))
    time.sleep(0.06)
    u.PostMessageW(h, 0x0202, 0, lparam(cx, cy))

def key(vk):
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    u.keybd_event(vk, 0, 0x0002, 0)

def log():
    try:
        return open(os.path.join(LOG, "menu2_out.log"), encoding="utf-8").read()
    except OSError:
        return ""

def chat_open():
    txt = log()
    return "chat opened" in txt and txt.rfind("chat opened") > txt.rfind("chat closed")

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h and rect(h)[2] - rect(h)[0] > 50:
        break
    time.sleep(0.1)
print("pet hwnd", h, "rect", rect(h))

try:
    post_click(h, 60, 70)
    time.sleep(0.9)
    ImageGrab.grab().save(os.path.join(LOG, "menu2_open.png"))
    print("log after click:", repr(log()[-200:]))
    print("chat after menu popup:", chat_open())

    key(0x28); key(0x0D)
    time.sleep(1.4)
    print("chat after Down+Enter:", chat_open())
    ImageGrab.grab().save(os.path.join(LOG, "menu2_chat.png"))

    if chat_open():
        key(0x1B)
        time.sleep(0.8)
        print("chat after Escape:", chat_open())

    post_click(h, 60, 70)
    time.sleep(0.8)
    key(0x23); key(0x0D)
    time.sleep(1.2)
    print("still running after End+Enter:", p.poll() is None)
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
print("stderr:", open(os.path.join(LOG, "menu2_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG, "menu2_out.log"), encoding="utf-8").read().strip())
