"""Resident-serial execution using the existing stage adapter."""

from dataclasses import dataclass

from ..adapters import LegacyCliAdapter, RunArtifactAdapter, StageRequest


@dataclass(frozen=True)
class ResidentSerialResult:
    """Stable orchestration result pointing at the unchanged run artifacts."""

    run: str
    artifact: RunArtifactAdapter
    stages: tuple[str, ...]
    stage_results: tuple[object, ...]


class ResidentSerialOrchestrator:
    """Run the current three-stage pipeline in resident-serial order.

    This class intentionally contains no grading or prompt logic. Each stage
    is delegated to ``LegacyCliAdapter``, which delegates to the existing CLI
    implementation and therefore retains its checkpoint/hash/reuse behavior.
    """

    stages = ("ricoh", "math_ocr", "ornith")

    def __init__(self, adapter=None):
        self.adapter = adapter or LegacyCliAdapter()

    def run(self, request: StageRequest, *, reuse_ocr_from=None):
        if not isinstance(request, StageRequest):
            raise TypeError("requestはStageRequestが必要です")
        results = (
            self.adapter.run_ricoh_phase(request, reuse_ocr_from=reuse_ocr_from),
            self.adapter.run_math_ocr_phase(request),
            self.adapter.run_ornith_phase(request),
        )
        return ResidentSerialResult(request.run, RunArtifactAdapter(request.run), self.stages, results)
