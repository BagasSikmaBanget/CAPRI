"""Narration lines and small text helpers.

The content is capri-desktop's lines.js, exported once to lines.json so the
same five languages (fr, en, es, pt, ru) work here.
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES_FILE = os.path.join(HERE, "lines.json")

LANGS = ("fr", "en", "es", "pt", "ru")


def _load() -> dict:
    try:
        with open(LINES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


_ALL = _load()


def system_lang() -> str:
    env = (os.environ.get("CAPRI_LANG") or os.environ.get("LANG") or "").lower()
    if env[:2] in LANGS:
        return env[:2]
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        primary = lid & 0x3FF
        return {0x0C: "fr", 0x0A: "es", 0x16: "pt", 0x19: "ru"}.get(primary, "en")
    except Exception:  # noqa: BLE001
        return "en"


def resolve_lang(pref: str) -> str:
    pref = (pref or "auto").strip().lower()
    if pref in LANGS:
        return pref
    return system_lang()


def pick(items):
    if not items:
        return ""
    return random.choice(items)


def fmt(text: str, vars: dict | None = None) -> str:
    vars = vars or {}

    def repl(match):
        return str(vars.get(match.group(1), ""))

    return re.sub(r"\{(\w+)\}", repl, text or "")


def basename(path: str = "") -> str:
    path = str(path or "").replace("\\", "/").rstrip("/")
    return path.split("/")[-1] if path else ""


def duration(ms: float, lang: str = "fr") -> str:
    ru = lang == "ru"
    s = max(0, round((ms or 0) / 1000))
    if s < 60:
        return f"{s} с" if ru else f"{s} s"
    m = s // 60
    ss = f"{s % 60:02d}"
    if m < 60:
        if lang == "en":
            return f"{m}m {ss}s"
        return f"{m} мин {ss} с" if ru else f"{m} min {ss}"
    return f"{m // 60} {ru and 'ч' or 'h'} {m % 60:02d}"


def plural(n: int, forms, lang: str) -> str:
    if isinstance(forms, list):
        word = forms[0] if n == 1 else forms[1]
    elif isinstance(forms, dict):
        if lang == "ru":
            mod10, mod100 = n % 10, n % 100
            if mod10 == 1 and mod100 != 11:
                key = "one"
            elif 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
                key = "few"
            else:
                key = "many"
        else:
            key = "one" if n == 1 else "other"
        word = forms.get(key) or forms.get("other") or ""
    else:
        word = str(forms)
    return f"{n} {word}"


def clip(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def readable(text: str) -> str:
    """Claude's answer as plain readable text (capri-desktop's readable())."""
    return (
        str(text or "")
        .replace("\r", "")
        .replace("```", "")
        .replace("\n#", "\n")
        .replace("**", "")
        .replace("__", "")
        .replace("`", "")
        .strip()
    )


def clean_markdown(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`#>]+", "", str(text or ""))).strip()


class Lines:
    def __init__(self, lang: str):
        self.lang = lang if lang in _ALL else "en"
        self.t = _ALL.get(self.lang) or _ALL.get("en") or {}

    def pick(self, key: str):
        return pick(self.t.get(key) or [])

    def get(self, key: str, default=""):
        return self.t.get(key, default)
