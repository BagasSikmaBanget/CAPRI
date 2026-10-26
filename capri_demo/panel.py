"""The transmission panel and the work ticker, drawn with Pillow.

capri-desktop renders these in HTML/CSS; here they are composed into the same
layered window as the pet. The panel shows one of her eight faces, the line,
a quote and a small action log. The ticker is the one-liner over her head while
Claude works.
"""

from __future__ import annotations

import math
import os
import random
import time

from PIL import Image, ImageChops, ImageDraw

from .art import content_box, fit_image, load_rgba, ui_font

KIND_COLOURS = {
    "work": (255, 86, 110),
    "done": (127, 220, 176),
    "alert": (255, 51, 85),
    "error": (255, 64, 80),
    "info": (150, 150, 170),
    "idle": (150, 150, 170),
}

KIND_FACE = {
    "alert": "face-many.png",
    "done": "face-look.png",
    "error": "face-laugh.png",
    "work": "face-calm.png",
    "idle": "face-calm.png",
    "info": "face-calm.png",
}

PRIORITY = {"info": 1, "idle": 1, "work": 2, "done": 3, "error": 3, "alert": 4}

BG = (17, 17, 24, 240)
BG_HEAD = (28, 28, 38, 245)
FG = (238, 238, 246, 255)
DIM = (158, 158, 176, 255)
GREEN = (127, 220, 176, 255)
PAPER = (242, 236, 222, 255)
VIOLET = (109, 74, 255, 255)
RED = (230, 36, 44, 255)


def _wrap(text: str, font, width: float) -> list[str]:
    out: list[str] = []
    for para in str(text or "").split("\n"):
        current = ""
        for word in para.split():
            probe = word if not current else current + " " + word
            if not current or font.getlength(probe) <= width:
                current = probe
            else:
                out.append(current)
                current = word
        if current:
            out.append(current)
    return out


