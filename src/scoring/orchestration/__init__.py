"""Execution orchestration around the legacy scoring adapter."""

from .execution import ExecutionMode, build_orchestrator
from .resident_serial import ResidentSerialOrchestrator
from .phased_auto import PhasedAutoOrchestrator, PhaseExecutionResult

__all__ = ["ExecutionMode", "ResidentSerialOrchestrator", "PhasedAutoOrchestrator",
           "PhaseExecutionResult", "build_orchestrator"]
