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

out = open(os.path.join(LOG, "menu_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "menu_err.log"), "w", encoding="utf-8")
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
    time.sleep(0.08)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)

def key(vk):
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    u.keybd_event(vk, 0, 0x0002, 0)

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h:
        r = rect(h)
        if r[2] - r[0] > 50:
            break
    time.sleep(0.1)
print("pet hwnd", h, "rect", rect(h))

def chat_open():
    try:
        txt = open(os.path.join(LOG, "menu_out.log"), encoding="utf-8").read()
    except OSError:
        return False
    return "chat opened" in txt and txt.rfind("chat opened") > txt.rfind("chat closed")
try:
    pr = rect(h)
    cx, cy = (pr[0] + pr[2]) // 2, (pr[1] + pr[3]) // 2
    print("click at", cx, cy)
    click(cx, cy)
    time.sleep(0.9)
    ImageGrab.grab().save(os.path.join(LOG, "menu_open.png"))
    print("chat after menu popup:", chat_open())

    key(0x28)   # Down -> first enabled item ("talk to capri")
    key(0x0D)   # Enter
    time.sleep(1.4)
    c = chat_open()
    print("chat after Down+Enter:", c)
    ImageGrab.grab().save(os.path.join(LOG, "menu_after_chat.png"))

    if not c:
        click(cx, cy)
        time.sleep(0.8)
        click(cx + 60, cy + 34)
        time.sleep(1.4)
        c = chat_open()
        print("chat after item click:", c)

    if c:
        key(0x1B)   # Escape closes chat
        time.sleep(0.8)
        print("chat after Escape:", chat_open())

    click(cx, cy)
    time.sleep(0.8)
    key(0x23)   # End -> last item ("close the pet")
    key(0x0D)   # Enter
    time.sleep(1.2)
    print("still running after End+Enter:", p.poll() is None)
    if p.poll() is None:
        click(cx, cy)
        time.sleep(0.8)
        click(cx + 60, cy + 118)
        time.sleep(1.2)
        print("still running after item click:", p.poll() is None)
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
print("stderr:", open(os.path.join(LOG, "menu_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG, "menu_out.log"), encoding="utf-8").read().strip())
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))

