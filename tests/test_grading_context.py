import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from scoring.api.app import create_app
from scoring.db import create_session_factory, init_database
from scoring.db.models import GradingJob, TestQuestionAsset as QuestionAsset
from scoring.domain import DomainService
from scoring.grading_context import ContextError, GradingReadinessService
from scoring.grading_inputs import apply_inputs
from scoring.domain_adapter import DomainGradingJobAdapter
from scoring.db.worker import JobWorker
from scoring.pdf_native import canonical_hash, sha256_file


class GradingContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine, self.factory = create_session_factory("sqlite:///:memory:")
        init_database(self.engine)
        self.s = self.factory()
        self.d = DomainService(self.s, artifact_root=self.root)
        self.u = self.d.user(display_name="Validation")
        c = self.d.course(self.u.id, name="Fixture")
        self.o = self.d.offering(c.id, academic_year=2026, term="fall")
        self.t = self.d.test(self.o.id, name="Context fixture", total_points=10)
        self.q = self.d.question(self.t.id, question_number="leaf", max_points=10,
                                 question_text="Child body")
        self.service = GradingReadinessService(self.s, root=self.root)

    def tearDown(self):
        self.s.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def approve(self):
        data = {"questions": [{"question_id": self.q.id, "max_points": 10,
                "criteria": [{"id": "c", "description": "Fixture criterion", "points": 10}]}]}
        r = self.d.rubric(self.t.id, data)
        self.d.approve_rubric(r.id, self.u.id)
        return r

    def complete(self):
        a = self.d.model_answer(self.t.id, question_id=self.q.id, answer_text="Fixture answer")
        r = self.approve()
        return a, r

    def row(self):
        return next(r for r in self.service.evaluate(self.t.id)["questions"] if r["question_id"] == self.q.id)

    def codes(self):
        return {r["code"] for r in self.row()["blockers"]}

    def parent(self):
        p = self.d.question(self.t.id, question_number="parent", max_points=None,
                            is_gradable=False, question_text="Parent stem")
        self.q.parent_id = p.id
        self.s.flush()
        return p

    def content(self, q, items):
        q.content = {"schema_version": "test-question-content.v1", "items": items}
        q.content_sha256 = canonical_hash(q.content)
        self.s.flush()

    def figure(self, q):
        path = self.root / "extract/assets/figure.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture figure bytes")
        a = QuestionAsset(question_id=q.id, asset_type="figure", artifact_ref="assets/figure.png",
                              sha256=sha256_file(path), mime_type="image/png",
                              provenance={"extraction_id": "extract"})
        self.s.add(a)
        self.s.flush()
        self.content(q, [{"type": "figure", "asset_id": a.id}])
        return a, path

    def test_legacy_flat_verbatim_and_hash(self):
        first = self.service.context(self.q.id)
        self.assertEqual(first["effective_text"], "Child body")
        self.assertEqual(first["ancestor_chain"], [])
        self.assertEqual(first, self.service.context(self.q.id))

    def test_nested_ancestors_formulas_and_no_db_copy(self):
        p = self.parent()
        root = self.d.question(self.t.id, question_number="root", max_points=None,
                               is_gradable=False, question_text="Root stem")
        p.parent_id = root.id
        formula = r"\frac{1}{2}"
        self.content(p, [{"type": "text", "text": "Parent stem"},
                         {"type": "formula", "transcription": formula}])
        self.content(self.q, [{"type": "formula", "transcription": "2 1"}])
        ctx = self.service.context(self.q.id)
        self.assertEqual(ctx["ancestor_chain"], [root.id, p.id])
        self.assertIn(formula, ctx["effective_text"])
        self.assertIn("2 1", ctx["effective_text"])
        self.assertEqual(self.q.question_text, "Child body")


    def test_parent_cycle_missing_and_cross_test(self):
        p = self.parent()
        p.parent_id = self.q.id
        with self.assertRaisesRegex(ContextError, "PARENT_CYCLE"):
            self.service.context(self.q.id)
        self.q.parent_id = "missing"
        with self.assertRaisesRegex(ContextError, "PARENT_MISSING"):
            self.service.context(self.q.id)

    def test_unknown_content_and_tamper(self):
        self.content(self.q, [{"type": "future"}])
        self.assertIn("UNSUPPORTED_CONTENT_ITEM", self.codes())
        self.q.content_sha256 = "0" * 64
        self.assertIn("CONTENT_HASH_MISMATCH", self.codes())

    def test_ready_and_missing_association_transitions(self):
        a, r = self.complete()
        self.assertTrue(self.service.evaluate(self.t.id)["can_start_grading"])
        a.is_current = False
        self.assertIn("MISSING_MODEL_ANSWER", self.codes())
        a.is_current = True
        r.status = "superseded"
        self.assertIn("MISSING_RUBRIC", self.codes())

    def test_unset_zero_nan_score_and_empty_answer(self):
        a, _ = self.complete()
        self.q.max_points = None
        self.assertIn("MISSING_MAX_POINTS", self.codes())
        self.q.max_points = 0
        self.assertIn("INVALID_MAX_POINTS", self.codes())
        self.q.max_points = 10
        a.answer_text = "  "
        self.assertIn("EMPTY_MODEL_ANSWER", self.codes())

    def test_rubric_mismatch_and_invalid(self):
        _, r = self.complete()
        self.q.max_points = 11
        self.assertIn("RUBRIC_SCORE_MISMATCH", self.codes())
        r.rubric_json = {"questions": [{"question_id": self.q.id, "max_points": 10, "criteria": []}]}
        self.assertIn("INVALID_RUBRIC", self.codes())

    def test_structural_protection_and_denominator(self):
        p = self.parent()
        self.complete()
        with self.assertRaisesRegex(ValueError, "STRUCTURAL"):
            self.d.model_answer(self.t.id, question_id=p.id, answer_text="No")
        with self.assertRaises(ValueError):
            self.d.rubric(self.t.id, {"questions": [{"question_id": p.id, "max_points": 10,
                "criteria": [{"id": "c", "description": "x", "points": 10}]}]})
        result = self.service.evaluate(self.t.id)
        self.assertEqual(result["gradable_count"], 1)
        self.assertEqual(result["structural_count"], 1)
        self.assertTrue(result["can_start_grading"])
        self.q.is_gradable = False
        self.assertFalse(self.service.evaluate(self.t.id)["can_start_grading"])

    def test_ancestor_asset_integrity_capability_and_ownership(self):
        p = self.parent()
        a, path = self.figure(p)
        self.complete()
        ctx = self.service.context(self.q.id)
        self.assertEqual(ctx["assets"][0]["source_question_id"], p.id)
        self.assertNotIn(str(self.root), json.dumps(ctx))
        unsupported = GradingReadinessService(self.s, root=self.root, supports_assets=False)
        self.assertIn("GRADER_ASSET_UNSUPPORTED", json.dumps(unsupported.evaluate(self.t.id)))
        path.write_bytes(b"tamper")
        self.assertIn("ASSET_HASH_MISMATCH", self.codes())
        path.unlink()
        self.assertIn("ASSET_MISSING", self.codes())
        self.content(self.q, [{"type": "figure", "asset_id": a.id}])
        self.q.parent_id = None
        self.assertIn("ASSET_MISSING", self.codes())

    def test_self_figure_and_escape(self):
        a, _ = self.figure(self.q)
        self.assertEqual(len(self.service.context(self.q.id)["assets"]), 1)
        a.provenance = {"extraction_id": "../escape"}
        self.assertIn("ASSET_MISSING", self.codes())

    def test_model_answer_version_and_unknown_ownership(self):
        a, _ = self.complete()
        b = self.d.model_answer(self.t.id, question_id=self.q.id, answer_text="Second version")
        self.assertEqual(b.version, 2)
        self.assertFalse(a.is_current)
        with self.assertRaises(ValueError):
            self.d.model_answer(self.t.id, question_id="missing", answer_text="bad")

    def test_grading_overlay_and_legacy_unchanged(self):
        p = self.parent()
        ctx = self.service.context(self.q.id)
        legacy = [{"question_id": "leaf", "text": "old", "asset_paths": []}]
        self.assertIs(apply_inputs(legacy, None), legacy)
        values = {"leaf": {"context": ctx, "reference_text": "answer", "rubric_data": {}, "assets": []}}
        result = apply_inputs(legacy, values)
        self.assertIn(p.question_text, result[0]["text"])
        self.assertEqual(legacy[0]["text"], "old")
        values["leaf"]["context"]["effective_text"] = "tampered"
        with self.assertRaisesRegex(ValueError, "CONTEXT_HASH_MISMATCH"):
            apply_inputs(legacy, values)

    def test_ready_job_snapshot_context_and_resume_without_live_associations(self):
        parent = self.parent()
        figure, source = self.figure(parent)
        self.content(parent, [{"type": "text", "text": "Parent stem"},
                              {"type": "figure", "asset_id": figure.id}])
        answer, rubric = self.complete()
        policy = self.d.policy(self.t.id, policy_text="Fixture policy")
        assignment = self.root / "assignment"
        assignment.mkdir()
        (assignment / "question.txt").write_text("Legacy leaf only")
        (assignment / "page.png").write_bytes(b"fixture image")
        (assignment / "submission.json").write_text(json.dumps({"submission_id": "s1",
            "pages": [{"page_id": "p1", "image": "page.png"}],
            "answers": [{"question_id": "leaf", "page_ids": ["p1"]}]}))
        (assignment / "rubric.json").write_text(json.dumps({
            "question_id": "leaf", "max_score": 10, "criteria": [{
                "criterion_id": "c", "name": "Fixture criterion", "max_score": 10,
                "levels": [{"score": 0, "condition": "Fixture zero"},
                           {"score": 10, "condition": "Fixture full"}]}]}))
        (assignment / "assignment.json").write_text(json.dumps({
            "assignment_id": "fixture", "questions": [{"question_id": "leaf",
                "question": "question.txt", "rubric": "rubric.json"}], "submissions": ["submission.json"]}))
        adapter = DomainGradingJobAdapter(self.s, artifact_root=self.root)
        job, manifest = adapter.create_legacy_job(self.t, rubric, [parent, self.q], policy, [],
            model_answers=[answer], assignment_path=str(assignment), run_path=str(self.root / "run"),
            config_path="unused-no-inference")
        self.assertEqual(manifest["question_ids"], [self.q.id])
        inputs = job.metadata_json["domain_inputs"]
        self.assertIn("Parent stem", inputs["leaf"]["context"]["effective_text"])
        self.assertEqual(sha256_file(Path(inputs["leaf"]["assets"][0]["path"])), figure.sha256)
        self.assertNotEqual(Path(inputs["leaf"]["assets"][0]["path"]), source)
        source.write_bytes(b"source changed after job snapshot")
        answer.is_current = False
        rubric.status = "superseded"
        self.assertEqual(apply_inputs([{"question_id": "leaf"}], inputs)[0]["reference_text"],
                         "Fixture answer")
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(self.q.question_text, "Child body")
        self.s.commit()

        class FakeOrchestrator:
            def run(inner, request):
                self.assertEqual(request.domain_inputs, inputs)
                return type("Outcome", (), {"state": "completed", "states": ["preparing", "completed"],
                                            "item_errors": [], "runtime_error": None})()

        outcome = JobWorker(self.factory, orchestrator_factory=lambda mode: FakeOrchestrator()).run_once(job.id)
        self.assertEqual(outcome.state, "completed")

    def test_context_asset_api_isolation_and_structural_http_rejection(self):
        p = self.parent()
        a, _ = self.figure(self.q)
        self.s.commit()
        with TestClient(create_app(self.factory, question_import_root=self.root)) as client:
            self.assertEqual(client.get(f"/api/v1/tests/{self.t.id}/test-question-assets/{a.id}").status_code, 200)
            self.assertEqual(client.get(f"/api/v1/tests/other/test-question-assets/{a.id}").status_code, 404)
            self.assertEqual(client.post(f"/api/v1/tests/{self.t.id}/model-answers", json={
                "question_id": p.id, "answer_text": "not allowed"}).status_code, 400)
            self.assertEqual(client.post(f"/api/v1/tests/{self.t.id}/rubrics", json={"rubric_json": {
                "questions": [{"question_id": p.id, "max_points": 10, "criteria": [
                    {"id": "c", "description": "x", "points": 10}]}]}}).status_code, 400)

    def test_http_readiness_guard_context_and_retirement(self):
        self.complete()
        self.s.commit()
        app = create_app(self.factory, allowed_roots=[self.root], question_import_root=self.root)
        with TestClient(app) as client:
            result = client.get(f"/api/v1/tests/{self.t.id}/grading-readiness")
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()["can_start_grading"])
            self.assertEqual(client.get(f"/api/v1/test-questions/{self.q.id}/effective-grading-context").status_code, 200)
            # Existing test-level policy/submission requirements remain enforced.
            with patch("scoring.domain_adapter.DomainGradingJobAdapter.create_legacy_job") as job:
                result = client.post(f"/api/v1/tests/{self.t.id}/grading-jobs", json={})
                self.assertEqual(result.status_code, 409)
                job.assert_not_called()
            self.assertFalse(self.s.scalars(select(GradingJob)).all())
            aid = client.get(f"/api/v1/tests/{self.t.id}/model-answers").json()[0]["id"]
            self.assertEqual(client.delete(f"/api/v1/model-answers/{aid}").status_code, 200)
            self.assertFalse(client.get(f"/api/v1/tests/{self.t.id}/grading-readiness").json()["can_start_grading"])

    def test_ready_http_passes_start_precondition_without_execution(self):
        self.complete()
        self.d.policy(self.t.id, policy_text="Synthetic policy")
        material = self.d.material(self.t.id, material_type="student_submission_source",
                                   storage_ref="synthetic")
        student = self.d.student(self.o.id, student_identifier="fixture")
        self.d.submission(self.t.id, student.id, submission_key="s1", material_id=material.id)
        job = GradingJob(external_id="synthetic-mocked", assignment_path=str(self.root),
                         run_path=str(self.root), config_path=str(self.root),
                         execution_mode="resident_serial", total_items=1)
        self.s.add(job)
        self.s.commit()
        with TestClient(create_app(self.factory, allowed_roots=[self.root], question_import_root=self.root)) as client:
            with patch("scoring.domain_adapter.DomainGradingJobAdapter.create_legacy_job", return_value=(job, {})) as adapter:
                response = client.post(f"/api/v1/tests/{self.t.id}/grading-jobs", json={
                    "assignment_path": str(self.root), "run_path": str(self.root),
                    "config_path": str(self.root)})
                self.assertEqual(response.status_code, 201, response.text)
                adapter.assert_called_once()

    def test_rubric_validator_rejects_nonfinite_duplicate(self):
        for points in [-1, 0, float("inf"), 0.5]:
            with self.assertRaises(ValueError):
                self.d.rubric(self.t.id, {"questions": [{"question_id": self.q.id, "max_points": 10,
                    "criteria": [{"id": "c", "description": "x", "points": points}]}]})


if __name__ == "__main__":
    unittest.main()
