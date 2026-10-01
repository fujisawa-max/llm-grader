"""Deployment entrypoint: configured RuntimeManager, lazy model loading."""

import argparse
import json
import os
import signal
import threading
from pathlib import Path
import urllib.request

from .config import load_runtime_config, _expand
from .hardware import HardwareSelection
from .http_api import serve
from .manager import RuntimeManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.getenv("LLM_GRADER_RUNTIME_CONFIG", "/etc/llm-grader/runtime.json"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--healthcheck", metavar="URL")
    args = parser.parse_args()
    if args.healthcheck:
        with urllib.request.urlopen(args.healthcheck, timeout=3) as response:
            value = json.load(response)
        if not value.get("ok"):
            raise SystemExit(1)
        return
    profiles, models = load_runtime_config(args.config)
    config = _expand(json.loads(Path(args.config).read_text(encoding="utf-8")))
    binaries = config.get("runtime_backends")
    hardware = HardwareSelection(binaries) if binaries else None
    manager = RuntimeManager(profiles, hardware=hardware)
    if hardware:
        print(json.dumps({"hardware": hardware.public(), "selection": manager.statuses()}), flush=True)
    server = serve(manager, args.host, args.port, models=models)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({"service": "runtime-manager", "port": server.server_port,
                      "profiles": list(profiles), "startup_policy": "lazy"}), flush=True)
    try:
        stop.wait()
    finally:
        server.shutdown()
        manager.close()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
