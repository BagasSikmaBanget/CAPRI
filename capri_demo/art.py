"""Art loading, layered surfaces and the animated sprites.

The Surface/Action/GazeFace/SpriteGlitch/TalkRenderer classes come from CAPRI's
capri.py; they are the part that makes the pet feel alive.
"""

from __future__ import annotations

import ctypes
import math
import os
import random
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .win32 import (
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BI_RGB,
    BITMAPINFO,
    BITMAPINFOHEADER,
    BLENDFUNCTION,
    POINT,
    SIZE,
    ULW_ALPHA,
    gdi32,
    user32,
)


# ------------------------------------------------------------------ images


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


def fit_image(img: Image.Image, width: int, height: int) -> Image.Image:
    """Scale an RGBA image to fit inside a box, keeping its aspect ratio."""
    if img.width <= 0 or img.height <= 0:
        return img
    k = min(width / img.width, height / img.height)
    size = (max(1, round(img.width * k)), max(1, round(img.height * k)))
    return img.resize(size, Image.LANCZOS)


# ---------------------------------------------------------------- surfaces


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

        r, g, b, a = img.split()
        prem = Image.merge(
            "RGBA",
            (
                ImageChops.multiply(r, a),
                ImageChops.multiply(g, a),
                ImageChops.multiply(b, a),
                a,
            ),
        )
        self.alpha = a.tobytes()
        ctypes.memmove(self.bits, prem.tobytes("raw", "BGRA"), self.w * self.h * 4)

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

    def image(self, facing_left: bool = False) -> Image.Image:
        img = self._img
        if facing_left:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        return img

    def surface(self, facing_left: bool, cache: dict) -> Surface:
        key = (self.name, facing_left)
        surf = cache.get(key)
        if surf is None:
            img = self.image(facing_left)
            surf = Surface(img, content_box(img))
            cache[key] = surf
        return surf

    def close(self) -> None:
        if self._img is not None:
            self._img.close()
            self._img = None


class WalkCycle:
    """A still walk pose animated with a small bob, sway and lean."""

    def __init__(
        self,
        action: Action,
        frames: int = 8,
        fps: float = 8.0,
        bob: float = 4.0,
        sway: float = 2.0,
        lean: float = 2.5,
    ):
        self.action = action
        self.frames = max(2, int(frames))
        self.fps = max(1.0, float(fps))
        self.bob = max(0.0, float(bob))
        self.sway = max(0.0, float(sway))
        self.lean = max(0.0, float(lean))
        self.pad = max(2, int(round(max(self.bob, self.sway, 4.0) + 4.0)))
        box = action.box
        self.box = (
            box[0] + self.pad,
            box[1] + self.pad,
            box[2] + self.pad,
            box[3] + self.pad,
        )
        self._images: dict[bool, list[Image.Image]] = {False: [], True: []}
        self._surfaces: dict[bool, list[Surface]] = {False: [], True: []}
        self._build()

    def _make_frame(self, base: Image.Image, phase: float) -> Image.Image:
        w, h = base.size
        cx, foot = w / 2.0, float(h)
        angle = math.radians(self.lean) * math.sin(phase)
        dx = self.sway * math.sin(phase)
        lift = self.bob * abs(math.sin(phase))
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        data = (
            cos_a,
            sin_a,
            cx - cos_a * (self.pad + cx + dx) - sin_a * (self.pad + foot - lift),
            -sin_a,
            cos_a,
            sin_a * (self.pad + cx + dx) - cos_a * (self.pad + foot - lift) + foot,
        )
        return base.transform(
            (w + self.pad * 2, h + self.pad * 2),
            Image.AFFINE,
            data,
            resample=Image.BICUBIC,
        )

    def _build(self) -> None:
        for facing_left in (False, True):
            base = self.action.image(facing_left)
            for index in range(self.frames):
                phase = math.tau * index / self.frames
                self._images[facing_left].append(self._make_frame(base, phase))

        boxes = [
            content_box(img)
            for frames in self._images.values()
            for img in frames
        ]
        if boxes:
            self.box = (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            )
        for facing_left in (False, True):
            for img in self._images[facing_left]:
                self._surfaces[facing_left].append(Surface(img, self.box))

    def _index(self, now: float) -> int:
        return int(now * self.fps) % self.frames

    def image(self, now: float, facing_left: bool) -> Image.Image:
        return self._images[bool(facing_left)][self._index(now)]

    def surface(self, now: float, facing_left: bool) -> Surface:
        return self._surfaces[bool(facing_left)][self._index(now)]

    def close(self) -> None:
        for frames in self._surfaces.values():
            for surf in frames:
                surf.free()
        self._surfaces = {False: [], True: []}
        for frames in self._images.values():
            for img in frames:
                img.close()
        self._images = {False: [], True: []}


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


