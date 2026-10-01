"""Isolated real RuntimeManager process shared by integration/browser tests."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from scoring.runtime.client import RuntimeManagerClient

REPO = Path(__file__).resolve().parents[1]


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url, process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 400:
                    return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"isolated service not ready: {url}")


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def runtime_service(root, *, model_present=True):
    root = Path(root)
    config = json.loads((REPO / "config/runtime.deployment.json").read_text())
    model_path = root / "synthetic.gguf"
    if model_present:
        model_path.write_text("Test artifact only: not real model weights.")
    config["model_definitions"]["default_text"].update(
        model_id="synthetic-text-model", model_path=str(model_path))
    config["runtime_defaults"].update(
        server_binary=str(REPO / "tests/fixtures/runtime/llama_server_stub.py"),
        advertise_host="127.0.0.2", startup_timeout_seconds=5)
    for name, profile in config["profiles"].items():
        profile.update(port=unused_port(), log_path=str(root / f"{name}.log"))
    path = root / "runtime.json"
    path.write_text(json.dumps(config))
    port = unused_port()
    url = f"http://127.0.0.1:{port}/internal"
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    with (root / "runtime-manager.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "scoring.runtime.server", "--config",
                                    str(path), "--host", "127.0.0.1", "--port", str(port)],
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_http(url + "/health", process)
            yield RuntimeManagerClient(url), url, process
        finally:
            stop_process(process)
