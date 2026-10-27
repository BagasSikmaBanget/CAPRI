"""Chat window for Capri.

One tkinter thread lives for the whole app and owns a single hidden window.
Open/close commands and network results go through queues, so nothing ever
blocks the pet's 60fps render loop and Tk is only ever touched by its own
thread.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request

from .menu_labels import LANGS, TRAY, labels as menu_labels

# --- palette --------------------------------------------------------------
BG = "#17171c"
BG_HEAD = "#1f1f27"
BG_INPUT = "#22222b"
FG = "#e6e6ee"
FG_DIM = "#8a8a99"
ACCENT = "#e0325a"
ACCENT_SOFT = "#ff5f7e"
USER_FG = "#7fdcb0"


class ChatConfig:
    def __init__(self, cfg: dict[str, str]):
        get = cfg.get
        self.api_base = get("CHAT_API_BASE", "https://api.cosmoshub.tech/v1").rstrip("/")
        self.api_key = (get("CHAT_API_KEY", "") or "").strip()
        if not self.api_key:
            self.api_key = os.environ.get("CAPRI_API_KEY", "").strip()
        if not self.api_key:
            self.api_key = os.environ.get("COSMOSHUB_API_KEY", "").strip()
        self.model = get("CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.system_prompt = get(
            "CHAT_SYSTEM_PROMPT",
            "You are Capri, a small gremlin-like desktop companion who lives on "
            "the user's screen. You are playful, a little sharp-tongued, and "
            "speak in short casual sentences. Keep replies brief - one to three "
            "sentences unless the user clearly wants detail.",
        )
        try:
            self.max_history = max(2, int(get("CHAT_MAX_HISTORY", "12")))
        except (TypeError, ValueError):
            self.max_history = 12
        try:
            self.timeout = max(5, int(get("CHAT_TIMEOUT", "60")))
        except (TypeError, ValueError):
            self.timeout = 60


def _post_chat(cc: ChatConfig, history: list[dict], text: str) -> str:
    """Blocking call to the OpenAI-compatible endpoint. Returns reply text."""
    messages = [{"role": "system", "content": cc.system_prompt}]
    messages.extend(history[-cc.max_history:])
    messages.append({"role": "user", "content": text})

    body = json.dumps(
        {"model": cc.model, "messages": messages, "stream": False}
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {cc.api_key}",
    }
    req = urllib.request.Request(
        cc.api_base + "/chat/completions", data=body, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=cc.timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        detail = _extract_error(detail) or f"HTTP {exc.code} {exc.reason}"
        raise RuntimeError(detail) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("request timed out") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bad response: {raw[:200]}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected response: {raw[:200]}") from exc

    if isinstance(content, list):  # some providers return content parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return (content or "").strip()


def _extract_error(raw: str) -> str:
    """Pull a human message out of a nested API error body if possible."""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:200].strip()
    if isinstance(data, dict):
        err = data.get("detail", data).get("error", data) if isinstance(
            data.get("detail", data), dict
        ) else data
        if isinstance(err, dict):
            msg = err.get("message") or err.get("error")
            if isinstance(msg, str):
                return msg
        if isinstance(data.get("detail"), str):
            return data["detail"]
    return raw[:200].strip()


class ChatWindow:
    """Frameless dark chat box that floats near the pet."""

    WIDTH = 360
    HEIGHT = 430

    def __init__(
        self,
        cfg: dict[str, str],
        on_state,
        anchor: tuple[int, int],
        on_menu=None,
    ):
        self.cc = ChatConfig(cfg)
        self.on_state = on_state
        self.on_menu = on_menu or (lambda _action: None)
        self.anchor = anchor
        self._choice: str | None = None
        self.history: list[dict] = []
        self.results: queue.Queue = queue.Queue()
        self.commands: queue.Queue = queue.Queue()
        self.root: tk.Tk | None = None
        self.thread: threading.Thread | None = None
        self._visible = False
        self._opened_once = False
        self._busy = False
        self._quit = False
        self._menu_lock = threading.Lock()
        self._menu_open = False
        self._menu_queued = False
        self._menu_vars: list = []
        self._submenus: list[tk.Menu] = []

    # ---- lifecycle (called from the pet thread)

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="capri-chat", daemon=True)
        self.thread.start()

    def open(self, anchor: tuple[int, int] | None = None) -> None:
        if anchor is not None:
            self.anchor = anchor
        self.start()
        self.commands.put(("show", None))

    def close(self) -> None:
        self.commands.put(("hide", None))

    def reload_config(self, cfg: dict[str, str]) -> None:
        self.commands.put(("reload", dict(cfg)))

    def popup_menu(self, x: int, y: int, state: dict | None = None) -> None:
        with self._menu_lock:
            if self._menu_open or self._menu_queued:
                return
            self._menu_queued = True
        self.start()
        self.commands.put(("menu", (int(x), int(y), dict(state or {}))))

    def quit(self) -> None:
        self.commands.put(("quit", None))
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def _run(self) -> None:
        try:
            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001
            print(f"[capri] chat window failed: {exc}")
            with self._menu_lock:
                self._menu_open = False
                self._menu_queued = False
            self.on_state(False)
            return

        self.root = root
        try:
            self._build()
            root.withdraw()
        except Exception as exc:  # noqa: BLE001
            print(f"[capri] chat window failed: {exc}")
            try:
                root.destroy()
                if tk._default_root is root:
                    tk._default_root = None
            except Exception:  # noqa: BLE001
                pass
            self.root = None
            with self._menu_lock:
                self._menu_open = False
                self._menu_queued = False
            self.on_state(False)
            return

        root.after(50, self._poll)
        try:
            root.mainloop()
        finally:
            was_visible = self._visible
            self._visible = False
            try:
                root.destroy()
                if tk._default_root is root:
                    tk._default_root = None
            except Exception:  # noqa: BLE001
                pass
            self.root = None
            self._clear_refs()
            if was_visible:
                self.on_state(False)

    def _clear_refs(self) -> None:
        """Drop every Tk object on the thread that created it."""
        self.text = None
        self.entry = None
        self.status = None
        self.send_btn = None
        self.menu = None
        self._menu_vars = []
        self._submenus = []
        self._choice = None
        self._drag = None
        with self._menu_lock:
            self._menu_open = False
            self._menu_queued = False

    # ---- build (tk thread)

    def _build(self) -> None:
        root = self.root
        root.title("capri")
        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", True)

        x, y = self._place()
        root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        shell = tk.Frame(root, bg=ACCENT, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True)

        inner = tk.Frame(shell, bg=BG, bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # header
        head = tk.Frame(inner, bg=BG_HEAD, height=34, cursor="fleur")
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(
            head, text="  capri", bg=BG_HEAD, fg=FG,
            font=("Segoe UI Semibold", 10), anchor="w",
        ).pack(side="left", fill="y")
        close = tk.Label(
            head, text="✕", bg=BG_HEAD, fg=FG_DIM,
            font=("Segoe UI", 11), width=3, cursor="hand2",
        )
        close.pack(side="right", fill="y")
        close.bind("<Button-1>", lambda _e: self._hide())
        close.bind("<Enter>", lambda _e: close.configure(fg=ACCENT_SOFT))
        close.bind("<Leave>", lambda _e: close.configure(fg=FG_DIM))

        head.bind("<Button-1>", self._drag_start)
        head.bind("<B1-Motion>", self._drag_move)

        # transcript
        body = tk.Frame(inner, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self.text = tk.Text(
            body, bg=BG, fg=FG, bd=0, highlightthickness=0,
            wrap="word", font=("Segoe UI", 10), padx=4, pady=4,
            insertbackground=FG, state="disabled", cursor="arrow",
        )
        self.text.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(body, command=self.text.yview, width=8,
                          bg=BG, troughcolor=BG, bd=0, highlightthickness=0,
                          activebackground=ACCENT, relief="flat")
        sb.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=sb.set)

        self.text.tag_configure("user", foreground=USER_FG, spacing1=8, spacing3=2)
        self.text.tag_configure("pet", foreground=FG, spacing1=8, spacing3=2)
        self.text.tag_configure("err", foreground=ACCENT_SOFT, spacing1=8, spacing3=2)
        self.text.tag_configure("dim", foreground=FG_DIM, spacing1=8, spacing3=2)

        # status line
        self.status = tk.Label(
            inner, text="", bg=BG, fg=FG_DIM, anchor="w",
            font=("Segoe UI", 8), height=1,
        )
        self.status.pack(fill="x", padx=14)

        # input
        bar = tk.Frame(inner, bg=BG)
        bar.pack(fill="x", padx=10, pady=(2, 10))

        entry_wrap = tk.Frame(bar, bg=BG_INPUT, highlightthickness=1,
                              highlightbackground=BG_INPUT,
                              highlightcolor=ACCENT)
        entry_wrap.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(
            entry_wrap, bg=BG_INPUT, fg=FG, bd=0, highlightthickness=0,
            insertbackground=FG, font=("Segoe UI", 10),
        )
        self.entry.pack(fill="x", padx=8, pady=7)
        self.entry.bind("<Return>", lambda _e: self._send())
        self.entry.bind("<Escape>", lambda _e: self._hide())

        self.send_btn = tk.Label(
            bar, text="send", bg=BG_INPUT, fg=ACCENT_SOFT,
            font=("Segoe UI Semibold", 9), padx=12, cursor="hand2",
        )
        self.send_btn.pack(side="right", padx=(6, 0), fill="y")
        self.send_btn.bind("<Button-1>", lambda _e: self._send())

        root.bind("<Escape>", lambda _e: self._hide())

        self.menu = tk.Menu(root, tearoff=0)
        self._menu_vars = []
        self._submenus = []

    def _build_menu(self, state: dict) -> None:
        """Rebuild the tray-style menu from capri-desktop before it opens."""
        menu = self.menu
        if menu is None:
            return
        menu.delete(0, "end")
        for sub in self._submenus:
            try:
                sub.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._submenus = []
        self._menu_vars = []

        lang = state.get("resolved_lang") or "en"
        t = menu_labels(lang)
        port = state.get("port", 47823)
        online = state.get("online", False)

        menu.add_command(
            label=t["online"].format(port=port) if online else t["offline"],
            state="disabled",
        )
        menu.add_separator()
        menu.add_command(label=t["teleport"], command=lambda: self._menu_choice("teleport"))
        menu.add_command(label=t["satellite"], command=lambda: self._menu_choice("satellite"))
        menu.add_command(label=t["possess"], command=lambda: self._menu_choice("possess"))
        menu.add_command(label=t["demo"], command=lambda: self._menu_choice("demo"))
        menu.add_command(label=t["help"], command=lambda: self._menu_choice("guide"))
        menu.add_command(
            label=t["show"] if state.get("away") else t["hide"],
            command=lambda: self._menu_choice("chip"),
        )
        menu.add_separator()

        size_menu = tk.Menu(menu, tearoff=0)
        self._submenus.append(size_menu)
        size_var = tk.StringVar(master=menu, value=state.get("size", "medium"))
        self._menu_vars.append(size_var)
        for name in ("small", "medium", "large"):
            size_menu.add_radiobutton(
                label=t[name],
                variable=size_var,
                value=name,
                command=lambda n=name: self._menu_choice("size-" + n),
            )
        menu.add_cascade(label=t["size"], menu=size_menu)

        sound_menu = tk.Menu(menu, tearoff=0)
        self._submenus.append(sound_menu)
        mute_var = tk.BooleanVar(master=menu, value=bool(state.get("muted")))
        self._menu_vars.append(mute_var)
        sound_menu.add_checkbutton(
            label=t["mute"],
            variable=mute_var,
            command=lambda: self._menu_choice("sound"),
        )
        menu.add_cascade(label=t["sound"], menu=sound_menu)

        wander_var = tk.BooleanVar(master=menu, value=bool(state.get("wander", True)))
        self._menu_vars.append(wander_var)
        menu.add_checkbutton(
            label=t["wander"],
            variable=wander_var,
            command=lambda: self._menu_choice("wander"),
        )

        claude_var = tk.BooleanVar(
            master=menu, value=bool(state.get("claude_mode", True))
        )
        self._menu_vars.append(claude_var)
        menu.add_checkbutton(
            label=t["claudeMode"],
            variable=claude_var,
            command=lambda: self._menu_choice("claude-mode"),
        )

        lang_menu = tk.Menu(menu, tearoff=0)
        self._submenus.append(lang_menu)
        lang_var = tk.StringVar(master=menu, value=state.get("lang", "auto"))
        self._menu_vars.append(lang_var)
        lang_menu.add_radiobutton(
            label=t["auto"],
            variable=lang_var,
            value="auto",
            command=lambda: self._menu_choice("lang-auto"),
        )
        for code in LANGS:
            lang_menu.add_radiobutton(
                label=TRAY[code]["name"],
                variable=lang_var,
                value=code,
                command=lambda c=code: self._menu_choice("lang-" + c),
            )
        menu.add_cascade(label=t["lang"], menu=lang_menu)

        menu.add_separator()
        if state.get("hooks"):
            menu.add_command(label=t["hooksOn"], state="disabled")
            menu.add_command(
                label=t["hooksRemove"],
                command=lambda: self._menu_choice("hooks-remove"),
            )
        else:
            menu.add_command(
                label=t["hooksOff"],
                command=lambda: self._menu_choice("hooks-install"),
            )

        menu.add_separator()
        menu.add_command(label=t["status"], command=lambda: self._menu_choice("status"))
        menu.add_command(label=t["say"], command=lambda: self._menu_choice("say"))
        menu.add_command(label=t["chat"], command=lambda: self._menu_choice("chat"))
        menu.add_separator()
        menu.add_command(label=t["quit"], command=lambda: self._menu_choice("quit"))

    # ---- show / hide (tk thread)

    def _show(self) -> None:
        root = self.root
        if root is None:
            return
        x, y = self._place()
        root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        root.deiconify()
        root.lift()
        self.entry.focus_force()
        self._visible = True
        if not self._opened_once:
            self._opened_once = True
            if not self.cc.api_key:
                self._append(
                    "no API key set - put CHAT_API_KEY in capri_config.txt", "err"
                )
                self._set_status("chat disabled: missing key")
            else:
                self._append("chat open. hi.", "dim")
        self.on_state(True)

    def _hide(self) -> None:
        if self.root is not None:
            try:
                self.root.withdraw()
            except Exception:  # noqa: BLE001
                pass
        if self._visible:
            self._visible = False
            self.on_state(False)

    def _popup(self, pos: tuple) -> None:
        if self.root is None or self.menu is None:
            with self._menu_lock:
                self._menu_queued = False
            return
        x, y = int(pos[0]), int(pos[1])
        state = pos[2] if len(pos) > 2 and isinstance(pos[2], dict) else {}
        with self._menu_lock:
            self._menu_queued = False
            self._menu_open = True
        try:
            self._build_menu(state)
            self.menu.tk_popup(x, y)
        finally:
            with self._menu_lock:
                self._menu_open = False
            try:
                self.menu.grab_release()
            except Exception:  # noqa: BLE001
                pass

    def _dismiss_menu(self) -> None:
        if self.menu is not None:
            try:
                self.menu.unpost()
            except Exception:  # noqa: BLE001
                pass

    def _menu_choice(self, action: str) -> None:
        print(f"[capri] menu choice: {action}")
        self._choice = action
        if self.menu is not None:
            try:
                self.menu.unpost()
            except Exception:  # noqa: BLE001
                pass

    def _place(self) -> tuple[int, int]:
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:  # noqa: BLE001
            return 100, 100
        ax, ay = self.anchor
        x = ax - self.WIDTH // 2
        y = ay - self.HEIGHT - 30
        x = max(0, min(x, sw - self.WIDTH))
        if y < 0:
            y = min(ay + 40, sh - self.HEIGHT)
        return x, y

    # ---- dragging

    def _drag_start(self, event) -> None:
        self._drag = (event.x_root, event.y_root,
                      self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event) -> None:
        if not hasattr(self, "_drag"):
            return
        sx, sy, wx, wy = self._drag
        self.root.geometry(
            f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}"
        )

    # ---- transcript

    def _append(self, text: str, tag: str) -> None:
        if self.root is None:
            return
        self.text.configure(state="normal")
        prefix = ""
        if tag == "user":
            prefix = "you  "
        elif tag == "pet":
            prefix = "her  "
        elif tag == "err":
            prefix = "!    "
        if prefix:
            self.text.insert("end", prefix, "dim")
        self.text.insert("end", text + "\n", tag)
        self.text.configure(state="disabled")
        self.text.see("end")

    def _set_status(self, text: str) -> None:
        if self.root is not None:
            self.status.configure(text=text)

    # ---- send

    def _send(self) -> None:
        if self._busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        if not self.cc.api_key:
            self._append("set CHAT_API_KEY in capri_config.txt first.", "err")
            return
        self.entry.delete(0, "end")
        self._append(text, "user")
        self._busy = True
        self.send_btn.configure(fg=FG_DIM)
        self._set_status("thinking…")

        history = list(self.history)
        threading.Thread(
            target=self._work, args=(history, text), daemon=True
        ).start()

    def _work(self, history: list[dict], text: str) -> None:
        try:
            reply = _post_chat(self.cc, history, text)
            self.results.put(("ok", text, reply))
        except Exception as exc:  # noqa: BLE001
            self.results.put(("err", text, str(exc) or exc.__class__.__name__))

    # ---- poll (tk thread)

    def _poll(self) -> None:
        if self.root is None:
            return

        try:
            while True:
                command, _arg = self.commands.get_nowait()
                if command == "show":
                    self._show()
                elif command == "hide":
                    self._hide()
                elif command == "menu":
                    self._popup(_arg)
                elif command == "reload":
                    self.cc = ChatConfig(_arg)
                elif command == "quit":
                    self._quit = True
        except queue.Empty:
            pass

        choice, self._choice = self._choice, None
        if choice is not None:
            try:
                self.on_menu(choice)
            except Exception as exc:  # noqa: BLE001
                print(f"[capri] menu action failed: {exc}")

        try:
            while True:
                kind, sent, payload = self.results.get_nowait()
                self._busy = False
                self.send_btn.configure(fg=ACCENT_SOFT)
                if kind == "ok":
                    self.history.append({"role": "user", "content": sent})
                    self.history.append({"role": "assistant", "content": payload})
                    self._append(payload or "(empty reply)", "pet")
                    self._set_status("")
                else:
                    self._append(payload, "err")
                    self._set_status("request failed")
        except queue.Empty:
            pass

        if self._quit:
            self._quit = False
            self._hide()
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                pass
            return
        if self.root is not None:
            self.root.after(80, self._poll)
