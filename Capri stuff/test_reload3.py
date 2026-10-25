import ctypes, ctypes.wintypes as wt, subprocess, sys, time, os, shutil
APP = r"C:\Users\aab06\Documents\CAPRI"
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
out = open(os.path.join(LOG, "reload3_out.log"), "w", encoding="utf-8")
err = open(os.path.join(LOG, "reload3_err.log"), "w", encoding="utf-8")
pyw = shutil.which("pythonw") or sys.executable
p = subprocess.Popen([pyw, "capri.py"], cwd=APP, stdout=out, stderr=err)
u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
h = None
for _ in range(80):
    h = u.FindWindowW("CapriPetWindow", None)
    if h: break
    time.sleep(0.1)
time.sleep(0.8)
print("post reload", u.PostMessageW(h, 0x0312, 2, 0))
time.sleep(1.5)
u.PostMessageW(h, 0x0010, 0, 0)
try: code = p.wait(timeout=10)
except subprocess.TimeoutExpired: p.kill(); code = "timeout"
out.close(); err.close()
print("exit", code)
print("stderr:", open(os.path.join(LOG,"reload3_err.log"), encoding="utf-8").read().strip())
print("stdout:")
print(open(os.path.join(LOG,"reload3_out.log"), encoding="utf-8").read().strip())
