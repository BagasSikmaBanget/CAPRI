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

out = open(os.path.join(LOG, "menu4_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "menu4_err.log"), "w", encoding="utf-8")
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
pr = rect(h)
print("pet", h, pr)

try:
    pet_pt = ((pr[0] + pr[2]) // 2 - 29, pr[3] - 19)
    print("click pet at", pet_pt)
    click(*pet_pt)
    time.sleep(0.9)
    m = find_menu()
    print("menu", m, rect(m) if m else None)
    if not m:
        raise SystemExit("menu did not open")
    mr = rect(m)
    ix = mr[0] + 60
    click(ix, mr[1] + 30)
    time.sleep(1.5)
    chat = u.FindWindowW("TkTopLevel", None)
    vis = bool(chat) and bool(u.IsWindowVisible(chat))
    print("chat visible:", vis, rect(chat) if chat else None)
    ImageGrab.grab().save(os.path.join(LOG, "menu4_chat.png"))

    click(*pet_pt)
    time.sleep(0.9)
    m = find_menu()
    print("menu again", m, rect(m) if m else None)
    if m:
        mr = rect(m)
        click(mr[0] + 60, mr[3] - 31)
        time.sleep(1.6)
    print("still running:", p.poll() is None)
    ImageGrab.grab().save(os.path.join(LOG, "menu4_after_close.png"))
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
print("stderr:", open(os.path.join(LOG, "menu4_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG, "menu4_out.log"), encoding="utf-8").read().strip())
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
