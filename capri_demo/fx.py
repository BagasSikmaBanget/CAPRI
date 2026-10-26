"""Full-screen effects, ported from capri-desktop's fx.js.

The desktop app paints its effects in a WebGL canvas that covers the work
area. Here a second layered window does the same job: one transparent,
click-through, always-on-top sheet the size of the desktop. Capri's own
window sits underneath it, so effects can draw over her and over the panel.

Everything is plain Pillow drawing. The canvas is only rendered while there
is at least one effect alive, then the window hides itself again.
"""

from __future__ import annotations

import ctypes
import math
import os
import random
import time

from PIL import Image, ImageChops, ImageDraw

from .art import Surface, ui_font
from .win32 import (
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BLENDFUNCTION,
    HWND_TOPMOST,
    POINT,
    SIZE,
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    ULW_ALPHA,
    WNDCLASSW,
    WNDPROC,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    WS_POPUP,
    HTTRANSPARENT,
    WM_NCHITTEST,
    gdi32,
    kernel32,
    user32,
    work_area,
)
from .windows import Rect

# ------------------------------------------------------------------ palette

INK = (14, 12, 20, 255)
PAPER = (242, 236, 222, 255)
RED = (230, 36, 44, 255)
VIOLET = (109, 74, 255, 255)
MINT = (79, 227, 176, 255)
WHITE = (255, 255, 255, 255)

FRAME = 1.0 / 24.0

# intro timings, in desktop frames at 24 fps
T_LINE = 9 / 24
T_TEAR = 13 / 24
T_FLASH = 21 / 24
T_HI = 42 / 24
T_POP = 44 / 24
T_BACK = 70 / 24
T_DIVE = 82 / 24
T_TRAVEL = 8 / 24
T_LAND = 92 / 24
T_END = 94 / 24

BEVEL = 0.12


