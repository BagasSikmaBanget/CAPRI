# capri-demo

This is a combined modification of my own program and the program at https://github.com/mochiiwuff/capri-desktop.

A Windows desktop pet that reacts to **Claude Code** while it works.

She is built on [CAPRI](../CAPRI) (the Python/Pillow/ctypes desktop pet) and
borrows the Claude Code narration, panel, expressions, sounds and demo from
[capri-desktop](../capri-desktop-main) (the Electron version). One small Python
process, no Electron, no browser.

```
Claude Code hook  ->  hooks/capri_hook.py  ->  http://127.0.0.1:47823/event
                                                       |
                                            capri_demo/brain.py
                                                       |
                              speech panel / ticker / expressions / movement
```

## What she does

- **Real hook reactions** - session start, prompts, every tool call and result,
  failures, permission prompts, subagents, compaction, stop and session end.
  Each event becomes a short line in the selected language plus the right face.
- **Work ticker** - the current action (`Reading src/db/gigs.ts`) rides above
  her head, then fades.
- **Speech panel** - her face, the line, a quote from the session and an action
  log, drawn in the same transparent overlay window.
- **Eight expressions** - calm, smug, wide, laugh, look, many, aside, grin.
- **Stage tricks** - teleport to the middle of the screen, walk to the cursor,
  flinch on errors, victory on success, sparkles, and the chip (tuck-away).
- **The original CAPRI pet** - wandering, eye tracking, dragging, "say
  something" speech bubbles with typewriter text, sprite glitches, chat window.
- **New walk cycle** - the single `walk1.png` pose gets a small procedural bob,
  sway and lean instead of sliding across the screen.
- **Idle chatter and teleports** - random "say something" and screen blinks,
  with maximum idle timers so they still happen when walking is off. Chatter
  only starts after 30 seconds without keyboard or mouse input.
- **Merged models** - CAPRI supplies the eye strip, walk and talking art;
  capri-desktop supplies the full body and cut-out (`capri-full.png` /
  `capri-cutout.png`) used for stand, sleep, doze, sit, peek, fall, point,
  gaze, uplink, victory, zap and the other desktop acts.
- **Rare idle poses** - the seated CAPRI pose plus the two capri-desktop poses
  rotate in when she is left alone.
- **Sleep and doze** - after ten idle minutes she sleeps in the desktop body;
  twenty seconds later she dissolves down to the mask. Any click, Claude event
  or action wakes her, and the mask can never cover an active pose.
- **Synthesized cues** - capri-desktop's `voice.js` palette (teleport, done,
  alert, error, hello, blip, tick, star, land, rise, bolt, charge, possess)
  rendered to small WAVs at runtime; no audio files ship.
- **Built-in demo** - replays a realistic Claude Code session and then a
  showcase, with no Claude Code installed.
- **Five languages** - French, English, Spanish, Portuguese, Russian (`auto`
  follows Windows).

## Requirements

- Windows 10/11
- Python 3.10+ with tkinter (the python.org installer includes it)
- Pillow: `pip install -r requirements.txt`

## Run

```bat
start.bat
```

or

```bat
python main.py
python main.py --demo     REM start and replay the demo immediately
```

`start.bat` reads `CLAUDE_MODE` from `capri_config.txt`. When it is `true`
(the default), the launcher uses `pythonw` so no console window appears and
runtime output goes to `capri.log`. Set `CLAUDE_MODE = false`, or untick
**Claude mode** in the menu, to get the console back. Running `python main.py`
from a terminal always keeps that terminal.

## Controls

| Action | Result |
| --- | --- |
| Drag her | Move her anywhere |
| Left- or right-click | Tray-style menu: status, teleport, satellite, demo, help, show/hide, size, sound, wander, Claude mode, language, hooks, chat |
| `Ctrl+Alt+Q` | Quit |
| `Ctrl+Alt+R` | Reload `capri_config.txt` and art |
| `Ctrl+Alt+C` | Tuck her into the corner / bring her back |

The menu mirrors capri-desktop's tray menu: a disabled "listening on port"
line, then teleport / satellite / demo / help, show-hide, size and sound
submenus, a wander toggle, the Claude mode toggle, the language submenu, the
Claude Code hook state, and finally her CAPRI extras (status, say something,
chat). Switching language from the menu reloads her narration immediately.
The menu's **teleport** jumps her to a random spot; Claude events still use the
stage-center teleport.

The menu's **play demo** replays the scripted session. **how does it work?**
shows the current setup and the hook bridge status. **Claude mode** toggles the
quiet launcher and is saved immediately.

Rare idle poses rotate between `IDLE2_FILE` (the seated CAPRI pose) and the two
capri-desktop poses in `IDLE3_FILE` / `IDLE4_FILE`; set a missing path to
disable one. `DESKTOP_FULL_FILE` / `DESKTOP_CUTOUT_FILE` point at the merged
desktop model, and `SLEEP_AFTER` / `DOZE_AFTER` control sleep and mask timing.
`IDLE_SOUNDS` adds a soft blip or tick after roughly 30-90 seconds
of cumulative idle time, and `IDLE_SOUND_MIN` / `IDLE_SOUND_MAX` change that
window. `IDLE_TALK_CHANCE` and `IDLE_TELEPORT_CHANCE` add the random
"say something" bubble and random teleport to the idle action pool; when
wandering is enabled, walks fill the rest. Chatter also waits until the
computer has had no keyboard/mouse input for `CHATTER_IDLE_SECONDS` (default
30). `IDLE_TALK_MIN` / `IDLE_TALK_MAX` and `IDLE_TELEPORT_MIN` /
`IDLE_TELEPORT_MAX` cap how long she can go without each. `WALK_ANIM` and the
`WALK_*` keys control the procedural walk cycle.

