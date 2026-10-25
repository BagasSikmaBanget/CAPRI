import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil

APP = r"C:\Users\aab06\Documents\CAPRI"
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
out = open(os.path.join(LOG, "smoke_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "smoke_err.log"), "w", encoding="utf-8")
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
    u.SetCursorPos(int(x), int(y)); time.sleep(0.12)
    u.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(0.06)
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
print("pet", pr, "topmost:", bool(u.GetWindowLongW(h, -20) & 0x00000008))

try:
    click(*pet_pt); time.sleep(0.7)
    m = menu()
    print("menu:", bool(m), rect(m) if m else None)
    if m:
        click(rect(m)[0] + 20, rect(m)[1] + 10)
    time.sleep(0.5)
    print("x closed:", not bool(menu()), "alive:", p.poll() is None)
    click(*pet_pt); time.sleep(0.7)
    print("reopen:", bool(menu()))
    if menu():
        click(rect(menu())[0] + 20, rect(menu())[1] + 10)
    time.sleep(0.4)
finally:
    u.SetCursorPos(orig[0], orig[1])
    if p.poll() is None:
        u.PostMessageW(h, 0x0312, 1, 0)
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
    out.close(); err.close()

print("exit", p.returncode, "stderr", repr(open(os.path.join(LOG, "smoke_err.log"), encoding="utf-8").read().strip()))
print("ffmpeg left:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/NH"], capture_output=True, text=True).stdout.strip()[:80])
