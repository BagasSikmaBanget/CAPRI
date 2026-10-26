"""A small Win32 window watcher, ported from capri-desktop's windows.js.

capri-desktop spawns a PowerShell helper that lists the other top-level
windows so Capri can sit on them, point at them or possess them. Here the
same information comes straight from user32: a z-ordered list of visible
windows with their rectangles, process names and titles.

Nothing is read from the windows themselves - only geometry, title and the
process image name - so the pet never needs to look inside another app.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

from .win32 import RECT, kernel32, user32, work_area

GWL_STYLE = -16
WS_MAXIMIZE = 0x01000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindow.restype = wt.BOOL

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL

GA_ROOT = 2
SHELL_CLASSES = {
    "progman",
    "workerw",
    "shell_traywnd",
    "traynotifywnd",
    "windows.ui.core.corewindow",
    "applicationframewindow",
    "inputswitch",
    "tasklistthumnailclass",
    "multitaskingviewframe",
}
IGNORED_EXES = {"textinputhost.exe", "shellexperiencehost.exe", "searchapp.exe"}


class Rect:
    __slots__ = ("left", "top", "right", "bottom")

    def __init__(self, left: int, top: int, right: int, bottom: int):
        self.left, self.top = int(left), int(top)
        self.right, self.bottom = int(right), int(bottom)

    @property
    def w(self) -> int:
        return self.right - self.left

    @property
    def h(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Rect({self.left},{self.top},{self.w}x{self.h})"


class WindowInfo:
    __slots__ = (
        "hwnd", "x", "y", "w", "h", "title", "cls", "pid", "exe",
        "maximized", "z", "visible",
    )

    def __init__(self, hwnd, rect: Rect, title: str, cls: str, pid: int, exe: str,
                 maximized: bool, z: int):
        self.hwnd = int(hwnd)
        self.x, self.y, self.w, self.h = rect.left, rect.top, rect.w, rect.h
        self.title = title
        self.cls = cls
        self.pid = pid
        self.exe = exe
        self.maximized = maximized
        self.z = z
        self.visible = True

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.x + self.w, self.y + self.h)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"WindowInfo({self.hwnd:#x}, {self.title!r}, {self.exe!r})"


def _window_text(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _rect_of(hwnd) -> Rect | None:
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return Rect(r.left, r.top, r.right, r.bottom)


def _own_window(cls: str) -> bool:
    return cls.startswith("CapriDemo")


def _collect() -> list[WindowInfo]:
    found: list[WindowInfo] = []
    counter = 0

    def callback(hwnd, _lparam):
        nonlocal counter
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
            if root != hwnd:
                return True
            cls = _class_name(hwnd)
            if _own_window(cls) or cls.lower() in SHELL_CLASSES:
                return True
            rect = _rect_of(hwnd)
            if rect is None or rect.w < 80 or rect.h < 60:
                return True
            title = _window_text(hwnd).strip()
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe = _process_name(pid.value)
            if exe.lower() in IGNORED_EXES:
                return True
            if not title and exe.lower() != "explorer.exe":
                return True
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            maximized = bool(style & WS_MAXIMIZE)
            found.append(
                WindowInfo(hwnd, rect, title, cls, pid.value, exe, maximized, counter)
            )
            counter += 1
        except Exception:  # noqa: BLE001
            pass
        return True

    cb = WNDENUMPROC(callback)
    user32.EnumWindows(cb, 0)
    return found


_cache: tuple[float, list[WindowInfo]] = (0.0, [])


def list_windows(max_age: float = 0.45) -> list[WindowInfo]:
    """Top-level windows, front to back. Cached briefly (EnumWindows is cheap)."""
    global _cache
    now = time.perf_counter()
    stamp, windows = _cache
    if now - stamp <= max_age and windows:
        return windows
    windows = _collect()
    _cache = (now, windows)
    return windows


def foreground() -> WindowInfo | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    for win in list_windows():
        if win.hwnd == int(hwnd):
            return win
    rect = _rect_of(hwnd)
    if rect is None:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(
        hwnd, rect, _window_text(hwnd).strip(), _class_name(hwnd),
        pid.value, _process_name(pid.value), False, -1,
    )


def by_hwnd(hwnd) -> WindowInfo | None:
    if not hwnd:
        return None
    h = int(hwnd)
    for win in list_windows():
        if win.hwnd == h:
            return win
    rect = _rect_of(hwnd)
    if rect is None:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(
        hwnd, rect, _window_text(hwnd).strip(), _class_name(hwnd),
        pid.value, _process_name(pid.value), False, -1,
    )


def find_claude_window(preferred: int | None = None) -> WindowInfo | None:
    """The window most likely to be running Claude Code."""
    wins = list_windows()
    if preferred:
        for win in wins:
            if win.hwnd == int(preferred):
                return win
    for win in wins:
        title = win.title.lower()
        exe = win.exe.lower()
        if "claude" in title or "claude" in exe:
            return win
    for win in wins:
        title = win.title.lower()
        if "terminal" in title or "powershell" in title or "cmd" in title:
            if "code" not in title:
                continue
            return win
    return None


def find_explorer_window(name: str = "") -> WindowInfo | None:
    needle = name.lower()
    for win in list_windows():
        if win.exe.lower() != "explorer.exe":
            continue
        title = win.title.lower()
        if "program manager" in title:
            continue
        if not needle or needle in title or "file explorer" in title:
            return win
    return None


def tray_rect() -> Rect:
    """Where the notification icons live, as a small target rect."""
    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    tray = user32.FindWindowW("TrayNotifyWnd", None)
    target = tray or taskbar
    rect = _rect_of(target) if target else None
    if rect is not None and rect.w > 20 and rect.h > 20:
        if rect.w > rect.h:
            # horizontal taskbar: a little block just left of the clock
            left = max(rect.left, rect.right - 150)
            return Rect(left, rect.top + 3, rect.right - 4, rect.bottom - 3)
        return Rect(rect.left + 3, max(rect.top, rect.bottom - 150), rect.right - 3, rect.bottom - 4)
    work = work_area()
    return Rect(work.right - 120, work.bottom - 42, work.right - 8, work.bottom - 6)


def taskbar_rect() -> Rect | None:
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    return _rect_of(hwnd) if hwnd else None


def open_folder(path: str) -> bool:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False
