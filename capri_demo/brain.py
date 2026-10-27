"""Turns Claude Code hook events into things Capri says and does.

Ported from capri-desktop's src/renderer/js/brain.js, minus the Electron-only
window tracking. The host object is the Pet; every call below is a small
animation or panel message.
"""

from __future__ import annotations

import time

from . import windows

from .lines import (
    Lines,
    basename,
    clean_markdown,
    clip,
    duration,
    fmt,
    pick,
    plural,
    readable,
)

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
HACKING_TOOLS = {"Bash", "PowerShell", "WebFetch", "WebSearch", "Agent", "Task"}
WORKING_EVERY = 20


class Brain:
    def __init__(self, host, lines: Lines, lang: str):
        self.host = host
        self.lines = lines
        self.lang = lang
        self.t = lines.t
        self.sessions: dict[str, dict] = {}
        self.linked = False
        self.reply_for = None

    # ---- session bookkeeping

    def session(self, evt: dict) -> dict:
        sid = evt.get("session_id") or "default"
        s = self.sessions.get(sid)
        if s is None:
            s = {
                "id": sid,
                "project": "Claude",
                "task_start": None,
                "count": 0,
                "files": set(),
                "log": [],
                "working": False,
                "waiting": False,
            }
            self.sessions[sid] = s
        if evt.get("cwd"):
            s["project"] = basename(evt["cwd"]) or "Claude"
        if evt.get("session_title"):
            s["title"] = evt["session_title"]
        s["seen"] = time.time()
        return s

    @property
    def busy_sessions(self) -> list[dict]:
        return [s for s in self.sessions.values() if s["working"]]

    def say(self, kind: str, line: str, s: dict | None = None, **extra) -> None:
        tag = (s.get("title") or s.get("project") or "") if s else ""
        self.host.say(kind, line, tag=tag, **extra)

    # ---- events

    def handle(self, evt: dict) -> None:
        name = evt.get("hook_event_name") or ""
        if name == "CapriShowcase":
            self.host.showcase()
            return
        if name == "CapriHooksResult":
            self._on_hooks_result(evt)
            return
        if name == "CapriGuide":
            self._on_guide(evt)
            return
        if name == "CapriStatus":
            self.status()
            return
        if name == "CapriDemo":
            return

        if not self.linked and not evt.get("demo"):
            self.linked = True
            self.host.on_linked()

        s = self.session(evt)
        if name in ("UserPromptSubmit", "Stop", "Notification"):
            self.host.wake()
        else:
            self.host.attend()

        if s["waiting"] and name != "Notification":
            s["waiting"] = False
            self.host.clear_panel_kind("alert")
            if self.host.activity_mode == "alert":
                self.host.set_mode("work" if s["working"] else "idle")

        if name == "SessionStart":
            self._on_session_start(evt, s)
        elif name == "UserPromptSubmit":
            self._on_prompt(evt, s)
        elif name == "PreToolUse":
            self._on_tool(evt, s)
        elif name == "PostToolUseFailure":
            self._on_tool_failure(evt, s)
        elif name == "Notification":
            self._on_notification(evt, s)
        elif name == "Stop":
            self._on_stop(evt, s)
        elif name == "StopFailure":
            self._on_stop_failure(evt, s)
        elif name == "SubagentStart":
            self._on_subagent(evt, s, True)
        elif name == "SubagentStop":
            self._on_subagent(evt, s, False)
        elif name == "PreCompact":
            self.say("info", pick(self.t.get("compact") or []), s, hold=4.0)
        elif name == "SessionEnd":
            self._on_session_end(evt, s)

    def _on_session_start(self, evt: dict, s: dict) -> None:
        if evt.get("source") in ("clear", "compact"):
            return
        key = "resume" if evt.get("source") == "resume" else "hello"
        self.host.play_sound("hello")
        self.host.attend()
        self.host.teleport_stage()
        self.say(
            "info",
            fmt(pick(self.t.get(key) or []), {"project": s["project"]}),
            s,
            face=pick(["grin", "look"]),
            hold=5.0,
        )

    def _on_prompt(self, evt: dict, s: dict) -> None:
        s.update(
            task_start=time.time() * 1000.0,
            count=0,
            files=set(),
            log=[],
            working=True,
        )
        self.host.set_mode("work")
        hwnd = evt.get("window_hwnd") or evt.get("hwnd")
        if not hwnd:
            fg = windows.foreground()
            if fg is not None and fg.exe.lower() not in ("capri-demo.exe",):
                hwnd = fg.hwnd
        if hwnd:
            self.host.note_prompt_window(hwnd)
        prompt = " ".join(str(evt.get("prompt") or "").split())
        self.say(
            "work",
            pick(self.t.get("prompt") or []),
            s,
            quote=clip(prompt, 110),
            hold=4.5,
        )
        self.host.go_to_work()

    def _on_tool(self, evt: dict, s: dict) -> None:
        action = self.describe(evt)
        s["working"] = True
        s["count"] += 1
        s["last"] = action
        s["log"].append(action)
        del s["log"][:-8]
        if evt.get("tool_name") in EDIT_TOOLS:
            data = evt.get("tool_input") or {}
            file = data.get("file_path") or data.get("notebook_path")
            if file:
                s["files"].add(file)
        if self.host.activity_mode != "alert":
            self.host.set_mode("work")
        self.host.pulse()
        if evt.get("tool_name") in HACKING_TOOLS:
            self.host.spark()
        self.host.set_ticker(action)
        if s["count"] % WORKING_EVERY == 0:
            self.say(
                "work",
                fmt(pick(self.t.get("working") or []), {"count": s["count"]}),
                s,
                log=list(s["log"]),
                hold=4.0,
            )

    def _on_tool_failure(self, evt: dict, s: dict) -> None:
        action = dict(self.describe(evt))
        action["error"] = True
        s["log"].append(action)
        del s["log"][:-8]
        if evt.get("is_interrupt"):
            self.say(
                "info",
                pick(self.t.get("interrupted") or []),
                s,
                face="wide",
                hold=4.0,
            )
            return
        lines = [ln.strip() for ln in str(evt.get("error") or "").split("\n") if ln.strip()]
        first = next(
            (ln for ln in lines if not ln.lower().startswith("exit code")),
            lines[0] if lines else "",
        )
        self.host.hurt()
        self.host.play_sound("error")
        self.host.cutin("many", "ERR")
        self.say(
            "error",
            fmt(pick(self.t.get("error") or []), {"tool": evt.get("tool_name") or "tool"}),
            s,
            face=pick(["laugh", "wide"]),
            log=[action, {"verb": "✕", "target": clip(first, 70), "error": True}],
            hold=5.5,
        )

    def _on_notification(self, evt: dict, s: dict) -> None:
        ntype = evt.get("notification_type")
        if ntype in ("permission_prompt", "elicitation_dialog", "agent_needs_input"):
            s["waiting"] = True
            self.host.set_mode("alert")
            self.host.play_sound("alert")
            self.host.summon_cursor()
            claude = windows.find_claude_window(getattr(self.host, "prompt_hwnd", None))
            if claude is not None:
                self.host.point_at(lambda: windows.by_hwnd(claude.hwnd), label="CLAUDE")
            self.host.cutin("eyes", "ALERT")
            self.say(
                "alert",
                pick(self.t.get("permission") or []),
                s,
                quote=clip(str(evt.get("message") or ""), 180),
                face="many",
                hold=None,
            )
            return
        if ntype == "idle_prompt":
            self.host.play_sound("tick")
            self.say(
                "info",
                pick(self.t.get("waiting") or []),
                s,
                face="smug",
                hold=6.0,
            )
            return
        if evt.get("message"):
            self.say("info", str(evt["message"]), s, hold=5.0)

    def _on_stop(self, evt: dict, s: dict) -> None:
        was_working = s["working"]
        s["working"] = False
        units = self.t.get("units") or {}
        summary = " · ".join(
            part
            for part in (
                plural(s["count"], units.get("action") or ["action", "actions"], self.lang)
                if s["count"]
                else "",
                plural(len(s["files"]), units.get("file") or ["file", "files"], self.lang)
                if s["files"]
                else "",
                duration(time.time() * 1000.0 - s["task_start"], self.lang)
                if s["task_start"]
                else "",
            )
            if part
        )
        quote = clip(clean_markdown(evt.get("last_assistant_message") or ""), 150)
        reply = clip(readable(evt.get("last_assistant_message") or ""), 600)

        if not self.busy_sessions:
            self.host.clear_ticker()
            self.host.set_mode("idle")

        def done() -> None:
            self.say(
                "done",
                pick(self.t.get("done") or []),
                s,
                quote=quote,
                summary=summary,
                reply=reply if reply else "",
                hold=14.0,
            )

        if not was_working and not s["count"]:
            done()
            return

        big_job = s["count"] >= 3 or (
            s["task_start"] and time.time() * 1000.0 - s["task_start"] > 20000
        )
        if big_job:
            self.host.teleport_stage()
        self.host.cutin("laugh" if big_job else "grin", "DONE")
        self.host.celebrate(done)
        long_job = (
            s["task_start"]
            and time.time() * 1000.0 - s["task_start"] >= self.host.long_job_ms
        ) or s["count"] >= self.host.long_job_actions
        if long_job:
            self.host.earn_uplink()

    def _on_stop_failure(self, evt: dict, s: dict) -> None:
        s["working"] = False
        if not self.busy_sessions:
            self.host.clear_ticker()
            self.host.set_mode("idle")
        self.host.hurt()
        self.host.play_sound("error")
        detail = evt.get("error") or evt.get("message") or ""
        self.say(
            "error",
            pick(self.t.get("crashed") or []),
            s,
            face="wide",
            quote=clip(str(detail), 120),
            hold=9.0,
        )

    def _on_subagent(self, evt: dict, s: dict, starting: bool) -> None:
        agent = evt.get("agent_type") or "agent"
        key = "subagentStart" if starting else "subagentStop"
        line = fmt(pick(self.t.get(key) or []), {"agent": agent})
        action = {"verb": "↗" if starting else "↘", "target": line}
        s["log"].append(action)
        del s["log"][:-8]
        self.host.set_ticker(action)

    def _on_session_end(self, evt: dict, s: dict) -> None:
        self.sessions.pop(s["id"], None)
        if not self.busy_sessions:
            self.host.clear_ticker()
            self.host.set_mode("idle")
        self.say(
            "info",
            fmt(pick(self.t.get("bye") or []), {"project": s["project"]}),
            s,
            face="aside",
            hold=4.0,
        )

    def _on_hooks_result(self, evt: dict) -> None:
        if evt.get("removed"):
            line = self.t.get("hooksRemoved", "Hooks removed.")
        elif evt.get("ok"):
            line = self.t.get("hooksOk", "Hooks installed. Restart Claude Code.")
        else:
            line = fmt(
                self.t.get("hooksFail", "Could not install hooks: {error}"),
                {"error": evt.get("error", "?")},
            )
        self.say("info", line, None, face="look" if evt.get("ok") else "wide", hold=8.0)
        try:
            self.host.guide.on_hooks_result(
                bool(evt.get("ok")), str(evt.get("error") or ""), bool(evt.get("removed"))
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_guide(self, evt: dict) -> None:
        if getattr(self.host.settings, "guide_enabled", True):
            self.host.guide.start()
            return
        welcome = self.t.get("welcome") or {}
        text = evt.get("text") or welcome.get("about") or ""
        self.say("info", text, None, face="calm", hold=9.0)

    # ---- status / description

    def status(self) -> None:
        busy = sorted(self.busy_sessions, key=lambda s: s.get("seen", 0), reverse=True)
        if not busy:
            self.say(
                "idle",
                pick(self.t.get("idle") or []),
                None,
                face=pick(["calm", "smug", "aside"]),
                hold=4.0,
            )
            return
        s = busy[0]
        took = (
            duration(time.time() * 1000.0 - s["task_start"], self.lang)
            if s["task_start"]
            else "…"
        )
        extra = ""
        if len(busy) > 1:
            extra = " " + fmt(self.t.get("sessions", ""), {"count": len(busy)})
        self.say(
            "work",
            fmt(self.t.get("status", ""), {"project": s["project"], "time": took}) + extra,
            s,
            log=list(s["log"]),
            hold=6.0,
        )

    def describe(self, evt: dict) -> dict:
        name = evt.get("tool_name") or ""
        data = evt.get("tool_input") or {}
        verbs = self.t.get("verbs") or {}
        verb = verbs.get(name) or verbs.get("default") or name
        target = ""
        if name in ("Read", "Write", "Edit", "MultiEdit"):
            target = basename(data.get("file_path"))
        elif name == "NotebookEdit":
            target = basename(data.get("notebook_path"))
        elif name in ("Bash", "PowerShell"):
            target = data.get("description") or data.get("command") or ""
        elif name == "Grep":
            target = f"“{data.get('pattern')}”" if data.get("pattern") else ""
        elif name == "Glob":
            target = data.get("pattern") or ""
        elif name == "WebFetch":
            target = data.get("url") or ""
        elif name == "WebSearch":
            target = data.get("query") or ""
        elif name in ("Agent", "Task"):
            target = data.get("description") or data.get("subagent_type") or ""
        elif name == "Skill":
            target = data.get("skill") or ""
        elif name.startswith("mcp__"):
            parts = name.split("__")
            server = parts[1] if len(parts) > 1 else ""
            tool = "__".join(parts[2:]).replace("_", " ") if len(parts) > 2 else ""
            verb = "MCP"
            target = f"{server} › {tool}" if server else tool
        else:
            target = name
        return {"verb": verb, "target": clip(str(target or ""), 64)}
