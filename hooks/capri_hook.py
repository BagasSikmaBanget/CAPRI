#!/usr/bin/env python3
"""Claude Code hook -> capri-demo.

Reads the hook event on stdin and forwards a trimmed copy to the pet on
127.0.0.1. Rule #1: never get in Claude's way. No output, always exit 0,
give up fast. Standalone: uses only the standard library.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

PORT = int(os.environ.get("CAPRI_PORT") or 47823)

KEEP = [
    "hook_event_name",
    "session_id",
    "cwd",
    "session_title",
    "permission_mode",
    "tool_name",
    "tool_input",
    "tool_use_id",
    "duration_ms",
    "error",
    "is_interrupt",
    "prompt",
    "message",
    "title",
    "notification_type",
    "last_assistant_message",
    "agent_id",
    "agent_type",
    "source",
    "reason",
    "trigger",
]

BIG_KEYS = {"content", "old_string", "new_string", "new_source", "edits"}
REPLY_MAX = 6000


def trim(value, depth: int = 0):
    if isinstance(value, str):
        return value if len(value) <= 280 else value[:280] + "…"
    if isinstance(value, list):
        return None if depth > 2 else [trim(v, depth + 1) for v in value[:8]]
    if isinstance(value, dict):
        if depth > 2:
            return None
        out = {}
        for key, val in value.items():
            if key in BIG_KEYS:
                out[key + "_len"] = (
                    len(val) if isinstance(val, (str, list)) else 0
                )
                continue
            out[key] = trim(val, depth + 1)
        return out
    return value


def slim(evt: dict) -> dict:
    out = {key: trim(evt[key]) for key in KEEP if key in evt}
    reply = evt.get("last_assistant_message")
    if isinstance(reply, str) and len(reply) > REPLY_MAX:
        out["last_assistant_message"] = reply[:REPLY_MAX] + "…"
    return out


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw or len(raw) > 8 * 1024 * 1024:
            return 0
        evt = json.loads(raw)
        if not isinstance(evt, dict):
            return 0
        body = json.dumps(slim(evt)).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/event",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.8):
            pass
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
