"""The little guided tour, ported from capri-desktop's guide.js.

Scenes are plain methods driven by panel buttons instead of promises. The
panel keeps the buttons, Pet forwards the chosen id here, and the guide shows
the next scene. Pointing is done by the full-screen FX layer.
"""

from __future__ import annotations

import os

from . import hookinstall, windows


class Guide:
    def __init__(self, pet):
        self.pet = pet
        self.active = False
        self.scene = ""
        self.waiting_install = False

    # -- helpers ---------------------------------------------------------

    @property
    def t(self) -> dict:
        return self.pet.lines.t or {}

    @property
    def g(self) -> dict:
        return self.t.get("guide") or {}

    def _say(self, line, face="look", quote="", actions=None, hold=None, decode=False):
        self.pet.say(
            "info", line, face=face, quote=quote, actions=actions or [],
            hold=hold, guide=True, decode=decode,
        )

    def _ok(self, label=None):
        return [{"id": "ok", "label": label or self.g.get("ok", "Got it"), "primary": True}]

    def _menu_actions(self):
        topics = self.g.get("topics") or {}
        out = []
        for key in ("connect", "icon", "claude", "folder"):
            label = topics.get(key)
            if label:
                out.append({"id": key, "label": label, "primary": key == "connect"})
        close = topics.get("close")
        if close:
            out.append({"id": "close", "label": close, "primary": False})
        return out

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self.waiting_install = False
        self._topics()

    def finish(self) -> None:
        self.active = False
        self.scene = ""
        self.waiting_install = False
        self.pet.stop_pointing()
        self.pet.panel.clear()

    def on_action(self, aid: str) -> None:
        if not self.active:
            return
        if aid == "ok":
            self.finish()
            return
        if aid == "close":
            self.finish()
            return
        if aid == "later":
            self.finish()
            return
        if aid == "connect":
            self._connect()
        elif aid == "install":
            self._install()
        elif aid == "icon":
            self._icon()
        elif aid == "claude":
            self._claude()
        elif aid == "folder":
            self._folder()
        elif aid == "menu":
            self._topics()
        else:
            self.finish()

    def on_dismiss(self) -> None:
        if self.active:
            self.finish()

    # -- scenes ----------------------------------------------------------

    def _topics(self) -> None:
        self.scene = "topics"
        self.pet.stop_pointing()
        menu = self.g.get("menu") or {}
        self._say(
            menu.get("line", "What should I show you?"),
            face="look",
            quote=menu.get("quote", "Pick one, I'll take you there."),
            actions=self._menu_actions(),
        )

    def _icon(self) -> None:
        self.scene = "icon"
        icon = self.g.get("icon") or {}
        labels = self.g.get("labels") or {}
        rect = windows.tray_rect()
        self.pet.point_at(
            lambda: windows.tray_rect(), label=labels.get("icon", "MY ICON"),
            fade_after=7.0,
        )
        self._say(
            icon.get("line", "My icon is right there, by the clock."),
            face="smug",
            quote=icon.get("quote", "Click it: my menu. Right-clicking me does the same."),
            actions=self._ok(),
        )
        self.pet.play_sound("tick")

    def _claude(self) -> None:
        self.scene = "claude"
        c = self.g.get("claude") or {}
        win = windows.find_claude_window(getattr(self.pet, "prompt_hwnd", None))
        if win is None:
            self._say(c.get("unknown", "I don't know where it is yet."),
                      face="aside", quote=c.get("unknownHow", ""), actions=self._ok())
            return
        fg = windows.foreground()
        behind = fg is None or fg.hwnd != win.hwnd
        key = "behind" if behind else "there"
        how = "behindHow" if behind else "thereHow"
        self.pet.point_at(lambda: windows.by_hwnd(win.hwnd), label=(self.g.get("labels") or {}).get("claude", "CLAUDE"))
        self._say(c.get(key, "Claude is that window right there."),
                  face="wide", quote=c.get(how, ""), actions=self._ok())
        self.pet.play_sound("tick")

    def _folder(self) -> None:
        self.scene = "folder"
        f = self.g.get("folder") or {}
        path = hookinstall.settings_path()
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            self._say(f.get("missing", "No Claude folder on this PC."),
                      face="aside", quote=f.get("missingHow", ""), actions=self._ok())
            return
        opened = windows.open_folder(folder)
        line = f.get("line", "This is Claude's folder: {dir}").format(dir=folder)
        quote = f.get("what", "")
        if os.path.isfile(path):
            quote = (quote + " " + f.get("hook", "")).strip()
        else:
            quote = f.get("empty", quote)
        self._say(line, face="calm", quote=quote, actions=self._ok())
        if opened:
            self.pet.play_sound("blip")

    def _connect(self) -> None:
        self.scene = "connect"
        w = self.t.get("welcome") or {}
        try:
            installed = bool(hookinstall.status().get("installed"))
        except Exception:  # noqa: BLE001
            installed = False
        if installed:
            self._say(w.get("ready", "I'm plugged into Claude Code."),
                      face="grin", quote=w.get("readyHow", ""), actions=self._ok())
            return
        self._say(
            w.get("connect", "Want me to plug into Claude Code?"),
            face="smug",
            quote=w.get("about", ""),
            actions=[
                {"id": "install", "label": w.get("connectBtn", "Plug me in"), "primary": True},
                {"id": "later", "label": w.get("later", "Later")},
            ],
        )

    def _install(self) -> None:
        self.scene = "install"
        w = self.t.get("welcome") or {}
        self.waiting_install = True
        self._say(w.get("restart", "Now close Claude Code completely and open it again."),
                  face="look", actions=self._ok())
        self.pet.install_hooks(False)

    def on_hooks_result(self, ok: bool, error: str = "", removed: bool = False) -> None:
        if not self.waiting_install:
            return
        self.waiting_install = False
        w = self.t.get("welcome") or {}
        if ok and not removed:
            self._say(w.get("connected", "Plugged in!"), face="grin",
                      quote=w.get("restart", ""), actions=self._ok())
            self.pet.play_sound("rise")
        else:
            self._say(w.get("failed", "I couldn't plug in: {error}").format(error=error or "?"),
                      face="aside", actions=self._ok())

    # -- welcome ---------------------------------------------------------

    def welcome(self) -> None:
        if self.active:
            return
        self.active = True
        w = self.t.get("welcome") or {}
        self._say(
            w.get("hi", "Hey, I'm Capri."),
            face="grin",
            quote=w.get("menu", ""),
            actions=[{"id": "ok", "label": w.get("ok", "Got it"), "primary": True}],
        )
