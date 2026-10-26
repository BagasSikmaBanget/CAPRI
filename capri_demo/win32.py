"""Win32 glue shared by the pet: layered window, hit-testing and screen info.

Taken from CAPRI's capri.py so the new app keeps the same transparent,
click-through, always-on-top behaviour.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LONG = ctypes.c_long
UINT = ctypes.c_uint
WORD = ctypes.c_ushort
DWORD = ctypes.c_ulong
BYTE = ctypes.c_ubyte
LRESULT = ctypes.c_ssize_t

ULW_ALPHA = 0x00000002
GW_HWNDPREV = 3
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
CREATE_NO_WINDOW = 0x08000000

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = wt.HWND(-1)

SM_CXSCREEN = 0
SM_CYSCREEN = 1

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_CAPTURECHANGED = 0x0215
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HTCLIENT = 1
CS_DBLCLKS = 0x0008

SPI_GETWORKAREA = 0x0030


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", BYTE),
        ("BlendFlags", BYTE),
        ("SourceConstantAlpha", BYTE),
        ("AlphaFormat", BYTE),
    ]


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", LONG), ("cy", LONG)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND),
        ("message", UINT),
        ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM),
        ("time", DWORD),
        ("pt", POINT),
    ]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.GetConsoleWindow.argtypes = []
kernel32.GetConsoleWindow.restype = wt.HWND

gdi32.CreateDIBSection.argtypes = [
    wt.HDC,
    ctypes.POINTER(BITMAPINFO),
    UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wt.HANDLE,
    DWORD,
]
gdi32.CreateDIBSection.restype = wt.HANDLE
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
gdi32.SelectObject.restype = wt.HANDLE
gdi32.DeleteObject.argtypes = [wt.HANDLE]
gdi32.DeleteDC.argtypes = [wt.HDC]

user32.CreateWindowExW.argtypes = [
    DWORD, wt.LPCWSTR, wt.LPCWSTR, DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.ATOM
user32.DefWindowProcW.argtypes = [wt.HWND, UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wt.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wt.BOOL
kernel32.GetTickCount.argtypes = []
kernel32.GetTickCount.restype = DWORD
user32.SystemParametersInfoW.argtypes = [UINT, UINT, ctypes.c_void_p, UINT]
user32.SystemParametersInfoW.restype = wt.BOOL
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, UINT, UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
user32.VkKeyScanW.restype = ctypes.c_short
user32.UpdateLayeredWindow.argtypes = [
    wt.HWND,
    wt.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wt.HDC,
    ctypes.POINTER(POINT),
    DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    DWORD,
]
user32.UpdateLayeredWindow.restype = wt.BOOL
user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(POINT)]
user32.ScreenToClient.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, UINT, UINT, UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.SetWindowPos.argtypes = [
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, UINT
]
user32.SetWindowPos.restype = wt.BOOL
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, UINT]
user32.GetWindow.restype = wt.HWND
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.SetCapture.argtypes = [wt.HWND]
user32.SetCapture.restype = wt.HWND
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wt.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wt.BOOL

gdi32.CreateSolidBrush.argtypes = [DWORD]
gdi32.CreateSolidBrush.restype = wt.HBRUSH


def set_dpi_aware() -> None:
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def work_area() -> RECT:
    r = RECT()
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
        r.left, r.top = 0, 0
        r.right = user32.GetSystemMetrics(SM_CXSCREEN)
        r.bottom = user32.GetSystemMetrics(SM_CYSCREEN)
    return r


def cursor_pos() -> tuple[int, int]:
    p = POINT()
    if user32.GetCursorPos(ctypes.byref(p)):
        return p.x, p.y
    return 0, 0


def system_idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    elapsed = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed / 1000.0
