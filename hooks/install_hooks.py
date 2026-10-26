#!/usr/bin/env python3
"""CLI wrapper for the Claude Code hook installer.

    python hooks/install_hooks.py              install (quiet, pythonw)
    python hooks/install_hooks.py --console    install with python.exe
    python hooks/install_hooks.py --uninstall
    python hooks/install_hooks.py --status
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from capri_demo.hookinstall import install, status, uninstall  # noqa: E402


def main() -> int:
    args = set(sys.argv[1:])
    silent = "--console" not in args
    arg = next((a for a in ("--uninstall", "--status") if a in args), "")
    try:
        if arg == "--uninstall":
            r = uninstall()
            print(
                f"Capri hooks removed from {r['file']}"
                if r["removed"]
                else f"No Capri hooks found in {r['file']}"
            )
        elif arg == "--status":
            r = status()
            if r.get("error"):
                print(f"Error: {r['error']}")
                return 1
            print(
                f"Installed ({', '.join(r['events'])}) in {r['file']}"
                if r["installed"]
                else f"Not installed ({r['file']})"
            )
        else:
            r = install(silent=silent)
            print(f"Capri hooks installed for {r['events']} events in {r['file']}")
            print(f"Command: {r['command']}")
            print("Start a new Claude Code session for them to take effect.")
    except Exception as exc:  # noqa: BLE001
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
