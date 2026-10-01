"""HTTP client for the runtime-manager internal API."""

import json
import urllib.error
import urllib.request
import urllib.parse

from .network import runtime_opener


class RuntimeManagerClient:
    def __init__(self, base_url="http://127.0.0.1:18000/internal", timeout=120, startup_timeout=None):
        self.base_url = base_url.rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in {"", "/internal"}):
            raise ValueError("runtime manager URL must be HTTP with /internal")
        if not parsed.path:
            self.base_url += "/internal"
        self.timeout = timeout
        self.startup_timeout = timeout if startup_timeout is None else startup_timeout
        self.opener = runtime_opener()

    def _call(self, method, path, payload=None, *, timeout=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout if timeout is None else timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"runtime-manager HTTP {exc.code}: {exc.read().decode()[:1000]}") from exc

    def ensure_running(self, runtime_id):
        return self._call("POST", f"/runtimes/{self._id(runtime_id)}/ensure", timeout=self.startup_timeout)

    # Short alias used by orchestration code and future API adapters.
    ensure = ensure_running

    def start(self, runtime_id):
        return self._call("POST", f"/runtimes/{self._id(runtime_id)}/start", timeout=self.startup_timeout)

    def stop(self, runtime_id):
        return self._call("POST", f"/runtimes/{self._id(runtime_id)}/stop")

    def restart(self, runtime_id):
        return self._call("POST", f"/runtimes/{self._id(runtime_id)}/restart", timeout=self.startup_timeout)

    def health(self, runtime_id):
        return self._call("GET", f"/runtimes/{self._id(runtime_id)}/health")

    def status(self, runtime_id):
        return self._call("GET", f"/runtimes/{self._id(runtime_id)}/status")

    def statuses(self):
        return self._call("GET", "/runtimes").get("runtimes", [])

    def logs(self, runtime_id, tail=200):
        return self._call("GET", f"/runtimes/{self._id(runtime_id)}/logs?tail={int(tail)}")

    def models(self):
        return self._call("GET", "/models").get("models", {})

    def profiles(self):
        return self._call("GET", "/profiles").get("profiles", [])

    @staticmethod
    def _id(runtime_id):
        if not runtime_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in runtime_id):
            raise ValueError("invalid runtime ID")
        return runtime_id
