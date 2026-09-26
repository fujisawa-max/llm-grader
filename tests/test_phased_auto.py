import json
import tempfile
import unittest
from pathlib import Path

from scoring.adapters import StageRequest
from scoring.orchestration import PhasedAutoOrchestrator, build_orchestrator


class FakeRuntimeClient:
    def __init__(self, unhealthy=None):
        self.events = []
        self.unhealthy = unhealthy
        self.stops = []

    def ensure_running(self, runtime_id):
        self.events.append(("ensure", runtime_id))
        return {"profile": {"endpoint": f"http://runtime/{runtime_id}/v1"}}

    def health(self, runtime_id):
        self.events.append(("health", runtime_id))
        return {"ok": runtime_id != self.unhealthy}

    def stop(self, runtime_id):
        self.events.append(("stop", runtime_id))
        self.stops.append(runtime_id)
        return {"state": "stopped"}


class FakeStageAdapter:
    def __init__(self, failures=()):
        self.events = []
        self.failures = set(failures)

    def _run(self, name, request):
        self.events.append((name, request.submission, request.runtime_endpoints))
        if (name, request.submission) in self.failures:
            raise ValueError("item schema error")
        return {"stage": name, "submission": request.submission}

    def run_ricoh_phase(self, request, reuse_ocr_from=None):
        return self._run("ricoh", request)

    def run_math_ocr_phase(self, request):
        return self._run("math_ocr", request)

    def run_ornith_phase(self, request):
        return self._run("ornith", request)


class PhasedAutoTests(unittest.TestCase):
    def setUp(self):
        import scoring.orchestration.phased_auto as module

        self.module = module
        self.original = module.load_assignment
        module.load_assignment = lambda _: (
            None,
            [],
            [{"submission_id": "s1"}, {"submission_id": "s2"}, {"submission_id": "s3"}],
        )

    def tearDown(self):
        self.module.load_assignment = self.original

    def test_factory_and_stage_barriers_dynamic_endpoints_and_no_per_item_switch(self):
        runtime = FakeRuntimeClient()
        adapter = FakeStageAdapter()
        result = build_orchestrator("phased_auto", adapter=adapter)
        # Replace the factory's client with the test transport.
        result.runtime_client = runtime
        outcome = result.run(StageRequest("assignment", "run", "config.json"))
        self.assertEqual(outcome.state, "completed")
        self.assertEqual(runtime.stops, ["ocr", "math_ocr", "grader"])
        self.assertEqual(
            [e[0] for e in adapter.events], ["ricoh"] * 3 + ["math_ocr"] * 3 + ["ornith"] * 3
        )
        self.assertEqual(
            [e[0] for e in runtime.events if e[0] == "ensure"], ["ensure", "ensure", "ensure"]
        )
        # Each stage gets the manager's allocated endpoint, rather than fixed ports.
        self.assertEqual(adapter.events[0][2]["ocr"], "http://runtime/ocr/v1")
        self.assertEqual(adapter.events[3][2]["math_ocr"], "http://runtime/math_ocr/v1")
        self.assertEqual(adapter.events[6][2]["grader"], "http://runtime/grader/v1")

    def test_barrier_order_and_item_error_continuation(self):
        runtime = FakeRuntimeClient()
        adapter = FakeStageAdapter({("math_ocr", "s2")})
        outcome = PhasedAutoOrchestrator(runtime, adapter).run(StageRequest("a", "r"))
        self.assertEqual(outcome.state, "item_errors")
        self.assertEqual(len(outcome.item_errors), 1)
        # All items continue after one Math OCR item error; Ornith starts only after all.
        self.assertEqual(
            [e[0] for e in adapter.events], ["ricoh"] * 3 + ["math_ocr"] * 3 + ["ornith"] * 3
        )
        self.assertLess(
            runtime.events.index(("stop", "ocr")), runtime.events.index(("ensure", "math_ocr"))
        )
        self.assertLess(
            runtime.events.index(("stop", "math_ocr")), runtime.events.index(("ensure", "grader"))
        )

    def test_runtime_error_stops_phase_before_next_runtime(self):
        runtime = FakeRuntimeClient(unhealthy="ocr")
        outcome = PhasedAutoOrchestrator(runtime, FakeStageAdapter()).run(StageRequest("a", "r"))
        self.assertEqual(outcome.state, "runtime_failed")
        self.assertEqual([e for e in runtime.events if e[0] == "ensure"], [("ensure", "ocr")])

    def test_keep_final_runtime_running(self):
        runtime = FakeRuntimeClient()
        outcome = PhasedAutoOrchestrator(
            runtime, FakeStageAdapter(), keep_final_runtime_running=True
        ).run(StageRequest("a", "r"))
        self.assertEqual(outcome.state, "completed")
        self.assertEqual(runtime.stops, ["ocr", "math_ocr"])

    def test_pause_at_safe_boundary_does_not_start_next_runtime(self):
        runtime = FakeRuntimeClient()
        outcome = PhasedAutoOrchestrator(runtime, FakeStageAdapter(), pause_check=lambda: True).run(
            StageRequest("a", "r")
        )
        self.assertEqual(outcome.state, "paused")
        self.assertEqual([e for e in runtime.events if e[0] == "ensure"], [("ensure", "ocr")])
        self.assertEqual(runtime.stops, ["ocr"])

    def test_completed_ricoh_and_math_checkpoints_resume_at_ornith(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run" / "submissions"
            for sid in ("s1", "s2", "s3"):
                ricoh = root / sid / "ocr/ricoh"
                ricoh.mkdir(parents=True)
                (ricoh / "page-001.status.json").write_text(json.dumps({"state": "success"}))
                (ricoh / "page-001.layout.status.json").write_text(json.dumps({"state": "success"}))
                math = root / sid / "ocr/unimumer/regions/page-001/r1"
                math.mkdir(parents=True)
                (math / "transcription.status.json").write_text(json.dumps({"state": "success"}))
            runtime = FakeRuntimeClient()
            adapter = FakeStageAdapter()
            outcome = PhasedAutoOrchestrator(runtime, adapter).run(
                StageRequest("assignment", str(root.parent))
            )
            self.assertEqual(outcome.state, "completed")
            self.assertEqual(
                [e for e in runtime.events if e[0] == "ensure"], [("ensure", "grader")]
            )
            self.assertEqual([e[0] for e in adapter.events], ["ornith"] * 3)


if __name__ == "__main__":
    unittest.main()
