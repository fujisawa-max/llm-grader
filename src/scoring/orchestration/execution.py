"""Small execution-mode boundary for future orchestration strategies."""

from enum import Enum

from ..adapters import LegacyCliAdapter
from ..runtime import RuntimeManagerClient
from .phased_auto import PhasedAutoOrchestrator
from .resident_serial import ResidentSerialOrchestrator


class ExecutionMode(str, Enum):
    RESIDENT_SERIAL = "resident_serial"
    PHASED_AUTO = "phased_auto"


def build_orchestrator(mode="resident_serial", adapter=None):
    """Build the requested strategy without changing the legacy CLI path."""
    mode = ExecutionMode(mode)
    if mode is ExecutionMode.RESIDENT_SERIAL:
        return ResidentSerialOrchestrator(adapter or LegacyCliAdapter())
    return PhasedAutoOrchestrator(RuntimeManagerClient(), adapter or LegacyCliAdapter())
