#!/usr/bin/env python3
"""Fail-closed operator launcher for the independent validation Compose only."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "llm-grading-validation"
MOUNTS = {
    "/work": "VALIDATION_WORK_ROOT", "/inputs/allowlist.json": "VALIDATION_ALLOWLIST",
    "/source/question_import": "VALIDATION_QUESTION_ROOT",
    "/source/answer_import": "VALIDATION_ANSWER_ROOT",
    "/source/postgres": "VALIDATION_PG_SOCKET_ROOT",
    "/run/secrets/readonly_database_url": "VALIDATION_READONLY_URL_FILE",
}


def private_paths(env):
    paths = {}
    for target, key in MOUNTS.items():
        path = Path(env.get(key, ""))
        if not path.is_absolute() or ".." in path.parts or len(path.parts) < 3:
            raise ValueError("VALIDATION_EXPLICIT_PATH_REQUIRED")
        if any(part.is_symlink() for part in [path, *path.parents]) or not path.exists():
            raise ValueError("VALIDATION_EXISTING_NONSYMLINK_PATH_REQUIRED")
        paths[target] = path
    work = paths["/work"]
    if not work.is_dir() or work.stat().st_mode & 0o077:
        raise ValueError("VALIDATION_PRIVATE_WORK_ROOT_REQUIRED")
    # Never permit the output to overlap a production source or operator input.
    for target, path in paths.items():
        if target != "/work" and (path == work or path in work.parents or work in path.parents):
            raise ValueError("VALIDATION_SOURCE_OUTPUT_OVERLAP")
    for target in ("/inputs/allowlist.json", "/run/secrets/readonly_database_url"):
        if not paths[target].is_file() or paths[target].stat().st_mode & 0o077:
            raise ValueError("VALIDATION_PRIVATE_INPUT_REQUIRED")
    for target in ("/source/question_import", "/source/answer_import", "/source/postgres"):
        if not paths[target].is_dir():
            raise ValueError("VALIDATION_SOURCE_DIRECTORY_REQUIRED")
    return paths


def validate_config(config, env):
    paths = private_paths(env)
    if config.get("name") != PROJECT or set(config.get("services", {})) != {"export", "acceptance"}:
        raise ValueError("VALIDATION_PROJECT_BOUNDARY_INVALID")
    if config.get("networks") or config.get("volumes") or config.get("secrets") or config.get("configs"):
        raise ValueError("VALIDATION_SHARED_RESOURCE_FORBIDDEN")
    allowed = {"image", "build", "network_mode", "read_only", "cap_drop", "security_opt",
               "user", "tmpfs", "restart", "command", "profiles", "volumes", "runtime"}
    for name, service in config["services"].items():
        if set(service) - allowed:
            raise ValueError("VALIDATION_UNEXPECTED_SERVICE_CONFIGURATION")
        expected = {
            "image": "llm-grading-validation:1d", "network_mode": "none", "runtime": "runc",
            "read_only": True, "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"], "restart": "no",
            "command": ["help"], "profiles": [name],
            "tmpfs": ["/tmp:rw,noexec,nosuid,size=64m"],
            "user": f"{env.get('VALIDATION_UID', '65534')}:{env.get('VALIDATION_GID', '65534')}",
        }
        if service.get("build") != {"context": str(ROOT), "dockerfile": "Dockerfile.validation"}:
            raise ValueError("VALIDATION_BUILD_BOUNDARY_INVALID")
        if any(service.get(key) != value for key, value in expected.items()):
            raise ValueError("VALIDATION_CONTAINER_ISOLATION_INVALID")
        if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", service["user"]):
            raise ValueError("VALIDATION_NONROOT_USER_REQUIRED")
        targets = set(paths) if name == "export" else {"/work", "/inputs/allowlist.json"}
        mounts = service.get("volumes", [])
        if len(mounts) != len(targets) or {v.get("target") for v in mounts} != targets:
            raise ValueError("VALIDATION_MOUNT_BOUNDARY_INVALID")
        for mount in mounts:
            if (set(mount) - {"type", "source", "target", "read_only", "bind"}
                    or mount.get("type") != "bind"
                    or mount.get("source") != str(paths[mount["target"]])
                    or mount.get("read_only", False) != (mount["target"] != "/work")
                    or mount.get("bind", {}).get("create_host_path", False)):
                raise ValueError("VALIDATION_MOUNT_BOUNDARY_INVALID")
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["config", "build", "export", "import", "acceptance"])
    parser.add_argument("--approved-export", action="store_true")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "HOME"} or key in set(MOUNTS.values()) | {"VALIDATION_UID", "VALIDATION_GID"}}
    private_paths(env)
    if args.operation == "export" and not args.approved_export:
        parser.error("explicit operator export approval required")
    if args.operation in {"import", "acceptance"} and not re.fullmatch(r"[a-f0-9]{64}", args.manifest_sha256 or ""):
        parser.error("trusted manifest SHA required")
    command = ["docker", "compose", "--env-file", "/dev/null", "--project-directory", str(ROOT),
               "--project-name", PROJECT, "-f", str(ROOT / "compose.validation.yaml"),
               "--profile", "export", "--profile", "acceptance"]
    result = subprocess.run(command + ["config", "--format", "json"], env=env,
                            check=True, capture_output=True, text=True)
    validate_config(json.loads(result.stdout), env)
    if args.operation == "config":
        print("VALIDATION_ISOLATION_CONFIG_OK")
        return
    if args.operation == "build":
        invocation = ["build", "acceptance"]
    else:
        service = "export" if args.operation == "export" else "acceptance"
        invocation = ["run", "--rm", "--no-deps", "--pull", "never", service, args.operation]
        if args.operation == "export":
            invocation += ["--approved-export"]
        else:
            invocation += ["--manifest-sha256", args.manifest_sha256]
    raise SystemExit(subprocess.run(command + invocation, env=env, check=False).returncode)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        safe = str(exc) if re.fullmatch(r"VALIDATION_[A-Z_]+", str(exc)) else "VALIDATION_LAUNCH_FAILED"
        raise SystemExit(safe)
