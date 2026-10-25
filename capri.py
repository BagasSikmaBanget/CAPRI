"""Capri - a small transparent desktop pet.

Idle 1 is drawn as eyeline.png + eyeballs.png so the eyes can slide around;
now and then she watches the cursor. Idle 2 is the rare full-body pose, and
walk1.png is used for walking. No sound, no tray icon.

Quit with  Ctrl+Alt+Q   (configurable)
Reload art/config with  Ctrl+Alt+R
Drag her anywhere to move her.
Left-click her for a small menu: "say something" loops the talking art inside
a glitching colour-cycling border and shows a random words.txt line in a speech
bubble; "talk to capri" opens the chat box.

Every action change is hidden behind a glitch distortion
(action/glitch.mp4) that runs over her body for about a second first.

Runs on the standard library + Pillow, plus ffmpeg for the glitch clip.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from chat import ChatWindow

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- Win32 glue

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


# --------------------------------------------------------------- config read


def read_config(path: str) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not os.path.isfile(path):
        return cfg
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            if line.startswith(">>") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            cfg[key.strip().upper()] = val.split("#", 1)[0].strip()
    return cfg


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class Settings:
    def __init__(self, cfg: dict[str, str]):
        def num(key, default, cast=float):
            try:
                return cast(cfg.get(key, default))
            except (TypeError, ValueError):
                return cast(default)

        def flag(key, default):
            return cfg.get(key, default).lower() in ("1", "true", "yes", "on")

        def path_of(key, default):
            value = cfg.get(key, default).replace("\\", "/")
            return value if os.path.isabs(value) else os.path.join(HERE, value)

        self.scale = _clamp(num("SCALE", 0.38), 0.05, 4.0)
        self.idle2_scale = _clamp(num("IDLE2_SCALE", 0.38), 0.05, 4.0)
        self.walk_scale = _clamp(num("WALK_SCALE", 0.38), 0.05, 4.0)

        self.speed = max(10.0, num("WALK_SPEED", 110.0))
        self.margin = _clamp(num("SCREEN_MARGIN", 40.0), 0.0, 2000.0)
        self.walk_min = max(30.0, num("WALK_MIN_DISTANCE", 120.0))
        self.walk_max = max(self.walk_min, num("WALK_MAX_DISTANCE", 420.0))

        self.idle_min = max(0.5, num("IDLE_MIN", 6.0))
        self.idle_max = max(self.idle_min, num("IDLE_MAX", 18.0))
        self.idle2_chance = _clamp(num("IDLE2_CHANCE", 0.15), 0.0, 1.0)
        self.idle2_duration = max(0.5, num("IDLE2_DURATION", 5.0))

        self.eye_track_chance = _clamp(num("EYE_TRACK_CHANCE", 0.5), 0.0, 1.0)
        self.eye_max_shift = _clamp(num("EYE_MAX_SHIFT", 8.0), 0.0, 60.0)
        self.eye_range = max(20.0, num("EYE_RANGE", 240.0))
        self.eye_ease = max(0.5, num("EYE_EASE", 10.0))
        self.eye_track_min = max(0.5, num("EYE_TRACK_MIN", 2.0))
        self.eye_track_max = max(self.eye_track_min, num("EYE_TRACK_MAX", 5.0))
        self.eye_glance_min = max(0.3, num("EYE_GLANCE_MIN", 1.5))
        self.eye_glance_max = max(self.eye_glance_min, num("EYE_GLANCE_MAX", 4.0))

        self.clicks_enabled = flag("ALLOW_CLICKS", "true")
        self.quit_hotkey = cfg.get("QUIT_HOTKEY", "ctrl+alt+q")
        self.reload_hotkey = cfg.get("RELOAD_HOTKEY", "ctrl+alt+r")

        self.glitch_enabled = flag("GLITCH_ENABLED", "true")
        self.glitch_duration = _clamp(num("GLITCH_DURATION", 1.01), 0.05, 30.0)
        self.glitch_fps = int(_clamp(num("GLITCH_FPS", 30), 1, 60))
        self.glitch_ffmpeg = cfg.get("GLITCH_FFMPEG", "").strip()
        self.glitch_file = path_of("GLITCH_FILE", "action/glitch.mp4")

        self.talk_scale = _clamp(num("TALK_SCALE", 0.25), 0.05, 4.0)
        self.talk_bubble_ratio = _clamp(num("TALK_BUBBLE_RATIO", 1.4), 0.3, 6.0)
        self.talk_fps = int(_clamp(num("TALK_FPS", 14), 4, 60))
        self.talk_min_seconds = max(1.0, num("TALK_MIN_SECONDS", 3.0))
        self.talk_max_seconds = max(
            self.talk_min_seconds, num("TALK_MAX_SECONDS", 8.0)
        )
        self.talk_type_cps = max(4.0, num("TALK_TYPE_CPS", 24.0))
        self.talk_hold_seconds = max(0.2, num("TALK_HOLD_SECONDS", 1.8))
        self.talk_file0 = path_of("TALK_FILE_0", "action/talking0.png")
        self.talk_file1 = path_of("TALK_FILE_1", "action/talking1.png")
        self.talk_overlays = [
            path_of(f"TALK_OVERLAY_{i}", f"Capri stuff/Overlay/overlay{i}.png")
            for i in range(3)
        ]
        self.talk_bubble_file = path_of(
            "TALK_BUBBLE_FILE", "Capri stuff/Overlay/OverlayTalk.png"
        )
        self.talk_words_file = path_of("TALK_WORDS_FILE", "words.txt")

        self.eyeline_file = path_of("EYELINE_FILE", "action/eyeline.png")
        self.eye_file = path_of("EYE_FILE", "action/eyeballs.png")
        self.idle2_file = path_of("IDLE2_FILE", "action/Idle2.png")
        self.walk_file = path_of("WALK_FILE", "action/walk1.png")
        self.idle_file = path_of("IDLE_FILE", "action/Idle.png")


# ------------------------------------------------------------------- art


def load_rgba(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def content_box(img: Image.Image, threshold: int = 8) -> tuple[int, int, int, int]:
    mask = img.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    return mask.getbbox() or (0, 0, img.width, img.height)


def _eye_boxes(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of the two dense eyeball blobs (left half / right half)."""
    w, h = img.size
    mask = img.getchannel("A").point(lambda v: 255 if v > 200 else 0)
    boxes = []
    for x0, x1 in ((0, w // 2), (w // 2, w)):
        box = mask.crop((x0, 0, x1, h)).getbbox()
        if box:
            boxes.append((box[0] + x0, box[1], box[2] + x0, box[3]))
    return boxes


def clean_eyes(img: Image.Image) -> Image.Image:
    """Drop stray pencil marks so only the two eyeballs slide around."""
    boxes = _eye_boxes(img)
    if len(boxes) < 2:
        return img
    keep = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(keep)
    for left, top, right, bottom in boxes:
        draw.rectangle((left - 4, top - 4, right + 4, bottom + 4), fill=255)
    cleaned = img.copy()
    cleaned.putalpha(ImageChops.multiply(img.getchannel("A"), keep))
    return cleaned


def eye_midpoint(img: Image.Image) -> tuple[float, float]:
    boxes = _eye_boxes(img)
    if not boxes:
        return (img.width / 2.0, img.height / 2.0)
    return (
        sum((b[0] + b[2]) / 2.0 for b in boxes) / len(boxes),
        sum((b[1] + b[3]) / 2.0 for b in boxes) / len(boxes),
    )


class Surface:
    """A premultiplied-BGRA DIB held in memory, ready for UpdateLayeredWindow."""

    def __init__(self, img: Image.Image, box=None):
        self.w = 0
        self.h = 0
        self.hdc = None
        self.hbmp = None
        self.bits = None
        self.alpha = b""
        self.box = box if box is not None else (0, 0, img.width, img.height)
        self.set_image(img)

    def _alloc(self, w: int, h: int) -> None:
        self._release()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        self.bits = ctypes.c_void_p()
        self.hdc = gdi32.CreateCompatibleDC(None)
        self.hbmp = gdi32.CreateDIBSection(
            self.hdc, ctypes.byref(bmi), 0, ctypes.byref(self.bits), None, 0
        )
        if not self.hbmp:
            raise OSError("CreateDIBSection failed")
        gdi32.SelectObject(self.hdc, self.hbmp)
        self.w, self.h = w, h

    def set_image(self, img: Image.Image, box=None) -> None:
        w, h = img.size
        if (w, h) != (self.w, self.h):
            self._alloc(w, h)
        if box is not None:
            self.box = box

        buf = bytearray(img.tobytes("raw", "BGRA"))
        for i in range(0, len(buf), 4):
            a = buf[i + 3]
            if a != 255:
                if a == 0:
                    buf[i] = buf[i + 1] = buf[i + 2] = 0
                else:
                    buf[i] = (buf[i] * a) // 255
                    buf[i + 1] = (buf[i + 1] * a) // 255
                    buf[i + 2] = (buf[i + 2] * a) // 255
        self.alpha = img.getchannel("A").tobytes()
        ctypes.memmove(self.bits, bytes(buf), len(buf))

    def opaque_at(self, px: int, py: int, threshold: int = 16) -> bool:
        if px < 0 or py < 0 or px >= self.w or py >= self.h:
            return False
        return self.alpha[py * self.w + px] > threshold

    @classmethod
    def blank(cls, w: int, h: int) -> "Surface":
        surf = cls.__new__(cls)
        surf.w = surf.h = 0
        surf.hdc = None
        surf.hbmp = None
        surf.bits = None
        surf.alpha = b""
        surf.box = (0, 0, w, h)
        surf._alloc(max(1, w), max(1, h))
        return surf

    def _release(self) -> None:
        if self.hbmp:
            gdi32.DeleteObject(self.hbmp)
            self.hbmp = None
        if self.hdc:
            gdi32.DeleteDC(self.hdc)
            self.hdc = None
        self.w = self.h = 0

    def free(self) -> None:
        self._release()


class Action:
    """One still image, scaled, with its visible bounds."""

    def __init__(self, name: str, path: str, scale: float):
        self.name = name
        self.path = path
        self.scale = max(0.05, scale)
        self._img: Image.Image | None = None
        self.box = (0, 0, 1, 1)
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"missing art file for '{self.name}': {self.path}")
        img = load_rgba(self.path)
        if self.scale != 1.0:
            size = (
                max(1, round(img.width * self.scale)),
                max(1, round(img.height * self.scale)),
            )
            img = img.resize(size, Image.LANCZOS)
        self._img = img
        self.box = content_box(img)

    def surface(self, facing_left: bool, cache: dict) -> Surface:
        key = (self.name, facing_left)
        surf = cache.get(key)
        if surf is None:
            img = self._img
            if facing_left:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            surf = Surface(img, content_box(img))
            cache[key] = surf
        return surf

    def close(self) -> None:
        if self._img is not None:
            self._img.close()
            self._img = None


class GazeFace:
    """Idle 1: green eyeline with eyeballs that can slide toward a target."""

    def __init__(self, base_path: str, eyes_path: str, scale: float):
        if not os.path.isfile(base_path):
            raise FileNotFoundError(f"missing eyeline art: {base_path}")
        if not os.path.isfile(eyes_path):
            raise FileNotFoundError(f"missing eyeball art: {eyes_path}")

        base = load_rgba(base_path)
        eyes = load_rgba(eyes_path)
        if eyes.size != base.size:
            eyes = eyes.resize(base.size, Image.LANCZOS)
        eyes = clean_eyes(eyes)

        self.scale = max(0.05, scale)
        self.size = (
            max(1, round(base.width * self.scale)),
            max(1, round(base.height * self.scale)),
        )
        if self.scale != 1.0:
            base = base.resize(self.size, Image.LANCZOS)
            eyes = eyes.resize(self.size, Image.LANCZOS)

        self.base = base
        self.eyes = eyes
        self.box = content_box(base)
        self.eye_mid = eye_midpoint(eyes)
        self._center = Image.alpha_composite(eyes, base)
        self._surface: Surface | None = None
        self._last: tuple[int, int] | None = None

    def _compose(self, dx: int, dy: int) -> Image.Image:
        if dx == 0 and dy == 0:
            return self._center
        canvas = Image.new("RGBA", self.size, (0, 0, 0, 0))
        canvas.paste(self.eyes, (dx, dy), self.eyes)
        return Image.alpha_composite(canvas, self.base)

    def draw(self, dx: int, dy: int) -> Surface:
        if self._surface is None:
            self._surface = Surface(self._compose(dx, dy), self.box)
            self._last = (dx, dy)
        elif (dx, dy) != self._last:
            self._surface.set_image(self._compose(dx, dy), self.box)
            self._last = (dx, dy)
        return self._surface

    def close(self) -> None:
        if self._surface is not None:
            self._surface.free()
            self._surface = None
        self.base.close()
        self.eyes.close()
        self._center.close()


# ------------------------------------------------------------- glitch video

GLITCH_PAD = 12
GLITCH_GAIN = 2.2


def _boost(v: int) -> int:
    return min(255, round(v * GLITCH_GAIN))


def find_ffmpeg(explicit: str = "") -> str | None:
    if explicit:
        path = explicit.replace("\\", "/")
        if not os.path.isabs(path):
            path = os.path.join(HERE, path)
        if os.path.isfile(path):
            return path
    try:
        import imageio_ffmpeg  # type: ignore

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path):
            return path
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg")


