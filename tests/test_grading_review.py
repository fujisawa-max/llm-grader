"""Read-only grading review DTOs use the authoritative resolver and history."""

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scoring.db.database import Base
from scoring.db.models import (
    GradingJob,
    GradingJobItem,
    ModelAnswer,
    RubricVersion,
    Student,
    StudentSubmission,
    Test,
    TestQuestion,
    TeacherGradingDecision,
)
from scoring.grading_review import GradingReviewService
from scoring.grading_actions import GradingActionService
from scoring.api.grading_review import build_grading_csv
from scoring.review_workspace import ReviewWorkspaceService
from scoring.grading_execution import snapshot_hash
from scoring.pdf_native import canonical_hash


def _fixture(total=10):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    offering = str(uuid4())
    test = Test(id=str(uuid4()), course_offering_id=offering, name="sample", total_points=total)
    question = TestQuestion(id=str(uuid4()), test_id=test.id, question_number="1",
                            display_label="問題1", stable_question_key="q1", question_text="説明",
                            max_points=total)
    student = Student(id=str(uuid4()), course_offering_id=offering, student_identifier="s1")
    submission = StudentSubmission(id=str(uuid4()), test_id=test.id, student_id=student.id,
                                   submission_key="s1", material_id=str(uuid4()))
    model_answer = ModelAnswer(id=str(uuid4()), test_id=test.id, question_id=question.id,
                               answer_text="reference", version=1, is_current=True)
    rubric = RubricVersion(id=str(uuid4()), test_id=test.id, version=1, status="approved",
                           rubric_json={"questions": [{"question_id": question.id,
                               "max_points": total, "criteria": [{"id": "criterion_1",
                               "description": "criterion", "points": total,
                               "levels": [{"score": total}, {"score": 0}]}]}]})
    session.add_all([test, question, student, submission, model_answer, rubric])
    session.flush()
    return session, test, question, student, submission


def _job(session, test, question, submission, score, *, needs_review=False, result=None):
    job = GradingJob(id=str(uuid4()), external_id=str(uuid4()), execution_mode="test",
                     state="completed", assignment_path="a", run_path="r", config_path="c",
                     test_id=test.id, metadata_json={"grading_execution": {
                         "snapshot_sha256": str(uuid4()),
                         "bundle": {"identity": {"question_id": question.id},
                                    "student_answer": {"submission_id": submission.id,
                                                        "answer_text": "answer"},
                                    "bundle_sha256": str(uuid4())}}})
    item = GradingJobItem(id=str(uuid4()), job_id=job.id, item_key="q",
                          state="completed", score=score, max_score=question.max_points,
                          needs_review=needs_review,
                          metadata_json={"submission_id": submission.id, "question_id": question.id,
                                         "bundle_sha256": job.metadata_json["grading_execution"]["bundle"]["bundle_sha256"],
                                         "result": result or {"criteria": [{"criterion_id": "criterion_1", "score": score, "max_score": question.max_points}]}})
    session.add_all([job, item])
    session.flush()
    return job


def _valid_action_job(session, test, question, submission, rubric):
    job = _job(session, test, question, submission, 10)
    entry = rubric.rubric_json["questions"][0]
    bundle = {"identity": {"test_id": test.id, "question_id": question.id},
              "student_answer": {"submission_id": submission.id, "student_id": submission.student_id,
                                  "sha256": "a" * 64},
              "question": {"max_points": question.max_points},
              "rubric": {"id": rubric.id, "entry": entry, "entry_sha256": canonical_hash(entry)},
              "bundle_sha256": "b" * 64}
    snapshot = {"bundle": bundle, "assets": [], "snapshot_sha256": ""}
    snapshot["snapshot_sha256"] = snapshot_hash(snapshot)
    job.rubric_version_id = rubric.id
    job.metadata_json = {"grading_execution": snapshot}
    session.flush()
    return job


def test_teacher_adjudication_precedes_model_and_history_is_visible():
    session, test, question, student, submission = _fixture()
    old = _job(session, test, question, submission, 0)
    decision = TeacherGradingDecision(
        id=str(uuid4()), test_id=test.id, submission_id=submission.id, question_id=question.id,
        source_grading_job_id=old.id, rubric_version_id=session.query(RubricVersion).first().id,
        decision_version=1, status="COMPLETE", score=10, max_score=10,
        criterion_scores=[{"criterion_id": "criterion_1", "score": 10, "max_score": 10}],
        teacher_reason="confirmed", input_snapshot_sha256="snapshot", bundle_sha256="bundle",
        artifact_ref="teacher/result.json", artifact_sha256="a" * 64)
    session.add(decision)
    session.commit()
    detail = GradingReviewService(session).detail(test.id, submission.id)
    row = detail["questions"][0]
    assert row["authoritative"]["source"] == "TEACHER_ADJUDICATION"
    assert row["authoritative"]["score"] == 10
    assert row["history"]
    assert row["criteria"][0]["score"] == 10


