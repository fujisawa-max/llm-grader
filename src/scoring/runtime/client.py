"""HTTP client for the runtime-manager internal API."""

import json
import urllib.error
import urllib.request


class RuntimeManagerClient:
    def __init__(self, base_url="http://127.0.0.1:18000/internal", timeout=120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                          headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"runtime-manager HTTP {exc.code}: {exc.read().decode()[:1000]}") from exc

    def ensure_running(self, runtime_id):
        return self._call("POST", f"/runtimes/{runtime_id}/ensure")

    # Short alias used by orchestration code and future API adapters.
    ensure = ensure_running

    def start(self, runtime_id):
        return self._call("POST", f"/runtimes/{runtime_id}/start")

    def stop(self, runtime_id):
        return self._call("POST", f"/runtimes/{runtime_id}/stop")

    def health(self, runtime_id):
        return self._call("GET", f"/runtimes/{runtime_id}/health")

    def status(self, runtime_id):
        return self._call("GET", f"/runtimes/{runtime_id}/status")

    def statuses(self):
        return self._call("GET", "/runtimes").get("runtimes", [])

    def logs(self, runtime_id, tail=200):
        return self._call("GET", f"/runtimes/{runtime_id}/logs?tail={int(tail)}")
