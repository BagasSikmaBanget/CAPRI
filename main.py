"""capri-demo entry point.

    python main.py
    python main.py --demo      # start and immediately replay the fake session
"""

from __future__ import annotations

import os
import sys

from capri_demo.config import read_config
from capri_demo.pet import CONFIG_PATH, Pet
from capri_demo.win32 import set_dpi_aware


def _stream_ok(stream) -> bool:
    if stream is None:
        return False
    try:
        stream.write("")
        stream.flush()
        return True
    except Exception:  # noqa: BLE001
        return False


def _ensure_streams() -> None:
    if _stream_ok(sys.stdout) and _stream_ok(sys.stderr):
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capri.log")
    try:
        log = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if not _stream_ok(sys.stdout):
        sys.stdout = log
    if not _stream_ok(sys.stderr):
        sys.stderr = log


def main() -> int:
    _ensure_streams()
    set_dpi_aware()
    cfg = read_config(CONFIG_PATH)
    if not cfg:
        print(f"[capri] no config found at {CONFIG_PATH}, using built-in defaults")
    try:
        pet = Pet(cfg)
    except FileNotFoundError as exc:
        print(f"[capri] {exc}")
        return 1
    except OSError as exc:
        print(f"[capri] could not create the pet window: {exc}")
        return 1
    print("[capri] running. Ctrl+Alt+Q quits, Ctrl+Alt+R reloads, Ctrl+Alt+C tucks her away.")
    if pet.bridge is not None:
        print(f"[capri] Claude Code hook bridge: http://127.0.0.1:{pet.settings.event_port}")
    else:
        print("[capri] hook bridge disabled or unavailable; the demo still works.")
    if "--demo" in sys.argv:
        pet.start_demo()
    try:
        pet.run()
    except KeyboardInterrupt:
        pet.running = False
        pet.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
