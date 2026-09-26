"""Internal-only HTTP API for RuntimeManager."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class RuntimeHTTPHandler(BaseHTTPRequestHandler):
    manager = None

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
            runtime_id = parts[2]
            if parts[3] == "health":
                return self._send(200, self.manager.health(runtime_id))
            if parts[3] == "status":
                return self._send(200, self.manager.status(runtime_id))
            if parts[3] == "logs":
                tail = parse_qs(parsed.query).get("tail", ["200"])[0]
                return self._send(200, self.manager.logs(runtime_id, int(tail)))
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError) as exc:
            self._send(404, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):  # noqa: N802
        parts = self.path.strip("/").split("/")
        try:
            runtime_id = parts[2]
            action = parts[3]
            if action == "ensure":
                value = self.manager.ensure_running(runtime_id)
            elif action == "start":
                value = self.manager.start(runtime_id)
            elif action == "stop":
                value = self.manager.stop(runtime_id)
            else:
                return self._send(404, {"error": "not found"})
            self._send(200, value)
        except (KeyError, ValueError) as exc:
            self._send(404, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, *_args):
        return


def serve(manager, host="127.0.0.1", port=18000):
    """Serve only on the supplied internal bind address."""
    RuntimeHTTPHandler.manager = manager
    server = ThreadingHTTPServer((host, port), RuntimeHTTPHandler)
    return server
