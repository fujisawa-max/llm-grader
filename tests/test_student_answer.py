import json
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from pathlib import Path

from scoring.db import create_session_factory, init_database
from scoring.api.app import create_app
from scoring.grading_mapping import GradingInputAssembler
from scoring.student_answer import (
    StudentAnswerError,
    StudentAnswerExtractionPipeline,
    StudentAnswerReconstructionInputBuilder,
    validate_reconstruction_output,
)
from tests.mapping_fixture import create_mapping_fixture
from tests.http_auth import authenticate_fixture


class StudentAnswerReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine, self.factory = create_session_factory("sqlite:///:memory:")
        init_database(self.engine)
        self.session = self.factory()
        self.fixture = create_mapping_fixture(self.session, self.root)
        # Reconstruction is permitted with synthetic ModelAnswer/Rubric rows,
        # but the builder must never read or expose them.
        self.session.flush()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_input_uses_h2g_identity_and_has_no_grading_fields_or_secrets(self):
        q = self.fixture["questions"]["A1"]
        value = StudentAnswerReconstructionInputBuilder(
            self.session, self.fixture["submission"].id, root=self.root
        ).build(q.id).as_dict()
        serialized = json.dumps(value, ensure_ascii=False)
        self.assertNotIn("MODEL_TOKEN_A1", serialized)
        self.assertNotIn("RUBRIC_TOKEN_A1", serialized)
        self.assertNotIn("max_points", serialized)
        self.assertEqual(value["question"]["question_id"], q.id)
        self.assertIn("PARENT_TOKEN_A", value["question"]["context"]["effective_text"])
        self.assertEqual(value["source_answer"]["resolution_method"], "test_question_id")
        with self.assertRaisesRegex(StudentAnswerError, "STRUCTURAL"):
            StudentAnswerReconstructionInputBuilder(
                self.session, self.fixture["submission"].id, root=self.root
            ).build(self.fixture["parents"]["A"].id)

    def test_pipeline_preserves_wrong_answer_and_formula_evidence(self):
        q = self.fixture["questions"]["A1"]
        calls = {"ricoh": [], "uni": [], "ornith": []}

        def ricoh(path, question_id):
            calls["ricoh"].append(path)
            page_id = f"STUDENT_TOKEN_{path.stem}"
            return {"student_text": "2 + 2 = 5", "question_id": question_id}, {
                "text_blocks": [{"text": "2 + 2 = 5"}],
                "formula_regions": [{"region_id": f"answer-formula-{path.stem}", "question_id": question_id, "page_id": page_id,
                                      "bbox": [0.01, 0.01, 0.8, 0.5],
                                      "coordinate_space": "normalized"}],
                "reading_order": [0],
            }

        def unimumer(crop, region):
            calls["uni"].append(crop)
            return {"recognized": r"x^3 = -8"}, {"transcription": r"x^3 = -8", "region_id": region["region_id"]}

        def ornith(payload):
            calls["ornith"].append(payload)
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("MODEL_TOKEN", serialized)
            self.assertNotIn("RUBRIC_TOKEN", serialized)
            self.assertNotIn("max_points", serialized)
            self.assertIn("2 + 2 = 5", serialized)
            return {"question_id": payload["question"]["question_id"], "answer_text": "2 + 2 = 5\nx^3 = -8",
                    "segments": [{"type": "text", "transcription": "2 + 2 = 5",
                                  "source_refs": ["STUDENT_TOKEN_A1"]}],
                    "uncertainties": [], "source_refs": ["STUDENT_TOKEN_A1"]}

        run, outputs = StudentAnswerExtractionPipeline(self.session, artifact_root=self.root).run(
            self.fixture["submission"].id, ricoh=ricoh, unimumer=unimumer,
            ornith_reconstruction=ornith, config={"fixture": "h3a"})
        self.session.commit()
        self.assertEqual(run.status, "completed")
        self.assertEqual(outputs[0]["answer_text"], "2 + 2 = 5\nx^3 = -8")
        self.assertEqual(len(calls["ricoh"]), 3)
        self.assertEqual(len(calls["uni"]), 3)
        self.assertEqual(len(calls["ornith"]), 3)
        from scoring.db.models import StudentAnswerReconstruction
        record = self.session.query(StudentAnswerReconstruction).filter_by(question_id=q.id).one()
        self.assertEqual(record.status, "COMPLETE")
        self.assertTrue((self.root / "student-answer").exists())
        bundle = GradingInputAssembler(self.session, self.fixture["test"].id,
                                       root=self.root, allowed_roots=[self.root]).evaluate(self.fixture["submission"].id)
        row = next(row for row in bundle["questions"] if row["question_id"] == q.id)
        self.assertEqual(row["bundle"]["student_answer"]["source"], "RECONSTRUCTED_FROM_DOCUMENT")
        self.assertIn("2 + 2 = 5", row["bundle"]["student_answer"]["answer_text"])

    def test_source_tamper_and_invalid_output_are_blocked(self):
        path = self.root / "submission.json"
        path.write_text(path.read_text() + " ", encoding="utf-8")
        with self.assertRaisesRegex(StudentAnswerError, "HASH_MISMATCH"):
            StudentAnswerReconstructionInputBuilder(
                self.session, self.fixture["submission"].id, root=self.root
            )
        with self.assertRaisesRegex(StudentAnswerError, "INVALID"):
            validate_reconstruction_output({"question_id": "q", "answer_text": 1}, "q")

    def test_uncertainty_sets_review_required_and_hash_is_deterministic(self):
        first = validate_reconstruction_output({"question_id": "q", "answer_text": "?",
            "segments": [], "uncertainties": [{"location": "line 1", "reason": "unreadable"}]}, "q")
        second = validate_reconstruction_output({"question_id": "q", "answer_text": "?",
            "segments": [], "uncertainties": [{"location": "line 1", "reason": "unreadable"}]}, "q")
        self.assertEqual(first["status"], "REVIEW_REQUIRED")
        self.assertEqual(first["output_sha256"], second["output_sha256"])

    def test_completed_run_is_reused_without_model_calls(self):
        calls = []

        def ricoh(path, question_id):
            calls.append("ricoh")
            return {}, {"text_blocks": [], "formula_regions": [], "reading_order": []}

        def unimumer(*args):
            calls.append("uni")
            return {}, {}

        def ornith(payload):
            calls.append("ornith")
            return {"question_id": payload["question"]["question_id"], "answer_text": "blank",
                    "segments": [], "uncertainties": [], "source_refs": []}

        pipeline = StudentAnswerExtractionPipeline(self.session, artifact_root=self.root)
        first, _ = pipeline.run(self.fixture["submission"].id, ricoh=ricoh, unimumer=unimumer,
                                ornith_reconstruction=ornith, config={"reuse": True})
        count = len(calls)
        second, _ = pipeline.run(self.fixture["submission"].id, ricoh=ricoh, unimumer=unimumer,
                                 ornith_reconstruction=ornith, config={"reuse": True})
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(calls), count)

    def test_http_input_preview_is_leak_safe_and_execute_does_not_start_runtime(self):
        self.session.commit()
        q = self.fixture["questions"]["A1"]
        with patch.dict(os.environ, {"LLM_GRADER_ARTIFACT_ROOT": str(self.root)}):
            app = create_app(self.factory, allowed_roots=[self.root], question_import_root=self.root)
        with TestClient(app) as raw:
            client = authenticate_fixture(raw, self.session, self.fixture["user"])
            prefix = f"/api/v1/tests/{self.fixture['test'].id}/submissions/{self.fixture['submission'].id}"
            response = client.get(prefix + f"/answer-reconstruction-input/{q.id}")
            self.assertEqual(response.status_code, 200, response.text)
            body = response.text
            self.assertNotIn("MODEL_TOKEN", body)
            self.assertNotIn("RUBRIC_TOKEN", body)
            self.assertNotIn("max_points", body)
            rejected = client.post(prefix + "/answer-reconstruction-runs", json={"execute": True})
            self.assertEqual(rejected.status_code, 409)


if __name__ == "__main__":
    unittest.main()