class Panel:
    def __init__(self, settings):
        self.settings = settings
        self.msg: dict | None = None
        self.msg_until: float | None = None
        self.msg_started = 0.0
        self.ticker: dict | None = None
        self.ticker_until = 0.0
        self._face_cache: dict[tuple[str, int], Image.Image] = {}
        self._panel_cache: tuple[tuple, Image.Image, list] | None = None
        self._ticker_cache: tuple[tuple, Image.Image] | None = None
        self._panel_rects: list[tuple[str, tuple[int, int, int, int]]] = []
        self._hit_actions: list[tuple[str, tuple[int, int, int, int]]] = []
        self.fx: dict | None = None

    # ---- messages

    def say(self, msg: dict, hold: float | None = 5.0) -> bool:
        now = time.perf_counter()
        cur = self.msg
        if (
            cur
            and self.active(now)
            and cur.get("kind") != msg.get("kind")
            and PRIORITY.get(cur.get("kind", "info"), 1) > PRIORITY.get(msg.get("kind", "info"), 1)
            and now - self.msg_started < 2.6
        ):
            return False
        self.msg = dict(msg)
        self.msg_started = now
        self.msg_until = None if hold is None else now + hold
        self._panel_cache = None
        return True

    def clear(self) -> None:
        self.msg = None
        self.msg_until = None
        self._panel_cache = None
        self._panel_rects = []
        self._hit_actions = []

    def clear_kind(self, kind: str) -> None:
        if self.msg and self.msg.get("kind") == kind:
            self.clear()

    def set_ticker(self, action: dict | None, seconds: float | None = None) -> None:
        if not self.settings.ticker_enabled:
            return
        if action is None:
            self.clear_ticker()
            return
        self.ticker = dict(action)
        self.ticker_until = time.perf_counter() + (
            self.settings.ticker_seconds if seconds is None else seconds
        )
        self._ticker_cache = None

    def clear_ticker(self) -> None:
        self.ticker = None
        self._ticker_cache = None

    def active(self, now: float | None = None) -> bool:
        now = time.perf_counter() if now is None else now
        if self.msg is not None and self.msg_until is not None and now >= self.msg_until:
            self.clear()
        if self.ticker is not None and now >= self.ticker_until:
            self.clear_ticker()
        return self.msg is not None or self.ticker is not None

    # ---- effects

    def effect(self, kind: str, seconds: float) -> None:
        self.fx = {
            "kind": kind,
            "started": time.perf_counter(),
            "until": time.perf_counter() + seconds,
            "seed": random.random() * 1000,
        }

    def _apply_fx(self, img: Image.Image, now: float) -> Image.Image:
        fx = self.fx
        if fx is None:
            return img
        if now >= fx["until"]:
            self.fx = None
            return img
        t = (now - fx["started"]) / max(0.001, fx["until"] - fx["started"])
        rng = random.Random(fx["seed"] + int(now * 30))
        out = img.copy()
        w, h = out.size
        kind = fx["kind"]

        if kind == "hurt":
            dx = int(math.sin(t * 40) * 9 * (1 - t))
            shifted = Image.new("RGBA", out.size, (0, 0, 0, 0))
            shifted.paste(out, (dx, 0))
            out = shifted
            red = Image.new("RGBA", out.size, (255, 30, 60, 255))
            alpha = out.getchannel("A").point(lambda v: int(v * 0.28 * (1 - t)))
            red.putalpha(alpha)
            out = Image.alpha_composite(out, red)

        elif kind == "spark":
            draw = ImageDraw.Draw(out)
            for _ in range(5):
                x0 = rng.randint(0, max(1, w))
                y0 = rng.randint(0, max(1, h))
                pts = [(x0, y0)]
                for _ in range(4):
                    x0 += rng.randint(-26, 26)
                    y0 += rng.randint(-22, 22)
                    pts.append((x0, y0))
                draw.line(pts, fill=(255, 40, 80, rng.randint(120, 230)), width=2)

        elif kind == "victory":
            draw = ImageDraw.Draw(out)
            cx, cy = w / 2, h * 0.55
            count = 34
            for i in range(count):
                angle = (i / count) * math.tau + rng.uniform(-0.03, 0.03)
                inner = max(w, h) * (0.28 + 0.05 * math.sin(t * 8 + i))
                outer = max(w, h) * 0.95
                x0 = cx + math.cos(angle) * inner
                y0 = cy + math.sin(angle) * inner
                x1 = cx + math.cos(angle) * outer
                y1 = cy + math.sin(angle) * outer
                colour = (255, 255, 255, 70) if i % 3 else (255, 60, 90, 90)
                draw.line((x0, y0, x1, y1), fill=colour, width=2)

        return out

    # ---- face

    def _face(self, name: str, height: int) -> Image.Image | None:
        key = (name, height)
        cached = self._face_cache.get(key)
        if cached is not None:
            return cached
        path = os.path.join(self.settings.face_dir, name)
        if not os.path.isfile(path):
            path = os.path.join(self.settings.face_dir, "face-calm.png")
        if not os.path.isfile(path):
            return None
        try:
            img = load_rgba(path)
        except Exception:  # noqa: BLE001
            return None
        box = content_box(img)
        img = img.crop(box)
        img = fit_image(img, max(1, int(height * 1.35)), height)
        self._face_cache[key] = img
        return img

    # ---- panel drawing

    def _panel_image(self, now: float) -> Image.Image | None:
        msg = self.msg
        if msg is None:
            return None
        s = self.settings
        k = s.panel_scale
        W = int(s.panel_width * k)
        pad = int(12 * k)
        gap = int(12 * k)
        face_h = int(104 * k)

        kind = msg.get("kind", "info")
        colour = KIND_COLOURS.get(kind, KIND_COLOURS["info"])
        face_name = msg.get("face") or KIND_FACE.get(kind, "face-calm.png")
        if not face_name.endswith(".png"):
            face_name += ".png"
        face = self._face(face_name, face_h)

        line_font = ui_font(int(15 * k), bold=True)
        tag_font = ui_font(int(9 * k))
        quote_font = ui_font(int(11 * k))
        summary_font = ui_font(int(10 * k), bold=True)
        log_font = ui_font(int(9 * k))
        badge_font = ui_font(int(8 * k), bold=True)
        reply_font = ui_font(int(10 * k))
        btn_font = ui_font(int(9 * k), bold=True)

        face_w = face.width if face is not None else 0
        text_x = pad + face_w + (gap if face is not None else 0)
        text_w = max(60, W - text_x - pad)

        line = msg.get("line") or ""
        reveal = min(len(line), int((now - self.msg_started) * 34) + 1)
        shown_line = line[:reveal]
        decode = bool(msg.get("decode"))
        if decode and now - self.msg_started < 0.38:
            rng = random.Random(int(now * 40))
            shown_line = "".join(
                rng.choice("01<>/\\[]{}#$%&") for _ in range(max(1, reveal))
            )
        line_lines = _wrap(shown_line, line_font, text_w)
        line_h = int(19 * k)
        tag = msg.get("tag") or ""
        quote = msg.get("quote") or ""
        summary = msg.get("summary") or ""
        reply = msg.get("reply") or ""
        log = msg.get("log") or []
        actions = msg.get("actions") or []

        quote_lines = _wrap(quote, quote_font, text_w) if quote else []
        summary_lines = _wrap(summary, summary_font, text_w) if summary else []
        reply_lines = _wrap(reply, reply_font, max(40, text_w - 14)) if reply else []
        log_rows = []
        for item in log[:4]:
            verb = str(item.get("verb") or "")
            target = str(item.get("target") or "")
            log_rows.append((verb, target, bool(item.get("error"))))

        btn_h = int(23 * k)
        btn_gap = int(6 * k)
        cols = 2 if len(actions) > 1 else 1
        rows = (len(actions) + cols - 1) // cols if actions else 0
        buttons_h = 0
        if rows:
            buttons_h = int(8 * k) + rows * btn_h + (rows - 1) * btn_gap

        text_h = max(1, len(line_lines)) * line_h
        if tag:
            text_h += int(12 * k)
        if quote_lines:
            text_h += int(6 * k) + len(quote_lines) * int(15 * k)
        if summary_lines:
            text_h += int(6 * k) + len(summary_lines) * int(14 * k)
        if log_rows:
            text_h += int(7 * k) + len(log_rows) * int(13 * k)

        content_h = max(face_h, text_h) + buttons_h
        if reply_lines:
            content_h += int(9 * k) + len(reply_lines) * int(14 * k)
        H = max(int(104 * k), pad * 2 + content_h)

        action_key = tuple(
            (str(a.get("id") or ""), str(a.get("label") or ""), bool(a.get("primary")))
            for a in actions
        )
        key = (
            kind, shown_line, tag, quote, summary, tuple(log_rows),
            face_name, W, H, int(now * 6) if kind == "alert" else 0,
            action_key, reply, decode and now - self.msg_started < 0.38,
        )
        if self._panel_cache is not None and self._panel_cache[0] == key:
            self._panel_rects = self._panel_cache[2]
            return self._panel_cache[1]

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pulse = 0
        if kind == "alert":
            pulse = int(35 * (0.5 + 0.5 * math.sin(now * 7)))
        outline = (*colour[:3], min(255, 160 + pulse))
        draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=int(7 * k), fill=BG, outline=outline, width=max(1, int(1.4 * k)))
        draw.rectangle((0, 0, max(2, int(4 * k)), H - 1), fill=colour)

        if face is not None:
            fx0, fy0 = pad, pad
            img.alpha_composite(face, (fx0, fy0))
            draw.rectangle(
                (fx0, fy0, fx0 + face.width, fy0 + face.height),
                outline=(*colour[:3], 90),
                width=1,
            )

        x = text_x
        y = pad
        if tag:
            draw.text((x, y), tag.upper(), font=tag_font, fill=(*colour[:3], 190))
            y += int(12 * k)
        for text in line_lines:
            draw.text((x, y), text, font=line_font, fill=FG)
            y += line_h
        if quote_lines:
            y += int(6 * k)
            for text in quote_lines:
                draw.text((x, y), text, font=quote_font, fill=DIM)
                y += int(15 * k)
        if summary_lines:
            y += int(6 * k)
            for text in summary_lines:
                draw.text((x, y), text, font=summary_font, fill=GREEN)
                y += int(14 * k)
        if log_rows:
            y += int(7 * k)
            for verb, target, is_error in log_rows:
                vcol = (*KIND_COLOURS["error"][:3], 255) if is_error else (*colour[:3], 230)
                draw.text((x, y), verb, font=log_font, fill=vcol)
                vw = log_font.getlength(verb)
                draw.text((x + vw + 6, y), target, font=log_font, fill=DIM if not is_error else (*KIND_COLOURS["error"][:3], 220))
                y += int(13 * k)

        if reply_lines:
            y += int(9 * k)
            bar_h = len(reply_lines) * int(14 * k)
            draw.rectangle((x, y, x + max(2, int(3 * k)), y + bar_h), fill=VIOLET)
            for text in reply_lines:
                draw.text((x + int(10 * k), y), text, font=reply_font, fill=FG)
                y += int(14 * k)

        rects: list[tuple[str, tuple[int, int, int, int]]] = []
        if actions:
            by = H - pad - rows * btn_h - (rows - 1) * btn_gap
            avail = W - pad * 2
            bw = (avail - (cols - 1) * btn_gap) // cols
            for i, action in enumerate(actions):
                aid = str(action.get("id") or "")
                label = str(action.get("label") or "")
                primary = bool(action.get("primary"))
                col = i % cols
                row = i // cols
                bx = pad + col * (bw + btn_gap)
                byy = by + row * (btn_h + btn_gap)
                fill = (*RED[:3], 235) if primary else (28, 28, 38, 245)
                outline = (*RED[:3], 230) if primary else (*DIM[:3], 150)
                draw.rounded_rectangle(
                    (bx, byy, bx + bw, byy + btn_h), radius=int(5 * k),
                    fill=fill, outline=outline, width=1,
                )
                label = label[: max(3, int(bw / max(1, btn_font.getlength("M"))))]
                tw = btn_font.getlength(label)
                draw.text(
                    (bx + (bw - tw) / 2, byy + (btn_h - int(12 * k)) / 2 - int(2 * k)),
                    label, font=btn_font, fill=PAPER if primary else FG,
                )
                rects.append((aid, (bx, byy, bx + bw, byy + btn_h)))
        self._panel_rects = rects

        # corner badge: the state word
        badge = msg.get("badge") or ""
        if badge:
            bw = badge_font.getlength(badge)
            draw.text((W - pad - bw, pad), badge, font=badge_font, fill=(*colour[:3], 220))

        # subtle scanlines
        scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scan)
        for yy in range(0, H, 4):
            sd.line((0, yy, W, yy), fill=(0, 0, 0, 22))
        img = Image.alpha_composite(img, scan)

        self._panel_cache = (key, img, rects)
        return img

    def _ticker_image(self) -> Image.Image | None:
        action = self.ticker
        if action is None:
            return None
        s = self.settings
        k = s.panel_scale
        verb = str(action.get("verb") or "")
        target = str(action.get("target") or "")
        error = bool(action.get("error"))
        colour = KIND_COLOURS["error"] if error else KIND_COLOURS["work"]
        font = ui_font(int(10 * k), bold=True)
        font2 = ui_font(int(10 * k))
        pad = int(10 * k)
        tw = verb and font.getlength(verb) or 0
        tw2 = target and font2.getlength(target) or 0
        W = int(pad * 2 + tw + (6 * k if verb and target else 0) + tw2 + 8 * k)
        W = min(max(W, int(120 * k)), int(s.panel_width * k))
        H = int(27 * k)
        key = (verb, target, error, W, H)
        if self._ticker_cache is not None and self._ticker_cache[0] == key:
            return self._ticker_cache[1]
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=int(5 * k), fill=(14, 14, 20, 235), outline=(*colour[:3], 170), width=1)
        draw.rectangle((0, 0, max(2, int(3 * k)), H - 1), fill=colour)
        x = pad
        if verb:
            draw.text((x, int(6 * k)), verb, font=font, fill=(*colour[:3], 255))
            x += tw + int(6 * k)
        if target:
            room = max(0, W - x - pad)
            while target and font2.getlength(target) > room:
                target = target[:-1]
            if len(target) < len(str(action.get("target") or "")):
                target = target[:-1] + "…"
            draw.text((x, int(6 * k)), target, font=font2, fill=FG)
        self._ticker_cache = (key, img)
        return img

    # ---- composition

    def action_at(self, x: int, y: int) -> str | None:
        for aid, rect in self._hit_actions:
            if rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                return aid
        return None

    def compose(self, pet_img: Image.Image, pet_box, now: float):
        """Return (image, box, hit_box) for the layered window."""
        if not self.settings.panel_enabled:
            self._hit_actions = []
            return pet_img, pet_box, pet_box
        self.active(now)
        pet_img = self._apply_fx(pet_img, now)
        panel = self._panel_image(now)
        ticker = self._ticker_image() if self.settings.ticker_enabled else None
        if panel is None and ticker is None:
            self._hit_actions = []
            return pet_img, pet_box, pet_box

        k = self.settings.panel_scale
        gap = int(9 * k)
        top_h = 0
        if panel is not None:
            top_h += panel.height + gap
        if ticker is not None:
            top_h += ticker.height + gap
        total_w = max(
            pet_img.width,
            panel.width if panel is not None else 0,
            ticker.width if ticker is not None else 0,
        )
        total_h = top_h + pet_img.height
        canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))

        self._hit_actions = []
        if panel is not None:
            ox = (total_w - panel.width) // 2
            canvas.alpha_composite(panel, (ox, 0))
            self._hit_actions = [
                (aid, (rect[0] + ox, rect[1], rect[2] + ox, rect[3]))
                for aid, rect in self._panel_rects
            ]
        if ticker is not None:
            y = (panel.height + gap) if panel is not None else 0
            canvas.alpha_composite(ticker, ((total_w - ticker.width) // 2, y))

        px = total_w // 2 - (pet_box[0] + pet_box[2]) // 2
        py = top_h
        canvas.alpha_composite(pet_img, (px, py))
        hit = (
            px + pet_box[0],
            py + pet_box[1],
            px + pet_box[2],
            py + pet_box[3],
        )
        return canvas, (0, 0, total_w, total_h), hit
