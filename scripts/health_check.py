#!/usr/bin/env python3
"""Read-only production health checks.

This command performs no database writes and never restarts a process.  It is
safe to run from a deployment shell or a monitoring probe.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _get(url: str, timeout: float, *, expect_json: bool = True) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            if expect_json:
                body_value = json.loads(body) if body else {}
            else:
                body_value = {"content_type": response.headers.get_content_type(),
                              "bytes": len(body.encode("utf-8"))}
            return {"ok": 200 <= response.status < 300, "status": response.status,
                    "body": body_value}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}


def _pid_alive(pid_file: Path | None) -> dict:
    if pid_file is None:
        return {"configured": False, "alive": None}
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return {"configured": True, "alive": True, "pid": pid}
    except (OSError, ValueError) as exc:
        return {"configured": True, "alive": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only API and artifact health checks")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3001")
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--worker-pid-file", type=Path)
    parser.add_argument("--runtime-url", help="Optional RuntimeManager base URL")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    api = _get(args.api_url.rstrip("/") + "/health", args.timeout)
    frontend = _get(args.frontend_url, args.timeout, expect_json=False)
    artifact = args.artifact_root.resolve()
    artifact_status = {
        "path": str(artifact),
        "exists": artifact.is_dir(),
        "readable": os.access(artifact, os.R_OK),
        "writable": os.access(artifact, os.W_OK),
    }
    runtime = _get(args.runtime_url.rstrip("/") + "/v1/models", args.timeout) if args.runtime_url else {
        "configured": False
    }
    report = {
        "api": api,
        "frontend": frontend,
        "worker": _pid_alive(args.worker_pid_file),
        "runtime_manager": runtime,
        "artifact_root": artifact_status,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    api_body = api.get("body") if isinstance(api.get("body"), dict) else {}
    api_healthy = api.get("ok") and api_body.get("status") == "ok"
    ok = api_healthy and frontend.get("ok") and artifact_status["exists"] and artifact_status["readable"]
    if args.worker_pid_file:
        ok = ok and report["worker"].get("alive", False)
    if args.runtime_url:
        ok = ok and runtime.get("ok", False)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
