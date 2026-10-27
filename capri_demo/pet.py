"""The pet window: CAPRI's animation loop plus capri-desktop's narration.

Pose and movement come from CAPRI (idle, gaze, walk, rare idle poses, talk, glitch,
drag, menu, chat). Claude Code events arrive through the local bridge and are
turned into panel messages, a ticker, expressions, sparks and sounds.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import os
import queue
import random
import threading
import time

from PIL import Image

from . import hookinstall
from .art import (
    Action,
    GazeFace,
    SpriteGlitch,
    Surface,
    TalkRenderer,
    WalkCycle,
    content_box,
)
from .brain import Brain
from .bridge import EventBridge
from .chat import ChatWindow
from .config import ROOT, Settings, read_config, write_setting
from .demo import start_demo
from .fx import FxLayer
from .guide import Guide
from .lines import Lines, pick, resolve_lang
from .menu_labels import labels as menu_labels
from .panel import Panel
from .poses import PoseRenderer
from .sounds import Sounds
from . import windows as winwatch
from .win32 import (
    CS_DBLCLKS,
    HTCLIENT,
    HTTRANSPARENT,
    HWND_TOPMOST,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MSG,
    POINT,
    RECT,
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    UINT,
    WM_CAPTURECHANGED,
    WM_CLOSE,
    WM_DESTROY,
    WM_HOTKEY,
    WM_LBUTTONDBLCLK,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    WM_NCHITTEST,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_QUIT,
    WNDCLASSW,
    WNDPROC,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_POPUP,
    cursor_pos,
    gdi32,
    kernel32,
    set_dpi_aware,
    system_idle_seconds,
    user32,
    work_area,
)
from .win32 import BLENDFUNCTION, SIZE, ULW_ALPHA  # noqa: F401

CONFIG_PATH = os.path.join(ROOT, "capri_config.txt")


def _ease_out_local(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


class Pet:
    SIZES = {"small": 0.26, "medium": 0.38, "large": 0.52}

    def __init__(self, cfg: dict[str, str]):
        self.settings = Settings(cfg)
        self._remember_art_ratios()
        self.size_name = next(
            (
                name
                for name, factor in self.SIZES.items()
                if abs(self.settings.scale - factor) < 0.01
            ),
            "medium",
        )
        self.work: RECT = work_area()
        self.baseline = self._baseline()

        self.cache: dict = {}
        self.actions: dict[str, Action | None] = {}
        self.face: GazeFace | None = None
        self.away_action: Action | None = None
        self.walk_cycle: WalkCycle | None = None
        self.walk_half = 80.0

        self.running = True
        self.hotkeys: list[tuple[int, str]] = []
        self.wndproc_ref = None
        self.hwnd = None

        self.current: Surface | None = None
        self.left = 0
        self.top = 0
        self.hit_box: tuple[int, int, int, int] | None = None
        self._composed: Surface | None = None

        self.x = float((self.work.left + self.work.right) // 2)
        self.facing_left = False

        self.dragging = False
        self._drag_origin: tuple[int, int, float, float] | None = None
        self._drag_moved = False

        self.transition: str | None = None
        self.sprite_glitch: SpriteGlitch | None = None
        self.pending_menu: str | None = None
        self.menu_lock = threading.Lock()

        self.mode = "idle"
        self.activity_mode = "idle"
        self.mode_timer = 0.0
        self.idle_pose = "idle2"
        self._idle_body = random.random() < self.settings.idle_body_chance
        self.next_thought = random.uniform(
            self.settings.idle_min, self.settings.idle_max
        )
        self.next_idle_sound = random.uniform(
            self.settings.idle_sound_min, self.settings.idle_sound_max
        )
        self._reset_idle_action_timers()
        self._chatter_idle_seen = False

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
        self.talk_typing_until = 0.0
        self.talk_wait_until = 0.0
        self._pending_line: str | None = None
        self.words = self._load_words()
        self.last_said: str | None = None

        self.away = False
        self._away_prev: tuple[float, float] | None = None
        self._away_click = False

        self.lang = resolve_lang(self.settings.lang)
        self.lines = Lines(self.lang)
        self.brain = Brain(self, self.lines, self.lang)
        self.panel = Panel(self.settings)
        self.sounds = Sounds(self.settings.sound_enabled)
        self.fx = FxLayer(self.settings, self.sounds)
        self.poses = PoseRenderer(self.settings)
        self.guide = Guide(self)
        self.intro_active = False
        self.prompt_hwnd: int | None = None
        self.stance = "stand"
        self._pose_surface: Surface | None = None
        self._pose_key: tuple | None = None
        self._sit_window = None
        self._peek_until = 0.0
        self._peek_side = 1
        self._peek_hold = False
        self._peek_app: int | None = None
        self._active_hwnd: int | None = None
        self._follow_cooldown = 0.0
        self._fall_started = 0.0
        self._fall_until = 0.0
        self._fall_vy = 0.0
        self._pointer_item = None
        self._possess_window = None
        self._possess_until = 0.0
        self._sleeping = False
        self._dozing = False
        self._sleep_started = 0.0
        self._anim_name: str | None = None
        self._anim_started = 0.0
        self._anim_until = 0.0
        self.last_activity = time.perf_counter()
        self._window_check = 0.0
        self.events: queue.Queue = queue.Queue()
        self.pending: list[tuple[float, callable]] = []
        self.long_job_ms = self.settings.long_job_minutes * 60.0 * 1000.0
        self.long_job_actions = self.settings.long_job_actions
        self.bridge: EventBridge | None = None

        self.load_art()
        self._create_window()
        self._apply_console_mode()
        self._start_bridge()

    # ---- layout

    def _work_area(self) -> RECT:
        return work_area()

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
        for name in ("idle2", "idle3", "idle4"):
            path = getattr(s, f"{name}_file")
            try:
                arts[name] = Action(
                    name, path, self._fit_scale(getattr(s, f"{name}_scale"), path)
                )
            except FileNotFoundError as exc:
                print(f"[capri] {exc} ({name} disabled)")
                arts[name] = None

        try:
            face = GazeFace(s.eyeline_file, s.eye_file, self._fit_scale(s.scale, s.eyeline_file))
        except FileNotFoundError as exc:
            print(f"[capri] {exc} (eyes will not follow the cursor)")

        try:
            arts["idle"] = Action("idle", s.idle_file, self._fit_scale(s.scale, s.idle_file))
        except FileNotFoundError:
            if face is None:
                raise

        try:
            arts["away"] = Action(
                "away", s.away_file, self._fit_scale(s.away_scale, s.away_file)
            )
        except FileNotFoundError:
            arts["away"] = None

        self._dispose_art()
        self.actions = arts
        self.face = face
        self.away_action = arts.get("away")
        walk = arts.get("walk")
        if walk is not None:
            if s.walk_anim:
                try:
                    self.walk_cycle = WalkCycle(
                        walk,
                        frames=s.walk_frames,
                        fps=s.walk_fps,
                        bob=s.walk_bob,
                        sway=s.walk_sway,
                        lean=s.walk_lean,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[capri] walk animation disabled: {exc}")
                    self.walk_cycle = None
            box = self.walk_cycle.box if self.walk_cycle is not None else walk.box
            self.walk_half = (box[2] - box[0]) / 2.0

    def _dispose_art(self) -> None:
        if self.walk_cycle is not None:
            self.walk_cycle.close()
            self.walk_cycle = None
        if self.face is not None:
            self.face.close()
            self.face = None
        for action in self.actions.values():
            if action is not None:
                action.close()
        self.actions = {}
        self.away_action = None

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
        self.talk_typing_until = 0.0
        self.talk_wait_until = 0.0
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

        cfg = read_config(CONFIG_PATH)
        for surf in self.cache.values():
            surf.free()
        self.cache.clear()
        self.current = None
        if self._composed is not None:
            self._composed.free()
            self._composed = None

        self.settings = Settings(cfg)
        self._remember_art_ratios()
        self.panel.settings = self.settings
        self.sounds.set_enabled(self.settings.sound_enabled)
        self.fx.close()
        self.fx = FxLayer(self.settings, self.sounds)
        self.poses = PoseRenderer(self.settings)
        if self._pose_surface is not None:
            self._pose_surface.free()
        self._pose_surface = None
        self._pose_key = None
        self.stance = "stand"
        self._sit_window = None
        self._sleeping = False
        self._dozing = False
        self._sleep_started = 0.0
        self._anim_name = None
        self._anim_started = 0.0
        self._anim_until = 0.0
        self.work = self._work_area()
        self.baseline = self._baseline()
        self.words = self._load_words()
        self.load_art()

        self.lang = resolve_lang(self.settings.lang)
        self.lines = Lines(self.lang)
        self.brain.lines = self.lines
        self.brain.t = self.lines.t
        self.brain.lang = self.lines.lang

        self._unregister_hotkeys()
        self._register_hotkey(1, self.settings.quit_hotkey)
        self._register_hotkey(2, self.settings.reload_hotkey)
        self._register_hotkey(3, self.settings.chip_hotkey)
        self._apply_topmost()

        if self.chat is not None:
            self.chat.reload_config(cfg)

        self.mode = "idle"
        self.activity_mode = "idle"
        self.mode_timer = 0.0
        self.idle_pose = "idle2"
        self._idle_body = random.random() < self.settings.idle_body_chance
        self.next_thought = random.uniform(
            self.settings.idle_min, self.settings.idle_max
        )
        self.next_idle_sound = random.uniform(
            self.settings.idle_sound_min, self.settings.idle_sound_max
        )
        self._reset_idle_action_timers()
        self._chatter_idle_seen = False
        self.eye_dx = self.eye_dy = 0.0
        self.eye_track = False
        self._clamp_position()

    # ---- bridge / events

    def _start_bridge(self) -> None:
        if not self.settings.enable_bridge:
            return
        self.bridge = EventBridge(
            self.settings.event_port, self.enqueue_event, self._debug
        )
        if not self.bridge.start():
            self.bridge = None

    def enqueue_event(self, evt: dict) -> None:
        self.touch()
        self.events.put(evt)

    def _debug(self, action: str, body: dict):
        if action == "demo":
            self.enqueue_event({"hook_event_name": "CapriDemo"})
            return "started"
        if action == "status":
            self.enqueue_event({"hook_event_name": "CapriStatus"})
            return "ok"
        if action == "event" and isinstance(body, dict):
            self.enqueue_event(body)
            return "ok"
        return "unknown"

    def _drain_events(self) -> None:
        for _ in range(30):
            try:
                evt = self.events.get_nowait()
            except queue.Empty:
                return
            try:
                if evt.get("hook_event_name") == "CapriDemo":
                    self.start_demo()
                else:
                    self.brain.handle(evt)
            except Exception as exc:  # noqa: BLE001
                print(f"[capri] event failed: {exc}")

    def _schedule(self, delay: float, fn) -> None:
        self.pending.append((time.perf_counter() + delay, fn))

    def _process_pending(self, now: float) -> None:
        if not self.pending:
            return
        due = [item for item in self.pending if item[0] <= now]
        if not due:
            return
        self.pending = [item for item in self.pending if item[0] > now]
        for _when, fn in due:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                print(f"[capri] scheduled action failed: {exc}")

    # ---- host API used by Brain

    def say(
        self,
        kind: str,
        line: str,
        face: str | None = None,
        quote: str = "",
        summary: str = "",
        log: list | None = None,
        reply: str = "",
        hold: float | None = 5.0,
        tag: str = "",
        badge: str | None = None,
        actions: list | None = None,
        guide: bool = False,
        decode: bool = False,
    ) -> bool:
        if not self.settings.panel_enabled:
            return False
        if self.guide.active and not guide:
            return False
        if (self._sleeping or self._dozing) and not self.away:
            self.rouse()
        if badge is None:
            badge = (self.lines.t.get("state") or {}).get(kind, "")
        msg = {
            "kind": kind,
            "line": line,
            "face": face,
            "quote": quote,
            "summary": summary,
            "log": log or [],
            "reply": reply,
            "tag": tag,
            "badge": badge,
            "actions": actions or [],
            "guide": guide,
            "decode": decode,
        }
        return self.panel.say(msg, hold)

    def clear_panel_kind(self, kind: str) -> None:
        self.panel.clear_kind(kind)

    def set_ticker(self, action: dict | None) -> None:
        self.panel.set_ticker(action)

    def clear_ticker(self) -> None:
        self.panel.clear_ticker()

    def set_mode(self, mode: str) -> None:
        if mode == self.activity_mode:
            return
        self.activity_mode = mode
        now = time.perf_counter()
        if mode == "idle":
            self.next_thought = random.uniform(
                self.settings.idle_min, self.settings.idle_max
            )
            self._reset_idle_action_timers()
            self._chatter_idle_seen = False
        else:
            self.next_thought = max(self.next_thought, 2.0)
        if mode == "alert" and self.face is not None:
            self.eye_track = True
            self.eye_track_until = max(self.eye_track_until, now + 3.0)

    def play_sound(self, name: str) -> None:
        self.sounds.play(name)

    def wake(self) -> None:
        if self.away:
            self.toggle_away(False)

    def attend(self) -> None:
        self.touch()
        if self.away:
            self.toggle_away(False)
        if self.face is not None:
            self.eye_track = True
            self.eye_track_until = time.perf_counter() + 1.5

    def pulse(self) -> None:
        self.touch()
        if self.face is not None:
            self.eye_track = True
            self.eye_track_until = time.perf_counter() + 1.2

    # ---- desktop-style poses and FX

    def _hand_pos(self) -> tuple[float, float]:
        box = self._current_box()
        height = max(1, box[3] - box[1])
        return (self.x, self.baseline - height * 0.56)

    def _play_pose(self, name: str, seconds: float = 1.0) -> None:
        if not getattr(self.poses, "has_desktop", False):
            return
        self.rouse()
        if self.mode in ("walk", "talk", "talk_wait"):
            self._end_talk()
            self.mode = "idle"
        now = time.perf_counter()
        self._anim_name = name
        self._anim_started = now
        self._anim_until = now + max(0.05, seconds)
        self._pose_key = None

    def point_at(self, rect_fn, label: str = "", fade_after: float | None = None) -> None:
        self.stop_pointing()
        self._play_pose("point", 1.2)
        self._pointer_item = self.fx.pointer(
            self._hand_pos, rect_fn, label=label, fade_after=fade_after,
        )

    def stop_pointing(self) -> None:
        item, self._pointer_item = self._pointer_item, None
        if item is not None:
            item["dead"] = True

    def cutin(self, kind: str, label: str = "") -> None:
        self.fx.cutin(kind, int(self.x), int(self.baseline - 130), label=label)

    def sit_on_window(self, win) -> None:
        if win is None:
            return
        if self.away:
            self.toggle_away(False)
        self.rouse()
        self._end_talk()
        self._cancel_transition()
        self.stance = "sit"
        self._sit_window = win
        self._peek_hold = False
        self._peek_app = None
        self._peek_until = 0.0
        rect = win.rect
        self.x = float(rect.center[0])
        self.baseline = float(rect.top + 6 + self.poses.sit_seat_offset())
        self._clamp_position()
        self._pose_key = None
        self.play_sound("land")
        print(f"[capri] sitting on {win.title!r}")

    def _teleport_to_window(self, win) -> None:
        if win is None:
            return
        if self.away:
            self.toggle_away(False)
        self.rouse()
        self._end_talk()
        self._cancel_transition()
        old = (self.x, self.baseline - 70)
        self.stance = "sit"
        self._sit_window = win
        self._peek_hold = False
        self._peek_app = None
        self._peek_until = 0.0
        rect = win.rect
        self.x = float(rect.center[0])
        self.baseline = float(rect.top + 6 + self.poses.sit_seat_offset())
        self._clamp_position()
        self._pose_key = None
        self.fx.teleport(old, (self.x, self.baseline - 70))
        self.play_sound("teleport")
        self.panel.effect("spark", 0.35)
        print(f"[capri] teleported to {win.title!r}")

    def unsit(self) -> None:
        if self.stance in ("sit", "peek", "fall"):
            self.stance = "stand"
            self._sit_window = None
            self._peek_hold = False
            self._peek_app = None
            self._peek_until = 0.0
            self._pose_key = None

    def peek_from_edge(self, side: int = 1, seconds: float = 3.5,
                       hold: bool = False) -> None:
        self.rouse()
        self._end_talk()
        self._cancel_transition()
        self.stance = "peek"
        self._peek_side = 1 if side >= 0 else -1
        self._peek_hold = hold
        self._peek_until = 0.0 if hold else time.perf_counter() + seconds
        half = 60.0
        try:
            pose = self.poses.peek(1.0, self._peek_side, 0.0)
            half = max(24.0, pose.image.width * 0.5)
        except Exception:  # noqa: BLE001
            pass
        # keep roughly half of her off the edge, leaning in from the corner
        inset = half * 0.55
        self.x = (self.work.right - inset if self._peek_side > 0
                  else self.work.left + inset)
        self.baseline = float(self.work.bottom)
        self._pose_key = None
        self.play_sound("tick")

    def unpeek(self) -> None:
        if self.stance == "peek":
            self.stance = "stand"
            self._peek_hold = False
            self._peek_app = None
            self._pose_key = None

    def fall_off(self) -> None:
        if self.stance == "fall":
            return
        self.rouse()
        self.stance = "fall"
        self._peek_hold = False
        self._peek_app = None
        self._sit_window = None
        self._fall_started = time.perf_counter()
        self._fall_until = self._fall_started + 2.0
        self._fall_vy = 0.0
        self._pose_key = None
        self.play_sound("fall")
        print("[capri] the app went away, falling down")

    def sleep(self) -> None:
        if self.away or self.stance != "stand":
            return
        self._sleeping = True
        self._dozing = False
        self._sleep_started = time.perf_counter()
        self._anim_name = None
        self._end_talk()
        self.panel.clear()
        self.play_sound("tick")

    def doze(self) -> None:
        if self.away or self.stance != "stand" or not self._sleeping:
            return
        self._dozing = True
        self._anim_name = None
        cx, cy = self._pet_center()
        left, top, right, bottom = self._current_box()
        w = max(40, right - left)
        h = max(60, bottom - top)
        self.fx.slices(cx, cy, w * 1.3, h * 1.2, 0.52)
        self.fx.burst(cx, cy, 0.6, 20, inward=True)
        self.fx.drift(cx, cy - h * 0.2, -1.4, 2.4)
        self.panel.clear()
        self.play_sound("tick")

    def rouse(self) -> None:
        self.last_activity = time.perf_counter()
        if self._sleeping or self._dozing:
            was_dozing = self._dozing
            self._sleeping = False
            self._dozing = False
            self._sleep_started = 0.0
            self._anim_name = None
            if was_dozing:
                cx, cy = self._pet_center()
                self.fx.burst(cx, cy, 0.5, 16)
                self.fx.ring(cx, cy, 0.45)
                self.play_sound("land")
            else:
                self.play_sound("blip")

    def touch(self) -> None:
        self.last_activity = time.perf_counter()
        if self._sleeping or self._dozing:
            self._sleeping = False
            self._dozing = False
            self._sleep_started = 0.0
            self._anim_name = None

    def possess_window(self, win=None) -> None:
        if win is None:
            win = winwatch.find_claude_window(self.prompt_hwnd)
        if win is None:
            self.say("info", "No window to possess yet.", face="aside", hold=3.0)
            return
        self.rouse()
        self._end_talk()
        self._cancel_transition()
        self._play_pose("possess", 1.0)
        self._possess_window = win
        self._possess_until = time.perf_counter() + 6.0
        self.fx.possess(
            lambda: winwatch.by_hwnd(win.hwnd),
            lambda: (self.eye_dx / 8.0, self.eye_dy / 8.0),
            entry=0.2,
            leave=5.4,
            label="POSSESS",
        )
        self.play_sound("possess")
        self.say(
            "info", "This window's mine now.", face="many", hold=4.0,
            decode=True,
        )
        print(f"[capri] possessing {win.title!r}")

    def go_to_work(self) -> None:
        if self.intro_active or self.guide.active:
            return
        win = winwatch.find_claude_window(self.prompt_hwnd)
        if win is not None:
            self.sit_on_window(win)
        else:
            self.peek_from_edge(1, 3.0)

    def note_prompt_window(self, hwnd) -> None:
        if hwnd:
            self.prompt_hwnd = int(hwnd)

    def _follow_windows(self, now: float) -> None:
        """Sit on the active app, fall when it is minimized, peek when it fills
        the screen. This mirrors capri-desktop's perch/peek, driven by the
        foreground window instead of Claude's window alone."""
        if self._possess_window is not None and now > self._possess_until:
            self._possess_window = None
        if not getattr(self.settings, "follow_active_app", True):
            if now - self._window_check < 0.45:
                return
            self._window_check = now
            if self._sit_window is not None:
                win = winwatch.by_hwnd(self._sit_window.hwnd)
                if win is None:
                    self.unsit()
                else:
                    self._sit_window = win
                    rect = win.rect
                    self.x = float(rect.center[0])
                    self.baseline = float(rect.top + 6 + self.poses.sit_seat_offset())
                    self._clamp_position()
            return
        if now < self._follow_cooldown:
            return
        if (self.intro_active or self.away or self.guide.active or self.dragging
                or self.chat_open or self._sleeping or self._dozing
                or self.transition is not None or self.stance == "fall"):
            return
        poll = max(0.1, getattr(self.settings, "active_app_poll", 0.45))
        if now - self._window_check < poll:
            return
        self._window_check = now

        # the app she sat on was minimized: she falls down to the desktop
        if self._sit_window is not None and winwatch.is_minimized(self._sit_window.hwnd):
            self.fall_off()
            self._follow_cooldown = now + max(0.0, getattr(self.settings, "follow_cooldown", 1.6))
            return
        if self._peek_hold and self._peek_app and winwatch.is_minimized(self._peek_app):
            self.fall_off()
            self._follow_cooldown = now + max(0.0, getattr(self.settings, "follow_cooldown", 1.6))
            return

        win = winwatch.foreground_app()
        if win is None:
            if self.stance in ("sit", "peek"):
                self.unsit()
            self._active_hwnd = None
            return

        # maximized or fullscreen: she peeks in from the bottom-right corner
        if winwatch.covers_work_area(win, getattr(self.settings, "fullscreen_cover", 0.92)):
            if self.stance != "peek":
                self.unsit()
                self.peek_from_edge(1, 0.0, hold=True)
                print(f"[capri] peeking over {win.title!r}")
            self._peek_app = win.hwnd
            self._active_hwnd = win.hwnd
            return

        self._peek_app = None
        previous = self._active_hwnd
        was_perched = self.stance in ("sit", "peek")
        if self.stance == "peek":
            self.unpeek()
        if (self.stance == "sit" and self._sit_window is not None
                and self._sit_window.hwnd == win.hwnd):
            self._sit_window = win
            rect = win.rect
            self.x = float(rect.center[0])
            self.baseline = float(rect.top + 6 + self.poses.sit_seat_offset())
            self._clamp_position()
            self._active_hwnd = win.hwnd
            return
        if self._active_hwnd != win.hwnd or self.stance != "sit":
            self._active_hwnd = win.hwnd
            if was_perched and previous is not None and previous != win.hwnd:
                self._teleport_to_window(win)
            else:
                self.sit_on_window(win)

    def _pose_surface_for(self, pose, key) -> Surface:
        if self._pose_key != key or self._pose_surface is None:
            if self._pose_surface is None:
                self._pose_surface = Surface(pose.image, pose.box)
            else:
                self._pose_surface.set_image(pose.image, pose.box)
            self._pose_key = key
        return self._pose_surface

    def spark(self) -> None:
        self._play_pose("curious", 0.45)
        self.panel.effect("spark", 0.35)

    def hurt(self) -> None:
        self._play_pose("flinch", 0.55)
        self.panel.effect("hurt", 0.55)

    def celebrate(self, on_speak) -> None:
        self._play_pose("victory", 1.8)
        self.play_sound("rise")
        self._schedule(0.18, lambda: self.play_sound("done"))
        self.panel.effect("victory", 1.8)
        self._schedule(1.1, on_speak)

    def teleport_stage(self) -> None:
        if self.guide.active:
            return
        if self.away:
            self.toggle_away(False)
        self.rouse()
        self._end_talk()
        self._cancel_transition()
        old = (self.x, self.baseline)
        self.unsit()
        self.x = (self.work.left + self.work.right) / 2.0
        height = max(1, self.work.bottom - self.work.top)
        self.baseline = self.work.top + int(height * 0.64)
        self._clamp_position()
        self.fx.teleport(old, (self.x, self.baseline - 70))
        self.play_sound("teleport")
        self._begin_transition("idle", force=True)
        self._schedule(self.settings.glitch_duration + 0.05, lambda: self._play_pose("land", 0.5))

    def _idle_teleport(self) -> None:
        if self.guide.active:
            return
        if self.away:
            self.toggle_away(False)
        self._end_talk()
        self._cancel_transition()
        lo, hi = self._walk_limits()
        x = random.uniform(lo, hi)
        span = hi - lo
        if span > 1.0:
            min_shift = min(320.0, span * 0.35)
            if abs(x - self.x) < min_shift:
                x = hi if self.x <= (lo + hi) / 2.0 else lo
        old = (self.x, self.baseline)
        self.unsit()
        self.x = x
        self.baseline = self._baseline()
        self._clamp_position()
        self.fx.teleport(old, (self.x, self.baseline - 70))
        self._reset_idle_teleport_timer()
        self._reset_idle_talk_timer()
        self._chatter_idle_seen = True
        self.play_sound("teleport")
        self.panel.effect("spark", 0.45)
        print(f"[capri] idle teleport -> {self.x:.0f}")
        self._begin_transition("idle", force=True)
        self._schedule(self.settings.glitch_duration + 0.05, lambda: self._play_pose("land", 0.5))

    def summon_cursor(self) -> None:
        self.rouse()
        if self.guide.active:
            return
        if self.away:
            self.toggle_away(False)
        cx, cy = cursor_pos()
        old = (self.x, self.baseline)
        self.unsit()
        self.x = cx + 110
        self.baseline = cy + 140
        self._clamp_position()
        self.fx.teleport(old, (self.x, self.baseline - 70))
        self.fx.bolt(old, (self.x, self.baseline - 70), 0.35, 2, 3)
        self.play_sound("teleport")
        self._begin_transition("idle", force=True)
        self._schedule(self.settings.glitch_duration + 0.05, lambda: self._play_pose("zap", 0.5))

    def earn_uplink(self) -> None:
        self.play_sound("star")
        self.panel.effect("spark", 0.8)
        self.say(
            "info",
            pick(self.lines.t.get("uplink") or []),
            face="many",
            hold=7.0,
        )

    def on_linked(self) -> None:
        self.play_sound("hello")
        welcome = self.lines.t.get("welcome") or {}
        self.say(
            "info",
            welcome.get("linked", "I can see Claude!"),
            face="look",
            hold=6.0,
        )

    def start_intro(self) -> None:
        if self.intro_active:
            return
        if not getattr(self.settings, "intro_enabled", True):
            return
        if os.environ.get("CAPRI_SKIP_INTRO", "").lower() in ("1", "true", "yes"):
            return
        self.intro_active = True
        user32.ShowWindow(self.hwnd, SW_HIDE)
        to = (self.x, self.baseline - 90)
        to_size = 90.0
        try:
            body = self.poses.stand(0).image
            if body.height > 8:
                to = (self.x, self.baseline - body.height * 0.70)
                to_size = max(40.0, body.width * 0.42)
        except Exception:  # noqa: BLE001
            pass
        self.fx.intro(
            to,
            caption="PROJECT CAPRICORN",
            label="hi",
            on_land=self._intro_land,
            to_size=to_size,
        )

    def _intro_land(self) -> None:
        self.intro_active = False
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.touch()
        self._chatter_idle_seen = True
        self.next_idle_talk = max(self.next_idle_talk, 8.0)
        if getattr(self.settings, "guide_enabled", True):
            # stay at the landing spot until the welcome panel is up: sitting on
            # a window near the top first would push the panel off the screen
            self._follow_cooldown = max(
                self._follow_cooldown, time.perf_counter() + 1.35
            )
            self._schedule(1.1, self.guide.welcome)

    def start_demo(self) -> None:
        start_demo(self, self.settings.demo_speed)
        print("[capri] demo started")

    def showcase(self) -> None:
        sc = self.lines.t.get("showcase") or {}

        def minds() -> None:
            self.play_sound("blip")
            self.cutin("many", "MINDS")
            self.say("info", sc.get("minds", "There's a crowd in here."), face="many", hold=3.0)
            self.spark()

        def zap() -> None:
            self.say("info", sc.get("zap", "Me? A menace?"), face="smug", hold=3.0)
            self.cutin("eyes", "ZAP")
            self.summon_cursor()
            self._schedule(1.05, lambda: self.play_sound("bolt"))
            self.spark()

        def possess() -> None:
            self.possess_window()
            self.hurt()

        def sleep() -> None:
            self.say("info", sc.get("sleep", "Quick nap..."), face="calm", hold=3.0)
            self._schedule(1.2, self.sleep)
            self._schedule(4.2, self.rouse)

        def chip() -> None:
            self.toggle_away(True)

        def end() -> None:
            self.toggle_away(False)
            self.say("info", sc.get("end", "That's the demo."), face="grin", hold=6.0)

        self._schedule(0.2, minds)
        self._schedule(2.6, zap)
        self._schedule(5.2, possess)
        self._schedule(7.8, sleep)
        self._schedule(10.4, chip)
        self._schedule(13.0, end)

    # ---- hooks / settings actions

    def install_hooks(self, remove: bool = False) -> None:
        def work() -> None:
            try:
                result = (
                    hookinstall.uninstall()
                    if remove
                    else hookinstall.install(silent=self.settings.claude_mode)
                )
                self.enqueue_event(
                    {
                        "hook_event_name": "CapriHooksResult",
                        "ok": True,
                        "removed": bool(result.get("removed")) if remove else False,
                        "file": result.get("file"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self.enqueue_event(
                    {"hook_event_name": "CapriHooksResult", "ok": False, "error": str(exc)}
                )

        threading.Thread(target=work, name="capri-hooks", daemon=True).start()

    def toggle_sound(self) -> None:
        self.settings.sound_enabled = not self.settings.sound_enabled
        self.sounds.set_enabled(self.settings.sound_enabled)
        if self.settings.sound_enabled:
            self.play_sound("blip")
        self.say(
            "info",
            "Sound on." if self.settings.sound_enabled else "Sound off.",
            face="smug",
            hold=2.5,
        )

    def _remember_art_ratios(self) -> None:
        base = self.settings.scale or 1.0
        self.art_ratios = {
            "idle2": self.settings.idle2_scale / base,
            "idle3": self.settings.idle3_scale / base,
            "idle4": self.settings.idle4_scale / base,
            "walk": self.settings.walk_scale / base,
        }

    def set_size(self, name: str) -> None:
        factor = self.SIZES.get(name)
        if factor is None:
            return
        self.size_name = name
        self._dispose_talk()
        self.settings.scale = factor
        for key, ratio in self.art_ratios.items():
            setattr(self.settings, f"{key}_scale", factor * ratio)
        for surf in self.cache.values():
            surf.free()
        self.cache.clear()
        self.current = None
        if self._composed is not None:
            self._composed.free()
            self._composed = None
        if self._pose_surface is not None:
            self._pose_surface.free()
            self._pose_surface = None
        self._pose_key = None
        self.poses = PoseRenderer(self.settings)
        self.load_art()
        self._clamp_position()
        labels = menu_labels(self.lang)
        self.say(
            "info",
            f"{labels['size']}: {labels[name]}.",
            face="calm",
            hold=2.5,
        )

    def toggle_away(self, force: bool | None = None) -> None:
        want = (not self.away) if force is None else bool(force)
        if want == self.away:
            return
        if want:
            self._away_prev = (self.x, float(self.baseline))
            old = (self.x, self.baseline)
            self._end_talk()
            self._cancel_transition()
            self.unsit()
            self.panel.clear()
            self.panel.clear_ticker()
            self.away = True
            self.mode = "idle"
            self.x = self.work.left + 48
            self.baseline = self.work.bottom - 12
            self.fx.teleport(old, (self.x, self.baseline - 30))
            self.play_sound("teleport-out")
        else:
            old = (self.x, self.baseline)
            self.away = False
            if self._away_prev is not None:
                self.x, self.baseline = self._away_prev
                self._away_prev = None
            self._clamp_position()
            self.fx.teleport(old, (self.x, self.baseline - 70))
            self.play_sound("teleport-in")
            self._schedule(0.3, lambda: self.play_sound("land"))
            self._begin_transition("idle", force=True)

    def satellite(self) -> None:
        if self.away:
            self.toggle_away(False)
        self.rouse()
        self.unsit()
        self._play_pose("uplink", 3.2)
        self.eye_track = True
        self.eye_track_until = time.perf_counter() + 4.0
        self.panel.effect("spark", 2.2)
        target = (self.work.right - 170, self.work.top + 100)
        self.fx.motes(self._hand_pos, lambda: target, 3.4, 0.4, 2.6)
        self.fx.satellite((self.x + 50, self.baseline - 120), target, 2.6, 1.6)
        self.fx.surge(self._hand_pos(), target, 1.3,
                      on_hit=lambda: self.fx.burst(target[0], target[1], 0.6, 16))
        self.fx.glyphs(target[0], target[1], "", 1.4, (79, 227, 176, 255))
        self.play_sound("star")
        self.say(
            "info",
            pick(self.lines.t.get("gaze") or []),
            face="look",
            hold=5.0,
        )

    def toggle_wander(self) -> None:
        self.settings.wander = not self.settings.wander
        if self.settings.wander:
            self.next_thought = min(self.next_thought, 1.0)

    def toggle_claude_mode(self) -> None:
        self.settings.claude_mode = not self.settings.claude_mode
        try:
            write_setting(
                CONFIG_PATH,
                "CLAUDE_MODE",
                "true" if self.settings.claude_mode else "false",
            )
        except OSError as exc:
            print(f"[capri] could not save Claude mode: {exc}")
        self._apply_console_mode()
        self.say(
            "info",
            (
                "Claude mode on. Next launch has no console."
                if self.settings.claude_mode
                else "Claude mode off. Next launch shows the console."
            ),
            face="smug",
            hold=3.0,
        )

    def _apply_console_mode(self) -> None:
        if os.environ.get("CAPRI_LAUNCHER") != "start.bat":
            return
        self._set_console_visible(not self.settings.claude_mode)

    def _set_console_visible(self, visible: bool) -> None:
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)

    def set_language(self, lang: str) -> None:
        self.settings.lang = lang
        self.lang = resolve_lang(lang)
        self.lines = Lines(self.lang)
        self.brain.lines = self.lines
        self.brain.t = self.lines.t
        self.brain.lang = self.lines.lang

    def _menu_state(self) -> dict:
        try:
            hooks_on = bool(hookinstall.status().get("installed"))
        except Exception:  # noqa: BLE001
            hooks_on = False
        return {
            "lang": self.settings.lang,
            "resolved_lang": self.lang,
            "size": self.size_name,
            "muted": not self.settings.sound_enabled,
            "wander": self.settings.wander,
            "claude_mode": self.settings.claude_mode,
            "away": self.away,
            "online": self.bridge is not None,
            "port": self.settings.event_port,
            "hooks": hooks_on,
        }

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
                if wparam == 3:
                    self.toggle_away()
                    return 0
            if msg == WM_NCHITTEST:
                if not self.settings.clicks_enabled or self.current is None:
                    return HTTRANSPARENT
                px = ctypes.c_short(lparam & 0xFFFF).value
                py = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                pt = POINT(px, py)
                user32.ScreenToClient(wt.HWND(hwnd), ctypes.byref(pt))
                if self.panel.action_at(pt.x, pt.y) is not None:
                    return HTCLIENT
                if self.away:
                    return HTCLIENT if self.current.opaque_at(pt.x, pt.y) else HTTRANSPARENT
                hit = self.hit_box or self.current.box
                if not (hit[0] <= pt.x < hit[2] and hit[1] <= pt.y < hit[3]):
                    return HTTRANSPARENT
                if self.current.opaque_at(pt.x, pt.y):
                    return HTCLIENT
                return HTTRANSPARENT
            if msg == WM_LBUTTONDBLCLK:
                return 0
            if msg == WM_LBUTTONDOWN:
                self.touch()
                if self.away:
                    self._away_click = True
                    return 0
                if (
                    self.settings.clicks_enabled
                    and not self.dragging
                    and self.transition is None
                ):
                    self._drag_begin(*self._mouse_screen(lparam))
                return 0
            if msg == WM_MOUSEMOVE:
                self.touch()
                if self.dragging:
                    self._drag_move(*self._mouse_screen(lparam))
                return 0
            if msg == WM_LBUTTONUP:
                if self._away_click:
                    self._away_click = False
                    self.toggle_away(False)
                    return 0
                if self.dragging:
                    self._drag_end(*self._mouse_screen(lparam))
                return 0
            if msg == WM_RBUTTONUP:
                if self.settings.clicks_enabled and not self.dragging:
                    self._show_menu(*self._mouse_screen(lparam))
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
        wc.lpszClassName = "CapriDemoPetWindow"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                raise OSError(f"RegisterClassW failed ({err})")

        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

        self.hwnd = user32.CreateWindowExW(
            ex, "CapriDemoPetWindow", "Capri", WS_POPUP,
            0, 0, 10, 10, None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError(
                f"CreateWindowExW failed ({ctypes.get_last_error()})"
            )
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

        self._register_hotkey(1, self.settings.quit_hotkey)
        self._register_hotkey(2, self.settings.reload_hotkey)
        self._register_hotkey(3, self.settings.chip_hotkey)

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
            if self.fx.active:
                self.fx.raise_()
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
            blend = BLENDFUNCTION(0, 0, 255, 1)
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

    def _pet_center(self) -> tuple[int, int]:
        left, top, right, bottom = self._current_box()
        return (
            int(self.left + (left + right) / 2),
            int(self.top + (top + bottom) / 2),
        )

    def _current_box(self) -> tuple[int, int, int, int]:
        if self.away and self.away_action is not None:
            return self.away_action.box
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
        self.touch()
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
            pt = POINT(sx, sy)
            user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
            aid = self.panel.action_at(pt.x, pt.y)
            if aid is not None:
                self.touch()
                if self.guide.active:
                    self.guide.on_action(aid)
                return
            if self.mode in ("talk", "talk_wait"):
                self._end_talk_click()
                return
            self._show_menu(sx, sy)
            return
        self._drag_moved = False
        if self.stance in ("sit", "peek", "fall"):
            self.unsit()
        if self.mode == "walk":
            self._enter_walk()
        self.next_thought = max(
            self.next_thought,
            random.uniform(self.settings.idle_min, self.settings.idle_max),
        )
        print(f"[capri] moved to {self.x:.0f},{self.baseline:.0f}")

    # ---- glitch transitions

    def _begin_transition(self, action: str, force: bool = False) -> None:
        self.rouse()
        self._anim_name = None
        if self.transition is not None:
            if not force:
                return
            self._cancel_transition()
        surf = self.current
        seconds = self.settings.glitch_duration
        if surf is None or not self.settings.glitch_enabled or seconds <= 0.0:
            self._apply_action(action)
            return
        try:
            self.sprite_glitch = SpriteGlitch(surf, seconds, self.settings.glitch_fps)
        except Exception as exc:  # noqa: BLE001
            print(f"[capri] glitch failed: {exc}")
            self._apply_action(action)
            return
        self.transition = action

    def _advance_transition(self, now: float) -> None:
        if self.transition is None:
            return
        glitch = self.sprite_glitch
        if glitch is None or now - glitch.started >= glitch.seconds:
            self._finish_transition()

    def _finish_transition(self) -> None:
        glitch, self.sprite_glitch = self.sprite_glitch, None
        action, self.transition = self.transition, None
        if glitch is not None:
            original = glitch.original
            glitch.close()
            if original is not None:
                self.current = original
                try:
                    self._blit(original)
                except Exception:  # noqa: BLE001
                    pass
        if action is not None:
            self._apply_action(action)

    def _cancel_transition(self) -> None:
        if self.transition is None and self.sprite_glitch is None:
            return
        self.transition = None
        glitch, self.sprite_glitch = self.sprite_glitch, None
        if glitch is None:
            return
        original = glitch.original
        glitch.close()
        if original is not None:
            self.current = original
            try:
                self._blit(original)
            except Exception:  # noqa: BLE001
                pass

    def _apply_action(self, action: str) -> None:
        self._anim_name = None
        if action == "walk":
            self._enter_walk()
            print(f"[capri] walk -> {self.walk_target:.0f}")
        elif action == "talk":
            self._start_talk()
        elif action == "say":
            self._say_something_now()
        elif action == "chat":
            self.open_chat()
        elif action == "quit":
            print("[capri] closing pet")
            self.running = False
        elif action == "idle2":
            poses = [
                name
                for name in ("idle2", "idle3", "idle4")
                if self.actions.get(name) is not None
            ]
            if poses:
                weights = [3 if name == "idle2" else 1 for name in poses]
                self.idle_pose = random.choices(poses, weights=weights, k=1)[0]
            else:
                self.idle_pose = "idle2"
            self.mode = "idle2"
            self.mode_timer = self.settings.idle2_duration
            print(f"[capri] idle pose: {self.idle_pose}")
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
            read_config(CONFIG_PATH),
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
        self._ensure_chat(self._chat_anchor()).popup_menu(
            x, y, self._menu_state()
        )

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
        if action == "status":
            self.brain.status()
        elif action == "demo":
            self.start_demo()
        elif action == "guide":
            self.enqueue_event({"hook_event_name": "CapriGuide"})
        elif action == "hooks-install":
            self.install_hooks(False)
        elif action == "hooks-remove":
            self.install_hooks(True)
        elif action == "sound":
            self.toggle_sound()
        elif action == "chip":
            self.toggle_away()
        elif action == "teleport":
            self._idle_teleport()
        elif action == "satellite":
            self.satellite()
        elif action == "possess":
            self.possess_window()
        elif action == "wander":
            self.toggle_wander()
        elif action == "claude-mode":
            self.toggle_claude_mode()
        elif action.startswith("lang-"):
            self.set_language(action[5:])
        elif action.startswith("size-"):
            self.set_size(action[5:])
        elif action in ("quit", "chat", "say"):
            self._begin_transition(action, force=True)
        else:
            self._begin_transition("idle", force=True)

    def _on_chat_state(self, is_open: bool, win: ChatWindow | None = None) -> None:
        """Called from the chat thread - only flips a flag."""
        with self.chat_lock:
            if win is not None and self.chat is not None and win is not self.chat:
                return
            self.chat_open = is_open
        print("[capri] chat opened" if is_open else "[capri] chat closed")

    # ---- say something

    def _pick_line(self) -> str | None:
        if not self.words:
            print("[capri] no words to say")
            return None
        choices = [w for w in self.words if w != self.last_said] or self.words
        line = random.choice(choices)
        self.last_said = line
        return line

    def _close_chat_for_talk(self) -> None:
        if self.chat_open:
            with self.chat_lock:
                self.chat_open = False
            if self.chat is not None:
                self.chat.close()

    def _say_something_now(self) -> None:
        line = self._pick_line()
        if line is None:
            return
        self._reset_idle_talk_timer()
        self._close_chat_for_talk()
        self._pending_line = line
        self._start_talk()

    def _start_talk(self) -> None:
        line = self._pending_line
        self._pending_line = None
        if line is None:
            self._enter_idle()
            return
        self.panel.clear()
        self.panel.clear_ticker()
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
        now = time.perf_counter()
        self.talk_typing_until = now + max(0.3, self.talk.typing_seconds) + 0.08
        self.talk_wait_until = 0.0
        self.current = self.talk.frame(now)
        self._clamp_position()
        self.play_sound("blip")
        print(f"[capri] says: {line}")

    def _settle_talk(self) -> None:
        if self.talk is None:
            self._enter_idle()
            return
        self.talk.rest()
        self.mode = "talk_wait"
        self.talk_wait_until = (
            time.perf_counter() + self.settings.talk_wait_seconds
        )
        print("[capri] talk done; click or wait to close")

    def _end_talk_click(self) -> None:
        self._pending_line = None
        self.talk_typing_until = 0.0
        self.talk_wait_until = 0.0
        if self.mode in ("talk", "talk_wait"):
            self._begin_transition("idle")

    def _end_talk(self) -> None:
        self._pending_line = None
        self.talk_typing_until = 0.0
        self.talk_wait_until = 0.0
        if self.mode in ("talk", "talk_wait"):
            self._enter_idle()

    # ---- behaviour

    def _reset_idle_talk_timer(self) -> None:
        self.next_idle_talk = random.uniform(
            self.settings.idle_talk_min, self.settings.idle_talk_max
        )

    def _reset_idle_teleport_timer(self) -> None:
        self.next_idle_teleport = random.uniform(
            self.settings.idle_teleport_min, self.settings.idle_teleport_max
        )

    def _reset_idle_action_timers(self) -> None:
        self._reset_idle_talk_timer()
        self._reset_idle_teleport_timer()

    def _enter_idle(self) -> None:
        self.mode = "idle"
        self.mode_timer = 0.0
        self._idle_body = random.random() < self.settings.idle_body_chance
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
        if self.activity_mode != "idle":
            return
        poses = [
            name
            for name in ("idle2", "idle3", "idle4")
            if self.actions.get(name) is not None
        ]
        talk_chance = (
            self.settings.idle_talk_chance
            if self.words
            and system_idle_seconds() >= self.settings.chatter_idle_seconds
            else 0.0
        )
        weights = [
            ("idle2", self.settings.idle2_chance if poses else 0.0),
            ("say", talk_chance),
            ("teleport", self.settings.idle_teleport_chance),
        ]
        if self.settings.wander:
            weights.append(
                ("walk", max(0.0, 1.0 - sum(weight for _, weight in weights)))
            )
        total = sum(weight for _, weight in weights)
        if total <= 0.0:
            self._enter_idle()
            return
        roll = random.random() * total
        for action, weight in weights:
            if roll < weight:
                if action == "teleport":
                    self._idle_teleport()
                else:
                    self._begin_transition(action)
                return
            roll -= weight
        self._enter_idle()

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

        self._drain_events()
        self._process_pending(now)
        self._consume_menu()
        self.fx.tick()
        if not self.running:
            return

        if self.transition == "quit":
            self._advance_transition(now)
            return

        if self.intro_active:
            return

        self._follow_windows(now)
        if self._peek_until and now >= self._peek_until:
            self._peek_until = 0.0
            self.unpeek()
        if self.stance == "fall":
            step = min(0.05, max(0.0, dt))
            self._fall_vy += 2600.0 * step
            self.baseline += self._fall_vy * step
            floor = float(self.work.bottom)
            if self.baseline >= floor or now >= self._fall_until:
                self.baseline = floor
                self._fall_vy = 0.0
                self.fx.burst(self.x, self.baseline - 10, life=0.3, count=12)
                self.play_sound("land")
                self.unsit()
        if self._anim_name and (now >= self._anim_until or self.stance != "stand"):
            self._anim_name = None

        if self.stance in ("sit", "peek", "fall"):
            return

        if self.guide.active:
            return

        if self.away:
            return

        if self.activity_mode != "idle" or self.chat_open or self.dragging:
            self.last_activity = now
        elif self.stance == "stand" and self.mode == "idle" and self.transition is None:
            idle_for = now - self.last_activity
            if not self._sleeping and idle_for >= self.settings.sleep_after:
                self.sleep()
            elif (
                self._sleeping
                and not self._dozing
                and now - self._sleep_started >= self.settings.doze_after
            ):
                self.doze()

        if self._sleeping or self._dozing:
            return

        if self.transition is not None:
            self._advance_transition(now)
            return

        if (
            not self.chat_open
            and now - self._topmost_at > 1.0
            and not self._tk_menu_open()
        ):
            self._apply_topmost()
            self._topmost_at = now

        if self.dragging:
            if self.mode == "idle":
                self._update_eyes(dt, now)
            return

        if self.mode == "talk":
            if now >= self.talk_typing_until:
                self._settle_talk()
            return

        if self.mode == "talk_wait":
            if now >= self.talk_wait_until:
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
            if self.activity_mode != "idle":
                self.next_thought = max(self.next_thought, 1.0)
            else:
                if self.settings.idle_sounds:
                    self.next_idle_sound -= dt
                    if self.next_idle_sound <= 0:
                        self.next_idle_sound = random.uniform(
                            self.settings.idle_sound_min,
                            self.settings.idle_sound_max,
                        )
                        self.play_sound(random.choice(("blip", "tick")))
                if self.settings.idle_teleport_chance > 0:
                    self.next_idle_teleport -= dt
                    if self.next_idle_teleport <= 0:
                        self._idle_teleport()
                        return
                if (
                    self.words
                    and self.settings.idle_talk_chance > 0
                    and system_idle_seconds() >= self.settings.chatter_idle_seconds
                ):
                    if not self._chatter_idle_seen:
                        self._chatter_idle_seen = True
                        self.next_idle_talk = 0.0
                    self.next_idle_talk -= dt
                    if self.next_idle_talk <= 0:
                        self._begin_transition("say")
                        return
                elif self._chatter_idle_seen:
                    self._chatter_idle_seen = False
                    self._reset_idle_talk_timer()
                self.next_thought -= dt
                if self.next_thought <= 0:
                    self.think()

    # ---- rendering

    def _plain_surface(self, now: float) -> Surface:
        if self.mode in ("talk", "talk_wait") and self.talk is not None:
            return self.talk.frame(now)
        if self._anim_name and self.stance == "stand":
            pose = self.poses.animate(self._anim_name, now - self._anim_started)
            return self._pose_surface_for(pose, ("anim", self._anim_name, int(now * 12)))
        if self.mode == "idle" and self._idle_body:
            pose = self.poses.stand(now)
            return self._pose_surface_for(pose, ("idle-body", int(now * 8)))
        if self.mode == "idle" and self.face is not None:
            return self.face.draw(int(round(self.eye_dx)), int(round(self.eye_dy)))
        if self.mode == "idle2":
            pose = self.actions.get(self.idle_pose)
            if pose is not None:
                return pose.surface(False, self.cache)
        if self.mode == "walk":
            if self.walk_cycle is not None:
                return self.walk_cycle.surface(now, self.facing_left)
            if self.actions.get("walk") is not None:
                return self.actions["walk"].surface(self.facing_left, self.cache)
        self.mode = "idle"
        idle = self.actions.get("idle")
        if idle is not None:
            return idle.surface(False, self.cache)
        if self.face is not None:
            return self.face.draw(0, 0)
        raise RuntimeError("no art loaded")

    def _pet_image(self) -> tuple[Image.Image, tuple[int, int, int, int]]:
        if self.mode in ("talk", "talk_wait") and self.talk is not None:
            return self.talk._compose(), self.talk._box
        if self._anim_name and self.stance == "stand":
            pose = self.poses.animate(self._anim_name, time.perf_counter() - self._anim_started)
            return pose.image, pose.box
        if self.mode == "idle" and self._idle_body:
            pose = self.poses.stand(time.perf_counter())
            return pose.image, pose.box
        if self.mode == "idle" and self.face is not None:
            return (
                self.face._compose(int(round(self.eye_dx)), int(round(self.eye_dy))),
                self.face.box,
            )
        if self.mode == "idle2":
            pose = self.actions.get(self.idle_pose)
            if pose is not None:
                return pose.image(False), pose.box
        if self.mode == "walk":
            if self.walk_cycle is not None:
                now = time.perf_counter()
                return (
                    self.walk_cycle.image(now, self.facing_left),
                    self.walk_cycle.box,
                )
            action = self.actions.get("walk")
            if action is not None:
                return action.image(self.facing_left), action.box
        idle = self.actions.get("idle")
        if idle is not None:
            return idle.image(False), idle.box
        if self.face is not None:
            return self.face._compose(0, 0), self.face.box
        raise RuntimeError("no art loaded")

    def render(self) -> None:
        now = time.perf_counter()
        if self.sprite_glitch is not None:
            surf = self.sprite_glitch.frame(now)
            self.hit_box = None
            self.current = surf
            self._blit(surf)
            return

        if self.away:
            waiting = self.panel.msg is not None
            pose = self.poses.chip(waiting=waiting)
            surf = self._pose_surface_for(pose, ("chip", waiting))
            self.hit_box = surf.box
            self.current = surf
            self._blit(surf)
            return

        if self._dozing:
            pose = self.poses.doze()
            surf = self._pose_surface_for(pose, ("doze",))
            self.hit_box = surf.box
            self.current = surf
            self._blit(surf)
            return

        if self._sleeping and self.poses.has_desktop:
            pose = self.poses.sleep(now)
            surf = self._pose_surface_for(pose, ("sleep", int(now * 8)))
            self.hit_box = surf.box
            self.current = surf
            self._blit(surf)
            return

        if self.stance in ("sit", "peek", "fall"):
            if self.stance == "sit":
                pose = self.poses.sit(now)
                key = ("sit", int(now * 6))
            elif self.stance == "peek":
                pose = self.poses.peek(1.0, self._peek_side, now)
                key = ("peek", self._peek_side, int(now * 6))
            else:
                p = min(1.0, max(0.0, (now - self._fall_started) / 1.1))
                angle = 26.0 * _ease_out_local(p)
                pose = self.poses.fall(angle, 18.0 * p)
                key = ("fall", int(angle * 4))
            surf = self._pose_surface_for(pose, key)
            self.hit_box = surf.box
            self.current = surf
            self._blit(surf)
            return

        decorated = self.panel.active(now) or self.panel.fx is not None
        if not decorated:
            surf = self._plain_surface(now)
            self.hit_box = surf.box
            self.current = surf
            self._blit(surf)
            return

        img, box = self._pet_image()
        img, box, hit = self.panel.compose(img, box, now)
        if self._composed is None:
            self._composed = Surface(img, box)
        else:
            self._composed.set_image(img, box)
        self.hit_box = hit
        self.current = self._composed
        self._blit(self._composed)

    # ---- main loop

    def run(self) -> None:
        self.start_intro()
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
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self._unregister_hotkeys()
        if self.dragging:
            try:
                user32.ReleaseCapture()
            except Exception:  # noqa: BLE001
                pass
            self.dragging = False
        self._cancel_transition()
        self._dispose_talk()
        chat = self.chat
        self.chat = None
        if chat is not None:
            chat.quit()
        self.current = None
        if self._composed is not None:
            self._composed.free()
            self._composed = None
        if self._pose_surface is not None:
            self._pose_surface.free()
            self._pose_surface = None
        self.fx.close()
        for surf in self.cache.values():
            surf.free()
        self.cache.clear()
        self._dispose_art()
