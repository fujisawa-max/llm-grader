"""Process lifecycle manager for local llama-server and external runtimes."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from functools import wraps
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

DEFAULT_RUNTIME_GENERATION = {
    "temperature": 0, "seed": 42, "top_k": 40, "top_p": 0.95,
    "min_p": 0.05, "repeat_penalty": 1.0, "max_output_tokens": 4096,
}


class RuntimeState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class RuntimeProfile:
    runtime_id: str
    runtime_type: str = "managed"
    endpoint: str = "http://127.0.0.1:8080/v1"
    model_id: str = ""
    model_path: str | None = None
    mmproj_path: str | None = None
    vision: bool = True
    expected_ftype: str | None = None
    server_binary: str = "llama-server"
    host: str = "127.0.0.1"
    advertise_host: str | None = None
    model_ref: str | None = None
    purpose: str | None = None
    port: int | None = None
    startup_timeout_seconds: float = 30.0
    stop_timeout_seconds: float = 5.0
    context_size: int | None = None
    batch_size: int | None = None
    ubatch_size: int | None = None
    gpu_layers: int | None = None
    flash_attention: str | None = None
    additional_args: list[str] = field(default_factory=list)
    log_path: str | None = None
    model_sha256: str | None = None
    mmproj_sha256: str | None = None
    llama_version: str | None = None
    generation: dict = field(default_factory=dict)

    def __post_init__(self):
        self.generation = {**DEFAULT_RUNTIME_GENERATION, **self.generation}

    @classmethod
    def from_mapping(cls, runtime_id, value):
        value = dict(value)
        value.setdefault("runtime_id", runtime_id)
        if "base_url" in value and "endpoint" not in value:
            value["endpoint"] = value.pop("base_url")
        profile = cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})
        profile.generation = {**DEFAULT_RUNTIME_GENERATION, **profile.generation}
        return profile

    def endpoint_root(self):
        return self.endpoint.rstrip("/")


@dataclass
class RuntimeRecord:
    profile: RuntimeProfile
    state: RuntimeState = RuntimeState.STOPPED
    pid: int | None = None
    allocated_port: int | None = None
    started_at: float | None = None
    stopped_at: float | None = None
    last_health_check: float | None = None
    error: str | None = None
    command: list[str] | None = None
    log_handle: object | None = field(default=None, repr=False)
    process: subprocess.Popen | None = field(default=None, repr=False)
    lock: object = field(default_factory=threading.RLock, repr=False)

    def public(self):
        result = {"profile": asdict(self.profile), "state": self.state.value,
                  "pid": self.pid, "allocated_port": self.allocated_port,
                  "started_at": self.started_at, "stopped_at": self.stopped_at,
                  "last_health_check": self.last_health_check, "error": self.error,
                  "command": self.command}
        result["state"] = self.state.value
        return result


class PortAllocator:
    """Process-local port allocator with a lock and bind check."""

    def __init__(self):
        self._lock = threading.Lock()
        self._allocated = set()

    def acquire(self, requested=None, host="127.0.0.1"):
        with self._lock:
            candidates = [requested] if requested else list(range(18080, 18180))
            for port in candidates:
                if port is None or port in self._allocated:
                    continue
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind((host, port))
                except OSError:
                    continue
                finally:
                    probe.close()
                self._allocated.add(port)
                return port
        raise RuntimeError("利用可能なportがありません")

    def release(self, port):
        with self._lock:
            self._allocated.discard(port)


def _synchronized(method):
    @wraps(method)
    def locked(self, runtime_id, *args, **kwargs):
        with self._record(runtime_id).lock:
            return method(self, runtime_id, *args, **kwargs)
    return locked


class RuntimeManager:
    """Manage runtime processes without any grading responsibilities."""

    def __init__(self, profiles=None, *, port_allocator=None, launcher=None,
                 request=None, clock=time.monotonic):
        self.records = {}
        self.ports = port_allocator or PortAllocator()
        self.launcher = launcher or self._launch
        self.request = request or self._request
        self.clock = clock
        for runtime_id, profile in (profiles or {}).items():
            self.register(profile if isinstance(profile, RuntimeProfile)
                          else RuntimeProfile.from_mapping(runtime_id, profile))

    def register(self, profile):
        if not profile.runtime_id:
            raise ValueError("runtime_idが必要です")
        if profile.runtime_type not in {"managed", "external"}:
            raise ValueError("runtime_typeはmanagedまたはexternalです")
        if profile.port is not None and not 1 <= profile.port <= 65535:
            raise ValueError("portが不正です")
        self.records[profile.runtime_id] = RuntimeRecord(profile)

    @_synchronized
    def status(self, runtime_id):
        record = self._record(runtime_id)
        self._observe_process(record)
        result = record.public()
        unavailable = self._missing_artifact(record.profile)
        result["availability"] = unavailable or "available"
        result["error_code"] = unavailable
        if unavailable and record.process is None:
            result["state"] = "unavailable"
        return result

    def statuses(self):
        return [self.status(runtime_id) for runtime_id in sorted(self.records)]

    @_synchronized
    def ensure_running(self, runtime_id):
        record = self._record(runtime_id)
        self._observe_process(record)
        if record.profile.runtime_type == "external":
            result = self.health(runtime_id)
            if not result["ok"]:
                raise RuntimeError(result.get("error") or "external runtime is unhealthy")
            return result
        if record.state == RuntimeState.READY:
            return record.public()
        return self.start(runtime_id)

    @_synchronized
    def start(self, runtime_id):
        record = self._record(runtime_id)
        profile = record.profile
        if profile.runtime_type == "external":
            # External processes are never started or stopped by this manager.
            return self.health(runtime_id)
        if record.state in {RuntimeState.STARTING, RuntimeState.READY}:
            return self.ensure_running(runtime_id)
        try:
            self._validate_model(profile)
            if profile.llama_version is None:
                profile.llama_version = self._binary_version(profile.server_binary)
            port = self.ports.acquire(profile.port, profile.host)
            record.allocated_port = port
            endpoint_host = profile.advertise_host or profile.host
            endpoint = f"http://{endpoint_host}:{port}/v1"
            command = self.build_command(profile, port)
            log_path = Path(profile.log_path or f"runtime-{runtime_id}.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            record.log_handle = log_handle
            record.state = RuntimeState.STARTING
            record.error = None
            record.command = command
            process = self.launcher(command, log_handle)
            record.process = process
            record.pid = process.pid
            record.started_at = self.clock()
            profile.endpoint = endpoint
            deadline = self.clock() + profile.startup_timeout_seconds
            while self.clock() < deadline:
                self._observe_process(record)
                if record.state == RuntimeState.ERROR:
                    raise RuntimeError(record.error or "runtime processが終了しました")
                try:
                    self._health_record(record)
                    record.state = RuntimeState.READY
                    return record.public()
                except (OSError, RuntimeError, ValueError):
                    time.sleep(0.05)
            record.state = RuntimeState.UNHEALTHY
            record.error = "startup timeout"
            self._terminate(record, force=True)
            raise TimeoutError(f"runtime起動timeout: {runtime_id}")
        except Exception as exc:
            self._terminate(record, force=True)
            record.error = str(exc)
            if record.state != RuntimeState.UNHEALTHY:
                record.state = RuntimeState.ERROR
            if record.allocated_port:
                self.ports.release(record.allocated_port)
                record.allocated_port = None
            raise

    @_synchronized
    def stop(self, runtime_id):
        record = self._record(runtime_id)
        if record.profile.runtime_type == "external":
            return {**record.public(), "stop_ignored": True}
        if record.process is None:
            self._terminate(record, force=False)
            record.state = RuntimeState.STOPPED
            return record.public()
        record.state = RuntimeState.STOPPING
        self._terminate(record, force=False)
        record.state = RuntimeState.STOPPED
        record.stopped_at = self.clock()
        return record.public()

    @_synchronized
    def restart(self, runtime_id):
        if self._record(runtime_id).profile.runtime_type == "external":
            return self.ensure_running(runtime_id)
        self.stop(runtime_id)
        return self.start(runtime_id)

    def close(self):
        for runtime_id in list(self.records):
            self.stop(runtime_id)

    @_synchronized
    def health(self, runtime_id):
        record = self._record(runtime_id)
        try:
            self._health_record(record)
            if record.profile.runtime_type == "managed":
                record.state = RuntimeState.READY
            return {"ok": True, **record.public()}
        except Exception as exc:
            record.last_health_check = self.clock()
            if record.profile.runtime_type == "managed" and record.process is not None:
                record.state = RuntimeState.UNHEALTHY
            return {"ok": False, "error": str(exc), **record.public()}

    def logs(self, runtime_id, tail=200):
        record = self._record(runtime_id)
        path = Path(record.profile.log_path or f"runtime-{runtime_id}.log")
        if not path.exists():
            return {"runtime_id": runtime_id, "lines": []}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"runtime_id": runtime_id, "path": str(path), "lines": lines[-tail:]}

    @staticmethod
    def build_command(profile, port):
        if not profile.model_path:
            raise ValueError("managed runtimeのmodel_pathが必要です")
        command = [profile.server_binary, "-m", profile.model_path,
                   "--host", profile.host, "--port", str(port)]
        # Keep the OpenAI model identity stable across dynamically allocated ports.
        if profile.model_id:
            command.extend(["--alias", profile.model_id])
        if profile.mmproj_path:
            command.extend(["--mmproj", profile.mmproj_path])
        options = (("-c", profile.context_size), ("-b", profile.batch_size),
                   ("-ub", profile.ubatch_size), ("-ngl", profile.gpu_layers))
        for flag, value in options:
            if value is not None:
                command.extend([flag, str(value)])
        if profile.flash_attention:
            command.extend(["-fa", str(profile.flash_attention)])
        command.extend(profile.additional_args)
        return command

    @staticmethod
    def _binary_version(binary):
        try:
            value = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                   timeout=5, check=False)
            text = (value.stdout or value.stderr).strip()
            return text or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    @staticmethod
    def _missing_artifact(profile):
        if profile.runtime_type != "managed":
            return None
        if not profile.model_path or not Path(profile.model_path).is_file():
            return "model_missing"
        if profile.vision and (not profile.mmproj_path or not Path(profile.mmproj_path).is_file()):
            return "mmproj_missing"
        return None

    def _validate_model(self, profile):
        if not profile.model_path or not Path(profile.model_path).is_file():
            raise ValueError("model pathが存在しません")
        if profile.vision and (not profile.mmproj_path or not Path(profile.mmproj_path).is_file()):
            raise ValueError("vision modelにはmmprojが必要です")

    def _health_record(self, record):
        profile = record.profile
        base = profile.endpoint_root()
        if profile.runtime_type == "managed" and record.allocated_port is not None:
            # The manager probes locally; consumers receive the advertised Docker host.
            host = "127.0.0.1" if profile.host == "0.0.0.0" else profile.host
            base = f"http://{host}:{record.allocated_port}/v1"
        health = self.request(base.removesuffix("/v1") + "/health")
        if isinstance(health, dict) and health.get("status") not in {None, "ok", "ready"}:
            raise RuntimeError(f"health status={health.get('status')}")
        models = self.request(base + "/models")
        ids = {item.get("id") for item in models.get("data", [])}
        if profile.model_id and profile.model_id not in ids:
            raise ValueError(f"model ID不一致: {profile.model_id}")
        props = self.request(base.removesuffix("/v1") + "/props")
        if profile.expected_ftype and props.get("model_ftype") != profile.expected_ftype:
            raise ValueError("ftype不一致")
        if profile.vision and not props.get("modalities", {}).get("vision", False):
            raise ValueError("vision capabilityがありません")
        record.last_health_check = self.clock()
        return {"health": health, "models": models, "props": props}

    def _observe_process(self, record):
        if record.process is not None and record.process.poll() is not None:
            if record.state not in {RuntimeState.STOPPED, RuntimeState.STOPPING}:
                record.state = RuntimeState.ERROR
                record.error = f"process exited with code {record.process.returncode}"
            record.process = None
            record.pid = None
            if record.log_handle is not None:
                record.log_handle.close()
                record.log_handle = None
            if record.allocated_port:
                self.ports.release(record.allocated_port)
                record.allocated_port = None

    def _terminate(self, record, force):
        process = record.process
        if process is not None:
            if force:
                process.kill()
            else:
                process.terminate()
            try:
                process.wait(timeout=record.profile.stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        record.process = None
        record.pid = None
        if record.log_handle is not None:
            record.log_handle.close()
            record.log_handle = None
        if record.allocated_port:
            self.ports.release(record.allocated_port)
            record.allocated_port = None

    @staticmethod
    def _launch(command, log_handle):
        return subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT,
                                start_new_session=True)

    @staticmethod
    def _request(url):
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.load(response)

    def _record(self, runtime_id):
        if runtime_id not in self.records:
            raise KeyError(f"runtimeがありません: {runtime_id}")
        return self.records[runtime_id]


def profiles_from_runtime_config(config):
    """Translate the legacy ``runtime.example.json`` models mapping."""
    profiles = {}
    for runtime_id, settings in config.get("models", {}).items():
        value = dict(settings)
        # The legacy file describes already-running local endpoints.  A
        # profile with a model_path is explicitly managed; otherwise it is
        # treated as external and can be health-checked without process
        # control.
        value.setdefault("runtime_type", "managed" if value.get("model_path") else "external")
        profiles[runtime_id] = RuntimeProfile.from_mapping(runtime_id, value)
    return profiles
