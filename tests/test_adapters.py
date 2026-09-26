import json
import tempfile
import unittest
from pathlib import Path

from scoring.adapters import LegacyCliAdapter, RunArtifactAdapter, Stage, StageRequest
from scoring.core import digest


class AdapterTests(unittest.TestCase):
    def test_stage_adapter_preserves_legacy_cli_arguments_and_result(self):
        calls = []

        def legacy(args):
            calls.append(args)
            return {"provisional_scores": {"s1": 5}}

        request = StageRequest(assignment="assignment", run="run")
        adapter = LegacyCliAdapter(legacy)
        expected = legacy(type("Args", (), {"assignment": "assignment", "run": "run",
                                             "config": "config/local.json", "stage": "ocr",
                                             "submission": None, "ocr_engine": "ricoh",
                                             "reuse_ocr_from": None})())
        actual = adapter.run_ricoh_phase(request)
        self.assertEqual(actual, expected)
        self.assertEqual(calls[-1].stage, "ocr")
        self.assertEqual(calls[-1].ocr_engine, Stage.RICOH.value)

    def test_artifact_adapter_uses_existing_json_and_hash_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            result = run / "submissions/s1/questions/q1/grading.json"
            status = run / "submissions/s1/questions/q1/grading.status.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"score": 5}), encoding="utf-8")
            status.write_text(json.dumps({"state": "success", "result_sha256": digest(result)}),
                              encoding="utf-8")
            adapter = RunArtifactAdapter(run)
            self.assertTrue(adapter.checkpoint_valid(
                "submissions/s1/questions/q1/grading.json",
                "submissions/s1/questions/q1/grading.status.json"))
            self.assertEqual(adapter.read("submissions/s1/questions/q1/grading.json")["score"], 5)


if __name__ == "__main__":
    unittest.main()