def _a(color, k: float):
    return (color[0], color[1], color[2], max(0, min(255, int(color[3] * k))))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp2(a, b, t):
    return (_lerp(a[0], b[0], t), _lerp(a[1], b[1], t))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _ease_in(t: float) -> float:
    return t * t * t


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def _bezier(p0, p1, p2, t):
    u = 1 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def _shift(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def _bevel_pts(w: int, h: int, cut: int):
    cut = max(2, min(cut, w // 2 - 1, h // 2 - 1))
    return [
        (cut, 0), (w - cut, 0), (w, cut), (w, h - cut),
        (w - cut, h), (cut, h), (0, h - cut), (0, cut),
    ]


def _star_pts(cx, cy, s):
    k = s * 0.24
    return [
        (cx, cy - s), (cx + k, cy - k), (cx + s, cy), (cx + k, cy + k),
        (cx, cy + s), (cx - k, cy + k), (cx - s, cy), (cx - k, cy - k),
    ]


def _shard_pts(cx, cy, angle, length, width):
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    return [
        (cx + dx * length / 2, cy + dy * length / 2),
        (cx + nx * width / 2, cy + ny * width / 2),
        (cx - dx * length / 2, cy - dy * length / 2),
        (cx - nx * width / 2, cy - ny * width / 2),
    ]


def _jag(a, b, segments: int, amp: float, rng: random.Random):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    pts = [(ax, ay)]
    for i in range(1, max(2, segments)):
        f = i / segments
        off = rng.uniform(-amp, amp)
        pts.append((ax + dx * f + nx * off, ay + dy * f + ny * off))
    pts.append((bx, by))
    return pts


def _dash(draw, a, b, color, width, dash=9, gap=7, offset=0.0):
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length < 1:
        return
    dx, dy = (bx - ax) / length, (by - ay) / length
    step = dash + gap
    pos = -offset % step
    while pos < length:
        start = max(0.0, pos)
        end = min(length, pos + dash)
        if end > start:
            draw.line(
                [(ax + dx * start, ay + dy * start), (ax + dx * end, ay + dy * end)],
                fill=color,
                width=max(1, int(width)),
            )
        pos += step


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    if img.width <= 0 or img.height <= 0 or w <= 0 or h <= 0:
        return Image.new("RGBA", (max(1, w), max(1, h)))
    k = max(w / img.width, h / img.height)
    nw, nh = max(w, round(img.width * k)), max(h, round(img.height * k))
    big = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return big.crop((x, y, x + w, y + h))


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    k = min(w / max(1, img.width), h / max(1, img.height))
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


# ------------------------------------------------------------------- window


class FxWindow:
    """One transparent sheet over the whole work area."""

    _class_name = "CapriDemoFxWindow"
    _registered = False

    def __init__(self, work: Rect):
        self.work = work
        self.hwnd = None
        self.surface: Surface | None = None
        self.visible = False
        self._proc = WNDPROC(self._wndproc)
        self._create()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _create(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        if not FxWindow._registered:
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            user32.RegisterClassW(ctypes.byref(wc))
            FxWindow._registered = True
        ex = (
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )
        self.hwnd = user32.CreateWindowExW(
            ex,
            self._class_name,
            "Capri effects",
            WS_POPUP,
            self.work.left,
            self.work.top,
            self.work.w,
            self.work.h,
            None,
            None,
            hinst,
            None,
        )
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def show(self) -> None:
        if not self.hwnd:
            return
        if not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.visible = True
        self.raise_()

    def raise_(self) -> None:
        if self.hwnd:
            user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )

    def hide(self) -> None:
        if self.hwnd and self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def blit(self, img: Image.Image) -> None:
        if not self.hwnd:
            return
        self.show()
        if self.surface is None:
            self.surface = Surface(img, (0, 0, img.width, img.height))
        else:
            self.surface.set_image(img)
        screen = user32.GetDC(None)
        try:
            dst = POINT(self.work.left, self.work.top)
            size = SIZE(img.width, img.height)
            src = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            ok = user32.UpdateLayeredWindow(
                self.hwnd, screen, ctypes.byref(dst), ctypes.byref(size),
                self.surface.hdc, ctypes.byref(src), 0,
                ctypes.byref(blend), ULW_ALPHA,
            )
            if not ok and os.environ.get("CAPRI_FX_DEBUG"):
                print(f"[fx] UpdateLayeredWindow failed: {ctypes.get_last_error()}")
        finally:
            user32.ReleaseDC(None, screen)

    def close(self) -> None:
        self.hide()
        if self.surface is not None:
            self.surface.free()
            self.surface = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None


# -------------------------------------------------------------------- layer


class FxLayer:
    def __init__(self, settings, sounds=None):
        self.settings = settings
        self.sounds = sounds
        r = work_area()
        self.work = Rect(r.left, r.top, r.right, r.bottom)
        self.window = FxWindow(self.work)
        self.items: list[dict] = []
        self.last_draw = 0.0
        self.faces: list[Image.Image] = []
        self._load_faces()

    # -- plumbing ---------------------------------------------------------

    def _load_faces(self) -> None:
        face_dir = getattr(self.settings, "desktop_face_dir", self.settings.face_dir)
        path = os.path.join(face_dir, "intro-face.webp")
        try:
            strip = Image.open(path).convert("RGBA")
        except OSError:
            return
        count = max(1, strip.width // 400)
        for i in range(count):
            self.faces.append(strip.crop((i * 400, 0, (i + 1) * 400, strip.height)))

    def _add(self, life: float, draw, fps: float = 24.0, delay: float = 0.0, done=None):
        item = {
            "born": time.perf_counter() + delay,
            "life": max(0.01, life),
            "draw": draw,
            "fps": fps,
            "done": done,
            "dead": False,
        }
        self.items.append(item)
        self.last_draw = 0.0
        return item

    def cue(self, name: str) -> None:
        if self.sounds is not None:
            try:
                self.sounds.play(name)
            except Exception:  # noqa: BLE001
                pass

    @property
    def active(self) -> bool:
        return bool(self.items)

    def tick(self) -> bool:
        now = time.perf_counter()
        if not self.items:
            self.window.hide()
            return False
        live = [it for it in self.items if it["born"] <= now and not it["dead"]]
        fps = max((it["fps"] for it in live), default=12.0)
        if now - self.last_draw < 1.0 / max(6.0, fps):
            return True

        img = Image.new("RGBA", (self.work.w, self.work.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        keep: list[dict] = []
        for it in list(self.items):
            if it["dead"]:
                continue
            age = now - it["born"]
            if age < 0:
                keep.append(it)
                continue
            t = age / it["life"]
            if t >= 1.0:
                if it["done"] is not None:
                    try:
                        it["done"]()
                    except Exception:  # noqa: BLE001
                        pass
                continue
            try:
                it["draw"](now, t, img, draw)
            except Exception as exc:  # noqa: BLE001
                if os.environ.get("CAPRI_FX_DEBUG"):
                    print(f"[fx] draw failed: {exc!r}")
                continue
            keep.append(it)
        self.items = keep
        self.last_draw = now
        if not self.items:
            self.window.hide()
            return False
        self.window.blit(img)
        return True

    def raise_(self) -> None:
        if self.items:
            self.window.raise_()

    def hide(self) -> None:
        self.items.clear()
        self.window.hide()

    def close(self) -> None:
        self.items.clear()
        self.window.close()

    # -- tiny primitives --------------------------------------------------

    @staticmethod
    def _sparkle(draw, x, y, s, color=WHITE, core=PAPER, k=1.0):
        if s <= 0:
            return
        draw.polygon(_star_pts(x, y, s), fill=_a(color, k))
        draw.polygon(_star_pts(x, y, s * 0.45), fill=_a(core, k))

    @staticmethod
    def _eye(draw, x, y, r, dx, dy, color=INK, lid=False):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=PAPER)
        px = x + dx * r * 0.38
        py = y + dy * r * 0.38
        draw.ellipse((px - r * 0.46, py - r * 0.46, px + r * 0.46, py + r * 0.46), fill=color)
        if lid:
            draw.rectangle((x - r, y - r, x + r, y - r * 0.1), fill=PAPER)

    @staticmethod
    def _tag(draw, x, y, text, fill=INK, ink=PAPER, size=10):
        font = ui_font(size, True)
        box = draw.textbbox((0, 0), text, font=font)
        w, h = box[2] - box[0] + 14, box[3] - box[1] + 8
        draw.polygon(
            [(x, y), (x + w, y), (x + w - 6, y + h), (x, y + h)],
            fill=fill,
        )
        draw.text((x + 6, y + 3 - box[1]), text, font=font, fill=ink)
        return w, h

    # -- effects ----------------------------------------------------------

    def sparkle_at(self, x, y, s=18, life=0.45, color=WHITE, delay=0.0):
        def draw(now, t, img, d):
            k = 1 - t
            grow = min(1.0, t * 5)
            self._sparkle(d, x, y, s * grow, color, WHITE, k)
            if t < 0.5:
                d.ellipse((x - s * 0.12, y - s * 0.12, x + s * 0.12, y + s * 0.12), fill=_a(RED, k))

        self._add(life, draw, delay=delay)

    def burst(self, x, y, life=0.55, count=18, inward=False, delay=0.0):
        rng = random.Random((int(x) * 73856093) ^ (int(y) * 19349663))
        parts = []
        for i in range(count):
            ang = rng.uniform(0, math.tau)
            speed = rng.uniform(90, 330)
            parts.append({
                "a": ang,
                "v": speed,
                "len": rng.uniform(7, 22),
                "wid": rng.uniform(2, 6),
                "spin": rng.uniform(-9, 9),
                "color": rng.choice((PAPER, PAPER, RED, VIOLET, MINT)),
                "r": rng.uniform(50, 120),
            })

        def draw(now, t, img, d):
            k = 1 - t
            cx, cy = x, y
            if inward:
                for p in parts:
                    r = p["r"] * (1 - _ease_in(t))
                    px = cx + math.cos(p["a"]) * r
                    py = cy + math.sin(p["a"]) * r
                    d.polygon(
                        _shard_pts(px, py, p["a"] + p["spin"] * t, p["len"] * 0.8, p["wid"]),
                        fill=_a(p["color"], k),
                    )
                d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=_a(PAPER, k))
                return
            d.ellipse(
                (cx - 14 - 46 * t, cy - 14 - 46 * t, cx + 14 + 46 * t, cy + 14 + 46 * t),
                outline=_a(RED, k * 0.8), width=2,
            )
            for p in parts:
                r = p["v"] * t
                px = cx + math.cos(p["a"]) * r
                py = cy + math.sin(p["a"]) * r + 120 * t * t
                d.polygon(
                    _shard_pts(px, py, p["a"] + p["spin"] * t, p["len"] * (1 - t * 0.5), p["wid"]),
                    fill=_a(p["color"], k),
                )
            if t < 0.35:
                self._sparkle(d, cx, cy, 34 * (1 - t * 3), WHITE, RED, k)

        self._add(life, draw, delay=delay)

    def slit(self, x, y, w=26, h=120, life=0.34, delay=0.0):
        def draw(now, t, img, d):
            k = math.sin(min(1.0, t) * math.pi)
            hh = h * k
            d.rectangle((x - w / 2, y - hh / 2, x + w / 2, y + hh / 2), fill=INK)
            d.line((x, y - hh / 2, x, y + hh / 2), fill=_a(RED, 0.9), width=2)
            if t < 0.6:
                self._sparkle(d, x, y - hh / 2, 10, RED, PAPER, 1 - t)

        self._add(life, draw, delay=delay)

    def slices(self, x, y, w=90, h=170, life=0.42, delay=0.0):
        rng = random.Random((int(x) * 2654435761) ^ int(y))
        bands = []
        for i in range(9):
            bands.append({
                "y": rng.uniform(-h / 2, h / 2),
                "h": rng.uniform(5, 16),
                "dx": rng.uniform(-90, 90),
                "dy": rng.uniform(-24, 24),
            })

        def draw(now, t, img, d):
            k = 1 - t
            for b in bands:
                off = _ease_in(t)
                yy = y + b["y"] + b["dy"] * off
                d.rectangle(
                    (x - w / 2 + b["dx"] * off, yy, x + w / 2 + b["dx"] * off, yy + b["h"]),
                    fill=_a(rng.choice((INK, INK, PAPER, VIOLET)), k * 0.85),
                )

        self._add(life, draw, delay=delay)

    def streak(self, a, b, life=0.2, color=RED, delay=0.0):
        rng = random.Random(7)
        pts = _jag(a, b, 9, 10, rng)

        def draw(now, t, img, d):
            k = 1 - t
            d.line(pts, fill=_a(color, k), width=3, joint="curve")
            d.line(pts, fill=_a(PAPER, k * 0.7), width=1, joint="curve")
            for i in range(5):
                f = (i / 5 + t) % 1.0
                px = _lerp(a[0], b[0], f)
                py = _lerp(a[1], b[1], f)
                d.rectangle((px - 2, py - 2, px + 2, py + 2), fill=_a(WHITE, k))

        self._add(life, draw, delay=delay)

    def beam(self, x, top, bottom, life=0.55, down=True, delay=0.0):
        rng = random.Random(int(x))

        def draw(now, t, img, d):
            k = 1 - t
            tip = _lerp(top, bottom, _ease_out(min(1, t * 1.6)))
            pts = _jag((x, top), (x, tip), 10, 16, rng)
            d.line(pts, fill=_a(RED, k), width=4, joint="curve")
            d.line(pts, fill=_a(PAPER, k * 0.8), width=2, joint="curve")
            for off in (-18, 18):
                fork = _jag((x, tip - 40), (x + off, tip), 5, 8, rng)
                d.line(fork, fill=_a(VIOLET, k * 0.7), width=2, joint="curve")
            d.ellipse((x - 12, tip - 12, x + 12, tip + 12), fill=_a(PAPER, k))
            d.ellipse((x - 5, tip - 5, x + 5, tip + 5), fill=_a(RED, k))

        self._add(life, draw, delay=delay)

    def vortex(self, x, y, r=110, life=0.55, delay=0.0):
        rng = random.Random(11)

        def draw(now, t, img, d):
            k = 1 - t
            for i in range(16):
                ang = i * math.tau / 16 + t * 5.2
                rr = r * (1 - t) * (0.35 + (i % 5) * 0.16)
                px, py = x + math.cos(ang) * rr, y + math.sin(ang) * rr
                d.polygon(
                    _shard_pts(px, py, ang + 1.2, 8 + (i % 4) * 5, 3),
                    fill=_a((PAPER, RED, VIOLET, MINT)[i % 4], k),
                )
            d.ellipse((x - r * (1 - t) * 0.9, y - 4, x + r * (1 - t) * 0.9, y + 4),
                      outline=_a(VIOLET, k * 0.8), width=2)
            d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=_a(INK, k))

        self._add(life, draw, delay=delay)

    def ring(self, x, y, life=0.5, color=VIOLET, delay=0.0):
        def draw(now, t, img, d):
            k = 1 - t
            rr = 20 + 190 * _ease_out(t)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=_a(color, k), width=max(1, int(6 * k)))
            rr2 = rr * 0.62
            d.ellipse((x - rr2, y - rr2, x + rr2, y + rr2), outline=_a(PAPER, k * 0.7), width=2)

        self._add(life, draw, delay=delay)

    def lines(self, x, y, life=0.55, delay=0.0):
        rng = random.Random(19)

        def draw(now, t, img, d):
            k = 1 - t
            for i in range(30):
                ang = i * math.tau / 30 + rng.uniform(-0.03, 0.03)
                inner = 40 + 260 * (1 - t)
                outer = inner + 150
                d.polygon(
                    [
                        (x + math.cos(ang) * inner, y + math.sin(ang) * inner),
                        (x + math.cos(ang + 0.02) * outer, y + math.sin(ang + 0.02) * outer),
                        (x + math.cos(ang - 0.02) * outer, y + math.sin(ang - 0.02) * outer),
                    ],
                    fill=_a(INK, k * 0.7),
                )
            d.ellipse((x - 34, y - 34, x + 34, y + 34), outline=_a(RED, k), width=3)

        self._add(life, draw, delay=delay)

    def glyphs(self, x, y, text="", life=1.1, color=MINT, delay=0.0):
        rng = random.Random(23)
        bits = [text] if text else ["01", "///", "ERR", ">", "<", "101", "NULL"]

        def draw(now, t, img, d):
            k = 1 - t
            font = ui_font(10, True)
            for i in range(7):
                px = x + rng.uniform(-60, 60)
                py = y - 70 * t + rng.uniform(-20, 20)
                d.text((px, py), rng.choice(bits), font=font, fill=_a(color, k * 0.8))

        self._add(life, draw, delay=delay)

    def bolt(self, a, b, life=0.38, forks=2, width=3, delay=0.0):
        rng = random.Random((int(a[0]) * 131) ^ (int(b[0]) * 17) ^ int(a[1] + b[1]))
        main = _jag(a, b, 11, 18, rng)
        branches = []
        for i in range(max(0, int(forks))):
            f = rng.uniform(0.25, 0.75)
            px = _lerp(a[0], b[0], f)
            py = _lerp(a[1], b[1], f)
            ang = rng.uniform(-1.1, 1.1)
            ln = rng.uniform(35, 90)
            branches.append(_jag((px, py), (px + math.cos(ang) * ln, py + math.sin(ang) * ln),
                                 5, 8, rng))

        def draw(now, t, img, d):
            k = 1 - t
            for pts in [main, *branches]:
                d.line(pts, fill=_a(VIOLET, k * 0.8), width=max(1, width + 2), joint="curve")
                d.line(pts, fill=_a(RED, k), width=width, joint="curve")
                d.line(pts, fill=_a(PAPER, k * 0.9), width=1, joint="curve")
            self._sparkle(d, a[0], a[1], 12 * k, RED, PAPER, k)
            self._sparkle(d, b[0], b[1], 18 * k, WHITE, RED, k)

        self._add(life, draw, delay=delay)

    def glyph(self, x, y, text="", life=1.15, color=MINT, delay=0.0):
        rng = random.Random((int(x) * 31) ^ int(y))
        word = text or rng.choice(("01", "///", "ERR", ">", "<", "101", "NULL"))
        drift = rng.uniform(-12, 12)
        px = x + rng.uniform(-40, 40)

        def draw(now, t, img, d):
            k = 1 - t
            font = ui_font(10, True)
            d.text((px + drift * t, y - 70 * t), word, font=font, fill=_a(color, k * 0.85))

        self._add(life, draw, delay=delay)

    def drift(self, x, y, angle, life=2.4, delay=0.0):
        rng = random.Random((int(x) * 977) ^ int(y))
        speed = rng.uniform(16, 34)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed - 10
        rot = angle + rng.uniform(-0.4, 0.4)
        vr = rng.uniform(-0.8, 0.8)
        length = rng.uniform(9, 20)
        wid = rng.uniform(3, 6)
        color = rng.choice((RED, RED, RED, INK, PAPER))

        def draw(now, t, img, d):
            k = 1 - t
            px = x + vx * t * life
            py = y + vy * t * life
            d.polygon(_shard_pts(px, py, rot + vr * t * life, length, wid), fill=_a(color, k))

        self._add(life, draw, delay=delay)

    def _face_image(self, i: int, w: int, h: int, split: float = 0.0):
        if not self.faces:
            return Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        face = _cover(self.faces[int(i) % len(self.faces)], w, h)
        if split:
            r, g, b, a = face.split()
            r = ImageChops.offset(r, int(split), 0)
            b = ImageChops.offset(b, -int(split), 0)
            face = Image.merge("RGBA", (r, g, b, a))
        return face

    def face(self, i, x, y, w, h, split=0, life=1.0, delay=0.0):
        face = self._face_image(i, w, h, split)

        def draw(now, t, img, d):
            k = math.sin(min(1.0, t * 1.4) * math.pi)
            img.alpha_composite(face, (int(x), int(y)))
            d.rectangle((x, y, x + w, y + max(2, h // 40)), fill=_a(RED, k))

        self._add(life, draw, delay=delay)

    def portrait(self, x, y, w, h, i, flat=None, glitch=0, copy=1, open=1,
                 bar=1, split=0, zoom=1, outline=None, life=1.2, delay=0.0):
        w, h = max(1, int(w)), max(1, int(h))
        frame = self._frame(int(i) % max(1, len(self.faces)), w, h,
                            open_=open, split=split, glitch=glitch)
        if flat is not None:
            d = ImageDraw.Draw(frame)
            d.rectangle((0, 0, w, h), fill=flat)
        if bar > 0:
            d = ImageDraw.Draw(frame)
            d.rectangle((int(w * 0.14), 0, int(w * 0.14 + w * 0.86 * bar),
                         max(2, int(w * 0.014))), fill=RED)

        def draw(now, t, img, d):
            k = 1.0 if t < 0.8 else max(0.0, (1.0 - t) / 0.2)
            if k <= 0:
                return
            if k < 1:
                local = frame.copy()
                local.putalpha(ImageChops.multiply(local.getchannel("A"),
                                                    Image.new("L", frame.size, int(255 * k))))
                img.alpha_composite(local, (int(x - w / 2), int(y - h / 2)))
            else:
                img.alpha_composite(frame, (int(x - w / 2), int(y - h / 2)))

        self._add(life, draw, delay=delay)

    def red_line(self, x, y, h, life=0.32, delay=0.0):
        def draw(now, t, img, d):
            k = math.sin(min(1.0, t) * math.pi)
            hh = h * k
            d.rectangle((x - 5, y - hh / 2 + 3, x + 1, y + hh / 2 + 3), fill=_a(VIOLET, k))
            d.rectangle((x - 2.5, y - hh / 2, x + 2.5, y + hh / 2), fill=_a(RED, k))
            d.rectangle((x - 0.75, y - hh * 0.42, x + 0.75, y + hh * 0.42), fill=_a(PAPER, k))

        self._add(life, draw, delay=delay)

    def void_slit(self, x, y, w, h, life=0.4, delay=0.0):
        def draw(now, t, img, d):
            k = math.sin(min(1.0, t) * math.pi)
            hh = h * k
            d.rectangle((x - w / 2 - 3, y - hh / 2, x + w / 2 + 3, y + hh / 2), fill=_a(VIOLET, k))
            d.rectangle((x - w / 2, y - hh / 2, x + w / 2, y + hh / 2), fill=_a(INK, k))
            d.rectangle((x - 1, y - hh * 0.42, x + 1, y + hh * 0.42), fill=_a(RED, k))

        self._add(life, draw, delay=delay)

    def crackle(self, x, y, life=0.4, delay=0.0):
        rng = random.Random(int(x + y))

        def draw(now, t, img, d):
            k = 1 - t
            for i in range(4):
                ang = rng.uniform(0, math.tau)
                end = (x + math.cos(ang) * 42, y + math.sin(ang) * 42)
                d.line(_jag((x, y), end, 4, 7, rng), fill=_a(VIOLET, k), width=1)
            self._sparkle(d, x, y, 12 * (1 - t), RED, PAPER, k)

        self._add(life, draw, delay=delay)

    # -- portrait / intro -------------------------------------------------

    def _frame(self, index: int, w: int, h: int, open_=1.0, split=0, glitch=0.0):
        local = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(local)
        cut = max(6, int(min(w, h) * BEVEL))
        bev = _bevel_pts(w, h, cut)
        d.polygon(_shift(bev, 7, 9), fill=VIOLET)
        d.polygon(bev, fill=INK)
        pad = max(3, cut // 3)
        inner = _bevel_pts(w - 2 * pad, h - 2 * pad, max(2, cut - pad))
        inner = _shift(inner, pad, pad)
        face = self.faces[index] if self.faces else None
        if face is not None:
            face = _cover(face, w - 2 * pad, h - 2 * pad)
            if split:
                r, g, b, a = face.split()
                r = ImageChops.offset(r, split, 0)
                b = ImageChops.offset(b, -split, 0)
                face = Image.merge("RGBA", (r, g, b, a))
            if glitch > 0:
                rng = random.Random(int(time.perf_counter() * 1000) & 0xFFFF)
                for _ in range(4):
                    yy = rng.randrange(0, max(1, face.height - 10))
                    hh = rng.randrange(4, 16)
                    band = face.crop((0, yy, face.width, min(face.height, yy + hh)))
                    face.paste(band, (rng.randrange(-12, 13), yy))
            mask = Image.new("L", (w - 2 * pad, h - 2 * pad), 0)
            ImageDraw.Draw(mask).polygon(
                _bevel_pts(w - 2 * pad, h - 2 * pad, max(2, cut - pad)), fill=255
            )
            local.paste(face, (pad, pad), mask)
        d.rectangle((pad, pad, w - pad, pad + max(2, h // 44)), fill=RED)
        d.line((pad, pad, pad + w // 6, pad), fill=PAPER, width=2)
        if open_ < 1:
            reveal = Image.new("L", (w, h), 0)
            ImageDraw.Draw(reveal).rectangle((0, 0, w, int(h * _clamp(open_, 0, 1))), fill=255)
            local.putalpha(ImageChops.multiply(local.getchannel("A"), reveal))
        return local

    def _name_tag(self, w: int, text: str) -> Image.Image:
        h = max(22, w // 11)
        tag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(tag)
        d.polygon([(0, 0), (w, 0), (w - 12, h), (0, h)], fill=INK)
        d.rectangle((0, 0, 8, h), fill=RED)
        font = ui_font(max(9, int(h * 0.52)), True)
        box = d.textbbox((0, 0), text, font=font)
        d.text((18, (h - (box[3] - box[1])) / 2 - box[1]), text, font=font, fill=PAPER)
        d.rectangle((w - 16, 4, w - 8, h - 4), fill=RED)
        return tag

    def _hi_tag(self, text="hi") -> Image.Image:
        w, h = 58, 36
        tag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(tag)
        d.polygon([(6, 0), (w, 0), (w - 6, h), (0, h)], fill=RED)
        font = ui_font(20, True)
        box = d.textbbox((0, 0), text, font=font)
        d.text(((w - (box[2] - box[0])) / 2, (h - (box[3] - box[1])) / 2 - box[1]),
               text, font=font, fill=PAPER)
        return tag

    def intro(self, to, caption: str = "PROJECT CAPRICORN", label: str = "hi", on_land=None):
        rng = random.Random(31)
        S = int(_clamp(self.work.h * 0.34, 170, 320))
        at = (self.work.right - S * 0.5 - 64, self.work.top + S * 0.5 + 58)
        to = (to[0], to[1])
        ctrl = (min(at[0], to[0]) - S * 0.72, _lerp(at[1], to[1], 0.25))
        state = {"landed": False, "cues": set()}

        def cue(name):
            if name not in state["cues"]:
                state["cues"].add(name)
                self.cue(name)

        def draw(now, t, img, d):
            f = t * T_END * 24
            if f < 2:
                self._sparkle(d, at[0], at[1], 20, WHITE, RED, 1 - f / 2)
                return
            if f < T_LINE * 24:
                grow = (f - 2) / max(1, T_LINE * 24 - 2)
                hh = S * 0.5 * grow
                d.line((at[0], at[1] - hh, at[0], at[1] + hh), fill=RED, width=3)
                self._sparkle(d, at[0], at[1] - hh, 10, RED, PAPER, 1)
                return
            if f < T_TEAR * 24:
                cue("open")
                p = (f - T_LINE * 24) / max(1, (T_TEAR - T_LINE) * 24)
                local = self._frame(0, S, S, open_=p)
                img.alpha_composite(local, (int(at[0] - S / 2), int(at[1] - S / 2)))
                d.line((at[0], at[1] - S / 2, at[0], at[1] + S / 2), fill=_a(RED, 1 - p), width=2)
                return
            if f < T_FLASH * 24:
                cue("tear")
                p = (f - T_TEAR * 24) / max(1, (T_FLASH - T_TEAR) * 24)
                frame = 0 if p < 0.4 else 1
                split = int(4 + 10 * p)
                local = self._frame(frame, S, S, open_=1.0, split=split, glitch=0.2)
                x = int(at[0] - S / 2)
                y = int(at[1] - S / 2)
                img.alpha_composite(local, (x, y))
                if p > 0.55:
                    name = self._name_tag(S, caption)
                    img.alpha_composite(name, (x, y + S + 4))
                if p > 0.7:
                    self._sparkle(d, x + S, y, 24, RED, PAPER, 1)
                return
            if f < T_DIVE * 24:
                cue("flash")
                p = (f - T_FLASH * 24) / max(1, (T_DIVE - T_FLASH) * 24)
                zoom = 1.0 + 0.18 * _ease_in(p)
                size = int(S * zoom)
                local = self._frame(1, size, size, glitch=0.35)
                x = int(at[0] - size / 2 + rng.uniform(-3, 3))
                y = int(at[1] - size / 2 + rng.uniform(-3, 3))
                img.alpha_composite(local, (x, y))
                if p > 0.25:
                    hi = self._hi_tag(label)
                    img.alpha_composite(hi, (x + size - 12, y - 18))
                if p > 0.55:
                    name = self._name_tag(S, caption)
                    img.alpha_composite(name, (int(at[0] - S / 2), int(at[1] + S / 2 + 4)))
                if p > 0.0:
                    tint = Image.new(
                        "RGBA", (self.work.w, self.work.h), _a(PAPER, p * 0.12)
                    )
                    img.alpha_composite(tint)
                return
            if f < T_LAND * 24:
                cue("dive")
                p = (f - T_DIVE * 24) / max(1, (T_LAND - T_DIVE) * 24)
                e = _ease_in(p)
                pos = _bezier(at, ctrl, to, e)
                size = max(18, int(S * (1 - 0.78 * e)))
                local = self._frame(2, size, size, glitch=0.4)
                img.alpha_composite(local, (int(pos[0] - size / 2), int(pos[1] - size / 2)))
                trail = 8
                for i in range(trail):
                    q = _bezier(at, ctrl, to, max(0.0, e - i * 0.025))
                    self._sparkle(d, q[0], q[1], max(2, 16 - i * 1.6), RED, PAPER, 0.6 * (1 - p))
                return
            if not state["landed"]:
                state["landed"] = True
                cue("land")
                if on_land is not None:
                    try:
                        on_land()
                    except Exception:  # noqa: BLE001
                        pass
            p = min(1.0, (f - T_LAND * 24) / max(1, (T_END - T_LAND) * 24))
            hh = 160 * (1 - p)
            if hh > 1:
                d.rectangle((to[0] - 12, to[1] - hh / 2, to[0] + 12, to[1] + hh / 2), fill=INK)
                d.line((to[0], to[1] - hh / 2, to[0], to[1] + hh / 2), fill=RED, width=2)
            self._sparkle(d, to[0], to[1], 26 * (1 - p), WHITE, RED, 1 - p)

        self._add(T_END, draw, fps=24)

    # -- pointer / possession --------------------------------------------

    def pointer(self, from_fn, rect_fn, aim_fn=None, label="", fade_after=None,
                retract_after=None, delay=0.0):
        state = {"born": time.perf_counter() + delay}
        rng = random.Random(41)

        def draw(now, t, img, d):
            age = now - state["born"]
            if age < 0:
                return
            back = 0.0
            if retract_after is not None and age > retract_after:
                back = min(1.0, (age - retract_after) / 0.18)
                if back >= 1.0:
                    return
            fade = 1.0
            if fade_after is not None and age > fade_after:
                fade = max(0.0, 1.0 - (age - fade_after) / 0.35)
                if fade <= 0.0:
                    return
            rect = rect_fn()
            if rect is None:
                return
            a = from_fn()
            if aim_fn is not None:
                b = aim_fn()
            else:
                b = rect.center
            frame = int(age * 24)
            grow = min(1.0, (frame + 1) / 2) * (1 - back)
            if grow <= 0:
                return
            end = _lerp2(a, b, grow)
            d.line((a, end), fill=_a(INK, 0.9 * fade), width=2)
            _dash(d, a, end, _a(PAPER, 0.95 * fade), 1, 9, 7, offset=age * 60)
            # little packets running down the wire
            for i in range(3):
                f = ((age * 0.9 + i / 3) % 1.0) * grow
                px, py = _lerp2(a, b, f)
                d.rectangle((px - 2, py - 2, px + 2, py + 2), fill=_a(RED, fade))
            ang = math.atan2(b[1] - a[1], b[0] - a[0])
            head = _shard_pts(end[0], end[1], ang, 16, 12)
            d.polygon(head, fill=_a(RED, fade))
            # reticle
            pad = 10 - 5 * min(1.0, frame / 3)
            l, tp, r, bt = rect.left, rect.top, rect.right, rect.bottom
            l = _clamp(l, 2, self.work.w - 2)
            tp = _clamp(tp, 2, self.work.h - 2)
            r = _clamp(r, 2, self.work.w - 2)
            bt = _clamp(bt, 2, self.work.h - 2)
            arm = max(10, min(30, (r - l) * 0.12))
            corners = [
                ((l - pad, tp - pad), (l - pad + arm, tp - pad), (l - pad, tp - pad + arm)),
                ((r + pad, tp - pad), (r + pad - arm, tp - pad), (r + pad, tp - pad + arm)),
                ((l - pad, bt + pad), (l - pad + arm, bt + pad), (l - pad, bt + pad - arm)),
                ((r + pad, bt + pad), (r + pad - arm, bt + pad), (r + pad, bt + pad - arm)),
            ]
            for corner, h1, v1 in corners:
                d.line((corner, h1), fill=_a(PAPER, fade), width=3)
                d.line((corner, v1), fill=_a(PAPER, fade), width=3)
                d.ellipse((corner[0] - 3, corner[1] - 3, corner[0] + 3, corner[1] + 3), fill=_a(RED, fade))
            if label:
                self._tag(d, int(l), int(tp - 24), label, INK, PAPER, 9)
            if frame < 4:
                d.rectangle((l - pad, tp - pad, r + pad, bt + pad), outline=_a(VIOLET, (4 - frame) / 4), width=2)

        return self._add(9999.0, draw, fps=24, delay=delay)

    def possess(self, rect_fn, look_fn, entry=0.0, leave=None, label="POSSESS", delay=0.0):
        state = {"born": time.perf_counter() + delay}

        def draw(now, t, img, d):
            age = now - state["born"]
            if age < 0:
                return
            rect = rect_fn()
            if rect is None:
                return
            x0 = _clamp(rect.left, 0, self.work.w)
            y0 = _clamp(rect.top, 0, self.work.h)
            x1 = _clamp(rect.right, 0, self.work.w)
            y1 = _clamp(rect.bottom, 0, self.work.h)
            w, h = int(x1 - x0), int(y1 - y0)
            if w < 20 or h < 20:
                return
            fade = 1.0
            if leave is not None and age > leave:
                fade = max(0.0, 1.0 - (age - leave) / 0.3)
                if fade <= 0:
                    return
            local = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ld = ImageDraw.Draw(local)
            open_ = 1.0
            if entry > 0:
                open_ = _clamp((age - entry) / 0.45, 0, 1)
            if open_ < 1:
                # shutters slide in from the edges
                for i in range(7):
                    yy = i * h / 7
                    ww = w * (1 - open_) * (1 if i % 2 else 0.8)
                    ld.rectangle((0, yy, ww, yy + h / 7 + 1), fill=_a(INK, 0.9))
                    ld.rectangle((w - ww, yy, w, yy + h / 7 + 1), fill=_a(INK, 0.9))
            else:
                ld.rectangle((0, 0, w, h), fill=(14, 12, 20, 220))
                # scan slices
                for i in range(0, h, 6):
                    if (i // 6) % 7 == 0:
                        ld.rectangle((0, i, w, i + 1), fill=_a(VIOLET, 0.25))
                # perimeter lightning
                per = [(0, 0), (w, 0), (w, h), (0, h)]
                rng = random.Random(53)
                for i in range(4):
                    a, b = per[i], per[(i + 1) % 4]
                    pts = _jag(a, b, 12, 8, rng)
                    ld.line(pts, fill=_a(RED if i % 2 == 0 else VIOLET, 0.95), width=3, joint="curve")
                    ld.line(pts, fill=_a(PAPER, 0.5), width=1, joint="curve")
                dx, dy = look_fn()
                # two big eyes
                for ex in (0.34, 0.66):
                    self._eye(ld, w * ex, h * 0.42, w * 0.09, dx, dy, INK)
                # seven small eyes
                rng2 = random.Random(59)
                for i in range(7):
                    ex = rng2.uniform(0.12, 0.88)
                    ey = rng2.uniform(0.62, 0.82)
                    r = w * rng2.uniform(0.016, 0.028)
                    self._eye(ld, w * ex, h * ey, r, dx, dy, INK)
                # grin
                gy = h * 0.66
                pts = []
                for i in range(11):
                    px = w * (0.2 + 0.6 * i / 10)
                    py = gy + (6 if i % 2 else -6) * (1 - abs(i - 5) / 7)
                    pts.append((px, py))
                ld.line(pts, fill=_a(RED, 0.95), width=3, joint="curve")
                ld.rectangle((0, 0, w, 3), fill=RED)
                self._tag(ld, 8, 8, label, INK, PAPER, 9)
            if fade < 1:
                local.putalpha(local.getchannel("A").point(lambda v: int(v * fade)))
            img.alpha_composite(local, (int(x0), int(y0)))

        self._add(9999.0, draw, fps=24, delay=delay)

    # -- satellites, motes, surges ---------------------------------------

    def motes(self, source_fn, target_fn, life=3.2, align_from=0.5, align_to=2.4, delay=0.0):
        rng = random.Random(67)
        ps = []
        for i in range(16):
            ps.append({
                "x": rng.uniform(-26, 26),
                "y": rng.uniform(-10, 18),
                "s": rng.uniform(1.0, 2.6),
                "ph": rng.uniform(0, math.tau),
                "v": rng.uniform(0.5, 1.4),
                "red": rng.random() < 0.25,
            })

        def draw(now, t, img, d):
            age = t * life
            src = source_fn()
            tgt = target_fn()
            if src is None:
                return
            home = age > align_to
            for i, p in enumerate(ps):
                if home:
                    q = (age - align_to) / max(0.01, life - align_to)
                    px = _lerp(p["x"] + src[0], src[0], _ease_in(q))
                    py = _lerp(p["y"] + src[1], src[1], _ease_in(q))
                    alpha = 1 - q
                else:
                    rise = min(1.0, age / max(0.1, align_from))
                    px = src[0] + p["x"] + math.sin(age * 2 + p["ph"]) * 16
                    py = src[1] + p["y"] - 80 * rise - age * 12 * p["v"]
                    alpha = min(1.0, age * 3)
                    if align_from < age < align_to:
                        q = (age - align_from) / max(0.01, align_to - align_from)
                        tx = tgt[0] + (i - 7) * 4
                        ty = tgt[1] + (i % 5) * 3
                        px = _lerp(px, tx, _ease_in(q) * 0.9)
                        py = _lerp(py, ty, _ease_in(q) * 0.9)
                color = RED if p["red"] else WHITE
                d.ellipse((px - p["s"], py - p["s"], px + p["s"], py + p["s"]),
                          fill=_a(color, alpha))
                if i % 3 == 0 and age > 0.35:
                    d.line((src[0], src[1], px, py), fill=_a(VIOLET, 0.18 * alpha), width=1)

        self._add(life, draw, fps=18, delay=delay)

    def satellite(self, a, b, life=2.4, twinkle=1.3, delay=0.0):
        def draw(now, t, img, d):
            p = _ease_out(min(1, t * 1.25))
            x = _lerp(a[0], b[0], p)
            y = _lerp(a[1], b[1], p) - math.sin(p * math.pi) * 46
            fade = 1.0 if t < 0.85 else (1 - (t - 0.85) / 0.15)
            body = 20
            d.polygon([(x - body, y - 6), (x + body, y - 6), (x + body, y + 6), (x - body, y + 6)],
                      fill=_a(PAPER, fade))
            d.polygon([(x - body - 2, y - 3), (x - body - 2, y + 3), (x - body - 16, y + 8),
                       (x - body - 16, y - 8)], fill=_a(VIOLET, fade))
            d.polygon([(x + body + 2, y - 3), (x + body + 2, y + 3), (x + body + 16, y + 8),
                       (x + body + 16, y - 8)], fill=_a(VIOLET, fade))
            d.rectangle((x - 5, y - 10, x + 5, y - 6), fill=_a(INK, fade))
            d.ellipse((x - 3, y - 12, x + 3, y - 6), fill=_a(RED, fade))
            for i in range(4):
                d.line((x - 18 - i * 3, y - 8, x - 18 - i * 3, y + 8), fill=_a(INK, fade), width=1)
            if twinkle <= t <= twinkle + 0.25:
                k = 1 - abs(t - (twinkle + 0.12)) / 0.13
                self._sparkle(d, x, y, 30 * k, WHITE, RED, k)
            d.line((x, y + 10, x, y + 24), fill=_a(VIOLET, 0.5 * fade), width=1)

        self._add(life, draw, fps=24, delay=delay)

    def surge(self, a, b, life=1.1, on_hit=None, delay=0.0):
        rng = random.Random(71)
        state = {"hit": False}
        pieces = [{
            "x": b[0] + rng.uniform(-30, 30), "y": b[1] + rng.uniform(-20, 20),
            "vx": rng.uniform(-50, 50), "vy": rng.uniform(-40, 70),
            "len": rng.uniform(4, 14), "spin": rng.uniform(-6, 6),
        } for _ in range(9)]

        def draw(now, t, img, d):
            if t < 0.3:
                p = _jag(a, b, 12, 18, rng)
                d.line(p, fill=_a(INK, 0.9), width=6, joint="curve")
                d.line(p, fill=_a(PAPER, 0.9), width=3, joint="curve")
                d.line(p, fill=_a(RED, 0.8), width=1, joint="curve")
                for i in range(4):
                    off = rng.uniform(-26, 26)
                    q = _jag(a, (b[0] + off, b[1] + off * 0.4), 7, 12, rng)
                    d.line(q, fill=_a(VIOLET, 0.65), width=2, joint="curve")
                self._sparkle(d, b[0], b[1], 28, WHITE, RED, 1)
                return
            if not state["hit"]:
                state["hit"] = True
                if on_hit is not None:
                    try:
                        on_hit()
                    except Exception:  # noqa: BLE001
                        pass
            q = (t - 0.3) / 0.7
            k = 1 - q
            for p in pieces:
                px = p["x"] + p["vx"] * q
                py = p["y"] + p["vy"] * q + 160 * q * q
                d.polygon(_shard_pts(px, py, p["spin"] * q, p["len"], 2),
                          fill=_a(rng.choice((PAPER, RED, VIOLET)), k))
            if q < 0.4:
                self._sparkle(d, b[0], b[1], 20 * (1 - q / 0.4), WHITE, RED, k)

        self._add(life, draw, fps=24, delay=delay)

    # -- cut-ins ----------------------------------------------------------

    def cutin(self, kind: str, x: int, y: int, life=1.7, label="", delay=0.0):
        face_dir = getattr(self.settings, "desktop_face_dir", self.settings.face_dir)
        path = os.path.join(face_dir, f"cutin-{kind}.png")
        try:
            art = Image.open(path).convert("RGBA")
        except OSError:
            art = None
        w, h = 360, 240
        rng = random.Random(73)

        def draw(now, t, img, d):
            open_ = min(1.0, t * 4)
            tall = min(1.0, max(0.0, (t - 0.12) / 0.3))
            fade = 1.0 if t < 0.8 else (1 - (t - 0.8) / 0.2)
            hh = h * tall * (1 - max(0, (t - 0.88) / 0.12))
            if hh < 4:
                return
            band = [
                (x - w / 2 + 26, y - hh / 2), (x + w / 2, y - hh / 2),
                (x + w / 2 - 26, y + hh / 2), (x - w / 2, y + hh / 2),
            ]
            d.polygon(_shift(band, 8, 10), fill=_a(VIOLET, fade))
            d.polygon(band, fill=_a(INK, fade))
            if art is not None:
                face = _fit(art, int(w * 0.55), int(hh * 0.82))
                mask = Image.new("L", face.size, 0)
                ImageDraw.Draw(mask).rectangle((0, 0, face.width, face.height), fill=255)
                face.putalpha(mask)
                img.alpha_composite(face, (int(x - w * 0.42), int(y - face.height / 2)))
            # speed lines
            for i in range(6):
                ly = y - hh / 2 + hh * (i + 0.5) / 6
                d.line((x + w * 0.05, ly, x + w / 2 - 20, ly + rng.uniform(-3, 3)),
                       fill=_a(PAPER, 0.5 * fade), width=1)
            d.rectangle((x - w / 2 + 20, y - hh / 2, x + w / 2 - 20, y - hh / 2 + 4),
                        fill=_a(RED, fade))
            if label:
                self._tag(d, int(x - w / 2 + 26), int(y + hh / 2 + 4), label, INK, PAPER, 9)
            if t < 0.18:
                d.rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2),
                            fill=_a(PAPER, (0.18 - t) / 0.18 * 0.3))

        self._add(life, draw, fps=24, delay=delay)

    # -- composite helpers ------------------------------------------------

    def teleport(self, a, b):
        self.slices(a[0], a[1], 100, 200, 0.42)
        self.slit(a[0], a[1], 28, 200, 0.34)
        self.burst(a[0], a[1], 0.4, count=14, inward=True)
        self.streak(a, b, 0.2, RED, delay=0.12)
        self.vortex(b[0], b[1], 110, 0.55, delay=0.18)
        self.beam(b[0], self.work.bottom, b[1], 0.55, delay=0.18)
        self.burst(b[0], b[1], 0.55, count=20, delay=0.18)
        self.ring(b[0], b[1], 0.5, VIOLET, delay=0.2)

    def scan(self, a, b, life=0.9):
        self.streak(a, b, life * 0.5, VIOLET)
        self.glyphs(b[0], b[1], "", life)
        self.ring(b[0], b[1], life * 0.7, MINT)
