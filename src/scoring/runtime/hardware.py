"""Conservative local hardware probe for runtime recommendations."""

import os
import platform
from pathlib import Path


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
