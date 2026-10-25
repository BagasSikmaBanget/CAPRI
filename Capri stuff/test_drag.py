import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil

APP = r"C:\Users\aab06\Documents\CAPRI"
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)
out = open(os.path.join(LOG, "drag_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "drag_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

def rect(h):
    r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return (r.left, r.top, r.right, r.bottom)

h = None
for _ in range(60):
    h = u.FindWindowW("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
if not h:
    print("no window"); p.kill(); sys.exit(1)

time.sleep(1.5)
r0 = rect(h)
print("rect before", r0)
cx = (r0[0] + r0[2]) // 2
cy = (r0[1] + r0[3]) // 2
orig = wt.POINT(); u.GetCursorPos(ctypes.byref(orig))
u.SetCursorPos(cx, cy); time.sleep(0.15)
u.mouse_event(0x0002, 0, 0, 0, None)  # left down
for i in range(1, 11):
    u.SetCursorPos(cx + 20 * i, cy - 10 * i)
    time.sleep(0.03)
u.mouse_event(0x0004, 0, 0, 0, None)  # left up
time.sleep(0.5)
r1 = rect(h)
print("rect after ", r1)
print("delta", (r1[0]-r0[0], r1[1]-r0[1]))
u.SetCursorPos(orig.x, orig.y)
u.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
try:
    code = p.wait(timeout=8)
except subprocess.TimeoutExpired:
    p.kill(); code = "timeout"
print("exit", code)
out.close(); err.close()
print("stderr:", open(os.path.join(LOG,"drag_err.log"), encoding="utf-8").read().strip())
print("stdout:", open(os.path.join(LOG,"drag_out.log"), encoding="utf-8").read().strip())
