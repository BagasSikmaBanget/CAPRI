"""Procedural poses for the merged CAPRI + capri-desktop model.

The CAPRI model supplies the eye strip, walk and talking art.  The
capri-desktop model supplies the full body and cut-out.  This module keeps
both model paths explicit and approximates the desktop rig's stance, sit,
peek, fall, sleep, doze, point, gaze, uplink, victory, zap and stow poses
with Pillow transforms.
"""

from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageChops, ImageDraw

from .art import content_box

INK = (14, 12, 20, 255)
PAPER = (242, 236, 222, 255)
RED = (230, 36, 44, 255)
VIOLET = (109, 74, 255, 255)
MINT = (79, 227, 176, 255)
GREEN = (86, 196, 132, 255)
GREEN_DARK = (42, 128, 84, 255)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class Pose:
    __slots__ = ("image", "box")

    def __init__(self, image: Image.Image, box=None):
        self.image = image
        self.box = box or content_box(image)


def _ellipse(draw, cx, cy, rx, ry, fill):
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=fill)


def _poly(draw, pts, fill, outline=None, width=2):
    draw.polygon(pts, fill=fill)
    if outline is not None:
        draw.line(pts + [pts[0]], fill=outline, width=width, joint="curve")


class MaskRenderer:
    """The sleeping mask from chip.js, drawn at the current pet scale."""

    def __init__(self, settings):
        self.settings = settings

    def render(self, asleep=True, wink=False, size=None) -> Pose:
        w = size or max(54, int(150 * self.settings.scale))
        h = max(28, int(w * 0.44))
        img = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x0, y0 = 10, 10
        # straps
        d.line((x0 - 8, y0 + h * 0.5, x0 + w * 0.18, y0 + h * 0.42),
               fill=INK, width=max(2, int(h * 0.1)))
        d.line((x0 + w * 0.82, y0 + h * 0.42, x0 + w + 8, y0 + h * 0.5),
               fill=INK, width=max(2, int(h * 0.1)))
        # mask shell
        shell = [
            (x0 + w * 0.08, y0 + h * 0.1), (x0 + w * 0.92, y0 + h * 0.1),
            (x0 + w, y0 + h * 0.48), (x0 + w * 0.78, y0 + h * 0.9),
            (x0 + w * 0.22, y0 + h * 0.9), (x0, y0 + h * 0.48),
        ]
        d.polygon(shell, fill=GREEN)
        d.line(shell + [shell[0]], fill=GREEN_DARK, width=max(2, int(h * 0.07)), joint="curve")
        # eye cups
        for cx in (0.34, 0.66):
            ex = x0 + w * cx
            ey = y0 + h * 0.47
            rx, ry = w * 0.13, h * 0.18
            _ellipse(d, ex, ey, rx, ry, GREEN_DARK)
            _ellipse(d, ex, ey, rx * 0.8, ry * 0.8, PAPER)
            if asleep or (wink and cx > 0.5):
                d.line((ex - rx * 0.6, ey, ex + rx * 0.6, ey), fill=INK, width=max(2, int(h * 0.07)))
            else:
                _ellipse(d, ex + w * 0.01, ey, rx * 0.34, ry * 0.34, INK)
                _ellipse(d, ex + w * 0.04, ey - ry * 0.12, rx * 0.09, ry * 0.09, PAPER)
        # little red stitch
        d.line((x0 + w * 0.5, y0 + h * 0.18, x0 + w * 0.5, y0 + h * 0.3),
               fill=RED, width=max(1, int(h * 0.05)))
        return Pose(img)

    def chip(self, waiting=False, size=None) -> Pose:
        pose = self.render(asleep=not waiting, wink=waiting, size=size)
        # the chip lies on its side, eyes toward the user
        pose.image = pose.image.rotate(-90, expand=True, resample=Image.BICUBIC)
        pose.box = content_box(pose.image)
        return pose


