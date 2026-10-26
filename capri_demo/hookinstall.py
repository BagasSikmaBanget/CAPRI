"""Install / remove the capri-demo hook in ~/.claude/settings.json.

Ported from capri-desktop's scripts/install-hooks.js. Existing settings and
hooks are kept; a timestamped backup is written before any change.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_SCRIPT = os.path.join(ROOT, "hooks", "capri_hook.py")

EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "SessionEnd",
]

MARK = "capri_hook.py"


def settings_path() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )
    return os.path.join(base, "settings.json")


def hook_python(silent: bool = True) -> str:
    python = sys.executable or "python"
    if silent:
        candidate = os.path.join(
            os.path.dirname(os.path.abspath(python)), "pythonw.exe"
        )
        if os.path.isfile(candidate):
            return candidate
    return python


def hook_command(silent: bool = True) -> str:
    python = hook_python(silent)
    script = HOOK_SCRIPT.replace("\\", "/")
    return f'"{python.replace(chr(92), "/")}" "{script}"'


def _read(file: str) -> dict:
    if not os.path.exists(file):
        return {}
    with open(file, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{file} is not valid JSON ({exc}). Fix it first, nothing was changed."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{file} is not a JSON object, nothing was changed.")
    return data


def _is_capri(group) -> bool:
    if not isinstance(group, dict):
        return False
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(MARK in str(h.get("command", "")) for h in hooks if isinstance(h, dict))


def _strip(settings: dict) -> dict:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    for event in list(hooks.keys()):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        hooks[event] = [g for g in groups if not _is_capri(g)]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings


def _write(file: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(file), exist_ok=True)
    if os.path.exists(file):
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
        shutil.copyfile(file, f"{file}.capri-backup-{stamp}")
    with open(file, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def install(silent: bool = True) -> dict:
    file = settings_path()
    original = _read(file)
    before = json.dumps(original, sort_keys=True)
    settings = _strip(original)
    hooks = settings.setdefault("hooks", {})
    command = hook_command(silent)
    for event in EVENTS:
        hooks.setdefault(event, [])
        hooks[event].append(
            {"hooks": [{"type": "command", "command": command, "async": True, "timeout": 10}]}
        )
    if json.dumps(settings, sort_keys=True) != before:
        _write(file, settings)
    return {"file": file, "command": command, "events": len(EVENTS)}


def uninstall() -> dict:
    file = settings_path()
    if not os.path.exists(file):
        return {"file": file, "removed": False}
    settings = _read(file)
    before = json.dumps(settings, sort_keys=True)
    _strip(settings)
    removed = json.dumps(settings, sort_keys=True) != before
    if removed:
        _write(file, settings)
    return {"file": file, "removed": removed}


def status() -> dict:
    file = settings_path()
    try:
        settings = _read(file)
        events = [
            event
            for event, groups in (settings.get("hooks") or {}).items()
            if isinstance(groups, list) and any(_is_capri(g) for g in groups)
        ]
        return {"file": file, "installed": bool(events), "events": events}
    except ValueError as exc:
        return {"file": file, "installed": False, "events": [], "error": str(exc)}