def test_warning_and_visual_assets_are_exposed_without_mutation():
    session, test, question, student, submission = _fixture()
    job = _job(session, test, question, submission, 0, needs_review=True,
               result={"criteria": [], "review_reasons": ["GRADING_REVIEW_REQUIRED"],
                       "feedback": "review"})
    bundle = dict(job.metadata_json["grading_execution"]["bundle"])
    bundle["student_answer"] = {**bundle["student_answer"], "answer_text": "answer"}
    bundle["visual_assets"] = [
        {"asset_id": "q", "role": "question_context", "sha256": "q"},
        {"asset_id": "m", "role": "model_answer_reference", "sha256": "m"},
        {"asset_id": "s", "role": "student_visual_answer", "sha256": "s", "bbox": [0, 0, 1, 1]},
    ]
    job.metadata_json = {"grading_execution": {**job.metadata_json["grading_execution"], "bundle": bundle}}
    session.commit()
    detail = GradingReviewService(session).detail(test.id, submission.id)
    row = detail["questions"][0]
    assert "GRADING_REVIEW_REQUIRED" in row["warnings"]
    assert "VISUAL_EVIDENCE" in row["warnings"]
    assert {asset["role"] for asset in row["visual_assets"]} == {
        "question_context", "model_answer_reference", "student_visual_answer"
    }


def test_overview_uses_authoritative_test_total_for_q4_style_total():
    session, test, question, student, submission = _fixture(total=110)
    _job(session, test, question, submission, 95)
    session.commit()
    overview = GradingReviewService(session).overview(test.id)
    assert overview["test"]["total_points"] == 110
    assert overview["students"][0]["max"] == 110
    assert overview["students"][0]["percentage"] == round(95 / 110 * 100, 2)


def test_teacher_decision_is_append_only_and_invalid_levels_are_rejected(tmp_path):
    session, test, question, student, submission = _fixture()
    rubric = session.query(RubricVersion).first()
    _valid_action_job(session, test, question, submission, rubric)
    actions = GradingActionService(session, artifact_root=tmp_path)
    try:
        actions.teacher_decision(test_id=test.id, submission_id=submission.id, question_id=question.id,
                                criterion_scores=[{"criterion_id": "criterion_1", "score": 5}],
                                teacher_reason="bad")
    except ValueError as exc:
        assert str(exc) == "TEACHER_GRADING_SCORE_NOT_ALLOWED"
    else:
        raise AssertionError("invalid score was accepted")
    row, created = actions.teacher_decision(
        test_id=test.id, submission_id=submission.id, question_id=question.id,
        criterion_scores=[{"criterion_id": "criterion_1", "score": 10}],
        teacher_reason="confirmed", teacher_note="note")
    assert created and row.decision_version == 1
    row2, created2 = actions.teacher_decision(
        test_id=test.id, submission_id=submission.id, question_id=question.id,
        criterion_scores=[{"criterion_id": "criterion_1", "score": 0}],
        teacher_reason="revised")
    assert created2 and row2.decision_version == 2
    assert session.query(TeacherGradingDecision).count() == 2


def test_regrade_request_blocks_finalize_until_resolved(tmp_path):
    session, test, question, student, submission = _fixture()
    _job(session, test, question, submission, 10)
    actions = GradingActionService(session, artifact_root=tmp_path)
    request = actions.request_regrade(test_id=test.id, submission_id=submission.id,
                                      question_id=question.id, reason="source changed")
    assert request["status"] == "REGRADING_REQUESTED"
    try:
        actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    except ValueError as exc:
        assert str(exc) == "FINALIZE_REGRADE_REQUEST_PENDING"
    else:
        raise AssertionError("pending regrade did not block finalization")


def test_finalize_is_append_only_and_idempotent(tmp_path):
    session, test, question, student, submission = _fixture()
    _job(session, test, question, submission, 10)
    actions = GradingActionService(session, artifact_root=tmp_path)
    payload, created = actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    assert created and payload["status"] == "FINALIZED"
    again, created_again = actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    assert not created_again and again["finalization_id"] == payload["finalization_id"]


