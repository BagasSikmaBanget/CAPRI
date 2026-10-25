import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil

APP = r"C:\Users\aab06\Documents\CAPRI"
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
os.makedirs(LOG, exist_ok=True)

out = open(os.path.join(LOG, "final2_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "final2_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]

h = None
for _ in range(120):
    h = u.FindWindowW("CapriPetWindow", None)
    if h:
        r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        if r.right - r.left > 50:
            break
    time.sleep(0.1)

time.sleep(2.5)
u.PostMessageW(h, 0x0312, 1, 0)
try:
    code = p.wait(timeout=10)
except subprocess.TimeoutExpired:
    p.kill(); code = "timeout"
out.close(); err.close()
print("exit", code)
print("stderr:", repr(open(os.path.join(LOG, "final2_err.log"), encoding="utf-8").read().strip()))
print("stdout:", open(os.path.join(LOG, "final2_out.log"), encoding="utf-8").read().strip())
print("leftover ffmpeg:", subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"], capture_output=True, text=True).stdout.count("ffmpeg.exe"))
