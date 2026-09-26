"""Stage-oriented boundary around the unchanged legacy CLI engine."""

from dataclasses import dataclass
from enum import Enum


class Stage(str, Enum):
    RICOH = "ricoh"
    MATH_OCR = "math_ocr"
    ORNITH = "ornith"


@dataclass(frozen=True)
class StageRequest:
    assignment: str
    run: str
    config: str = "config/local.json"
    submission: str | None = None
    runtime_endpoints: dict[str, str] | None = None
    domain_inputs: dict | None = None


class LegacyCliAdapter:
    """Expose existing CLI stages to workers without forking grading logic.

    The adapter deliberately delegates to ``scoring.cli.run_exam``. Therefore
    checkpoint signatures, artifact paths, reuse rules, and model prompts are
    exactly the same as the command-line path.
    """

    def __init__(self, runner=None):
        if runner is None:
            from ..cli import run_exam
            runner = run_exam
        self._runner = runner

    def run(self, request, stage="all", ocr_engine="both", reuse_ocr_from=None):
        from argparse import Namespace

        if not isinstance(request, StageRequest):
            raise TypeError("requestはStageRequestが必要です")
        args = Namespace(config=request.config, assignment=request.assignment,
                         run=request.run, stage=stage, submission=request.submission,
                         ocr_engine=ocr_engine, reuse_ocr_from=reuse_ocr_from,
                         runtime_endpoints=request.runtime_endpoints or {},
                         domain_inputs=request.domain_inputs)
        return self._runner(args)

    def run_ricoh_phase(self, request, reuse_ocr_from=None):
        return self.run(request, stage="ocr", ocr_engine="ricoh", reuse_ocr_from=reuse_ocr_from)

    def run_math_ocr_phase(self, request):
        return self.run(request, stage="ocr", ocr_engine="unimumer")

    def run_ornith_phase(self, request):
        # The legacy grade stage intentionally keeps reconstruction and
        # grading together; separating their prompts would change behavior.
        return self.run(request, stage="grade", ocr_engine="both")

    def run_reconstruction_phase(self, request):
        return self.run_ornith_phase(request)

    def run_grading_phase(self, request):
        return self.run_ornith_phase(request)