def test_teacher_decision_resolves_model_review_for_finalization(tmp_path):
    session, test, question, student, submission = _fixture()
    rubric = session.query(RubricVersion).first()
    job = _valid_action_job(session, test, question, submission, rubric)
    item = job.items[0]
    item.needs_review = True
    item.metadata_json = {**item.metadata_json, "result": {
        "criteria": [{"criterion_id": "criterion_1", "score": 10, "max_score": 10}],
        "review_reasons": ["GRADING_REVIEW_REQUIRED"],
    }}
    actions = GradingActionService(session, artifact_root=tmp_path)
    actions.teacher_decision(test_id=test.id, submission_id=submission.id, question_id=question.id,
                             criterion_scores=[{"criterion_id": "criterion_1", "score": 10}],
                             teacher_reason="reviewed")
    payload, created = actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    assert created and payload["status"] == "FINALIZED"


def test_csv_export_has_bom_and_authoritative_test_total():
    session, test, question, student, submission = _fixture(total=110)
    _job(session, test, question, submission, 95)
    content = build_grading_csv(session, test.id)
    assert content.startswith("\ufeff")
    assert "1_score" in content.splitlines()[0]
    assert ",110," in content


def test_review_and_regrade_queues_filter_and_reject_without_job(tmp_path):
    session, test, question, student, submission = _fixture()
    _job(session, test, question, submission, 10)
    actions = GradingActionService(session, artifact_root=tmp_path)
    request = actions.request_regrade(test_id=test.id, submission_id=submission.id,
                                      question_id=question.id, reason="verify source")
    workspace = ReviewWorkspaceService(session)
    queue = workspace.review_queue(test.id)
    assert queue["items"] and queue["progress"]["regrade_pending"] == 1
    regrades = workspace.regrade_queue(test.id)
    assert regrades["pending_count"] == 1
    rejected = actions.reject_regrade(request_id=request["request_id"], test_id=test.id,
                                      reason="no longer needed")
    assert rejected["status"] == "REJECTED"
    assert not workspace.regrade_queue(test.id)["requests"]


def test_approve_regrade_creates_one_job_and_duplicate_is_blocked(tmp_path):
    session, test, question, student, submission = _fixture()
    rubric = session.query(RubricVersion).first()
    source = _valid_action_job(session, test, question, submission, rubric)
    config = tmp_path / "config.json"
    config.write_text('{"models":{"grader":{"model_id":"grader"}}}', encoding="utf-8")
    source.config_path = str(config)
    session.flush()
    actions = GradingActionService(session, artifact_root=tmp_path,
                                   execution_job_factory=lambda *args, **kwargs:
                                   _valid_action_job(session, test, question, submission, rubric))
    request = actions.request_regrade(test_id=test.id, submission_id=submission.id,
                                      question_id=question.id, reason="recheck")
    approval = actions.approve_regrade(request_id=request["request_id"], test_id=test.id,
                                       approved_by="teacher")
    assert approval["status"] == "APPROVED"
    assert approval["job_id"]
    assert session.query(GradingJob).count() == 2
    try:
        actions.approve_regrade(request_id=request["request_id"], test_id=test.id)
    except ValueError as exc:
        assert str(exc) == "REGRADE_REQUEST_NOT_PENDING"
    else:
        raise AssertionError("duplicate approval created a second job")


def test_failed_regrade_stays_review_blocking_until_rejected(tmp_path):
    session, test, question, student, submission = _fixture()
    _job(session, test, question, submission, 10)
    actions = GradingActionService(session, artifact_root=tmp_path)
    request = actions.request_regrade(test_id=test.id, submission_id=submission.id,
                                      question_id=question.id, reason="runtime failure")
    session.add(__import__("scoring.db.models", fromlist=["DomainEvent"]).DomainEvent(
        entity_type="regrade_request", entity_id=request["request_id"],
        event_type="regrade_failed", payload={"request_id": request["request_id"]}))
    session.flush()
    try:
        actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    except ValueError as exc:
        assert str(exc) == "FINALIZE_REGRADE_REQUEST_PENDING"
    else:
        raise AssertionError("failed regrade did not block finalization")
    actions.reject_regrade(request_id=request["request_id"], test_id=test.id,
                           reason="keep existing result")
    payload, created = actions.finalize_submission(test_id=test.id, submission_id=submission.id)
    assert created and payload["status"] == "FINALIZED"
