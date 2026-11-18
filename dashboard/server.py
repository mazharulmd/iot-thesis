"""A small HTTP server for the dashboard (standard library only).

    GET  /                 the page
    GET  /api/state        the live snapshot (JSON)
    POST /api/inject       {"fault": "<type>"}                   simulation only
    POST /api/decide       {"incident": "<id>", "decision": "approve"|"reject"}
    POST /api/speed        {"speed": 10}                         simulation only
    POST /api/pause        {"paused": true}                      simulation only
    POST /api/demo         guided sequence of three faults                 simulation only
    POST /api/reset        start a fresh simulation / clear the AWS view

When the server listens on anything but localhost, every request must carry the access token
(?token=… on the page, X-Token header on the API): the page can approve high-risk actions.
"""
from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE = Path(__file__).resolve().parent / "static" / "index.html"


def make_handler(state, source, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "dc-selfheal-dashboard"

        def log_message(self, fmt, *args):            # keep the terminal quiet
            pass

        def _authorised(self) -> bool:
            if not token:
                return True
            given = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if not self._authorised():
                return self._send(403, b"forbidden: add ?token=... to the URL", "text/plain")
            if path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(200, state.snapshot())
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._authorised():
                return self._json(403, {"ok": False, "message": "forbidden"})
            path = urlparse(self.path).path
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n <= 10_000 else {}
                if path == "/api/inject":
                    msg = source.inject(str(body.get("fault", "")))
                elif path == "/api/decide":
                    msg = source.decide(str(body.get("incident", "")), str(body.get("decision", "")))
                elif path == "/api/speed":
                    source.set_speed(float(body.get("speed", 10)))
                    msg = f"speed x{source.speed:g}"
                elif path == "/api/pause":
                    source.set_paused(bool(body.get("paused")))
                    msg = "paused" if body.get("paused") else "running"
                elif path == "/api/demo":
                    msg = source.demo()
                elif path == "/api/reset":
                    source.restart()
                    msg = "reset"
                else:
                    return self._json(404, {"ok": False, "message": "not found"})
                return self._json(200, {"ok": True, "message": msg})
            except (ValueError, TypeError, AttributeError) as exc:
                return self._json(400, {"ok": False, "message": str(exc)})

    return Handler


def serve(state, source, host: str, port: int, token: str | None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(state, source, token))
    httpd.daemon_threads = True
    return httpd
