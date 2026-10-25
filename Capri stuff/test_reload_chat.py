import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil
APP = r"C:\Users\aab06\Documents\CAPRI"
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)
out = open(os.path.join(LOG, "reload_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "reload_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)
u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_void_p]

def find(cls, title):
    return u.FindWindowW(cls, title)

h = None
for _ in range(80):
    h = find("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
time.sleep(1.0)
print("pet hwnd", h)

# reload hotkey
u.keybd_event(0x11, 0, 0, None)   # ctrl
u.keybd_event(0x12, 0, 0, None)   # alt
u.keybd_event(0x52, 0, 0, None)   # R
time.sleep(0.05)
u.keybd_event(0x52, 0, 2, None)
u.keybd_event(0x12, 0, 2, None)
u.keybd_event(0x11, 0, 2, None)
time.sleep(1.2)

# double click pet center
r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
cx, cy = (r.left+r.right)//2, (r.top+r.bottom)//2
orig = wt.POINT(); u.GetCursorPos(ctypes.byref(orig))
u.SetCursorPos(cx, cy); time.sleep(0.15)
for _ in range(2):
    u.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.03)
    u.mouse_event(0x0004, 0, 0, 0, None)
    time.sleep(0.06)
time.sleep(1.2)
chat = find(None, "capri")
print("chat hwnd", chat, "visible", bool(chat) and bool(u.IsWindowVisible(chat)))
# close it again
u.SetCursorPos(cx, cy); time.sleep(0.1)
for _ in range(2):
    u.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.03)
    u.mouse_event(0x0004, 0, 0, 0, None)
    time.sleep(0.06)
time.sleep(0.8)
print("chat hwnd after close", find(None, "capri"), "visible", bool(u.IsWindowVisible(chat)) if chat else None)
u.SetCursorPos(orig.x, orig.y)
u.PostMessageW(h, 0x0010, 0, 0)
try: code = p.wait(timeout=10)
except subprocess.TimeoutExpired: p.kill(); code = "timeout"
out.close(); err.close()
print("exit", code)
print("stderr:", open(os.path.join(LOG,"reload_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG,"reload_out.log"), encoding="utf-8").read().strip())
