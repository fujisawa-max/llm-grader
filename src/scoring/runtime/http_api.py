"""Internal-only HTTP API for RuntimeManager."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class RuntimeHTTPHandler(BaseHTTPRequestHandler):
    manager = None
    models = {}

    def _send(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        try:
            if parts == ["internal", "runtimes"]:
                return self._send(200, {"runtimes": self.manager.statuses()})
            if parts == ["internal", "health"]:
                return self._send(200, {"ok": True, "runtimes": self.manager.statuses()})
            if parts == ["internal", "profiles"]:
                return self._send(200, {"profiles": [row["profile"] for row in self.manager.statuses()]})
            if parts == ["internal", "hardware"]:
                return self._send(200, self.manager.hardware.public() if self.manager.hardware else {})
            if parts == ["internal", "models"]:
                return self._send(200, {"models": self.models})
            if len(parts) != 4 or parts[:2] != ["internal", "runtimes"]:
                return self._send(404, {"error": "not found"})
            runtime_id = parts[2]
            if parts[3] == "health":
                return self._send(200, self.manager.health(runtime_id))
            if parts[3] == "status":
                return self._send(200, self.manager.status(runtime_id))
            if parts[3] == "logs":
                tail = parse_qs(parsed.query).get("tail", ["200"])[0]
                return self._send(200, self.manager.logs(runtime_id, min(1000, max(1, int(tail)))))
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError) as exc:
            self._send(404, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):  # noqa: N802
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if len(parts) != 4 or parts[:2] != ["internal", "runtimes"]:
                return self._send(404, {"error": "not found"})
            runtime_id = parts[2]
            action = parts[3]
            if action == "ensure":
                value = self.manager.ensure_running(runtime_id)
            elif action == "start":
                value = self.manager.start(runtime_id)
            elif action == "stop":
                value = self.manager.stop(runtime_id)
            elif action == "restart":
                value = self.manager.restart(runtime_id)
            else:
                return self._send(404, {"error": "not found"})
            self._send(200, value)
        except (KeyError, ValueError) as exc:
            self._send(404, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, *_args):
        return


def serve(manager, host="127.0.0.1", port=18000, *, models=None):
    """Serve only on the supplied internal bind address."""
    handler = type("ConfiguredRuntimeHandler", (RuntimeHTTPHandler,),
                   {"manager": manager, "models": models or {}})
    server = ThreadingHTTPServer((host, port), handler)
    return server
