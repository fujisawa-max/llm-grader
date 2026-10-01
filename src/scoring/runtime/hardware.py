"""Probe runnable llama backends at runtime, never infer usability from a device node."""

from dataclasses import asdict, dataclass, field
import os
import platform
from pathlib import Path
import re
import subprocess

BACKENDS = ("cuda", "rocm", "vulkan", "cpu")
DEVICE_LINE = re.compile(r"^\s*(\S+):\s+(.+?)\s+\((\d+) MiB,\s*(\d+) MiB free\)\s*$")


@dataclass
class Capability:
    backend: str
    binary: str
    usable: bool = False
    devices: list[dict] = field(default_factory=list)
    error_code: str | None = None
    diagnostic: str = ""

    def public(self):
        return asdict(self)


def parse_devices(text, backend):
    """Parse pinned llama.cpp --list-devices output (memory units are MiB)."""
    prefixes = {"cuda": ("CUDA",), "rocm": ("ROCm", "HIP"), "vulkan": ("Vulkan",)}
    devices = []
    for line in text.splitlines():
        match = DEVICE_LINE.match(line)
        if not match or not match[1].startswith(prefixes.get(backend, ())):
            continue
        name = match[2]
        if any(software in name.lower() for software in ("llvmpipe", "lavapipe", "swiftshader")):
            continue
        devices.append({"id": match[1], "name": name,
                        "memory_bytes": int(match[3]) * 1024 ** 2,
                        "free_memory_bytes": int(match[4]) * 1024 ** 2})
    return devices


def probe_backend(backend, binary, *, runner=subprocess.run):
    result = Capability(backend=backend, binary=binary)
    if not binary:
        result.error_code = "backend_not_installed"
        return result
    try:
        # Subprocess isolation contains driver/library crashes; version alone is insufficient for GPUs.
        completed = runner([binary, "--version" if backend == "cpu" else "--list-devices"],
                           capture_output=True, text=True, timeout=20, check=False)
        text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        result.diagnostic = text[-2000:]
        if completed.returncode:
            result.error_code = "device_permission_denied" if "permission denied" in text.lower() else "backend_load_failed"
        elif backend == "cpu":
            result.usable = True
        else:
            result.devices = parse_devices(text, backend)
            result.usable = bool(result.devices)
            result.error_code = None if result.usable else "gpu_not_accessible"
    except FileNotFoundError:
        result.error_code = "backend_not_installed"
    except PermissionError:
        result.error_code = "device_permission_denied"
    except (OSError, subprocess.SubprocessError) as exc:
        result.error_code = "backend_probe_failed"
        result.diagnostic = type(exc).__name__
    return result


class BackendUnavailable(RuntimeError):
    code = "backend_unavailable"


class HardwareSelection:
    """Operator-owned binaries, proven device enumeration, per-profile override."""
    def __init__(self, binaries, *, runner=subprocess.run, device_root=Path("/dev")):
        self.capabilities = {name: probe_backend(name, binaries.get(name, ""), runner=runner)
                             for name in BACKENDS}
        self.hints = {"nvidia_device_nodes": bool(list(device_root.glob("nvidia[0-9]*"))),
                      "drm_render_nodes": bool(list((device_root / "dri").glob("renderD*"))),
                      "kfd": (device_root / "kfd").exists(),
                      "nvidia_runtime_environment": bool(os.getenv("NVIDIA_VISIBLE_DEVICES"))}

    def select(self, override="auto"):
        if override not in (*BACKENDS, "auto"):
            raise ValueError("backend must be auto, cuda, rocm, vulkan, or cpu")
        names = BACKENDS if override == "auto" else (override,)
        for name in names:
            capability = self.capabilities[name]
            if capability.usable:
                return capability
        raise BackendUnavailable(f"Requested backend {override} is unavailable; inspect hardware diagnostics")

    def public(self):
        return {"host": probe_hardware(), "device_hints": self.hints,
                "capabilities": {key: item.public() for key, item in self.capabilities.items()}}


def selection_status(capability, requested, layers, *, fallback_reason=None):
    devices = capability.devices
    if capability.backend == "cpu" and requested == "auto" and fallback_reason is None:
        fallback_reason = "no_usable_gpu"
    vendor = {"cuda": "nvidia", "rocm": "amd", "cpu": "cpu"}.get(capability.backend, "unknown")
    if capability.backend == "vulkan":
        names = " ".join(item["name"] for item in devices).lower()
        vendor = "amd" if "amd" in names or "radeon" in names else ("nvidia" if "nvidia" in names else "unknown")
    return {"backend": capability.backend, "requested_backend": requested,
            "hardware_vendor": vendor, "gpu_count": len(devices), "devices": devices,
            "gpu_names": [item["name"] for item in devices],
            "total_vram_bytes": sum(item["memory_bytes"] for item in devices),
            "gpu_layers": layers, "selected_server_binary": capability.binary,
            "fallback_reason": fallback_reason}


def effective_gpu_layers(value, backend):
    if value == "auto":
        # Pinned llama.cpp supports native VRAM-aware fitting with -ngl auto.
        return "auto" if backend != "cpu" else 0
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < -1):
        raise ValueError("gpu_layers must be auto or an integer >= -1")
    return value


def probe_hardware():
    memory_bytes = 0
    try:
        memory_bytes = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, ValueError, OSError):
        pass
    nvidia = Path("/dev/nvidia0").exists() or bool(os.environ.get("CUDA_VISIBLE_DEVICES"))
    dri = Path("/dev/dri").exists()
    backends = ["cpu"]
    if dri:
        backends.append("vulkan")
    if nvidia:
        backends.append("cuda")
    return {"os": platform.platform(), "cpu": platform.processor(),
            "ram_bytes": memory_bytes, "gpu_device": dri or nvidia,
            "dev_dri": dri, "nvidia_device": nvidia,
            "recommended_backends": backends}
