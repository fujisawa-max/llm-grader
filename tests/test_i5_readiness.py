"""I.5 production-readiness checks using deterministic service fixtures."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from scoring.api.grading_review import build_grading_csv
from scoring.auth import teacher_guard
from scoring.db.models import (Course, CourseOffering, DomainEvent, GradingJob,
                               GradingJobEvent, Student, StudentSubmission, User)
from scoring.db.repository import JobRepository
from scoring.grading_actions import GradingActionService
from scoring.publishing import PublicationError, ResultPublicationService
from scoring.recovery import build_artifact_manifest, verify_artifact_manifest

from .test_publishing import fixture


def _request(headers=None):
    return Request({
        "type": "http", "method": "GET", "path": "/",
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    })


def test_full_result_lifecycle_is_consistent_and_idempotent(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)

    first, created = service.publish_submission(test.id, submission.id, actor_user_id="teacher")
    again, duplicate = service.publish_submission(test.id, submission.id, actor_user_id="teacher")
    assert created is True and duplicate is False
    assert first["publication_id"] == again["publication_id"]

    result = service.student_result(submission.id, requester_student_id=student.student_identifier)
    assert (result["score"], result["max_score"], result["status"]) == (8, 10, "PUBLISHED")
    csv = build_grading_csv(session, test.id)
    assert ",8,8,10.0,80.0,YES,0,0,YES," in csv
    assert service.result_pdf_bytes("", submission.id, requester_student_id=student.id, student=True).startswith(b"%PDF")

    override = service.feedback_override(test.id, submission.id, question.id, "Clear final step.",
                                         teacher_note="private", actor_user_id="teacher")
    duplicate_override = service.feedback_override(test.id, submission.id, question.id, "Clear final step.",
                                                   teacher_note="private", actor_user_id="teacher")
    assert override["created"] is True and duplicate_override["created"] is False
    changed = service.student_result(submission.id, requester_student_id=student.id)
    assert changed["status"] == "RESULT_CHANGED_AFTER_PUBLICATION"
    service.publish_submission(test.id, submission.id, actor_user_id="teacher")
    republished = service.student_result(submission.id, requester_student_id=student.id)
    assert republished["status"] == "PUBLISHED"
    assert republished["questions"][0]["feedback"] == "Clear final step."
    assert len(session.scalars(select(DomainEvent).where(
        DomainEvent.event_type == "results_published")).all()) == 2


def test_student_cross_submission_and_unpublished_isolation(tmp_path):
    session, test, _question, student, submission = fixture(tmp_path)
    other = Student(id=str(uuid4()), course_offering_id=student.course_offering_id,
                    student_identifier="s2", display_name="Other")
    other_submission = StudentSubmission(id=str(uuid4()), test_id=test.id, student_id=other.id,
                                         submission_key="s2", material_id=submission.material_id)
    session.add_all([other, other_submission])
    session.commit()
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    service.publish_submission(test.id, submission.id)
    with pytest.raises(PublicationError, match="STUDENT_ACCESS_DENIED"):
        service.student_result(submission.id, requester_student_id=other.student_identifier)
    with pytest.raises(PublicationError, match="RESULT_NOT_PUBLISHED"):
        service.student_result(other_submission.id, requester_student_id=other.student_identifier)
    with pytest.raises(PublicationError, match="PUBLISHED_VISUAL_ASSET_NOT_FOUND"):
        service.visual_path_for_student_token("not-a-token", requester_student_id=other.student_identifier)


def test_teacher_action_is_idempotent_and_finalized_submission_rejects_regrade(tmp_path):
    session, test, question, _student, submission = fixture(tmp_path)
    from scoring.grading_execution import snapshot_hash
    job = session.query(GradingJob).first()
    snapshot = dict(job.metadata_json["grading_execution"])
    snapshot["assets"] = []
    snapshot["snapshot_sha256"] = snapshot_hash(snapshot)
    job.metadata_json = {"grading_execution": snapshot}
    session.commit()
    actions = GradingActionService(session, artifact_root=tmp_path)
    first, created = actions.teacher_decision(
        test_id=test.id, submission_id=submission.id, question_id=question.id,
        criterion_scores=[{"criterion_id": "criterion_1", "score": 10}],
        teacher_reason="reviewed", teacher_note="same", teacher_user_id="teacher")
    second, duplicate = actions.teacher_decision(
        test_id=test.id, submission_id=submission.id, question_id=question.id,
        criterion_scores=[{"criterion_id": "criterion_1", "score": 10}],
        teacher_reason="reviewed", teacher_note="same", teacher_user_id="teacher")
    assert created is True and duplicate is False and first.id == second.id
    with pytest.raises(ValueError, match="REGRADE_AFTER_FINALIZATION"):
        actions.request_regrade(test_id=test.id, submission_id=submission.id,
                                question_id=question.id, reason="late review")


def test_teacher_guard_requires_active_course_owner():
    session, test, _question, _student, _submission = fixture(__import__("pathlib").Path("/tmp"))
    user = User(id=str(uuid4()), display_name="Teacher", is_active=True)
    course = Course(id=str(uuid4()), owner_user_id=user.id, name="Course")
    offering = CourseOffering(id=test.course_offering_id, course_id=course.id,
                              academic_year=2026, term="fall")
    session.add_all([user, course, offering])
    session.commit()
    with pytest.raises(HTTPException) as missing:
        teacher_guard(test.id, _request(), session)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as wrong_role:
        teacher_guard(test.id, _request({"X-Role": "student", "X-User-ID": user.id}), session)
    assert wrong_role.value.status_code == 403
    assert teacher_guard(test.id, _request({"X-Role": "teacher", "X-User-ID": user.id}), session).id == user.id


def test_artifact_manifest_detects_tampering_without_mutating_tree(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("immutable", encoding="utf-8")
    manifest = build_artifact_manifest(tmp_path)
    assert verify_artifact_manifest(tmp_path, manifest)["valid"] is True
    artifact.write_text("changed", encoding="utf-8")
    report = verify_artifact_manifest(tmp_path, manifest)
    assert report["valid"] is False and report["mismatched"] == ["artifact.json"]


def test_restart_recovery_requeues_stale_job_without_changing_snapshot(tmp_path):
    session, _test, _question, _student, _submission = fixture(tmp_path)
    job = session.query(GradingJob).first()
    snapshot_sha = job.metadata_json["grading_execution"]["snapshot_sha256"]
    job.state = "preparing"
    job.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.commit()
    recovered = JobRepository(session).recover_stale_jobs(stale_after_seconds=60)
    assert [row.id for row in recovered] == [job.id]
    assert session.get(GradingJob, job.id).state == "queued"
    assert session.get(GradingJob, job.id).metadata_json["grading_execution"]["snapshot_sha256"] == snapshot_sha
    assert session.query(GradingJobEvent).filter_by(
        job_id=job.id, event_type="job_recovered_after_restart").count() == 1