# ---------------------------------------------------------- sprite glitch

SPRITE_GLITCH_PAD = 24


def _sprite_image(surf: Surface) -> Image.Image:
    """Recover an un-premultiplied RGBA image from a Surface."""
    raw = ctypes.string_at(surf.bits, surf.w * surf.h * 4)
    img = Image.frombytes("RGBA", (surf.w, surf.h), raw, "raw", "BGRA")
    px = img.load()
    for y in range(surf.h):
        for x in range(surf.w):
            r, g, b, a = px[x, y]
            if 0 < a < 255:
                px[x, y] = (
                    min(255, (r * 255 + a // 2) // a),
                    min(255, (g * 255 + a // 2) // a),
                    min(255, (b * 255 + a // 2) // a),
                    a,
                )
    return img


class SpriteGlitch:
    """Tears the current pet sprite apart before a pose or menu change runs."""

    def __init__(self, surf: Surface, seconds: float, fps: int):
        self.seconds = max(0.08, seconds)
        self.fps = max(4, fps)
        self.original: Surface | None = surf
        self.pad = SPRITE_GLITCH_PAD
        self.base = Image.new(
            "RGBA",
            (surf.w + self.pad * 2, surf.h + self.pad * 2),
            (0, 0, 0, 0),
        )
        self.base.alpha_composite(_sprite_image(surf), (self.pad, self.pad))
        l, t, r, b = surf.box
        self.box = (l + self.pad, t + self.pad, r + self.pad, b + self.pad)
        self._alpha = self.base.getchannel("A")
        self._count = max(4, round(self.seconds * self.fps))
        self._rng = random.Random()
        self.out: Surface | None = Surface.blank(self.base.width, self.base.height)
        self.out.box = self.box
        self.started = time.perf_counter()
        self._last = -1

    def _make_frame(self, progress: float, rng: random.Random) -> Image.Image:
        base = self.base
        alpha = self._alpha
        w, h = base.size
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        shift = max(8, round(w * 0.22))
        y = 0
        while y < h:
            band = rng.randint(2, max(4, h // 9))
            dx = 0
            if rng.random() < 0.35 + 0.5 * progress:
                dx = rng.randint(-shift, shift)
            dy = rng.randint(-12, 12) if rng.random() < 0.12 else 0
            canvas.alpha_composite(
                base.crop((0, y, w, min(h, y + band))), (dx, y + dy)
            )
            y += band

        for _ in range(rng.randint(0, 2)):
            y = rng.randint(0, max(0, h - 1))
            band = rng.randint(2, max(4, h // 6))
            canvas.alpha_composite(
                base.crop((0, y, w, min(h, y + band))),
                (rng.randint(-shift, shift), y),
            )

        r, g, b, a = canvas.split()
        split = max(2, round(w * 0.05))
        r = ImageChops.offset(r, rng.randint(-split, split), 0)
        b = ImageChops.offset(b, rng.randint(-split, split), 0)
        canvas = Image.merge("RGBA", (r, g, b, a))

        if rng.random() < 0.5:
            y = rng.randint(0, max(0, h - 1))
            band = rng.randint(2, max(3, h // 6))
            patch = canvas.crop((0, y, w, min(h, y + band)))
            rgb = ImageChops.invert(patch.convert("RGB"))
            patch = Image.merge("RGBA", (*rgb.split(), patch.getchannel("A")))
            canvas.paste(patch, (0, y))

        if rng.random() < 0.35:
            div = rng.choice((4, 6, 8))
            small = canvas.resize(
                (max(2, w // div), max(2, h // div)), Image.NEAREST
            )
            canvas = small.resize((w, h), Image.NEAREST)

        if rng.random() < 0.3:
            colour = rng.choice(
                (
                    (255, 40, 90),
                    (40, 255, 220),
                    (255, 255, 255),
                    (0, 0, 0),
                    (160, 70, 255),
                )
            )
            fx = Image.new("RGBA", (w, h), (*colour, 255))
            strength = rng.randint(80, 210)
            fx.putalpha(alpha.point(lambda v: v * strength // 255))
            canvas = Image.alpha_composite(canvas, fx)

        fx = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fx)
        for _ in range(rng.randint(1, 5)):
            yy = rng.randint(0, max(0, h - 1))
            bh = rng.randint(1, 3)
            colour = rng.choice(
                (
                    (255, 255, 255),
                    (0, 0, 0),
                    (255, 0, 80),
                    (0, 255, 220),
                    (255, 240, 0),
                )
            )
            draw.rectangle(
                (0, yy, w, yy + bh), fill=(*colour, rng.randint(110, 220))
            )
        fx.putalpha(ImageChops.multiply(fx.getchannel("A"), alpha))
        canvas = Image.alpha_composite(canvas, fx)

        if progress > 0.7 and rng.random() < 0.35:
            colour = rng.choice(((255, 255, 255), (255, 40, 90), (40, 255, 220)))
            flash = Image.new("RGBA", (w, h), (*colour, 255))
            flash.putalpha(alpha)
            canvas = flash
        return canvas

    def frame(self, now: float) -> Surface:
        idx = min(
            self._count - 1,
            max(0, int((now - self.started) * self.fps)),
        )
        if idx != self._last:
            self._last = idx
            progress = idx / max(1, self._count - 1)
            img = self._make_frame(progress, self._rng)
            if self.out is not None:
                self.out.set_image(img, self.box)
        return self.out  # type: ignore[return-value]

    def close(self) -> None:
        if self.out is not None:
            self.out.free()
            self.out = None
        self.base = None  # type: ignore[assignment]
        self._alpha = None  # type: ignore[assignment]
        self.original = None


# ---------------------------------------------------------- say something

TALK_PALETTE = [
    (255, 38, 62),
    (60, 226, 96),
    (255, 228, 46),
    (70, 220, 255),
    (255, 96, 214),
    (170, 92, 255),
    (255, 255, 255),
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


def ui_font(size: int, bold: bool = False):
    names = ("consolab.ttf", "segoeuib.ttf") if bold else ("consola.ttf", "segoeui.ttf")
    for name in names + ("lucon.ttf",):
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


_talk_font = ui_font


class TalkRenderer:
    """Full talking pose: mouth-flap art inside a glitching colour-cycling frame,
    with the line from words.txt in a speech bubble above her."""

    def __init__(self, settings, line: str):
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
        self.typing_seconds = 0.0
        self.settled = False
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

    def _bubble_layer(self, settings, line: str) -> Image.Image | None:
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

    def _build(self, settings, line: str) -> None:
        self.line = line
        bubble = self._bubble_layer(settings, line)
        self._bubble_img = bubble
        self._started_at = None
        self._reveal = -1
        self._caret_on = True
        self.settled = False
        self.typing_seconds = max(0.0, (self._text_total - 1) / self._type_cps)
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

    def restart(self, settings, line: str) -> None:
        self._build(settings, line)

    def rest(self) -> None:
        """Hold the closed-mouth talking pose while the bubble stays visible."""
        self.settled = True
        self._mouth = 0
        self._glitch_img = None
        self._next_glitch = 0.0

    def _glitch_frame(self, now: float) -> Image.Image:
        if now >= self._tint_until or self._rng.random() < 0.15:
            self._tint = self._rng.choice(TALK_PALETTE)
            self._tint_until = now + self._rng.uniform(0.07, 0.28)
        variant = self._rng.randrange(len(self._tinted))
        colour = TALK_PALETTE.index(self._tint)
        src = self._tinted[variant][colour]
        out = src.copy()
        w, h = out.size

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
        if not self.settled and now >= self._next_mouth:
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