## Connect real Claude Code

The hook script is plain Python (standard library only) and always exits 0, so
it can never block Claude Code.

Install from the pet's menu: **install Claude Code hooks**, or run:

```bat
python hooks\install_hooks.py
python hooks\install_hooks.py --console
python hooks\install_hooks.py --status
python hooks\install_hooks.py --uninstall
```

The default install uses `pythonw.exe` so hook calls stay quiet; `--console`
uses `python.exe` for debugging. This edits
`%USERPROFILE%\.claude\settings.json` (or `CLAUDE_CONFIG_DIR` if set), keeps
every existing setting, and writes a timestamped backup first. It adds one
async hook per event:

```
SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure,
Notification, Stop, StopFailure, SubagentStart, SubagentStop, PreCompact,
SessionEnd
```

The command is pinned to the Python interpreter that ran the installer, using
its `pythonw.exe` sibling for quiet hook calls. If you move the project or
reinstall Python, remove and reinstall the hooks.

By default the bridge listens on `127.0.0.1:47823`. To use another port, change
`EVENT_PORT` and reinstall the hooks with `CAPRI_PORT` set to the same value
(the hook reads `CAPRI_PORT` from the environment at run time):

```bat
set CAPRI_PORT=49000
python hooks\install_hooks.py
```

The bridge only accepts local requests without an `Origin` header, caps bodies
at 512 KB and exposes `GET /health`, `POST /event`, plus a few
`POST /debug/*` helpers for testing.

## Configuration

Everything lives in `capri_config.txt`. Relative paths resolve from the project
folder, so the app can be launched from anywhere.

| Group | Keys |
| --- | --- |
| Art | `EYELINE_FILE`, `EYE_FILE`, `IDLE_FILE`, `IDLE2_FILE`, `IDLE3_FILE`, `IDLE4_FILE`, `WALK_FILE`, `AWAY_FILE` |
| Pet | `SCALE`, `WALK_SPEED`, `WALK_ANIM`, `WALK_*`, `WANDER`, `IDLE_*`, `CHATTER_IDLE_SECONDS`, `IDLE_SOUNDS`, `EYE_*`, `GLITCH_*` |
| Launch | `CLAUDE_MODE` |
| Speech bubble | `TALK_*` (files, scale, typewriter speed, hold time) |
| Hotkeys | `QUIT_HOTKEY`, `RELOAD_HOTKEY`, `CHIP_HOTKEY` |
| Narration | `LANG`, `ENABLE_BRIDGE`, `EVENT_PORT`, `PANEL_*`, `TICKER_*`, `SOUND_ENABLED` |
| Demo | `DEMO_SPEED`, `LONG_JOB_MINUTES`, `LONG_JOB_ACTIONS` |
| Hooks | `HOOK_SCRIPT`, `FACE_DIR` |
| Chat | `CHAT_API_KEY`, `CHAT_API_BASE`, `CHAT_MODEL`, `CHAT_TIMEOUT`, `CHAT_MAX_HISTORY`, `CHAT_SYSTEM_PROMPT` |

The chat window is optional. Leave `CHAT_API_KEY` empty (or set
`CAPRI_API_KEY`) and the rest of the pet still works.

## Layout

```
capri-demo/
  main.py                 entry point
  start.bat               Windows launcher (quiet when Claude mode is on)
  capri.log               output from the quiet launcher
  capri_config.txt        all settings
  lines.json              narration data (generated from capri-desktop's lines.js)
  words.txt               "say something" lines
  capri_demo/
    win32.py              ctypes bindings, DPI, hotkeys, screen work area
    art.py                surfaces, actions, gaze face, sprite glitch, talk renderer
    sounds.py             capri-desktop cue palette, synthesized to WAV
    config.py             config parser + typed Settings
    lines.py              language resolution and text helpers
    menu_labels.py        tray-menu labels in five languages
    brain.py              hook event -> reaction mapping
    panel.py              speech panel, ticker, effects
    demo.py               scripted session
    bridge.py             local HTTP event bridge
    chat.py               chat window and right-click menu
    hookinstall.py        install/remove/status of Claude Code hooks
    pet.py                window, rendering, movement, host API
  hooks/
    capri_hook.py         stdin -> HTTP hook (stdlib only)
    install_hooks.py      CLI wrapper
  assets/
    art/ overlay/ faces/ icons/
```

## Credits

- **capri-desktop** by mochiiwuff - the Claude Code brain, panel, expressions,
  sounds, language data and demo sequence.

Both upstream licenses are included as `LICENSE-CAPRI.txt` and
`LICENSE-capri-desktop.txt`.
