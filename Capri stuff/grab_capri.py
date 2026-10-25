import ctypes
import ctypes.wintypes as wt
import sys
from PIL import ImageGrab

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]


class R(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(R)]
h = u.FindWindowW("CapriPetWindow", None)
if not h:
    print("window not found")
    sys.exit(1)
r = R()
u.GetWindowRect(h, ctypes.byref(r))
pad = 16
box = (r.l - pad, r.t - pad, r.r + pad, r.b + pad)
print("rect", r.l, r.t, r.r, r.b)
ImageGrab.grab(bbox=box, all_screens=True).save(sys.argv[1])
print("saved", sys.argv[1])
