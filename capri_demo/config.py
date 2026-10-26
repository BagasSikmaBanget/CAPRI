"""Configuration reader and typed settings.

The format is CAPRI's capri_config.txt: KEY = value, '#' comments.
Every relative path is resolved from the project root (the folder that holds
this package), so the app can be launched from anywhere.
"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def write_setting(path: str, key: str, value: str) -> None:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        lines = []

    wanted = key.strip().upper()
    replacement = f"{wanted} = {value}\n"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        if "=" not in line:
            continue
        found, _, rest = line.partition("=")
        if found.strip().upper() != wanted:
            continue
        comment = ""
        if "#" in rest:
            comment = "  #" + rest.split("#", 1)[1].rstrip("\r\n")
        lines[index] = replacement.rstrip("\n") + comment + "\n"
        break
    else:
        lines.append(replacement)

    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


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
            return value if os.path.isabs(value) else os.path.join(ROOT, value)

        # ---- sprite / movement (CAPRI)
        self.scale = _clamp(num("SCALE", 0.38), 0.05, 4.0)
        self.idle2_scale = _clamp(num("IDLE2_SCALE", 0.20), 0.05, 4.0)
        self.idle3_scale = _clamp(num("IDLE3_SCALE", 0.55), 0.05, 4.0)
        self.idle4_scale = _clamp(num("IDLE4_SCALE", 0.55), 0.05, 4.0)
        self.walk_scale = _clamp(num("WALK_SCALE", 0.38), 0.05, 4.0)
        self.walk_anim = flag("WALK_ANIM", "true")
        self.walk_frames = int(_clamp(num("WALK_FRAMES", 8, int), 2, 24))
        self.walk_fps = _clamp(num("WALK_FPS", 8.0), 1.0, 60.0)
        self.walk_bob = _clamp(num("WALK_BOB", 4.0), 0.0, 40.0)
        self.walk_sway = _clamp(num("WALK_SWAY", 2.0), 0.0, 40.0)
        self.walk_lean = _clamp(num("WALK_LEAN", 2.5), 0.0, 20.0)

        self.speed = max(10.0, num("WALK_SPEED", 110.0))
        self.margin = _clamp(num("SCREEN_MARGIN", 40.0), 0.0, 2000.0)
        self.walk_min = max(30.0, num("WALK_MIN_DISTANCE", 120.0))
        self.walk_max = max(self.walk_min, num("WALK_MAX_DISTANCE", 420.0))

        self.idle_min = max(0.5, num("IDLE_MIN", 6.0))
        self.idle_max = max(self.idle_min, num("IDLE_MAX", 18.0))
        self.idle2_chance = _clamp(num("IDLE2_CHANCE", 0.25), 0.0, 1.0)
        self.idle_talk_chance = _clamp(num("IDLE_TALK_CHANCE", 0.25), 0.0, 1.0)
        self.idle_teleport_chance = _clamp(
            num("IDLE_TELEPORT_CHANCE", 0.08), 0.0, 1.0
        )
        self.chatter_idle_seconds = _clamp(
            num("CHATTER_IDLE_SECONDS", 30.0), 0.0, 3600.0
        )
        self.idle_talk_min = max(3.0, num("IDLE_TALK_MIN", 12.0))
        self.idle_talk_max = max(self.idle_talk_min, num("IDLE_TALK_MAX", 30.0))
        self.idle_teleport_min = max(5.0, num("IDLE_TELEPORT_MIN", 10.0))
        self.idle_teleport_max = max(
            self.idle_teleport_min, num("IDLE_TELEPORT_MAX", 20.0)
        )
        self.idle2_duration = max(0.5, num("IDLE2_DURATION", 5.0))
        self.idle_sounds = flag("IDLE_SOUNDS", "true")
        self.idle_sound_min = max(5.0, num("IDLE_SOUND_MIN", 30.0))
        self.idle_sound_max = max(self.idle_sound_min, num("IDLE_SOUND_MAX", 90.0))

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
        self.chip_hotkey = cfg.get("CHIP_HOTKEY", "ctrl+alt+c")

        self.glitch_enabled = flag("GLITCH_ENABLED", "true")
        self.glitch_duration = _clamp(num("GLITCH_DURATION", 0.9), 0.0, 5.0)
        self.glitch_fps = int(_clamp(num("GLITCH_FPS", 24), 4, 60))

        self.talk_scale = _clamp(num("TALK_SCALE", 0.25), 0.05, 4.0)
        self.talk_bubble_ratio = _clamp(num("TALK_BUBBLE_RATIO", 1.4), 0.3, 6.0)
        self.talk_fps = int(_clamp(num("TALK_FPS", 14), 4, 60))
        self.talk_type_cps = max(4.0, num("TALK_TYPE_CPS", 24.0))
        self.talk_wait_seconds = max(0.0, num("TALK_WAIT_SECONDS", 5.0))
        self.talk_file0 = path_of("TALK_FILE_0", "assets/art/talking0.png")
        self.talk_file1 = path_of("TALK_FILE_1", "assets/art/talking1.png")
        self.talk_overlays = [
            path_of(f"TALK_OVERLAY_{i}", f"assets/overlay/overlay{i}.png")
            for i in range(3)
        ]
        self.talk_bubble_file = path_of(
            "TALK_BUBBLE_FILE", "assets/overlay/OverlayTalk.png"
        )
        self.talk_words_file = path_of("TALK_WORDS_FILE", "words.txt")

        self.eyeline_file = path_of("EYELINE_FILE", "assets/art/eyeline.png")
        self.eye_file = path_of("EYE_FILE", "assets/art/eyeballs.png")
        self.idle2_file = path_of("IDLE2_FILE", "assets/art/Idle2.png")
        self.desktop_full_file = path_of(
            "DESKTOP_FULL_FILE", "assets/art/capri-full.png"
        )
        self.desktop_cutout_file = path_of(
            "DESKTOP_CUTOUT_FILE", "assets/art/capri-cutout.png"
        )
        self.desktop_face_dir = path_of("DESKTOP_FACE_DIR", "assets/faces")
        self.desktop_model_scale = _clamp(
            num("DESKTOP_MODEL_SCALE", 0.55), 0.05, 4.0
        )
        self.idle3_file = path_of("IDLE3_FILE", self.desktop_full_file)
        self.idle4_file = path_of("IDLE4_FILE", self.desktop_cutout_file)
        self.walk_file = path_of("WALK_FILE", "assets/art/walk1.png")
        self.idle_file = path_of("IDLE_FILE", "assets/art/Idle.png")

        # ---- Claude Code narration (capri-desktop)
        self.lang = (cfg.get("LANG", "auto") or "auto").strip().lower()
        self.claude_mode = flag("CLAUDE_MODE", "true")
        self.enable_bridge = flag("ENABLE_BRIDGE", "true")
        self.event_port = int(_clamp(num("EVENT_PORT", 47823, int), 1, 65535))
        self.sound_enabled = flag("SOUND_ENABLED", "true")
        self.ticker_enabled = flag("TICKER_ENABLED", "true")
        self.panel_enabled = flag("PANEL_ENABLED", "true")
        self.panel_scale = _clamp(num("PANEL_SCALE", 1.0), 0.5, 2.0)
        self.panel_width = int(_clamp(num("PANEL_WIDTH", 430, int), 260, 900))
        self.ticker_seconds = _clamp(num("TICKER_SECONDS", 6.0), 0.5, 60.0)
        self.wander = flag("WANDER", "true")
        self.intro_enabled = flag("INTRO_ENABLED", "true")
        self.guide_enabled = flag("GUIDE_ENABLED", "true")
        self.sleep_after = max(20.0, num("SLEEP_AFTER", 600.0))
        self.doze_after = max(5.0, num("DOZE_AFTER", 20.0))
        self.demo_speed = _clamp(num("DEMO_SPEED", 1.0), 0.1, 5.0)
        self.long_job_minutes = max(1.0, num("LONG_JOB_MINUTES", 8.0))
        self.long_job_actions = int(max(1, num("LONG_JOB_ACTIONS", 50, int)))

        self.face_dir = path_of("FACE_DIR", "assets/faces")
        self.away_file = path_of("AWAY_FILE", "assets/faces/face-calm.png")
        self.away_scale = _clamp(num("AWAY_SCALE", 0.18), 0.02, 2.0)
        self.hook_script = path_of("HOOK_SCRIPT", "hooks/capri_hook.py")

        # ---- chat (CAPRI)
        self.chat_api_key = (cfg.get("CHAT_API_KEY", "") or "").strip()
        self.chat_api_base = cfg.get("CHAT_API_BASE", "https://api.cosmoshub.tech/v1")
        self.chat_model = cfg.get("CHAT_MODEL", "gpt-4o-mini")
        self.chat_timeout = int(max(5, num("CHAT_TIMEOUT", 60, int)))
        self.chat_max_history = int(max(2, num("CHAT_MAX_HISTORY", 12, int)))
        self.chat_system_prompt = cfg.get(
            "CHAT_SYSTEM_PROMPT",
            "You are Capri, a small gremlin-like desktop companion who lives on "
            "the user's screen. You are playful, a little sharp-tongued, and "
            "speak in short casual sentences. Keep replies brief - one to three "
            "sentences unless the user clearly wants detail.",
        )