class PoseRenderer:
    def __init__(self, settings):
        self.settings = settings
        self._source = self._load(
            getattr(settings, "desktop_cutout_file", ""), "capri-cutout.png"
        )
        self._full = self._load(
            getattr(settings, "desktop_full_file", ""), "capri-full.png"
        )
        self._sit = self._load(getattr(settings, "desktop_sit_file", ""), "sit.png")
        self._scale = max(0.05, getattr(settings, "desktop_model_scale", settings.scale))
        self.has_desktop = self._source.width > 1 and self._source.height > 1

    def _load(self, path: str, fallback: str) -> Image.Image:
        candidates = []
        if path:
            candidates.append(path)
        cutout = getattr(self.settings, "desktop_cutout_file", "")
        if cutout:
            candidates.append(os.path.join(os.path.dirname(cutout), fallback))
        candidates.append(os.path.join(self.settings.face_dir, fallback))
        for candidate in candidates:
            try:
                return Image.open(candidate).convert("RGBA")
            except OSError:
                continue
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    def _scaled(self, img: Image.Image) -> Image.Image:
        w = max(1, round(img.width * self._scale))
        h = max(1, round(img.height * self._scale))
        return img.resize((w, h), Image.LANCZOS)

    def stand(self, phase: float = 0.0) -> Pose:
        body = self._scaled(self._full if self._full.width > 1 else self._source)
        if not self.has_desktop:
            return Pose(body)
        bob = math.sin(phase * 1.7) * max(1.0, body.height * 0.004)
        out = Image.new("RGBA", (body.width, body.height + int(abs(bob)) + 2), (0, 0, 0, 0))
        out.alpha_composite(body, (0, max(0, int(abs(bob) - bob))))
        return Pose(out)

    def sit(self, phase: float = 0.0) -> Pose:
        if self._sit.width > 1 and self._sit.height > 1:
            return Pose(self._sit)
        body = self._scaled(self._source)
        w, h = body.size
        hip = int(h * 0.56)
        upper = body.crop((0, 0, w, hip))
        leg_h = max(24, int(h * 0.48))
        out = Image.new("RGBA", (w + max(10, w // 5), hip + leg_h + 6), (0, 0, 0, 0))
        out.alpha_composite(upper, ((out.width - w) // 2, 0))
        d = ImageDraw.Draw(out)
        cx = out.width / 2
        thick = max(7, int(w * 0.13))
        # two bent legs, one tucked
        for i, (side, bend) in enumerate(((-1, 0.6), (1, 0.15))):
            swing = math.sin(phase * 3.2 + i * 1.7) * leg_h * 0.07
            hx = cx + side * w * 0.14
            knee_x = hx + side * w * 0.18
            knee_y = hip + leg_h * bend + swing
            foot_x = knee_x + side * w * 0.12 + swing * 0.4
            foot_y = hip + leg_h * 0.94
            _poly(d, [
                (hx - thick * 0.5, hip - 4), (hx + thick * 0.5, hip - 4),
                (knee_x + thick * 0.42, knee_y), (knee_x - thick * 0.42, knee_y),
            ], PAPER, INK, max(2, thick // 4))
            _poly(d, [
                (knee_x - thick * 0.42, knee_y), (knee_x + thick * 0.42, knee_y),
                (foot_x + thick * 0.34, foot_y), (foot_x - thick * 0.34, foot_y),
            ], PAPER, INK, max(2, thick // 4))
            d.ellipse((foot_x - thick * 0.7, foot_y - thick * 0.4,
                       foot_x + thick * 0.8, foot_y + thick * 0.4), fill=INK)
        # hip seam
        d.line((cx - w * 0.3, hip, cx + w * 0.3, hip), fill=INK, width=max(2, thick // 3))
        return Pose(out)

    def sit_seat_offset(self) -> float:
        if self._sit.width > 1 and self._sit.height > 1:
            return self._sit.height * 0.34
        return 0.0

    def peek(self, lean: float = 1.0, side: int = 1, phase: float = 0.0) -> Pose:
        body = self._scaled(self._source)
        w, h = body.size
        lean = max(-1.0, min(1.0, lean))
        # x' = x - side * lean * (1 - y/h) * w/10
        coeffs = (1.0, side * lean * (w / 10.0) / max(1, h), -side * lean * (w / 10.0),
                  0.0, 1.0, 0.0)
        out = body.transform((w, h), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        lift = int(abs(math.sin(phase * 2.1)) * h * 0.02)
        if lift:
            shifted = Image.new("RGBA", (w, h + lift), (0, 0, 0, 0))
            shifted.alpha_composite(out, (0, 0))
            out = shifted
        return Pose(out)

    def fall(self, angle: float = 28.0, drop: float = 0.0) -> Pose:
        body = self._scaled(self._source)
        w, h = body.size
        rotated = body.rotate(angle, expand=True, resample=Image.BICUBIC)
        out = Image.new("RGBA", (rotated.width, rotated.height + int(h * 0.1) + 2), (0, 0, 0, 0))
        out.alpha_composite(rotated, (0, int(drop)))
        return Pose(out)

    def sleep(self, phase: float = 0.0) -> Pose:
        body = self._scaled(self._full if self._full.width > 1 else self._source)
        if not self.has_desktop:
            return Pose(body)
        breath = math.sin(phase * 1.35) * 0.025
        w, h = body.size
        out = body.rotate(5.0, expand=True, resample=Image.BICUBIC)
        out = out.resize(
            (max(1, round(out.width * (1.0 + breath * 0.25))),
             max(1, round(out.height * (1.0 + breath)))),
            Image.BICUBIC,
        )
        return Pose(out)

    def doze(self) -> Pose:
        size = max(40, int(self._scaled(self._source).width * 0.9))
        return self.mask(True, size=size)

    def _lean(self, amount: float, lift: float = 0.0, squash: float = 1.0) -> Pose:
        body = self._scaled(self._source)
        w, h = body.size
        coeffs = (1.0, amount / max(1, h), -amount * 0.5, 0.0, squash, lift * h)
        out = body.transform((w, max(1, int(h * squash))), Image.AFFINE, coeffs,
                             resample=Image.BICUBIC)
        return Pose(out)

    def point(self, phase: float = 0.0, side: int = 1) -> Pose:
        return self._lean(side * (5.0 + math.sin(phase * 4.0) * 2.0))

    def gaze(self, phase: float = 0.0) -> Pose:
        return self._lean(-3.0 - math.sin(phase * 1.8) * 1.5, lift=-0.01)

    def uplink(self, phase: float = 0.0) -> Pose:
        return self._lean(-5.0 - math.sin(phase * 1.2) * 2.0, lift=-0.02, squash=0.99)

    def victory(self, phase: float = 0.0) -> Pose:
        bounce = abs(math.sin(phase * 5.0))
        return self._lean(0.0, lift=-0.035 * bounce, squash=1.0 + 0.03 * bounce)

    def zap(self, phase: float = 0.0) -> Pose:
        return self._lean(6.0 + math.sin(phase * 7.0) * 2.5)

    def stow(self, progress: float = 0.0) -> Pose:
        body = self._scaled(self._source)
        k = max(0.08, 1.0 - 0.92 * _clamp01(progress))
        out = body.resize((max(1, round(body.width * k)), max(1, round(body.height * k))),
                          Image.LANCZOS)
        if progress > 0.15:
            out = out.rotate(-90 * _clamp01(progress), expand=True, resample=Image.BICUBIC)
        return Pose(out)

    def unstow(self, progress: float = 0.0) -> Pose:
        return self.stow(1.0 - _clamp01(progress))

    def possess(self, phase: float = 0.0) -> Pose:
        body = self._scaled(self._source)
        if not self.has_desktop:
            return Pose(body)
        pulse = 0.5 + 0.5 * math.sin(phase * 6.0)
        tint = Image.new("RGBA", body.size, (230, 36, 44, int(38 + 42 * pulse)))
        out = body.copy()
        out.alpha_composite(tint)
        return Pose(out)

    def _variant(self, angle=0.0, sx=1.0, sy=1.0, dx=0.0, dy=0.0) -> Pose:
        body = self._scaled(self._source)
        w, h = body.size
        out = body
        if abs(angle) > 0.01:
            out = out.rotate(angle, expand=True, resample=Image.BICUBIC)
        nw, nh = max(1, round(out.width * sx)), max(1, round(out.height * sy))
        if (nw, nh) != out.size:
            out = out.resize((nw, nh), Image.BICUBIC)
        pad_x, pad_y = int(abs(dx)) + 2, int(abs(dy)) + 2
        canvas = Image.new(
            "RGBA", (out.width + pad_x * 2, out.height + pad_y * 2), (0, 0, 0, 0)
        )
        canvas.alpha_composite(out, (pad_x + int(dx), pad_y + int(dy)))
        return Pose(canvas)

    def talk(self, phase: float = 0.0) -> Pose:
        return self._variant(angle=math.sin(phase * 6.0) * 0.9)

    def curious(self, phase: float = 0.0) -> Pose:
        return self._variant(angle=math.sin(phase * 2.2) * 2.5)

    def look(self, phase: float = 0.0) -> Pose:
        return self._variant(angle=math.sin(phase * 3.4) * 1.6)

    def pointing(self, phase: float = 0.0, side: int = 1) -> Pose:
        return self.point(phase, side)

    def unpoint(self, phase: float = 0.0, side: int = 1) -> Pose:
        return self.point(phase, side)

    def fold(self, progress: float = 0.0) -> Pose:
        return self.stow(progress)

    def dive(self, progress: float = 0.0) -> Pose:
        return self._variant(angle=18.0 * _clamp01(progress),
                             sy=1.0 - 0.18 * _clamp01(progress),
                             dy=18.0 * _clamp01(progress))

    def split(self, progress: float = 0.0) -> Pose:
        body = self._scaled(self._source)
        out = body.copy()
        rng = random.Random(7)
        for _ in range(7):
            y = rng.randrange(0, max(1, out.height - 6))
            hh = rng.randrange(2, 9)
            dx = int((rng.random() - 0.5) * out.width * 0.35 * _clamp01(progress))
            band = out.crop((0, y, out.width, min(out.height, y + hh)))
            out.paste(band, (dx, y))
        return Pose(out)

    def alarm(self, phase: float = 0.0) -> Pose:
        return self._variant(dx=math.sin(phase * 28.0) * 3.0)

    def flinch(self, phase: float = 0.0) -> Pose:
        return self._variant(angle=-6.0 * min(1.0, phase * 3.0),
                             sy=0.97, dx=-3.0 * min(1.0, phase * 3.0))

    def turn(self, phase: float = 0.0) -> Pose:
        sx = max(0.08, abs(math.cos(phase * math.pi)))
        return self._variant(sx=sx)

    def spin(self, progress: float = 0.0) -> Pose:
        return self._variant(angle=360.0 * _clamp01(progress))

    def hop(self, phase: float = 0.0) -> Pose:
        return self._variant(dy=-abs(math.sin(phase * 4.0)) * 12.0)

    def land(self, phase: float = 0.0) -> Pose:
        k = min(1.0, max(0.0, phase * 4.0))
        return self._variant(sy=1.0 - 0.10 * (1.0 - k), sx=1.0 + 0.06 * (1.0 - k))

    def plop(self, progress: float = 0.0) -> Pose:
        k = _clamp01(progress)
        return self._variant(sy=1.0 - 0.12 * k, dy=16.0 * k)

    def mask(self, asleep=True, wink=False, size=None) -> Pose:
        return MaskRenderer(self.settings).render(asleep, wink, size)

    def chip(self, waiting=False, size=None) -> Pose:
        return MaskRenderer(self.settings).chip(waiting, size)

    def animate(self, name: str, phase: float = 0.0) -> Pose:
        if name == "fall":
            p = _clamp01(phase)
            return self.fall(26.0 * p, 18.0 * p)
        fn = {
            "stand": self.stand,
            "talk": self.talk,
            "sit": self.sit,
            "peek": self.peek,
            "fall": self.fall,
            "sleep": self.sleep,
            "doze": self.doze,
            "point": self.point,
            "gaze": self.gaze,
            "uplink": self.uplink,
            "victory": self.victory,
            "zap": self.zap,
            "stow": self.stow,
            "unstow": self.unstow,
            "possess": self.possess,
            "curious": self.curious,
            "look": self.look,
            "pointing": self.pointing,
            "unpoint": self.unpoint,
            "fold": self.fold,
            "dive": self.dive,
            "split": self.split,
            "alarm": self.alarm,
            "flinch": self.flinch,
            "turn": self.turn,
            "spin": self.spin,
            "hop": self.hop,
            "land": self.land,
            "plop": self.plop,
            "mask": self.mask,
            "chip": self.chip,
        }.get(name)
        if fn is None:
            return self.stand(phase)
        return fn(phase) if name not in ("doze", "mask", "chip") else fn()
