"""Local HTTP bridge: Claude Code hooks POST events to 127.0.0.1.

Ported from capri-desktop's src/main/bridge.js. Only the loopback interface is
used, browser requests (which carry an Origin header) are refused, and bodies
are capped so a rogue page cannot puppet the pet or exhaust memory.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 512 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "CapriBridge/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - silence the default stderr log
        pass

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("bad content length")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data

    def do_GET(self):  # noqa: N802
        if self.headers.get("Origin"):
            return self._send(403, {"ok": False})
        if self.path.split("?")[0] == "/health":
            return self._send(
                200, {"ok": True, "name": "capri-demo", "pid": self.server.pid}
            )
        return self._send(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        if self.headers.get("Origin"):
            return self._send(403, {"ok": False})
        path = self.path.split("?")[0]
        try:
            evt = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"ok": False, "error": str(exc)})

        if path == "/event":
            if not isinstance(evt.get("hook_event_name"), str):
                return self._send(400, {"ok": False, "error": "missing hook_event_name"})
            self.server.on_event(evt)
            return self._send(200, {"ok": True})

        if path.startswith("/debug/") and self.server.on_debug is not None:
            try:
                result = self.server.on_debug(path[7:], evt)
            except Exception as exc:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": str(exc)})
            return self._send(200, {"ok": True, "result": result})

        return self._send(404, {"ok": False})


class EventBridge:
    def __init__(self, port: int, on_event, on_debug=None):
        self.port = int(port)
        self.on_event = on_event
        self.on_debug = on_debug
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except OSError as exc:
            print(f"[capri] bridge: port {self.port} unavailable ({exc})")
            return False
        server.daemon_threads = True
        server.on_event = self.on_event
        server.on_debug = self.on_debug
        server.pid = os.getpid()
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="capri-bridge", daemon=True
        )
        self._thread.start()
        print(f"[capri] bridge listening on 127.0.0.1:{self.port}")
        return True

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
        self._thread = None