class GlitchOverlay:
    """Distortion that swallows the pet and spills around her silhouette."""

    def __init__(self, settings: Settings, hinst):
        self.duration = settings.glitch_duration
        self.fps = max(1, settings.glitch_fps)
        self.path = settings.glitch_file
        self.ffmpeg = find_ffmpeg(settings.glitch_ffmpeg)

        self.dw = 2
        self.dh = 2
        self.frame_bytes = 12
        self.buf = ctypes.create_string_buffer(self.frame_bytes)
        self.bmi = BITMAPINFO()
        self.pet_rgb: Image.Image | None = None
        self.pet_a: Image.Image | None = None
        self.halo: Image.Image | None = None
        self.out: Surface | None = None
        self.ox = 0
        self.oy = 0

        self.enabled = bool(
            settings.glitch_enabled
            and self.ffmpeg
            and os.path.isfile(self.path)
            and self.duration > 0
        )
        self.proc: subprocess.Popen | None = None
        self.active = False
        self.next_frame_at = 0.0
        self.ow = 1
        self.oh = 1
        self.hwnd = None
        self.wndproc_ref = None
        self.brush = None

        if self.enabled:
            self._create_window()
        else:
            reason = "disabled"
            if not settings.glitch_enabled:
                reason = "GLITCH_ENABLED is off"
            elif not self.ffmpeg:
                reason = "no ffmpeg found"
            elif not os.path.isfile(self.path):
                reason = f"missing {self.path}"
            print(f"[capri] glitch transition off ({reason})")

    def _setup_frame(self, w: int, h: int) -> None:
        self.dw = max(1, w)
        self.dh = max(1, h)
        self.frame_bytes = self.dw * self.dh * 3
        self.buf = ctypes.create_string_buffer(self.frame_bytes)
        head = self.bmi.bmiHeader
        head.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        head.biWidth = self.dw
        head.biHeight = -self.dh
        head.biPlanes = 1
        head.biBitCount = 24
        head.biCompression = BI_RGB
        head.biSizeImage = self.frame_bytes

    def reconfigure(self, settings: Settings) -> None:
        self.stop()
        self.duration = settings.glitch_duration
        self.fps = max(1, settings.glitch_fps)
        self.path = settings.glitch_file
        self.ffmpeg = find_ffmpeg(settings.glitch_ffmpeg)
        self.enabled = bool(
            settings.glitch_enabled
            and self.ffmpeg
            and os.path.isfile(self.path)
            and self.duration > 0
        )
        if self.enabled and self.hwnd is None:
            self._create_window()
        print(
            f"[capri] glitch transition {'on' if self.enabled else 'off'}"
            f" ({self.duration:.2f}s @ {self.fps}fps)"
        )

    # ---- window

    def _create_window(self) -> None:
        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_DESTROY:
                return 0
            return user32.DefWindowProcW(
                wt.HWND(hwnd), UINT(msg), wt.WPARAM(wparam), wt.LPARAM(lparam)
            )

        self.wndproc_ref = WNDPROC(proc)
        self.brush = gdi32.CreateSolidBrush(0)

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self.wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = self.brush
        wc.lpszMenuName = None
        wc.lpszClassName = "CapriGlitchWindow"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                print(f"[capri] glitch window class failed ({err})")
                self.enabled = False
                return

        ex = (
            WS_EX_LAYERED
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
            | WS_EX_TRANSPARENT
        )
        self.hwnd = user32.CreateWindowExW(
            ex, "CapriGlitchWindow", "Capri", WS_POPUP,
            0, 0, 1, 1, None, None, wc.hInstance, None,
        )
        if not self.hwnd:
            print(f"[capri] glitch window failed ({ctypes.get_last_error()})")
            self.enabled = False

    def _cmd(self) -> list[str]:
        return [
            self.ffmpeg or "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-i", self.path,
            "-t", f"{self.duration + 0.3:.3f}",
            "-vf", f"fps={self.fps},scale={self.dw}:{self.dh}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]

    # ---- playback

    def start(self, x: int, y: int, surf: Surface, pet_hwnd=None) -> bool:
        if not self.enabled or self.hwnd is None or self.active:
            return False
        if surf is None or surf.bits is None or surf.w < 1 or surf.h < 1:
            return False
        self._kill_proc()
        pad = GLITCH_PAD
        self.ox, self.oy = int(x) - pad, int(y) - pad
        self.ow, self.oh = surf.w + pad * 2, surf.h + pad * 2
        self._setup_frame(self.ow, self.oh)
        raw = ctypes.string_at(surf.bits, surf.w * surf.h * 4)
        pet = Image.frombuffer(
            "RGBA", (surf.w, surf.h), raw, "raw", "BGRA", 0, 1
        )
        canvas = Image.new("RGBA", (self.ow, self.oh), (0, 0, 0, 0))
        canvas.paste(pet, (pad, pad))
        self.pet_rgb = canvas.convert("RGB")
        self.pet_a = canvas.getchannel("A")
        self.halo = (
            self.pet_a.filter(ImageFilter.MaxFilter(7))
            .filter(ImageFilter.GaussianBlur(2.5))
        )
        if self.out is None or self.out.w != self.ow or self.out.h != self.oh:
            if self.out is not None:
                self.out.free()
            self.out = Surface.blank(self.ow, self.oh)
        try:
            self.proc = subprocess.Popen(
                self._cmd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[capri] glitch ffmpeg failed: {exc}")
            return False
        if not self._read_frame():
            self._kill_proc()
            return False
        self._blit()
        above = user32.GetWindow(pet_hwnd, GW_HWNDPREV) if pet_hwnd else None
        while above and int(above) == int(self.hwnd):
            above = user32.GetWindow(above, GW_HWNDPREV)
        user32.SetWindowPos(
            self.hwnd,
            above if above else HWND_TOPMOST,
            self.ox, self.oy, self.ow, self.oh,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        self.active = True
        self.next_frame_at = time.perf_counter() + 1.0 / self.fps
        return True

    def tick(self, now: float) -> None:
        if not self.active:
            return
        for _ in range(4):
            if now < self.next_frame_at:
                break
            if not self._read_frame():
                break
            self._blit()
            self.next_frame_at += 1.0 / self.fps

    def stop(self) -> None:
        self.active = False
        self._hide()
        self._kill_proc()

    def close(self) -> None:
        self.stop()
        if self.out is not None:
            self.out.free()
            self.out = None
        self.pet_rgb = None
        self.pet_a = None
        self.halo = None
        if self.hwnd is not None:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:  # noqa: BLE001
                pass
            self.hwnd = None
        if self.brush is not None:
            try:
                gdi32.DeleteObject(self.brush)
            except Exception:  # noqa: BLE001
                pass
            self.brush = None

    def _read_frame(self) -> bool:
        if self.proc is None or self.proc.stdout is None:
            return False
        data = self.proc.stdout.read(self.frame_bytes)
        if not data or len(data) < self.frame_bytes:
            return False
        ctypes.memmove(self.buf, data, self.frame_bytes)
        return True

    def _blit(self) -> None:
        if (
            self.hwnd is None
            or self.out is None
            or self.pet_rgb is None
            or self.pet_a is None
            or self.halo is None
        ):
            return
        raw = ctypes.string_at(self.buf, self.frame_bytes)
        glitch = Image.frombuffer(
            "RGB", (self.ow, self.oh), raw, "raw", "RGB", 0, 1
        ).point(_boost)
        weight = ImageChops.multiply(self.halo, glitch.convert("L"))
        rest = ImageChops.invert(weight)
        weight3 = Image.merge("RGB", (weight, weight, weight))
        rest3 = Image.merge("RGB", (rest, rest, rest))
        rgb = ImageChops.add(
            ImageChops.multiply(glitch, weight3),
            ImageChops.multiply(self.pet_rgb, rest3),
        )
        alpha = ImageChops.add(
            weight, ImageChops.multiply(self.pet_a, rest)
        )
        rgba = Image.merge("RGBA", (*rgb.split(), alpha))
        ctypes.memmove(
            self.out.bits, rgba.tobytes("raw", "BGRA"), self.ow * self.oh * 4
        )

        screen = user32.GetDC(None)
        try:
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            dst = POINT(self.ox, self.oy)
            size = SIZE(self.ow, self.oh)
            src = POINT(0, 0)
            user32.UpdateLayeredWindow(
                self.hwnd, screen, ctypes.byref(dst), ctypes.byref(size),
                self.out.hdc, ctypes.byref(src), 0, ctypes.byref(blend),
                ULW_ALPHA,
            )
        finally:
            user32.ReleaseDC(None, screen)

    def _hide(self) -> None:
        if self.hwnd is not None:
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def _kill_proc(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------- say something

# Border recolours the talking frame cycles through. The first entries match the
# three supplied overlay colours; the rest keep the glitch lively.
TALK_PALETTE = [
    (255, 38, 62),     # overlay red
    (60, 226, 96),     # overlay green
    (255, 228, 46),    # overlay yellow
    (70, 220, 255),    # cyan
    (255, 96, 214),    # magenta
    (170, 92, 255),    # violet
    (255, 255, 255),   # white flash
]

TALK_TEXT_BOX = (689, 438, 1448, 820)
TALK_TEXT_COLOR = (205, 201, 214, 255)
TALK_PAD = 10


def _hole_rect(img: Image.Image, threshold: int = 128) -> tuple[int, int, int, int]:
    """Inner opening of a border overlay, as (left, top, right, bottom) exclusive."""
    alpha = img.getchannel("A")
    w, h = img.size
    px = alpha.load()

    def runs(values) -> list[tuple[int, int]]:
        found: list[tuple[int, int]] = []
        start = None
        for i, v in enumerate(values):
            if v > threshold and start is None:
                start = i
            elif v <= threshold and start is not None:
                found.append((start, i - 1))
                start = None
        if start is not None:
            found.append((start, len(values) - 1))
        return found

    row = runs([px[x, h // 2] for x in range(w)])
    col = runs([px[w // 2, y] for y in range(h)])
    if len(row) < 2 or len(col) < 2:
        box = alpha.point(lambda v: 255 if v > threshold else 0).getbbox()
        return box or (0, 0, w, h)
    return (row[0][1] + 1, col[0][1] + 1, row[-1][0], col[-1][0])


def _talk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("consola.ttf", "consolab.ttf", "lucon.ttf", "segoeui.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class TalkRenderer:
    """Full talking pose: mouth-flap art inside a glitching colour-cycling frame,
    with the line from words.txt in a speech bubble above her."""

    def __init__(self, settings: Settings, line: str):
        self.line = line
        self.fps = max(4, settings.talk_fps)
        self.scale = settings.talk_scale
        self._rng = random.Random()
        self._mouth = 0
        self._next_mouth = 0.0
        self._surface: Surface | None = None
        self._box = (0, 0, 1, 1)
        self._frame_w = 1
        self._frame_h = 1
        self._frame_variants: list[Image.Image] = []
        self._tinted: list[list[Image.Image]] = []
        self._glitch_img: Image.Image | None = None
        self._tint = TALK_PALETTE[0]
        self._tint_until = 0.0
        self._type_cps = max(4.0, settings.talk_type_cps)
        self._started_at: float | None = None
        self._reveal = -1
        self._caret_on = True
        self._bubble_notext: Image.Image | None = None
        self._text_lines: list[str] = [""]
        self._text_total = 0
        self._text_font = ImageFont.load_default()
        self._text_origin = (0, 0)
        self._text_size = 12
        self._text_spacing = 3

        arts = [load_rgba(settings.talk_file0), load_rgba(settings.talk_file1)]
        aw = max(1, round(arts[0].width * self.scale))
        ah = max(1, round(arts[0].height * self.scale))
        self._arts = [
            art if art.size == (aw, ah) else art.resize((aw, ah), Image.LANCZOS)
            for art in arts
        ]
        self._art_layers: list[Image.Image] = []

        overlays: list[tuple[Image.Image, int, int]] = []
        for path in settings.talk_overlays:
            if not os.path.isfile(path):
                continue
            raw = load_rgba(path)
            ov = raw.crop(content_box(raw))
            hx0, hy0, hx1, hy1 = _hole_rect(ov)
            hw = max(1, hx1 - hx0)
            hh = max(1, hy1 - hy0)
            kx = aw / hw
            ky = ah / hh
            size = (max(1, round(ov.width * kx)), max(1, round(ov.height * ky)))
            ov = ov.resize(size, Image.LANCZOS)
            overlays.append((ov, round(hx0 * kx), round(hy0 * ky)))
        if not overlays:
            raise FileNotFoundError("missing talking border overlays")

        left = max(px for _ov, px, _py in overlays)
        top = max(py for _ov, _px, py in overlays)
        right = max(ov.width - px - aw for ov, px, _py in overlays)
        bottom = max(ov.height - py - ah for ov, _px, py in overlays)
        fw = left + aw + right + TALK_PAD * 2
        fh = top + ah + bottom + TALK_PAD * 2
        self._frame_w, self._frame_h = fw, fh
        ax, ay = TALK_PAD + left, TALK_PAD + top

        for ov, px, py in overlays:
            layer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
            layer.paste(ov, (ax - px, ay - py))
            self._frame_variants.append(layer)
        for art in self._arts:
            layer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
            layer.paste(art, (ax, ay))
            self._art_layers.append(layer)

        for layer in self._frame_variants:
            alpha = layer.getchannel("A")
            lum = layer.convert("L")
            shade = lum.point(lambda v: 140 + (v * 115) // 255)
            shade3 = Image.merge(
                "RGBA", (shade, shade, shade, Image.new("L", layer.size, 255))
            )
            tints = []
            for colour in TALK_PALETTE:
                flat = Image.new("RGBA", layer.size, (*colour, 255))
                tinted = ImageChops.multiply(flat, shade3)
                tinted.putalpha(alpha)
                tints.append(tinted)
            self._tinted.append(tints)

        self._bubble_img: Image.Image | None = None
        self._build(settings, line)

    # ---- layout

    def _bubble_layer(self, settings: Settings, line: str) -> Image.Image | None:
        path = settings.talk_bubble_file
        if not os.path.isfile(path):
            return None
        bubble = load_rgba(path)
        box = content_box(bubble)
        bubble = bubble.crop(box)
        bw = max(1, round(self._arts[0].width * settings.talk_bubble_ratio))
        bh = max(1, round(bubble.height * bw / max(1, bubble.width)))
        bubble = bubble.resize((bw, bh), Image.LANCZOS)

        scale = bw / max(1, box[2] - box[0])
        tx0 = (TALK_TEXT_BOX[0] - box[0]) * scale
        ty0 = (TALK_TEXT_BOX[1] - box[1]) * scale
        tx1 = (TALK_TEXT_BOX[2] - box[0]) * scale
        ty1 = (TALK_TEXT_BOX[3] - box[1]) * scale
        width = max(20, tx1 - tx0)
        height = max(20, ty1 - ty0)

        size = max(8, round(42 * scale))
        font = _talk_font(size)
        lines = self._wrap(line, font, width)
        while size > 8 and len(lines) * (size + max(2, round(13 * scale))) > height:
            size -= 1
            font = _talk_font(size)
            lines = self._wrap(line, font, width)

        self._bubble_notext = bubble
        self._text_font = font
        self._text_origin = (round(tx0), round(ty0))
        self._text_size = size
        self._text_spacing = max(2, round(13 * scale))
        self._text_lines = lines
        self._text_total = sum(len(text) for text in lines)
        return bubble

    def _render_bubble(self, reveal: int, caret_on: bool) -> Image.Image | None:
        if self._bubble_notext is None:
            return None
        bubble = self._bubble_notext.copy()
        draw = ImageDraw.Draw(bubble)
        x0, y0 = self._text_origin
        step = self._text_size + self._text_spacing
        remaining = reveal
        caret: tuple[float, float] | None = None
        y = y0
        for text in self._text_lines:
            if remaining <= 0:
                caret = (x0, y)
                break
            shown = text[:remaining]
            draw.text((x0, y), shown, font=self._text_font, fill=TALK_TEXT_COLOR)
            remaining -= len(shown)
            if remaining <= 0:
                caret = (x0 + self._text_font.getlength(shown), y)
                break
            y += step
        if caret is None and self._text_lines:
            last_y = y0 + (len(self._text_lines) - 1) * step
            caret = (x0 + self._text_font.getlength(self._text_lines[-1]), last_y)
        if caret is not None and caret_on:
            left = caret[0] + max(1.0, self._text_size * 0.08)
            cw = max(2, round(self._text_size * 0.12))
            draw.rectangle(
                (left, caret[1], left + cw, caret[1] + self._text_size),
                fill=TALK_TEXT_COLOR,
            )
        return bubble

    @staticmethod
    def _wrap(text: str, font, width: float) -> list[str]:
        lines: list[str] = []
        for para in text.split("\n"):
            current = ""
            for word in para.split():
                probe = word if not current else current + " " + word
                if not current or font.getlength(probe) <= width:
                    current = probe
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
        return lines or [""]

    def _build(self, settings: Settings, line: str) -> None:
        self.line = line
        bubble = self._bubble_layer(settings, line)
        self._bubble_img = bubble
        self._started_at = None
        self._reveal = -1
        self._caret_on = True
        self._mouth = 0
        self._next_mouth = 0.0
        self._tint = TALK_PALETTE[0]
        self._tint_until = 0.0
        self._next_glitch = 0.0
        self._glitch_img = None

        gap = 6 if bubble is not None else 0
        bw, bh = bubble.size if bubble is not None else (0, 0)
        total_w = max(self._frame_w, bw)
        total_h = bh + gap + self._frame_h
        self._total_w, self._total_h, self._gap = total_w, total_h, gap
        self._bubble_xy = ((total_w - bw) // 2, 0)
        self._frame_xy = ((total_w - self._frame_w) // 2, bh + gap)
        self._box = (0, 0, total_w, total_h)
        self._base = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
        if self._surface is not None:
            surf, self._surface = self._surface, None
            surf.free()

    def restart(self, settings: Settings, line: str) -> None:
        self._build(settings, line)

    # ---- animation

    def _glitch_frame(self, now: float) -> Image.Image:
        if now >= self._tint_until or self._rng.random() < 0.15:
            self._tint = self._rng.choice(TALK_PALETTE)
            self._tint_until = now + self._rng.uniform(0.07, 0.28)
        variant = self._rng.randrange(len(self._tinted))
        colour = TALK_PALETTE.index(self._tint)
        src = self._tinted[variant][colour]
        out = src.copy()
        w, h = out.size

        # Colour bands only: the alpha silhouette never moves, so the border
        # stays locked around the art while it flickers.
        for _ in range(self._rng.randint(0, 3)):
            band_h = self._rng.randint(2, max(3, h // 14))
            y = self._rng.randint(0, max(0, h - band_h))
            other = self._rng.choice(
                [i for i in range(len(TALK_PALETTE)) if i != colour] or [colour]
            )
            out.paste(
                self._tinted[variant][other].crop((0, y, w, y + band_h)), (0, y)
            )

        if self._rng.random() < 0.55:
            y = self._rng.randint(0, max(0, h - 1))
            bh = self._rng.randint(1, 4)
            region = out.crop((0, y, w, min(h, y + bh)))
            dark = Image.new("L", region.size, self._rng.randint(70, 190))
            r, g, b, a = region.split()
            out.paste(
                Image.merge(
                    "RGBA",
                    (
                        ImageChops.multiply(r, dark),
                        ImageChops.multiply(g, dark),
                        ImageChops.multiply(b, dark),
                        a,
                    ),
                ),
                (0, y),
            )

        if self._rng.random() < 0.05:
            out = self._tinted[variant][6].copy()
        return out

    def _refresh_text(self, now: float) -> bool:
        if self._started_at is None:
            self._started_at = now
        elapsed = max(0.0, now - self._started_at)
        total = self._text_total
        reveal = min(total, int(elapsed * self._type_cps) + 1) if total else 0
        caret_on = int(elapsed / 0.45) % 2 == 0
        if reveal == self._reveal and caret_on == self._caret_on:
            return False
        self._reveal = reveal
        self._caret_on = caret_on
        bubble = self._render_bubble(reveal, caret_on)
        base = Image.new("RGBA", (self._box[2], self._box[3]), (0, 0, 0, 0))
        if bubble is not None:
            base.alpha_composite(bubble, dest=self._bubble_xy)
        self._base = base
        self._bubble_img = bubble
        return True

    def _compose(self) -> Image.Image:
        layer = self._art_layers[self._mouth].copy()
        if self._glitch_img is not None:
            layer.alpha_composite(self._glitch_img)
        out = self._base.copy()
        out.alpha_composite(layer, dest=self._frame_xy)
        return out

    def frame(self, now: float) -> Surface:
        changed = self._refresh_text(now)
        if now >= self._next_mouth:
            self._mouth ^= 1
            self._next_mouth = now + self._rng.uniform(0.09, 0.19)
            changed = True
        if self._glitch_img is None or now >= self._next_glitch:
            self._glitch_img = self._glitch_frame(now)
            self._next_glitch = now + 1.0 / self.fps
            changed = True
        if self._surface is None:
            self._surface = Surface(self._compose(), self._box)
        elif changed:
            self._surface.set_image(self._compose(), self._box)
        return self._surface

    def close(self) -> None:
        if self._surface is not None:
            self._surface.free()
            self._surface = None
        self._arts = []
        self._art_layers = []
        self._frame_variants = []
        self._tinted = []
        self._base = None
        self._bubble_img = None


# --------------------------------------------------------------- the pet


class Pet:
    def __init__(self, cfg: dict[str, str]):
        self.settings = Settings(cfg)
        self.work = self._work_area()
        self.baseline = self._baseline()

        self.cache: dict = {}
        self.actions: dict[str, Action | None] = {}
        self.face: GazeFace | None = None
        self.walk_half = 80.0

        self.running = True
        self.hotkeys: list[tuple[int, str]] = []
        self.wndproc_ref = None
        self.hwnd = None

        self.current: Surface | None = None
        self.left = 0
        self.top = 0

        self.x = float((self.work.left + self.work.right) // 2)
        self.facing_left = False

        self.dragging = False
        self._drag_origin: tuple[int, int, float, float] | None = None
        self._drag_moved = False

        self.transition: str | None = None
        self.transition_start = 0.0
        self.glitch: GlitchOverlay | None = None
        self.pending_menu: str | None = None
        self.menu_lock = threading.Lock()

        self.mode = "idle"
        self.mode_timer = 0.0
        self.next_thought = random.uniform(
            self.settings.idle_min, self.settings.idle_max
        )

        self.eye_dx = 0.0
        self.eye_dy = 0.0
        self.eye_track = False
        self.eye_track_until = 0.0
        self.eye_wander = (0.0, 0.0)
        now = time.perf_counter()
        self.eye_next = now + random.uniform(
            self.settings.eye_glance_min, self.settings.eye_glance_max
        )

        self.chat: ChatWindow | None = None
        self.chat_open = False
        self.chat_lock = threading.Lock()
        self._topmost_at = 0.0

        self.talk: TalkRenderer | None = None
        self.talk_until = 0.0
        self._pending_line: str | None = None
        self.words = self._load_words()
        self.last_said: str | None = None

        self.load_art()
        self._create_window()
        self.glitch = GlitchOverlay(self.settings, self._hinst)

    # ---- layout

    def _work_area(self) -> RECT:
        r = RECT()
        if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            r.left, r.top = 0, 0
            r.right = user32.GetSystemMetrics(0)
            r.bottom = user32.GetSystemMetrics(1)
        return r

    def _baseline(self) -> int:
        height = max(1, self.work.bottom - self.work.top)
        margin = min(max(4, int(self.settings.margin)), max(4, height // 2))
        return self.work.bottom - margin

    def _fit_scale(self, configured: float, path: str) -> float:
        try:
            with Image.open(path) as im:
                w, h = im.size
        except Exception:  # noqa: BLE001
            return configured
        avail_w = max(1, self.work.right - self.work.left) * 0.85
        avail_h = max(1, self.work.bottom - self.work.top) * 0.85
        scale = configured
        if w > 0 and w * scale > avail_w:
            scale = avail_w / w
        if h > 0 and h * scale > avail_h:
            scale = avail_h / h
        return max(0.05, scale)

    # ---- art

    def load_art(self) -> None:
        s = self.settings
        arts: dict[str, Action | None] = {}
        face: GazeFace | None = None

        arts["walk"] = Action("walk", s.walk_file, self._fit_scale(s.walk_scale, s.walk_file))
        try:
            arts["idle2"] = Action(
                "idle2", s.idle2_file, self._fit_scale(s.idle2_scale, s.idle2_file)
            )
        except FileNotFoundError as exc:
            print(f"[capri] {exc} (idle 2 disabled)")
            arts["idle2"] = None

        try:
            face = GazeFace(s.eyeline_file, s.eye_file, self._fit_scale(s.scale, s.eyeline_file))
        except FileNotFoundError as exc:
            print(f"[capri] {exc} (eyes will not follow the cursor)")

        try:
            arts["idle"] = Action("idle", s.idle_file, self._fit_scale(s.scale, s.idle_file))
        except FileNotFoundError:
            if face is None:
                raise

        self._dispose_art()
        self.actions = arts
        self.face = face
        walk_box = arts["walk"].box
        self.walk_half = (walk_box[2] - walk_box[0]) / 2.0

    def _dispose_art(self) -> None:
        if self.face is not None:
            self.face.close()
            self.face = None
        for action in self.actions.values():
            if action is not None:
                action.close()
        self.actions = {}

    def _load_words(self) -> list[str]:
        path = self.settings.talk_words_file
        words: list[str] = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
                        line = line[1:-1].strip()
                    if line:
                        words.append(line)
        except OSError as exc:
            print(f"[capri] could not read words: {exc}")
        return words

    def _dispose_talk(self) -> None:
        self._pending_line = None
        self.talk_until = 0.0
        if self.talk is not None:
            self.talk.close()
            self.talk = None

    def reload(self) -> None:
        print("[capri] reloading config + art")
        self._cancel_transition()
        self._dispose_talk()
        self.dragging = False
        self._drag_origin = None
        self._drag_moved = False

        cfg = read_config(os.path.join(HERE, "capri_config.txt"))
        for surf in self.cache.values():
            surf.free()
        self.cache.clear()
        self.current = None

        self.settings = Settings(cfg)
        self.work = self._work_area()
        self.baseline = self._baseline()
        self.words = self._load_words()
        self.load_art()

        if self.glitch is not None:
            self.glitch.reconfigure(self.settings)

        self._unregister_hotkeys()
        self._register_hotkey(1, self.settings.quit_hotkey)
        self._register_hotkey(2, self.settings.reload_hotkey)
        self._apply_topmost()

        if self.chat is not None:
            self.chat.reload_config(cfg)

        self.mode = "idle"
        self.mode_timer = 0.0
        self.next_thought = random.uniform(
            self.settings.idle_min, self.settings.idle_max
        )
        self.eye_dx = self.eye_dy = 0.0
        self.eye_track = False
        self._clamp_position()

    # ---- window plumbing

    def _create_window(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        self._hinst = hinst

        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_HOTKEY:
                if wparam == 1:
                    self.running = False
                    return 0
                if wparam == 2:
                    try:
                        self.reload()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[capri] reload failed: {exc}")
                    return 0
            if msg == WM_NCHITTEST:
                if not self.settings.clicks_enabled or self.current is None:
                    return HTTRANSPARENT
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                pt = POINT(x, y)
                user32.ScreenToClient(wt.HWND(hwnd), ctypes.byref(pt))
                if self.current.opaque_at(pt.x, pt.y):
                    return HTCLIENT
                return HTTRANSPARENT
            if msg == WM_LBUTTONDBLCLK:
                return 0
            if msg == WM_LBUTTONDOWN:
                if (
                    self.settings.clicks_enabled
                    and not self.dragging
                    and self.transition is None
                ):
                    self._drag_begin(*self._mouse_screen(lparam))
                return 0
            if msg == WM_MOUSEMOVE:
                if self.dragging:
                    self._drag_move(*self._mouse_screen(lparam))
                return 0
            if msg == WM_LBUTTONUP:
                if self.dragging:
                    self._drag_end(*self._mouse_screen(lparam))
                return 0
            if msg == WM_CAPTURECHANGED:
                if self.dragging:
                    self.dragging = False
                    self._drag_origin = None
                return 0
            if msg == WM_CLOSE:
                self.running = False
                user32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(
                wt.HWND(hwnd), UINT(msg), wt.WPARAM(wparam), wt.LPARAM(lparam)
            )

        self.wndproc_ref = WNDPROC(proc)

        wc = WNDCLASSW()
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = self.wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = "CapriPetWindow"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                raise OSError(f"RegisterClassW failed ({err})")

        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

        self.hwnd = user32.CreateWindowExW(
            ex, "CapriPetWindow", "Capri", WS_POPUP,
            0, 0, 10, 10, None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed ({ctypes.get_last_error()})")
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

        self._register_hotkey(1, self.settings.quit_hotkey)
        self._register_hotkey(2, self.settings.reload_hotkey)

    def _tk_menu_open(self) -> bool:
        menu = user32.FindWindowW("#32768", None)
        return bool(menu) and bool(user32.IsWindowVisible(menu))

    def _apply_topmost(self) -> None:
        if self.hwnd is None:
            return
        try:
            user32.SetWindowPos(
                self.hwnd,
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:  # noqa: BLE001
            pass

    def _register_hotkey(self, ident: int, spec: str) -> None:
        if not spec:
            return
        mods = 0
        key = ""
        for part in spec.lower().replace(" ", "").split("+"):
            if part in ("ctrl", "control"):
                mods |= MOD_CONTROL
            elif part == "alt":
                mods |= MOD_ALT
            elif part == "shift":
                mods |= MOD_SHIFT
            else:
                key = part
        if not key:
            return
        if len(key) == 1:
            vk = ord(key.upper())
        else:
            scan = user32.VkKeyScanW(key)
            if scan == -1:
                print(f"[capri] unknown key in hotkey '{spec}'")
                return
            vk = scan & 0xFF
        if user32.RegisterHotKey(None, ident, mods | MOD_NOREPEAT, vk):
            self.hotkeys.append((ident, spec))
            print(f"[capri] hotkey {spec} -> id {ident}")
        else:
            print(f"[capri] could not register hotkey {spec} (already in use?)")

    def _unregister_hotkeys(self) -> None:
        for ident, _spec in self.hotkeys:
            try:
                user32.UnregisterHotKey(None, ident)
            except Exception:  # noqa: BLE001
                pass
        self.hotkeys.clear()

    def _blit(self, surf: Surface) -> None:
        left_, top_, right_, bottom_ = surf.box
        self.left = int(round(self.x - (left_ + right_) / 2.0))
        self.top = int(round(self.baseline - bottom_))
        screen = user32.GetDC(None)
        try:
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            dst = POINT(self.left, self.top)
            size = SIZE(surf.w, surf.h)
            src = POINT(0, 0)
            user32.UpdateLayeredWindow(
                self.hwnd, screen, ctypes.byref(dst), ctypes.byref(size),
                surf.hdc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
            )
        finally:
            user32.ReleaseDC(None, screen)

    # ---- drag

    def _current_box(self) -> tuple[int, int, int, int]:
        if self.current is not None:
            return self.current.box
        if self.face is not None:
            return self.face.box
        return (0, 0, 1, 1)

    def _clamp_position(self) -> None:
        left, top, right, bottom = self._current_box()
        half = (right - left) / 2.0
        height = bottom - top
        lo, hi = self.work.left + half, self.work.right - half
        self.x = (lo + hi) / 2.0 if lo > hi else min(max(self.x, lo), hi)
        lo, hi = float(self.work.top + height), float(self.work.bottom)
        self.baseline = (lo + hi) / 2.0 if lo > hi else min(max(self.baseline, lo), hi)

    def _mouse_screen(self, lparam) -> tuple[int, int]:
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        pt = POINT(x, y)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        return pt.x, pt.y

    def _drag_begin(self, sx: int, sy: int) -> None:
        self.dragging = True
        self._drag_moved = False
        self._drag_origin = (sx, sy, self.x, float(self.baseline))
        user32.SetCapture(self.hwnd)

    def _drag_move(self, sx: int | None = None, sy: int | None = None) -> None:
        if not self.dragging or self._drag_origin is None:
            return
        if sx is None or sy is None:
            p = POINT()
            if not user32.GetCursorPos(ctypes.byref(p)):
                return
            sx, sy = p.x, p.y
        ox, oy, x0, b0 = self._drag_origin
        dx, dy = sx - ox, sy - oy
        if not self._drag_moved and abs(dx) + abs(dy) < 3:
            return
        self._drag_moved = True
        self.x = x0 + dx
        self.baseline = b0 + dy
        self._clamp_position()

    def _drag_end(self, sx: int | None = None, sy: int | None = None) -> None:
        if not self.dragging:
            return
        if self._drag_moved:
            self._drag_move(sx, sy)
        self.dragging = False
        self._drag_origin = None
        try:
            user32.ReleaseCapture()
        except Exception:  # noqa: BLE001
            pass
        if not self._drag_moved:
            if sx is None or sy is None:
                p = POINT()
                if not user32.GetCursorPos(ctypes.byref(p)):
                    return
                sx, sy = p.x, p.y
            self._show_menu(sx, sy)
            return
        self._drag_moved = False
        if self.mode == "walk":
            self._enter_walk()
        self.next_thought = max(
            self.next_thought,
            random.uniform(self.settings.idle_min, self.settings.idle_max),
        )
        print(f"[capri] moved to {self.x:.0f},{self.baseline:.0f}")

    # ---- glitch transitions

    def _begin_transition(self, action: str) -> None:
        if self.transition is not None:
            return
        surf = self.current
        if (
            surf is not None
            and self.glitch is not None
            and self.glitch.start(self.left, self.top, surf, self.hwnd)
        ):
            self.transition = action
            self.transition_start = time.perf_counter()
            return
        self._apply_action(action)

    def _finish_transition(self) -> None:
        action, self.transition = self.transition, None
        if self.glitch is not None:
            self.glitch.stop()
        if action is not None:
            self._apply_action(action)

    def _cancel_transition(self) -> None:
        if self.transition is None:
            return
        self.transition = None
        if self.glitch is not None:
            self.glitch.stop()

    def _apply_action(self, action: str) -> None:
        if action == "walk":
            self._enter_walk()
            print(f"[capri] walk -> {self.walk_target:.0f}")
        elif action == "talk":
            self._start_talk()
        elif action == "idle2":
            self.mode = "idle2"
            self.mode_timer = self.settings.idle2_duration
            print("[capri] idle 2")
        else:
            self._enter_idle()

    # ---- chat + menu

    def _chat_anchor(self) -> tuple[int, int]:
        box = self.face.box if self.face is not None else (
            self.current.box if self.current is not None else None
        )
        if box is not None:
            anchor_y = int(self.baseline - (box[3] - box[1]))
        else:
            anchor_y = int(self.baseline - 100)
        return (int(self.x), anchor_y)

    def _ensure_chat(self, anchor: tuple[int, int]) -> ChatWindow:
        with self.chat_lock:
            if self.chat is not None:
                return self.chat
        holder: dict[str, ChatWindow] = {}
        win = ChatWindow(
            read_config(os.path.join(HERE, "capri_config.txt")),
            lambda is_open: self._on_chat_state(is_open, holder.get("w")),
            anchor,
            on_menu=self._on_menu,
        )
        holder["w"] = win
        with self.chat_lock:
            if self.chat is None:
                self.chat = win
            else:
                win = self.chat
        return win

    def open_chat(self) -> None:
        self._end_talk()
        self._cancel_transition()
        with self.chat_lock:
            self.chat_open = True
        anchor = self._chat_anchor()
        self._ensure_chat(anchor).open(anchor)

    def _show_menu(self, x: int, y: int) -> None:
        self._ensure_chat(self._chat_anchor()).popup_menu(x, y)

    def _on_menu(self, action: str) -> None:
        """Called from the chat thread - only records the choice."""
        with self.menu_lock:
            self.pending_menu = action

    def _consume_menu(self) -> None:
        with self.menu_lock:
            action, self.pending_menu = self.pending_menu, None
        if action is None:
            return
        print(f"[capri] menu action: {action}")
        if action == "quit":
            self.running = False
        elif action == "chat":
            self.open_chat()
        elif action == "say":
            self._say_something()

    def _on_chat_state(self, is_open: bool, win: ChatWindow | None = None) -> None:
        """Called from the chat thread - only flips a flag."""
        with self.chat_lock:
            if win is not None and self.chat is not None and win is not self.chat:
                return
            self.chat_open = is_open
        print("[capri] chat opened" if is_open else "[capri] chat closed")

    # ---- say something

    def _say_something(self) -> None:
        if not self.words:
            print("[capri] no words to say")
            return
        if self.transition is not None:
            return
        if self.chat_open:
            with self.chat_lock:
                self.chat_open = False
            if self.chat is not None:
                self.chat.close()
        choices = [w for w in self.words if w != self.last_said] or self.words
        line = random.choice(choices)
        self.last_said = line
        self._pending_line = line
        if self.mode == "talk":
            self._start_talk()
            return
        self._begin_transition("talk")

    def _talk_duration(self, line: str) -> float:
        seconds = len(line) / self.settings.talk_type_cps + self.settings.talk_hold_seconds
        return _clamp(seconds, self.settings.talk_min_seconds, self.settings.talk_max_seconds)

    def _start_talk(self) -> None:
        line = self._pending_line
        self._pending_line = None
        if line is None:
            self._enter_idle()
            return
        try:
            if self.talk is None:
                self.talk = TalkRenderer(self.settings, line)
            else:
                self.talk.restart(self.settings, line)
        except Exception as exc:  # noqa: BLE001
            print(f"[capri] say something failed: {exc}")
            self._enter_idle()
            return
        self.mode = "talk"
        self.eye_track = False
        self.talk_until = time.perf_counter() + self._talk_duration(line)
        self.current = self.talk.frame(time.perf_counter())
        self._clamp_position()
        print(f"[capri] says: {line}")

    def _end_talk(self) -> None:
        self._pending_line = None
        self.talk_until = 0.0
        if self.mode == "talk":
            self._enter_idle()

    # ---- behaviour

    def _enter_idle(self) -> None:
        self.mode = "idle"
        self.mode_timer = 0.0
        self.next_thought = random.uniform(
            self.settings.idle_min, self.settings.idle_max
        )

    def _walk_limits(self) -> tuple[float, float]:
        half = self.walk_half
        lo = self.work.left + half + 8.0
        hi = self.work.right - half - 8.0
        if lo >= hi:
            mid = (self.work.left + self.work.right) / 2.0
            return mid, mid
        return lo, hi

    def _enter_walk(self) -> None:
        self.mode = "walk"
        self.mode_timer = 0.0
        direction = random.choice((-1, 1))
        dist = random.uniform(self.settings.walk_min, self.settings.walk_max)
        target = self.x + direction * dist
        lo, hi = self._walk_limits()
        target = min(max(target, lo), hi)
        if abs(target - self.x) < 30.0:
            target = self.x - direction * random.uniform(
                self.settings.walk_min, self.settings.walk_min + 80.0
            )
            target = min(max(target, lo), hi)
        self.walk_target = target
        self.facing_left = target < self.x

    def think(self) -> None:
        """Called after each idle stretch: pick the next thing to do."""
        if self.actions.get("idle2") is not None and random.random() < self.settings.idle2_chance:
            self._begin_transition("idle2")
        else:
            self._begin_transition("walk")

    def _eye_target(self) -> tuple[float, float]:
        if not self.eye_track or self.face is None:
            return self.eye_wander
        p = POINT()
        if not user32.GetCursorPos(ctypes.byref(p)):
            return (0.0, 0.0)
        ex = self.left + self.face.eye_mid[0]
        ey = self.top + self.face.eye_mid[1]
        dx = p.x - ex
        dy = p.y - ey
        dist = math.hypot(dx, dy)
        if dist < 2.0:
            return (0.0, 0.0)
        mag = min(1.0, dist / self.settings.eye_range) * self.settings.eye_max_shift
        return (dx / dist * mag, dy / dist * mag)

    def _update_eyes(self, dt: float, now: float) -> None:
        if self.face is None or self.mode != "idle":
            return
        s = self.settings

        if self.chat_open:
            self.eye_track = True
        elif now >= self.eye_next:
            if random.random() < s.eye_track_chance:
                self.eye_track = True
                self.eye_track_until = now + random.uniform(s.eye_track_min, s.eye_track_max)
                self.eye_next = self.eye_track_until + random.uniform(
                    s.eye_glance_min, s.eye_glance_max
                )
            else:
                self.eye_track = False
                self.eye_next = now + random.uniform(s.eye_glance_min, s.eye_glance_max)
                if random.random() < 0.5:
                    self.eye_wander = (0.0, 0.0)
                else:
                    angle = random.uniform(0.0, math.tau)
                    radius = random.uniform(0.25, 0.6) * s.eye_max_shift
                    self.eye_wander = (math.cos(angle) * radius, math.sin(angle) * radius)

        if self.eye_track and not self.chat_open and now >= self.eye_track_until:
            self.eye_track = False
            self.eye_next = max(
                self.eye_next, now + random.uniform(s.eye_glance_min, s.eye_glance_max)
            )

        tx, ty = self._eye_target()
        k = min(1.0, dt * s.eye_ease)
        self.eye_dx += (tx - self.eye_dx) * k
        self.eye_dy += (ty - self.eye_dy) * k

    def _clamp_x(self) -> float:
        lo, hi = self._walk_limits()
        return min(max(self.x, lo), hi)

    def update(self, dt: float) -> None:
        now = time.perf_counter()

        self._consume_menu()
        if not self.running:
            return

        if (
            self.transition is None
            and not self.chat_open
            and now - self._topmost_at > 1.0
            and not self._tk_menu_open()
        ):
            self._apply_topmost()
            self._topmost_at = now

        if self.transition is not None:
            glitch = self.glitch
            if glitch is not None:
                glitch.tick(now)
                if now - self.transition_start < glitch.duration:
                    return
            self._finish_transition()
            return

        if self.dragging:
            if self.mode == "idle":
                self._update_eyes(dt, now)
            return

        if self.mode == "talk":
            if now >= self.talk_until:
                self._begin_transition("idle")
            return

        if self.chat_open:
            if self.mode != "idle":
                self.mode = "idle"
                self.mode_timer = 0.0
                self.next_thought = random.uniform(
                    self.settings.idle_min, self.settings.idle_max
                )
            self._update_eyes(dt, now)
            return

        if self.mode == "walk":
            remaining = self.walk_target - self.x
            step = self.settings.speed * dt
            if abs(remaining) <= step:
                self.x = self.walk_target
                self._begin_transition("idle")
            else:
                self.x += step if remaining > 0 else -step
                self.facing_left = remaining < 0
            self.x = self._clamp_x()

        elif self.mode == "idle2":
            self.mode_timer -= dt
            if self.mode_timer <= 0:
                self._begin_transition("idle")

        else:
            self._update_eyes(dt, now)
            self.next_thought -= dt
            if self.next_thought <= 0:
                self.think()

    def render(self) -> None:
        if self.transition is not None:
            return
        if self.mode == "talk" and self.talk is not None:
            surf = self.talk.frame(time.perf_counter())
        elif self.mode == "idle" and self.face is not None:
            surf = self.face.draw(int(round(self.eye_dx)), int(round(self.eye_dy)))
        elif self.mode == "idle2" and self.actions.get("idle2") is not None:
            surf = self.actions["idle2"].surface(False, self.cache)
        elif self.mode == "walk":
            surf = self.actions["walk"].surface(self.facing_left, self.cache)
        else:
            self.mode = "idle"
            idle = self.actions.get("idle")
            surf = (
                idle.surface(False, self.cache)
                if idle is not None
                else self.face.draw(0, 0)
            )
        self.current = surf
        self._blit(surf)

    # ---- main loop

    def run(self) -> None:
        msg = MSG()
        last = time.perf_counter()
        target = 1.0 / 60.0
        while self.running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_QUIT:
                    self.running = False
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if not self.running:
                break
            now = time.perf_counter()
            dt = now - last
            last = now
            self.update(min(dt, 0.1))
            try:
                self.render()
            except Exception as exc:  # noqa: BLE001
                print(f"[capri] render error: {exc}")
                time.sleep(0.5)
            slept = time.perf_counter() - now
            if slept < target:
                time.sleep(target - slept)
        self.shutdown()

    def shutdown(self) -> None:
        self._unregister_hotkeys()
        if self.dragging:
            try:
                user32.ReleaseCapture()
            except Exception:  # noqa: BLE001
                pass
            self.dragging = False
        self._cancel_transition()
        self._dispose_talk()
        if self.glitch is not None:
            self.glitch.close()
            self.glitch = None
        chat = self.chat
        self.chat = None
        if chat is not None:
            chat.quit()
        self.current = None
        for surf in self.cache.values():
            surf.free()
        self.cache.clear()
        self._dispose_art()


def main() -> int:
    set_dpi_aware()
    cfg_path = os.path.join(HERE, "capri_config.txt")
    cfg = read_config(cfg_path)
    if not cfg:
        print(f"[capri] no config found at {cfg_path}, using built-in defaults")
    try:
        pet = Pet(cfg)
    except FileNotFoundError as exc:
        print(f"[capri] {exc}")
        return 1
    print("[capri] running. Ctrl+Alt+Q quits, Ctrl+Alt+R reloads.")
    pet.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
