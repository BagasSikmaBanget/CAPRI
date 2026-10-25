import ctypes
import ctypes.wintypes as wt
import time
from PIL import ImageGrab

u = ctypes.WinDLL("user32", use_last_error=True)
u.FindWindowW.restype = wt.HWND
u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


class R(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(R)]

orig = wt.POINT()
u.GetCursorPos(ctypes.byref(orig))
h = u.FindWindowW("CapriPetWindow", None)
r = R()
u.GetWindowRect(h, ctypes.byref(r))
pad = 12
box = (r.l - pad, r.t - pad, r.r + pad, r.b + pad)

try:
    for name, pos in (("ul", (150, 120)), ("ur", (1750, 120))):
        u.SetCursorPos(*pos)
        time.sleep(1.2)
        ImageGrab.grab(bbox=box, all_screens=True).save(
            f"C:\\Users\\aab06\\AppData\\Local\\Temp\\opencode\\capri_dbg\\eyes_{name}.png"
        )
        print("saved", name)
finally:
    u.SetCursorPos(orig.x, orig.y)
    print("cursor restored", orig.x, orig.y)
