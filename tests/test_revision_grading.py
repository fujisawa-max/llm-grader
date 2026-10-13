"""End-to-end Web grading isolation for pinned confirmed editions."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import event, func, select, text, update

from scoring.db.models import (
    GradingJob,
    GradingJobItem,
    GradingJobEvent,
    DomainEvent,
    ModelAnswer,
    RubricVersion,
    StudentAnswerExtractionResult,
    StudentAnswerExtractionRun,
    StudentAnswerReconstruction,
    StudentSubmission,
    TestMaterial as Material,
    TestQuestion as FormalQuestion,
)
from scoring.domain import DomainService
from scoring.grading_execution import GradingExecutionRunner, execution_rubric, snapshot_hash
from scoring.pdf_native import canonical_hash, sha256_file
from scoring.db.worker import JobWorker
from tests.test_test_authoring import base, begin, workspace as authoring_workspace
from tests.synthetic_validation import (
    IsolatedSyntheticValidationWorker,
    create_synthetic_validation_job,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GRADER_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    underlying = authoring_workspace.__wrapped__(tmp_path)
    w = next(underlying)
    try:
        yield w
    finally:
        with w.sf() as session:
            for job in session.scalars(select(GradingJob)).all():
                session.delete(job)
            session.commit()
        try:
            next(underlying)
        except StopIteration:
            pass


def confirm(w, revision):
    return w.client.post(base(w) + "/authoring/confirm", json={
        "revision_id": revision["id"],
        "expected_edit_version": revision["edit_version"],
        "expected_snapshot_sha256": revision["snapshot_sha256"],
    })


def set_edition_values(w, revision, *, question_text, answer_text, levels):
    value = deepcopy(revision["snapshot"])
    node = value["nodes"][0]
    node["body_text"] = question_text
    node["ordered_content"] = [{"type": "text", "order": 0, "text": question_text}]
    key = node["stable_key"]
    value["answers"][key]["primary"] = answer_text
    criterion = value["domains"]["rubric"]["entries"][0]["criteria"][0]
    criterion["levels"] = deepcopy(levels)
    saved = w.client.put(base(w) + "/authoring", json={
        "expected_edit_version": revision["edit_version"], "snapshot": value,
    })
    assert saved.status_code == 200, saved.text
    return saved.json()


def create_submission(w, tmp_path, student_identifier):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    source = artifact_root / f"{student_identifier}.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "student answer source")
        pdf.save(source)
    with w.sf() as session:
        service = DomainService(session)
        material = service.material(w.legacy, material_type="student_answer_source",
            storage_ref=str(source), original_filename=source.name,
            mime_type="application/pdf", sha256=sha256_file(source))
        material_id = material.id
        session.commit()
    response = w.client.post(base(w) + "/submissions", json={
        "material_ids": [material_id], "student_identifier": student_identifier,
        "display_name": student_identifier,
    })
    assert response.status_code == 201, response.text
    return response.json()


def add_selected_reconstruction(w, tmp_path, submission):
    from scoring.grading_definition import confirmed_definition
    from scoring.db.models import ConfirmedAuthoringRevision
    from scoring.student_answer import SelectedImageStudentAnswerReconstruction

    artifact_root = tmp_path / "artifacts"
    with w.sf() as session:
        sub = session.get(StudentSubmission, submission["id"])
        revision = session.get(ConfirmedAuthoringRevision, sub.confirmed_authoring_revision_id)
        definition = confirmed_definition(revision)
        question = next(q for q in definition["questions"] if q["gradable"])
        question_id = question["formal_question_id"]
        SelectedImageStudentAnswerReconstruction(
            session, artifact_root=artifact_root, question_root=artifact_root
        ).run(
            submission["id"], question_id,
            ricoh=lambda *_args: ({}, {"formula_regions": []}),
            unimumer=lambda *_args: pytest.fail("unexpected formula OCR"),
            ornith_reconstruction=lambda payload: {
                "question_id": question_id, "answer_text": "student response",
                "segments": [], "uncertainties": [], "source_refs": [],
            },
            config={"fixture": "revision-bound-synthetic"},
        )
        session.commit()
        return question_id


def create_job(w, tmp_path, submission, question_id, suffix):
    config = tmp_path / f"grader-{suffix}.json"
    config.write_text(json.dumps({"models": {"grader": {
        "model_id": "synthetic-revision-grader",
        "base_url": "http://127.0.0.1:18080/v1",
    }}}), encoding="utf-8")
    response = w.client.post(base(w) + "/grading-jobs", json={
        "input_stage": "selected_reconstruction", "submission_id": submission["id"],
        "question_id": question_id, "config_path": str(config),
        "run_path": str(tmp_path / f"run-{suffix}"),
    })
    if response.status_code != 201:
        readiness = w.client.get(base(w) + f"/submissions/{submission['id']}/grading-input-readiness")
        assert response.status_code == 201, f"{response.text}; readiness={readiness.text}"
    with w.sf() as session:
        return session.get(GradingJob, response.json()["id"]), response.json()


def preview_package(w, submission, question_id, *, synthetic_answer_text=None):
    body = {"question_id": question_id}
    if synthetic_answer_text is not None:
        body["synthetic_answer_text"] = synthetic_answer_text
    return w.client.post(base(w) + f"/submissions/{submission['id']}/grading-package-preview",
                         json=body)


class SyntheticRuntime:
    def status(self, _runtime_id):
        return {"profile": {"runtime_type": "managed", "model_id": "synthetic-revision-grader"},
                "pid": None}

    def ensure_running(self, _runtime_id):
        return {"profile": {"runtime_type": "managed", "model_id": "synthetic-revision-grader"},
                "endpoint": "http://127.0.0.1:18080/v1"}

    def health(self, _runtime_id):
        return {"ok": True}

    def stop(self, _runtime_id):
        return {"state": "stopped"}


def synthetic_client_factory(requests):
    class Client:
        audit_path = None

        def chat(self, _prompt, materials, _images):
            requests.append(deepcopy(materials))
            Path(self.audit_path).write_text(json.dumps({"materials": materials}), encoding="utf-8")
            rubric = materials["rubric"]
            criterion = rubric["criteria"][0]
            response = {"question_id": materials["question_id"], "criteria": [{
                "criterion_id": criterion["criterion_id"], "score": 0,
                "max_score": criterion["max_score"],
                "evidence": [{"page_id": next(iter(materials["ocr"])), "quote": "student response"}],
                "reason": "synthetic verification result",
            }], "needs_review": False, "review_reasons": []}
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(response),
            }}]}

    return Client()


def test_web_submissions_jobs_and_grading_inputs_remain_on_their_confirmed_editions(
        workspace, tmp_path):
    w = workspace
    first_working = begin(w)
    first_working = set_edition_values(w, first_working, question_text="Question edition A",
        answer_text="Model answer edition A", levels=[
            {"score": 0, "condition": "A: no credit"},
            {"score": 10, "condition": "A: complete"},
        ])
    first_response = confirm(w, first_working)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()

    submission_a = create_submission(w, tmp_path, "REVISION-A")
    assert submission_a["confirmed_authoring_revision_id"] == first["id"]
    question_a = add_selected_reconstruction(w, tmp_path, submission_a)
    preview_a_initial = preview_package(w, submission_a, question_a)
    assert preview_a_initial.status_code == 200, preview_a_initial.text
    job_a_before, job_a_before_response = create_job(w, tmp_path, submission_a, question_a, "a-before")
    bundle_a_before = job_a_before.metadata_json["grading_execution"]["bundle"]
    assert preview_a_initial.json()["canonical_package_hash"] == bundle_a_before["bundle_sha256"]
    assert bundle_a_before["question"]["context"]["effective_text"].endswith("Question edition A")
    assert bundle_a_before["model_answer"]["content"] == "Model answer edition A"
    assert [level["score"] for level in bundle_a_before["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 10]

    revised = w.client.post(base(w) + "/authoring/revisions", json={
        "confirmed_revision_id": first["id"],
    })
    assert revised.status_code == 200, revised.text
    second_working = set_edition_values(w, revised.json(), question_text="Question edition B",
        answer_text="Model answer edition B", levels=[
            {"score": 0, "condition": "B: no credit"},
            {"score": 5, "condition": "B: partial"},
            {"score": 10, "condition": "B: complete"},
        ])
    second_response = confirm(w, second_working)
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["id"] != first["id"]

    submission_b = create_submission(w, tmp_path, "REVISION-B")
    assert submission_b["confirmed_authoring_revision_id"] == second["id"]
    question_b = add_selected_reconstruction(w, tmp_path, submission_b)
    with w.sf() as session:
        source_material = session.scalar(select(Material).where(
            Material.test_id == w.legacy,
            Material.material_type == "student_answer_source",
            Material.original_filename == "REVISION-A.pdf"))
        assert source_material is not None
        source_material_id = source_material.id
    retry_submission = w.client.post(base(w) + "/submissions", json={
        "material_ids": [source_material_id], "student_identifier": "REVISION-A",
        "display_name": "REVISION-A",
    })
    assert retry_submission.status_code == 201, retry_submission.text
    assert retry_submission.json()["id"] == submission_a["id"]
    assert retry_submission.json()["confirmed_authoring_revision_id"] == first["id"]

    # Simulate drift in current formal projections. The Web assembler must only
    # use each Submission's frozen revision for semantics.
    with w.sf() as session:
        rubric = session.scalar(select(RubricVersion).where(
            RubricVersion.test_id == w.legacy).order_by(RubricVersion.version.desc()))
        drifted = deepcopy(rubric.rubric_json)
        drifted["questions"][0]["criteria"][0]["description"] = "mutable projection drift"
        drifted["questions"][0]["criteria"][0]["levels"] = [
            {"score": 0, "condition": "drift zero"},
            {"score": 4, "condition": "drift partial"},
            {"score": 10, "condition": "drift full"},
        ]
        session.execute(update(FormalQuestion).where(FormalQuestion.id == question_a).values(
            question_text="MUTABLE QUESTION DRIFT"))
        session.execute(update(ModelAnswer).where(ModelAnswer.test_id == w.legacy,
            ModelAnswer.is_current.is_(True)).values(answer_text="MUTABLE ANSWER DRIFT"))
        session.execute(update(RubricVersion).where(RubricVersion.id == rubric.id).values(
            rubric_json=drifted))
        session.commit()

    # A reconstruction explicitly run after edition B was activated must also
    # use A's frozen Question context, even though the formal projection now
    # contains deliberately drifted/current text. All extraction stages are
    # controlled local stubs; no model service is contacted.
    from scoring.student_answer import SelectedImageStudentAnswerReconstruction
    from scoring.db.models import StudentAnswerExtractionRun
    with w.sf() as session:
        SelectedImageStudentAnswerReconstruction(
            session, artifact_root=tmp_path / "artifacts",
            question_root=tmp_path / "artifacts",
        ).run(
            submission_a["id"], question_a,
            ricoh=lambda *_args: ({}, {"formula_regions": []}),
            unimumer=lambda *_args: pytest.fail("unexpected formula OCR"),
            ornith_reconstruction=lambda payload: {
                "question_id": question_a, "answer_text": "student response after B",
                "segments": [], "uncertainties": [], "source_refs": [],
            },
            config={"fixture": "pinned-after-edition-B"},
        )
        selected_run = session.scalar(select(StudentAnswerExtractionRun).where(
            StudentAnswerExtractionRun.submission_id == submission_a["id"],
            StudentAnswerExtractionRun.selected.is_(True)))
        assert selected_run is not None
        reconstruction_input = json.loads((tmp_path / "artifacts" / selected_run.artifact_ref
            / "questions" / question_a / "reconstruction-input.json").read_text(encoding="utf-8"))
        assert reconstruction_input["question"]["context"]["effective_text"].endswith(
            "Question edition A")
        session.commit()

    # Delayed job creation for S1 occurs after B is active and still inherits A.
    # Exercise the real API/assembler while forbidding reads from mutable
    # Question/ModelAnswer tables and from Rubric policy columns. A narrowly
    # selected RubricVersion ID/provenance is retained only for the legacy FK.
    def reject_mutable_authoring_reads(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower()
        if ("from test_questions" in sql or "from model_answers" in sql
                or "rubric_versions.rubric_json" in sql
                or "rubric_versions.rubric_text" in sql):
            raise AssertionError(f"revision-bound grading read mutable authoring table: {statement}")

    event.listen(w.engine, "before_cursor_execute", reject_mutable_authoring_reads)
    try:
        preview_a_after = preview_package(w, submission_a, question_a)
        preview_b_after = preview_package(w, submission_b, question_b)
        assert preview_a_after.status_code == preview_b_after.status_code == 200
        job_a_after, job_a_response = create_job(w, tmp_path, submission_a, question_a, "a-after")
        job_b, job_b_response = create_job(w, tmp_path, submission_b, question_b, "b-after")
    finally:
        event.remove(w.engine, "before_cursor_execute", reject_mutable_authoring_reads)
    bundle_a = job_a_after.metadata_json["grading_execution"]["bundle"]
    bundle_b = job_b.metadata_json["grading_execution"]["bundle"]
    assert preview_a_after.json()["confirmed_authoring_revision_id"] == first["id"]
    assert preview_a_after.json()["edition_label"] == "第1版"
    assert preview_a_after.json()["question"]["effective_text"].endswith("Question edition A")
    assert preview_a_after.json()["model_answer"]["primary"] == "Model answer edition A"
    assert [level["score"] for level in preview_a_after.json()["rubric"]["criteria"][0]["levels"]] == [0, 10]
    assert preview_a_after.json()["canonical_package_hash"] == bundle_a["bundle_sha256"]
    assert preview_b_after.json()["confirmed_authoring_revision_id"] == second["id"]
    assert preview_b_after.json()["edition_label"] == "第2版"
    assert preview_b_after.json()["question"]["effective_text"].endswith("Question edition B")
    assert preview_b_after.json()["model_answer"]["primary"] == "Model answer edition B"
    assert [level["score"] for level in preview_b_after.json()["rubric"]["criteria"][0]["levels"]] == [0, 5, 10]
    assert preview_b_after.json()["canonical_package_hash"] == bundle_b["bundle_sha256"]
    assert job_a_before.confirmed_authoring_revision_id == first["id"]
    assert job_a_after.confirmed_authoring_revision_id == first["id"]
    assert job_b.confirmed_authoring_revision_id == second["id"]
    assert bundle_a["question"]["context"]["effective_text"].endswith("Question edition A")
    assert bundle_a["model_answer"]["content"] == "Model answer edition A"
    assert [x["score"] for x in bundle_a["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 10]
    assert bundle_b["question"]["context"]["effective_text"].endswith("Question edition B")
    assert bundle_b["model_answer"]["content"] == "Model answer edition B"
    assert [x["score"] for x in bundle_b["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 5, 10]
    assert [c["max_score"] for c in execution_rubric(bundle_a)["criteria"]] == [10]
    assert [c["max_score"] for c in execution_rubric(bundle_b)["criteria"]] == [10]
    assert job_a_response["confirmed_edition_label"] == "第1版"
    assert job_b_response["confirmed_edition_label"] == "第2版"

    with w.sf() as session:
        bound_submission = session.get(StudentSubmission, submission_a["id"])
        bound_submission.confirmed_authoring_revision_id = second["id"]
        with pytest.raises(ValueError, match="CONFIRMED_AUTHORING_REVISION_BINDING_IMMUTABLE"):
            session.commit()
        session.rollback()
        bound_job = session.get(GradingJob, job_a_before.id)
        bound_job.confirmed_authoring_revision_id = second["id"]
        with pytest.raises(ValueError, match="CONFIRMED_AUTHORING_REVISION_BINDING_IMMUTABLE"):
            session.commit()
        session.rollback()
        assert session.get(StudentSubmission, submission_a["id"]).confirmed_authoring_revision_id == first["id"]
        assert session.get(GradingJob, job_a_before.id).confirmed_authoring_revision_id == first["id"]

    requests = []
    worker = JobWorker(w.sf, grading_runner_factory=lambda: GradingExecutionRunner(
        SyntheticRuntime(), lambda *_args: synthetic_client_factory(requests)))
    for job in (job_a_before, job_a_after, job_b):
        outcome = worker.run_once(job.id)
        assert outcome.state == "completed"
    assert len(requests) == 3
    assert requests[1]["question"].endswith("Question edition A")
    assert requests[1]["reference_answer"] == "Model answer edition A"
    assert [x["levels"] for x in requests[1]["rubric"]["criteria"]] == [[
        {"score": 0, "condition": "A: no credit"},
        {"score": 10, "condition": "A: complete"},
    ]]
    assert requests[2]["question"].endswith("Question edition B")
    assert requests[2]["reference_answer"] == "Model answer edition B"
    assert [x["levels"] for x in requests[2]["rubric"]["criteria"]] == [[
        {"score": 0, "condition": "B: no credit"},
        {"score": 5, "condition": "B: partial"},
        {"score": 10, "condition": "B: complete"},
    ]]

    review_a = w.client.get(base(w) + f"/grading/{submission_a['id']}")
    review_b = w.client.get(base(w) + f"/grading/{submission_b['id']}")
    assert review_a.status_code == review_b.status_code == 200
    assert review_a.json()["submission"]["confirmed_revision_label"] == "第1版"
    assert review_b.json()["submission"]["confirmed_revision_label"] == "第2版"
    assert review_a.json()["questions"][0]["question"]["text"] == "Question edition A"
    assert review_a.json()["questions"][0]["model_answer"]["content"] == "Model answer edition A"
    assert review_a.json()["questions"][0]["rubric"]["entry"]["criteria"][0]["levels"] == [
        {"score": 0, "condition": "A: no credit"},
        {"score": 10, "condition": "A: complete"},
    ]
    finalized = w.client.post(base(w) + f"/grading/{submission_a['id']}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["confirmed_revision_label"] == "第1版"
    assert finalized.json()["total_points"] == 10
    with w.sf() as session:
        for job in session.scalars(select(GradingJob).where(GradingJob.test_id == w.legacy)).all():
            session.delete(job)
        session.commit()


def test_package_preview_synthetic_answer_is_in_memory_and_read_only(workspace, tmp_path, monkeypatch):
    w = workspace
    working = set_edition_values(w, begin(w), question_text="Preview question",
        answer_text="Preview model answer", levels=[
            {"score": 0, "condition": "No credit"},
            {"score": 10, "condition": "Complete"},
        ])
    confirmed = confirm(w, working)
    assert confirmed.status_code == 200, confirmed.text
    revision_id = confirmed.json()["id"]
    submission = create_submission(w, tmp_path, "PREVIEW-SYNTHETIC")
    synthetic_text = "SYNTHETIC-ANSWER-MUST-NOT-BE-PERSISTED"

    from scoring.db.models import ConfirmedAuthoringRevision
    from scoring.db.worker import JobWorker
    from scoring.grading_execution import GradingExecutionRunner
    from scoring.student_answer import SelectedImageStudentAnswerReconstruction
    import scoring.grading_execution as grading_execution

    def forbidden(*_args, **_kwargs):
        pytest.fail("package preview attempted grading, runtime, OCR, or reconstruction")

    monkeypatch.setattr(GradingExecutionRunner, "run", forbidden)
    monkeypatch.setattr(JobWorker, "run_once", forbidden)
    monkeypatch.setattr(SelectedImageStudentAnswerReconstruction, "run", forbidden)
    monkeypatch.setattr(grading_execution.RuntimeManagerClient, "__init__", forbidden)
    monkeypatch.setattr(grading_execution.GradingClient, "__init__", forbidden)

    def counts():
        with w.sf() as session:
            return {
                "jobs": session.scalar(select(func.count()).select_from(GradingJob)),
                "items": session.scalar(select(func.count()).select_from(GradingJobItem)),
                "job_events": session.scalar(select(func.count()).select_from(GradingJobEvent)),
                "domain_events": session.scalar(select(func.count()).select_from(DomainEvent)),
                "reconstructions": session.scalar(select(func.count()).select_from(StudentAnswerReconstruction)),
                "extraction_runs": session.scalar(select(func.count()).select_from(StudentAnswerExtractionRun)),
                "extraction_results": session.scalar(select(func.count()).select_from(StudentAnswerExtractionResult)),
            }

    before_counts = counts()
    with w.sf() as session:
        before_submission = session.get(StudentSubmission, submission["id"])
        submission_state = (before_submission.test_id, before_submission.student_id,
            before_submission.material_id, before_submission.confirmed_authoring_revision_id)
        before_revision = session.get(ConfirmedAuthoringRevision, revision_id)
        snapshot_hash_before = before_revision.snapshot_sha256

    response = preview_package(w, submission, w.question,
        synthetic_answer_text=synthetic_text)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["synthetic_input"] is True
    assert preview["confirmed_authoring_revision_id"] == revision_id
    assert preview["edition_label"] == "第1版"
    assert preview["question"]["effective_text"].endswith("Preview question")
    assert preview["model_answer"]["primary"] == "Preview model answer"
    assert preview["rubric"]["criteria"][0]["max_score"] == 10
    assert preview["student_answer_sha256"]
    assert synthetic_text not in response.text
    assert str(tmp_path) not in response.text
    assert "artifact_ref" not in response.text
    assert "student_id" not in preview
    assert counts() == before_counts
    with w.sf() as session:
        after_submission = session.get(StudentSubmission, submission["id"])
        assert (after_submission.test_id, after_submission.student_id,
            after_submission.material_id, after_submission.confirmed_authoring_revision_id) == submission_state
        assert session.get(ConfirmedAuthoringRevision, revision_id).snapshot_sha256 == snapshot_hash_before
    assert not (tmp_path / "artifacts" / "student-answer").exists()


def test_package_preview_rejects_foreign_test_and_cross_test_submission(workspace, tmp_path):
    w = workspace
    response = w.client.post(base(w, "foreign") + "/submissions/not-a-submission/grading-package-preview",
        json={"question_id": w.question})
    assert response.status_code == 403
    confirmed = confirm(w, begin(w))
    assert confirmed.status_code == 200, confirmed.text
    same_owner_submission = create_submission(w, tmp_path, "CROSS-TEST")
    cross = w.client.post(base(w, "fresh") +
        f"/submissions/{same_owner_submission['id']}/grading-package-preview",
        json={"question_id": w.question, "synthetic_answer_text": "not allowed across tests"})
    assert cross.status_code == 404


@pytest.mark.parametrize("corruption,expected_code", [
    ("snapshot_hash", "GRADING_DEFINITION_SNAPSHOT_HASH_MISMATCH"),
    ("missing_definition", "GRADING_DEFINITION_LEGACY_INCOMPLETE"),
    ("incomplete_definition", "GRADING_DEFINITION_INCOMPLETE_OR_CHANGED"),
    ("unsupported_schema", "GRADING_DEFINITION_LEGACY_INCOMPLETE"),
])
def test_package_preview_fails_closed_for_invalid_confirmed_definition(
        workspace, tmp_path, corruption, expected_code):
    w = workspace
    confirmed = confirm(w, begin(w))
    assert confirmed.status_code == 200, confirmed.text
    submission = create_submission(w, tmp_path, f"INVALID-PREVIEW-{corruption}")
    snapshot = deepcopy(confirmed.json()["snapshot"])
    if corruption == "snapshot_hash":
        snapshot["metadata"]["description"] = "tampered without updating attestation"
        stored_hash = confirmed.json()["snapshot_sha256"]
    elif corruption == "missing_definition":
        snapshot["domains"].pop("grading_definition", None)
        stored_hash = canonical_hash(snapshot)
    elif corruption == "incomplete_definition":
        snapshot["domains"]["grading_definition"]["complete"] = False
        stored_hash = canonical_hash(snapshot)
    else:
        snapshot["domains"]["grading_definition"]["schema_version"] = "unsupported.v999"
        stored_hash = canonical_hash(snapshot)
    with w.engine.begin() as connection:
        connection.execute(text("""
            UPDATE confirmed_authoring_revisions
            SET snapshot=:snapshot, snapshot_sha256=:sha WHERE id=:id
        """), {"snapshot": json.dumps(snapshot), "sha": stored_hash,
              "id": confirmed.json()["id"]})
    response = preview_package(w, submission, w.question,
        synthetic_answer_text="not persisted")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == expected_code


def test_web_submission_without_active_complete_revision_fails_closed(workspace, tmp_path):
    w = workspace
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    source = artifact_root / "unconfirmed.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    with w.sf() as session:
        service = DomainService(session)
        material = service.material(w.legacy, material_type="student_answer_source",
            storage_ref=str(source), original_filename=source.name,
            mime_type="application/pdf", sha256=sha256_file(source))
        material_id = material.id
        session.commit()
    response = w.client.post(base(w) + "/submissions", json={
        "material_ids": [material_id], "student_identifier": "NO-ACTIVE-EDITION",
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WEB_GRADING_REVISION_REQUIRED"
    assert "確定してください" in response.json()["error"]["message"]


@pytest.mark.parametrize("corruption,expected_code", [
    ("snapshot_hash", "GRADING_DEFINITION_SNAPSHOT_HASH_MISMATCH"),
    ("missing_definition", "GRADING_DEFINITION_LEGACY_INCOMPLETE"),
    ("incomplete_definition", "GRADING_DEFINITION_INCOMPLETE_OR_CHANGED"),
])
def test_new_submission_rejects_invalid_confirmed_grading_definition(
        workspace, tmp_path, corruption, expected_code):
    w = workspace
    working = begin(w)
    confirmed = confirm(w, working)
    assert confirmed.status_code == 200, confirmed.text
    changed = deepcopy(confirmed.json()["snapshot"])
    if corruption == "snapshot_hash":
        changed["metadata"]["description"] = "corrupted without updating hash"
        sha = confirmed.json()["snapshot_sha256"]
    elif corruption == "missing_definition":
        changed["domains"].pop("grading_definition", None)
        sha = canonical_hash(changed)
    else:
        changed["domains"]["grading_definition"]["complete"] = False
        sha = canonical_hash(changed)
    with w.engine.begin() as connection:
        connection.execute(
            __import__("sqlalchemy").text(
                "UPDATE confirmed_authoring_revisions SET snapshot=:snapshot, snapshot_sha256=:sha WHERE id=:id"
            ),
            {"snapshot": json.dumps(changed), "sha": sha, "id": confirmed.json()["id"]},
        )

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    source = artifact_root / f"invalid-{corruption}.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    with w.sf() as session:
        material = DomainService(session).material(w.legacy, material_type="student_answer_source",
            storage_ref=str(source), original_filename=source.name,
            mime_type="application/pdf", sha256=sha256_file(source))
        material_id = material.id
        session.commit()
    response = w.client.post(base(w) + "/submissions", json={
        "material_ids": [material_id], "student_identifier": f"INVALID-{corruption}",
    })
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == expected_code


def test_revision_bound_submission_rejects_revision_from_another_test(workspace):
    from scoring.grading_definition import confirmed_revision_for_test
    from scoring.db.models import ConfirmedAuthoringRevision

    w = workspace
    confirmed = confirm(w, begin(w))
    assert confirmed.status_code == 200, confirmed.text
    with w.sf() as session:
        revision = session.get(ConfirmedAuthoringRevision, confirmed.json()["id"])
        with pytest.raises(ValueError, match="WEB_GRADING_REVISION_TEST_MISMATCH"):
            confirmed_revision_for_test(session, w.fresh, revision.id)


def test_frozen_visual_reference_package_uses_each_revision_sha_and_geometry(tmp_path):
    from scoring.revision_grading import frozen_question_package

    def question_for(edition, digest, bbox):
        ref = {
            "asset_id": f"diagram-{edition}", "sha256": digest,
            "mime_type": "image/png", "role": "model_answer_reference",
            "page_index": 0, "bbox": bbox,
            "immutable_artifact": {"namespace": "answer_import",
                                   "artifact_ref": f"{edition}.png", "sha256": digest},
        }
        return {
            "question_key": "q1", "max_points": 10,
            "context": {"question_id": "q1", "context_sha256": "context-hash",
                        "assets": []},
            "content": {"items": [{"type": "text", "text": f"Question {edition}"}]},
            "answer": {"primary": "Answer", "alternatives": []},
            "visual_references": [ref], "rubric": {"aggregation": "sum", "criteria": []},
        }

    Path(tmp_path / "A.png").write_bytes(b"edition A diagram")
    Path(tmp_path / "B.png").write_bytes(b"edition B diagram")
    sha_a, sha_b = sha256_file(tmp_path / "A.png"), sha256_file(tmp_path / "B.png")
    package_a = frozen_question_package({"source_provenance": {}}, "revision-A",
        question_for("A", sha_a, [1, 2, 30, 40]), "formal-q1", {"q1": "formal-q1"})
    package_b = frozen_question_package({"source_provenance": {}}, "revision-B",
        question_for("B", sha_b, [5, 6, 35, 46]), "formal-q1", {"q1": "formal-q1"})
    assert package_a["assets"][0]["sha256"] == sha_a
    assert package_a["assets"][0]["bbox"] == [1, 2, 30, 40]
    assert package_b["assets"][0]["sha256"] == sha_b
    assert package_b["assets"][0]["bbox"] == [5, 6, 35, 46]
    assert package_a["assets"][0]["artifact_ref"] == "A.png"
    assert package_b["assets"][0]["artifact_ref"] == "B.png"


def test_worker_rejects_rehashed_bundle_that_disagrees_with_pinned_revision(workspace, tmp_path):
    from scoring.grading_definition import revision_safe_grading_history

    w = workspace
    working = set_edition_values(w, begin(w), question_text="Frozen question",
        answer_text="Frozen answer", levels=[
            {"score": 0, "condition": "no credit"},
            {"score": 10, "condition": "complete"},
        ])
    confirmed = confirm(w, working)
    assert confirmed.status_code == 200, confirmed.text
    submission = create_submission(w, tmp_path, "BUNDLE-TAMPER")
    question_id = add_selected_reconstruction(w, tmp_path, submission)
    job, _ = create_job(w, tmp_path, submission, question_id, "bundle-tamper")

    # Model a metadata rewrite with every cached checksum recomputed. The
    # worker must still compare executable content with the immutable revision.
    with w.sf() as session:
        stored = session.get(GradingJob, job.id)
        execution = deepcopy(stored.metadata_json["grading_execution"])
        bundle = execution["bundle"]
        bundle["question"]["context"]["effective_text"] = "forged mutable question"
        bundle["question"]["context"]["context_sha256"] = canonical_hash(
            {k: v for k, v in bundle["question"]["context"].items()
             if k != "context_sha256"}
        )
        bundle["question"]["context_sha256"] = bundle["question"]["context"]["context_sha256"]
        bundle["bundle_sha256"] = canonical_hash(
            {k: v for k, v in bundle.items() if k != "bundle_sha256"}
        )
        execution["snapshot_sha256"] = snapshot_hash(execution)
        stored.metadata_json = {**stored.metadata_json, "grading_execution": execution}
        stored.items[0].metadata_json = {
            **stored.items[0].metadata_json,
            "bundle_sha256": bundle["bundle_sha256"],
        }
        session.commit()
        assert not revision_safe_grading_history(session, w.legacy)

    requests = []
    worker = JobWorker(w.sf, grading_runner_factory=lambda: GradingExecutionRunner(
        SyntheticRuntime(), lambda *_args: synthetic_client_factory(requests)))
    with pytest.raises(ValueError, match="WEB_GRADING_REVISION_BUNDLE_MISMATCH"):
        worker.run_once(job.id)
    assert requests == []


def test_isolated_synthetic_execution_review_and_finalize_never_touch_runtime(
        workspace, tmp_path, monkeypatch):
    """Run the real JobWorker/review/finalize path inside a separate test DB."""
    from fastapi.testclient import TestClient
    from scoring.db.models import DomainEvent, Test as TestRow
    from scoring.grading_execution import GradingClient, RuntimeManagerClient
    w = workspace
    validation_db = Path(w.engine.url.database)
    normal_root = tmp_path / "normal-worker-db"
    normal_root.mkdir()
    normal_generator = authoring_workspace.__wrapped__(normal_root)
    normal = next(normal_generator)
    normal_job_id = None
    try:
        # Edition A and S1 are created first. S1 deliberately receives its Job
        # only after edition B is active, exercising delayed-job binding.
        edition_a_working = set_edition_values(
            w, begin(w), question_text="Question edition A",
            answer_text="ModelAnswer edition A", levels=[
                {"score": 0, "condition": "A: no credit"},
                {"score": 10, "condition": "A: full credit"},
            ])
        response_a = confirm(w, edition_a_working)
        assert response_a.status_code == 200, response_a.text
        edition_a = response_a.json()
        submission_a = create_submission(w, tmp_path, "ISOLATED-SYNTHETIC-A")
        assert submission_a["confirmed_authoring_revision_id"] == edition_a["id"]

        revised = w.client.post(base(w) + "/authoring/revisions", json={
            "confirmed_revision_id": edition_a["id"],
        })
        assert revised.status_code == 200, revised.text
        edition_b_working = set_edition_values(
            w, revised.json(), question_text="Question edition B",
            answer_text="ModelAnswer edition B", levels=[
                {"score": 0, "condition": "B: no credit"},
                {"score": 5, "condition": "B: partial credit"},
                {"score": 10, "condition": "B: full credit"},
            ])
        response_b = confirm(w, edition_b_working)
        assert response_b.status_code == 200, response_b.text
        edition_b = response_b.json()
        submission_b = create_submission(w, tmp_path, "ISOLATED-SYNTHETIC-B")
        assert submission_b["confirmed_authoring_revision_id"] == edition_b["id"]
        assert edition_a["id"] != edition_b["id"]

        answer_a = "Synthetic validation answer for edition A"
        answer_b = "Synthetic validation answer for edition B"
        preview_a = preview_package(w, submission_a, w.question,
                                    synthetic_answer_text=answer_a)
        preview_b = preview_package(w, submission_b, w.question,
                                    synthetic_answer_text=answer_b)
        assert preview_a.status_code == preview_b.status_code == 200

        # Deliberately drift mutable formal projections after both confirmations.
        # Package creation and review must continue to use the sealed editions.
        with w.sf() as session:
            session.execute(update(FormalQuestion).where(
                FormalQuestion.id == w.question).values(question_text="MUTABLE QUESTION DRIFT"))
            session.execute(update(ModelAnswer).where(
                ModelAnswer.test_id == w.legacy).values(answer_text="MUTABLE ANSWER DRIFT"))
            rubric = session.scalar(select(RubricVersion).where(
                RubricVersion.test_id == w.legacy).order_by(RubricVersion.version.desc()))
            changed = deepcopy(rubric.rubric_json)
            changed["questions"][0]["criteria"][0]["levels"] = [
                {"score": 0, "condition": "mutable zero"},
                {"score": 2, "condition": "mutable partial"},
                {"score": 10, "condition": "mutable full"},
            ]
            session.execute(update(RubricVersion).where(
                RubricVersion.id == rubric.id).values(rubric_json=changed))
            assert session.scalar(select(func.count()).select_from(GradingJob)) == 0
            job_a, package_a = create_synthetic_validation_job(
                session, disposable_root=tmp_path, validation_database_path=validation_db,
                allowlisted_test_id=w.legacy,
                test_id=w.legacy, submission_id=submission_a["id"],
                question_id=w.question, synthetic_answer_text=answer_a, job_name="edition-a")
            job_b, package_b = create_synthetic_validation_job(
                session, disposable_root=tmp_path, validation_database_path=validation_db,
                allowlisted_test_id=w.legacy,
                test_id=w.legacy, submission_id=submission_b["id"],
                question_id=w.question, synthetic_answer_text=answer_b, job_name="edition-b")
            job_a_id, job_b_id = job_a.id, job_b.id
            snapshot_a = deepcopy(job_a.metadata_json["grading_execution"])
            snapshot_b = deepcopy(job_b.metadata_json["grading_execution"])
            session.commit()

        assert preview_a.json()["canonical_package_hash"] == package_a["bundle"]["bundle_sha256"]
        assert preview_b.json()["canonical_package_hash"] == package_b["bundle"]["bundle_sha256"]
        assert snapshot_a["bundle"]["question"]["context"]["effective_text"] == "Question edition A"
        assert snapshot_a["bundle"]["model_answer"]["content"] == "ModelAnswer edition A"
        assert [level["score"] for level in snapshot_a["bundle"]["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 10]
        assert snapshot_b["bundle"]["question"]["context"]["effective_text"] == "Question edition B"
        assert snapshot_b["bundle"]["model_answer"]["content"] == "ModelAnswer edition B"
        assert [level["score"] for level in snapshot_b["bundle"]["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 5, 10]
        assert job_a.confirmed_authoring_revision_id == edition_a["id"]
        assert job_b.confirmed_authoring_revision_id == edition_b["id"]
        assert snapshot_a["snapshot_sha256"] != snapshot_b["snapshot_sha256"]

        # The synthetic answer exists only in the validation Job's sealed bundle,
        # never in the regular Submission reconstruction tables.
        with w.sf() as session:
            assert session.scalar(select(func.count()).select_from(StudentAnswerReconstruction).where(
                StudentAnswerReconstruction.submission_id.in_([submission_a["id"], submission_b["id"]]))) == 0
            assert session.scalar(select(func.count()).select_from(GradingJobItem)) == 2
            assert session.scalar(select(func.count()).select_from(GradingJobEvent)) == 2

        # Another real SQLite database represents the ordinary worker domain.
        # It has a normal queued Job, but cannot see either validation Job ID.
        with normal.sf() as session:
            regular_test = session.get(TestRow, normal.legacy)
            regular_job = GradingJob(
                external_id="normal-job-isolation-fixture", execution_mode="phased_auto",
                assignment_path="", run_path=str(normal_root / "ordinary-run"),
                config_path=str(normal_root / "ordinary-config.json"),
                test_id=regular_test.id, total_items=1, metadata_json={},
            )
            session.add(regular_job)
            session.flush()
            regular_job_id = regular_job.id
            session.add(GradingJobItem(job_id=regular_job.id, item_key="normal-item", metadata_json={}))
            session.commit()
            normal_job_id = regular_job.id

        # A normal worker cannot see/claim synthetic IDs because they are in a
        # different physical database. The validation worker refuses unmarked
        # normal Jobs and Jobs from a Test outside its explicit allowlist.
        synthetic_worker = IsolatedSyntheticValidationWorker(
            w.sf, disposable_root=tmp_path, validation_database_path=validation_db,
            allowed_test_ids={w.legacy})
        normal_worker = JobWorker(normal.sf,
            grading_runner_factory=lambda: pytest.fail("normal worker reached grader"),
            orchestrator_factory=lambda *_args: pytest.fail("normal worker reached orchestrator"))
        assert normal_worker.run_once(job_a_id) is None
        assert synthetic_worker.run_once(regular_job_id) is None
        assert synthetic_worker.run_once("job-id-not-in-validation-db") is None

        # An ordinary, unmarked job inside the disposable DB is also denied.
        with w.sf() as session:
            unmarked = GradingJob(
                external_id="unmarked-validation-db-job", execution_mode="phased_auto",
                assignment_path="", run_path=str(tmp_path / "ordinary-in-validation-db"),
                config_path=str(tmp_path / "ordinary-config.json"),
                test_id=w.legacy, total_items=1, metadata_json={},
            )
            session.add(unmarked)
            session.flush()
            unmarked_id = unmarked.id
            session.add(GradingJobItem(job_id=unmarked.id, item_key="ordinary", metadata_json={}))
            session.commit()
        assert synthetic_worker.run_once(unmarked_id) is None

        # Claim arbitration is still the normal atomic queued-state transition.
        # Two concurrent claimers cannot both acquire the same queued Job.
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from scoring.db.repository import JobRepository
        barrier = Barrier(2)

        def claim_once():
            with w.sf() as session:
                barrier.wait(timeout=5)
                claimed = JobRepository(session).claim(unmarked_id)
                session.commit()
                return claimed

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _index: claim_once(), range(2)))
        assert sorted(claims) == [False, True]
        with w.sf() as session:
            claimed_job = session.get(GradingJob, unmarked_id)
            claimed_job.state = "queued"
            session.delete(claimed_job)
            session.commit()

        from scoring.student_answer import SelectedImageStudentAnswerReconstruction

        def forbidden(*_args, **_kwargs):
            pytest.fail("synthetic validation touched a model, OCR, or reconstruction runtime")

        monkeypatch.setattr(RuntimeManagerClient, "__init__", forbidden)
        monkeypatch.setattr(GradingClient, "__init__", forbidden)
        monkeypatch.setattr(GradingClient, "chat", forbidden)
        monkeypatch.setattr(SelectedImageStudentAnswerReconstruction, "run", forbidden)

        # Review auth remains mandatory; no special synthetic bypass exists.
        anonymous = TestClient(w.client.app)
        try:
            denied = anonymous.get(base(w) + f"/grading/{submission_a['id']}")
            assert denied.status_code in {401, 403}
        finally:
            anonymous.close()

        # A fixed expected A/B response is derived only from each frozen policy.
        outcome_a = synthetic_worker.run_once(job_a_id)
        outcome_b = synthetic_worker.run_once(job_b_id)
        assert outcome_a.state == outcome_b.state == "completed"
        assert synthetic_worker.run_once(job_a_id) is None  # duplicate execution is idempotent

        with w.sf() as session:
            completed_a = session.get(GradingJob, job_a_id)
            completed_b = session.get(GradingJob, job_b_id)
            assert completed_a.state == completed_b.state == "completed"
            assert completed_a.items[0].score == 10
            assert completed_a.items[0].max_score == 10
            assert completed_b.items[0].score == 5
            assert completed_b.items[0].max_score == 10
            result_a = completed_a.items[0].metadata_json["result"]
            result_b = completed_b.items[0].metadata_json["result"]
            assert result_a["criteria"][0]["criterion_id"] == "c1"
            assert result_b["criteria"][0]["criterion_id"] == "c1"
            assert "合成検証結果" in result_a["criteria"][0]["reason"]
            assert "合成検証結果" in result_b["criteria"][0]["reason"]
            assert completed_a.metadata_json["grading_execution"]["snapshot_sha256"] == snapshot_a["snapshot_sha256"]
            assert completed_b.metadata_json["grading_execution"]["snapshot_sha256"] == snapshot_b["snapshot_sha256"]

        detail_a = w.client.get(base(w) + f"/grading/{submission_a['id']}")
        detail_b = w.client.get(base(w) + f"/grading/{submission_b['id']}")
        assert detail_a.status_code == detail_b.status_code == 200
        review_a, review_b = detail_a.json(), detail_b.json()
        assert review_a["submission"]["confirmed_revision_label"] == "第1版"
        assert review_b["submission"]["confirmed_revision_label"] == "第2版"
        question_review_a = review_a["questions"][0]
        question_review_b = review_b["questions"][0]
        assert question_review_a["question"]["text"] == "Question edition A"
        assert question_review_a["model_answer"]["content"] == "ModelAnswer edition A"
        assert [level["score"] for level in question_review_a["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 10]
        assert question_review_b["question"]["text"] == "Question edition B"
        assert question_review_b["model_answer"]["content"] == "ModelAnswer edition B"
        assert [level["score"] for level in question_review_b["rubric"]["entry"]["criteria"][0]["levels"]] == [0, 5, 10]
        assert question_review_a["authoritative"]["score"] == 10
        assert question_review_b["authoritative"]["score"] == 5
        assert "合成検証結果" in question_review_a["criteria"][0]["reason"]

        finalize_a = w.client.post(base(w) + f"/grading/{submission_a['id']}/finalize", json={})
        finalize_b = w.client.post(base(w) + f"/grading/{submission_b['id']}/finalize", json={})
        assert finalize_a.status_code == finalize_b.status_code == 200
        assert finalize_a.json()["confirmed_revision_label"] == "第1版"
        assert finalize_b.json()["confirmed_revision_label"] == "第2版"
        assert finalize_a.json()["total_points"] == finalize_b.json()["total_points"] == 10
        assert w.client.post(base(w) + f"/grading/{submission_a['id']}/finalize", json={}).json()["created"] is False
        assert w.client.post(base(w) + f"/grading/{submission_b['id']}/finalize", json={}).json()["created"] is False

        # A stale-job recovery retry revalidates the existing artifact manifest;
        # it neither regenerates the score nor resolves the current edition.
        with w.sf() as session:
            retried = session.get(GradingJob, job_a_id)
            retried.state = "preparing"
            retried.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
            session.commit()
        retry = synthetic_worker.run_once(job_a_id)
        assert retry.state == "completed"
        with w.sf() as session:
            retried = session.get(GradingJob, job_a_id)
            assert retried.confirmed_authoring_revision_id == edition_a["id"]
            assert retried.items[0].score == 10
            assert retried.items[0].metadata_json["manifest_sha256"]
            assert session.scalar(select(func.count()).select_from(StudentAnswerReconstruction).where(
                StudentAnswerReconstruction.submission_id.in_([submission_a["id"], submission_b["id"]]))) == 0
            assert session.scalar(select(func.count()).select_from(DomainEvent).where(
                DomainEvent.event_type.in_(["results_published", "results_unpublished"]))) == 0
            from scoring.publishing import ResultPublicationService
            publication = ResultPublicationService(session, root=tmp_path / "artifacts").publication_state(
                w.legacy, submission_a["id"])
            assert publication["published"] is False

        # Allowlist denial is an authorization failure before Job creation.
        with w.sf() as session:
            before = session.scalar(select(func.count()).select_from(GradingJob))
            with pytest.raises(PermissionError, match="SYNTHETIC_VALIDATION_TEST_NOT_ALLOWLISTED"):
                create_synthetic_validation_job(
                    session, disposable_root=tmp_path, validation_database_path=validation_db,
                    allowlisted_test_id=w.fresh,
                    test_id=w.legacy, submission_id=submission_a["id"],
                    question_id=w.question, synthetic_answer_text="denied", job_name="denied")
            assert session.scalar(select(func.count()).select_from(GradingJob)) == before

        # Historical null-pin rows remain legacy and cannot enter this path.
        unconfirmed_pdf = tmp_path / "artifacts" / "legacy-null-pin.pdf"
        with fitz.open() as pdf:
            pdf.new_page()
            pdf.save(unconfirmed_pdf)
        with w.sf() as session:
            fresh_test = session.get(TestRow, w.fresh)
            service = DomainService(session)
            material = service.material(w.fresh, material_type="student_answer_source",
                storage_ref=str(unconfirmed_pdf), original_filename=unconfirmed_pdf.name,
                mime_type="application/pdf", sha256=sha256_file(unconfirmed_pdf))
            student = service.student(fresh_test.course_offering_id,
                student_identifier="SYNTHETIC-LEGACY-NULL-PIN", display_name="Synthetic Legacy")
            legacy_submission = service.submission(w.fresh, student.id,
                submission_key="synthetic-legacy-null-pin", material_id=material.id)
            assert legacy_submission.confirmed_authoring_revision_id is None
            session.commit()
            with pytest.raises(Exception, match="WEB_GRADING_REVISION_REQUIRED"):
                create_synthetic_validation_job(
                    session, disposable_root=tmp_path, validation_database_path=validation_db,
                    allowlisted_test_id=w.fresh,
                    test_id=w.fresh, submission_id=legacy_submission.id,
                    question_id=w.question, synthetic_answer_text="legacy must fail closed",
                    job_name="legacy-null-pin")
    finally:
        if normal_job_id:
            with normal.sf() as session:
                job = session.get(GradingJob, normal_job_id)
                if job:
                    session.delete(job)
                    session.commit()
        normal.client.close()
        normal.engine.dispose()
        try:
            next(normal_generator)
        except StopIteration:
            pass
