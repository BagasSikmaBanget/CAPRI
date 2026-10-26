"""A fake but realistic Claude Code session, then her showcase.

Ported from capri-desktop's scripts/demo-sequence.js. It is deliberately
event-driven: the demo simply posts the same events a real hook would, so the
whole Brain/reaction path is exercised without Claude Code installed.
"""

from __future__ import annotations

import copy
import threading
import time

SESSION = "demo-session"
CWD = "C:/Users/you/projects/night-city-api"


def _base(name: str, **extra) -> dict:
    evt = {
        "hook_event_name": name,
        "session_id": SESSION,
        "cwd": CWD,
        "demo": True,
    }
    evt.update(extra)
    return evt


def _tool(name: str, data: dict) -> dict:
    return _base("PreToolUse", tool_name=name, tool_input=data)


def _done(name: str, data: dict, ms: int) -> dict:
    return _base("PostToolUse", tool_name=name, tool_input=data, duration_ms=ms)


DEMO_STEPS: list[tuple[int, dict]] = [
    (0, _base("SessionStart", source="startup")),
    (2600, _base("UserPromptSubmit", prompt="Add a /gigs endpoint with pagination and tests")),
    (1800, _tool("Glob", {"pattern": "src/**/*.ts"})),
    (700, _tool("Read", {"file_path": f"{CWD}/src/routes/index.ts"})),
    (900, _tool("Read", {"file_path": f"{CWD}/src/db/gigs.ts"})),
    (1100, _tool("Grep", {"pattern": "paginate"})),
    (900, _tool("WebFetch", {"url": "https://docs.night.city/api/pagination"})),
    (1000, _tool("Agent", {"description": "Check the other routes", "subagent_type": "Explore"})),
    (500, _base("SubagentStart", agent_type="Explore")),
    (2400, _base("SubagentStop", agent_type="Explore")),
    (1500, _tool("Write", {"file_path": f"{CWD}/src/routes/gigs.ts", "content_len": 1840})),
    (1300, _tool("Edit", {"file_path": f"{CWD}/src/routes/index.ts", "old_string_len": 40, "new_string_len": 92})),
    (1200, _tool("Bash", {"command": "npm test -- gigs", "description": "Run the gigs tests"})),
    (
        2200,
        _base(
            "PostToolUseFailure",
            tool_name="Bash",
            tool_input={"command": "npm test -- gigs"},
            error="Exit code 1\nExpected 20 items, received 21",
        ),
    ),
    (1600, _tool("Edit", {"file_path": f"{CWD}/src/routes/gigs.ts", "old_string_len": 12, "new_string_len": 14})),
    (1000, _tool("Bash", {"command": "git push origin main", "description": "Push to main"})),
    (
        700,
        _base(
            "Notification",
            notification_type="permission_prompt",
            title="Permission needed",
            message="Claude needs your permission to use Bash",
        ),
    ),
    (5200, _done("Bash", {"command": "npm test -- gigs"}, 3100)),
    (
        1500,
        _base(
            "Stop",
            last_assistant_message=(
                "I added **GET /gigs** with cursor pagination, and 6 tests pass. "
                "The push is done."
            ),
        ),
    ),
    (9000, _base("CapriShowcase")),
]


def start_demo(host, speed: float = 1.0) -> None:
    """Post the demo events to the pet on a background thread."""

    def run() -> None:
        for delay_ms, evt in DEMO_STEPS:
            time.sleep(max(0.0, delay_ms / 1000.0 / max(0.1, speed)))
            host.enqueue_event(copy.deepcopy(evt))

    threading.Thread(target=run, name="capri-demo", daemon=True).start()
