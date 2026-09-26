import json
import tempfile
import unittest
from pathlib import Path

from scoring.adapters import StageRequest
from scoring.orchestration import (ExecutionMode, PhasedAutoOrchestrator,
                                    ResidentSerialOrchestrator, build_orchestrator)


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    def run_ricoh_phase(self, request, reuse_ocr_from=None):
        self.calls.append(("ricoh", request, reuse_ocr_from))
        return {"stage": "ricoh", "total": 5}

    def run_math_ocr_phase(self, request):
        self.calls.append(("math_ocr", request, None))
        return {"stage": "math_ocr", "total": 5}

    def run_ornith_phase(self, request):
        self.calls.append(("ornith", request, None))
        return {"stage": "ornith", "total": 5}


class OrchestrationTests(unittest.TestCase):
    def test_resident_serial_uses_legacy_stage_order_and_reuse_argument(self):
        adapter = RecordingAdapter()
        request = StageRequest("assignment", "run", "config.json")
        result = ResidentSerialOrchestrator(adapter).run(request, reuse_ocr_from="old-run")
        self.assertEqual([call[0] for call in adapter.calls], ["ricoh", "math_ocr", "ornith"])
        self.assertEqual(adapter.calls[0][2], "old-run")
        self.assertEqual(result.stages, ("ricoh", "math_ocr", "ornith"))
        self.assertEqual(result.run, "run")
        self.assertEqual(result.stage_results[-1], {"stage": "ornith", "total": 5})

    def test_factory_supports_both_execution_mode_boundaries(self):
        self.assertIsInstance(build_orchestrator(ExecutionMode.RESIDENT_SERIAL, RecordingAdapter()),
                              ResidentSerialOrchestrator)
        self.assertIsInstance(build_orchestrator(ExecutionMode.PHASED_AUTO, RecordingAdapter()),
                              PhasedAutoOrchestrator)

    def test_cli_and_orchestration_adapter_return_identical_stage_results(self):
        direct_calls = []

        def legacy_runner(args):
            direct_calls.append((args.stage, args.ocr_engine, args.run))
            return {"score": 5, "reconstruction": "x=4", "grading": {"score": 5}}

        from scoring.adapters import LegacyCliAdapter
        request = StageRequest("assignment", "run", "config.json")
        adapter = LegacyCliAdapter(legacy_runner)
        direct = legacy_runner(type("Args", (), {
            "stage": "ocr", "ocr_engine": "ricoh", "run": "run"})())
        via_orchestration = ResidentSerialOrchestrator(adapter).run(request)
        self.assertEqual(direct, {"score": 5, "reconstruction": "x=4", "grading": {"score": 5}})
        self.assertEqual(direct_calls[0], ("ocr", "ricoh", "run"))
        self.assertEqual(via_orchestration.stages, ("ricoh", "math_ocr", "ornith"))
        self.assertEqual([c[:2] for c in direct_calls[1:]],
                         [("ocr", "ricoh"), ("ocr", "unimumer"), ("grade", "both")])
        self.assertEqual(via_orchestration.stage_results[-1], direct)

    def test_artifact_is_not_replaced_by_orchestration(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            (run / "totals.json").write_text(json.dumps({"score": 5}), encoding="utf-8")
            adapter = RecordingAdapter()
            result = ResidentSerialOrchestrator(adapter).run(StageRequest("a", str(run)))
            self.assertEqual(result.artifact.read("totals.json")["score"], 5)

    def test_item_failure_propagates_and_does_not_start_later_stage(self):
        class FailingAdapter(RecordingAdapter):
            def run_math_ocr_phase(self, request):
                self.calls.append(("math_ocr", request, None))
                raise RuntimeError("one item failed")

        adapter = FailingAdapter()
        with self.assertRaisesRegex(RuntimeError, "one item failed"):
            ResidentSerialOrchestrator(adapter).run(StageRequest("a", "run"))
        self.assertEqual([call[0] for call in adapter.calls], ["ricoh", "math_ocr"])

    def test_rubric_change_is_a_grading_input_and_does_not_rerun_ocr(self):
        # Stage calls are independent; changing a grading-only material must
        # not invalidate the already completed Ricoh/Math OCR stages.
        class CheckpointingAdapter(RecordingAdapter):
            def __init__(self):
                super().__init__()
                self.ocr_runs = 0
                self.math_runs = 0
                self.grade_runs = 0

            def run_ricoh_phase(self, request, reuse_ocr_from=None):
                self.calls.append(("ricoh", request, reuse_ocr_from))
                if not hasattr(self, "ricoh_result"):
                    self.ocr_runs += 1
                    self.ricoh_result = {"ocr": "saved"}
                return self.ricoh_result

            def run_math_ocr_phase(self, request):
                self.calls.append(("math_ocr", request, None))
                if not hasattr(self, "math_result"):
                    self.math_runs += 1
                    self.math_result = {"math": "saved"}
                return self.math_result

            def run_ornith_phase(self, request):
                self.calls.append(("ornith", request, None))
                self.grade_runs += 1
                return {"grading": f"v{self.grade_runs}"}

        adapter = CheckpointingAdapter()
        request = StageRequest("a", "run")
        first = ResidentSerialOrchestrator(adapter).run(request)
        second = ResidentSerialOrchestrator(adapter).run(request)
        self.assertEqual(first.stage_results[:2], second.stage_results[:2])
        self.assertEqual(adapter.ocr_runs, 1)
        self.assertEqual(adapter.math_runs, 1)
        self.assertEqual(second.stage_results[-1], {"grading": "v2"})


if __name__ == "__main__":
    unittest.main()
