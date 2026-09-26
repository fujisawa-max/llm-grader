"""Read-only views for the teacher grading review UI.

The review surface deliberately contains no write path.  It resolves each
question through :func:`resolve_authoritative_result`, then adds the immutable
input/history records needed to audit that decision.  Selection precedence is
therefore kept in the same production helper used by the grading audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .db.models import (
    GradingJob,
    DomainEvent,
    ModelAnswer,
    RubricVersion,
    Student,
    StudentAnswerExtractionResult,
    StudentAnswerExtractionRun,
    StudentAnswerReconstruction,
    StudentSubmission,
    Test,
    TestQuestion,
    TestQuestionAsset,
    TeacherGradingDecision,
)
from .grading_audit import (
    GRADING_MODEL_INPUT_CONTRADICTION,
    GRADING_MODEL_SELF_CONTRADICTION,
    grading_response_warnings,
    resolve_authoritative_result,
    resolve_selected_reconstruction,
)
from .grading_context import ContextError, EffectiveQuestionContextBuilder
from .pdf_native import canonical_hash
from .student_identity import StudentIdentityService


REVIEW_REQUIRED = "GRADING_REVIEW_REQUIRED"
RECONSTRUCTION_HISTORY = "RECONSTRUCTION_CORRECTION_HISTORY"
VISUAL_EVIDENCE = "VISUAL_EVIDENCE"
HISTORICAL_GRADING_FAILURE = "HISTORICAL_GRADING_FAILURE"
MODEL_NEW_RESULT_AVAILABLE = "MODEL_NEW_RESULT_AVAILABLE"
REVIEW_CODES = frozenset({REVIEW_REQUIRED, GRADING_MODEL_INPUT_CONTRADICTION,
                          GRADING_MODEL_SELF_CONTRADICTION,
                          "ANSWER_RECONSTRUCTION_REVIEW_REQUIRED"})


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _target(test_id: str, submission_id: str, question_id: str) -> str:
    return f"{test_id}/{submission_id}/{question_id}"


def _read_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _public_artifact_ref(value: str | None) -> str | None:
    """Return an opaque/relative reference, never a local filesystem path."""
    if not value:
        return None
    text = str(value).replace("\\", "/")
    if "/artifacts/" in text:
        text = "artifacts/" + text.split("/artifacts/", 1)[1]
    elif text.startswith("/"):
        text = Path(text).name
    return text


def _bundle(job: GradingJob) -> dict[str, Any]:
    return ((job.metadata_json or {}).get("grading_execution") or {}).get("bundle") or {}


def _snapshot(job: GradingJob) -> dict[str, Any]:
    return (job.metadata_json or {}).get("grading_execution") or {}


def _item_target(item, job: GradingJob, submission_id: str, question_id: str) -> bool:
    metadata = item.metadata_json or {}
    bundle = _bundle(job)
    identity = bundle.get("identity") or {}
    answer = bundle.get("student_answer") or {}
    return (
        (metadata.get("submission_id") == submission_id and metadata.get("question_id") == question_id)
        or (identity.get("question_id") == question_id and answer.get("submission_id") == submission_id)
    )


def _model_record(job: GradingJob, item, target: str) -> dict[str, Any]:
    snapshot = _snapshot(job)
    bundle = _bundle(job)
    metadata = item.metadata_json or {}
    result = metadata.get("result")
    if not isinstance(result, dict):
        result = _read_json(item.normalized_result_path) or {}
    return {
        "id": str(job.id),
        "item_id": str(item.id),
        "target": target,
        "state": str(item.state or job.state),
        "status": str(item.state or job.state),
        "score": item.score,
        "max_score": item.max_score,
        "needs_review": bool(item.needs_review),
        "completed_at": _iso(item.completed_at or job.completed_at or job.created_at),
        "created_at": _iso(job.created_at),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "bundle_sha256": metadata.get("bundle_sha256") or bundle.get("bundle_sha256"),
        "bundle": bundle,
        "result": result,
        "artifact_ref": _public_artifact_ref(item.normalized_result_path),
        "error_type": item.error_type or job.error_type,
        "error_message": item.error_message or job.error_message,
    }


def _decision_record(row: TeacherGradingDecision, target: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "target": target,
        "status": row.status,
        "score": row.score,
        "max_score": row.max_score,
        "decision_version": row.decision_version,
        "criterion_scores": row.criterion_scores or [],
        "teacher_reason": row.teacher_reason,
        "teacher_note": (row.provenance or {}).get("teacher_note"),
        "bundle_sha256": row.bundle_sha256,
        "snapshot_sha256": row.input_snapshot_sha256,
        "artifact_ref": _public_artifact_ref(row.artifact_ref),
        "artifact_sha256": row.artifact_sha256,
        "created_at": _iso(row.created_at),
        "source": "TEACHER_ADJUDICATION",
    }


class GradingReviewService:
    """Build overview/detail DTOs without mutating the session."""

    def __init__(self, session, *, root: str | Path | None = None,
                 identity_root: str | Path | None = None):
        self.s = session
        self.root = root
        self.identity_root = identity_root or root

    def _questions(self, test_id: str) -> list[TestQuestion]:
        return list(self.s.scalars(select(TestQuestion).where(
            TestQuestion.test_id == test_id,
            TestQuestion.is_gradable.is_(True),
        ).order_by(TestQuestion.sort_order, TestQuestion.id)))

    def _rubric(self, test_id: str) -> RubricVersion | None:
        return self.s.scalar(select(RubricVersion).where(
            RubricVersion.test_id == test_id,
            RubricVersion.status == "approved",
        ).order_by(RubricVersion.version.desc(), RubricVersion.created_at.desc()))

    def _context_builder(self, test_id: str):
        questions = list(self.s.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)))
        assets = list(self.s.scalars(select(TestQuestionAsset).join(TestQuestion).where(
            TestQuestion.test_id == test_id)))
        return EffectiveQuestionContextBuilder(questions, assets, root=self.root)

    def _student_identity(self, submission: StudentSubmission) -> dict[str, Any]:
        """Resolve the source-image identity without exposing fixture keys."""
        if self.identity_root:
            try:
                value = StudentIdentityService(self.s, root=self.identity_root).load(submission.id)
            except (OSError, ValueError, TypeError):
                value = None
            if value:
                return value
        return {
            "student_number": "", "student_name": "",
            "display_label": "学生情報未確認", "confidence": 0.0,
            "review_required": True,
        }

    def _reconstruction(self, submission_id: str, question_id: str) -> tuple[Any | None, list[Any]]:
        revisions = list(self.s.scalars(select(StudentAnswerReconstruction).join(
            StudentAnswerExtractionResult,
            StudentAnswerReconstruction.extraction_result_id == StudentAnswerExtractionResult.id,
        ).join(
            StudentAnswerExtractionRun,
            StudentAnswerExtractionResult.run_id == StudentAnswerExtractionRun.id,
        ).where(
            StudentAnswerReconstruction.submission_id == submission_id,
            StudentAnswerReconstruction.question_id == question_id,
            StudentAnswerExtractionRun.selected.is_(True),
            StudentAnswerExtractionRun.status == "completed",
        ).order_by(StudentAnswerReconstruction.version.desc())))
        if not revisions:
            return None, []
        try:
            current = resolve_selected_reconstruction(revisions)
        except ValueError:
            current = None
        history = list(self.s.scalars(select(StudentAnswerReconstruction).where(
            StudentAnswerReconstruction.submission_id == submission_id,
            StudentAnswerReconstruction.question_id == question_id,
        ).order_by(StudentAnswerReconstruction.version)))
        return current, history

    def _jobs(self, test_id: str, submission_id: str, question_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for job in self.s.scalars(select(GradingJob).where(
            GradingJob.test_id == test_id).order_by(GradingJob.created_at)):
            for item in job.items:
                if _item_target(item, job, submission_id, question_id):
                    rows.append(_model_record(job, item, _target(test_id, submission_id, question_id)))
        return rows

    def _resolve(self, test_id: str, submission_id: str, question_id: str, jobs: list[dict[str, Any]]):
        target = _target(test_id, submission_id, question_id)
        decisions = [_decision_record(row, target) for row in self.s.scalars(select(
            TeacherGradingDecision).where(
                TeacherGradingDecision.submission_id == submission_id,
                TeacherGradingDecision.question_id == question_id,
        ).order_by(TeacherGradingDecision.decision_version))]
        completed = [row for row in jobs if row["state"].lower() == "completed"]
        latest = completed[-1] if completed else None
        try:
            result = resolve_authoritative_result(
                target,
                teacher_decisions=decisions,
                model_results=jobs,
                current_snapshot_sha=latest.get("snapshot_sha256") if latest else None,
                current_bundle_sha=latest.get("bundle_sha256") if latest else None,
            )
        except ValueError:
            result = None
        selected = next((row for row in decisions if row["id"] == getattr(result, "result_id", None)), None)
        model = next((row for row in jobs if row["id"] == getattr(result, "result_id", None)), None)
        return result, selected, model, decisions

    def _warnings(self, current, history, jobs, model, bundle):
        warnings: list[str] = []
        if len(history) > 1:
            warnings.append(RECONSTRUCTION_HISTORY)
        if bundle.get("visual_assets"):
            warnings.append(VISUAL_EVIDENCE)
        if any(bool(row.get("needs_review")) for row in jobs):
            warnings.append(REVIEW_REQUIRED)
        if any(row.get("error_type") for row in jobs):
            warnings.append(HISTORICAL_GRADING_FAILURE)
        if len(jobs) > 1:
            warnings.append(MODEL_NEW_RESULT_AVAILABLE)
        if model and isinstance(model.get("result"), dict):
            warnings.extend(grading_response_warnings(model["result"], bundle))
            reasons = model["result"].get("review_reasons") or []
            if reasons:
                warnings.append(REVIEW_REQUIRED)
        return list(dict.fromkeys(warnings))

    def _action_events(self, test_id, submission_id, question_id, decision_ids=()):
        events = []
        for event in self.s.scalars(select(DomainEvent)):
            payload = event.payload or {}
            if event.entity_id in set(decision_ids):
                events.append(event)
            elif (payload.get("test_id") == test_id and payload.get("submission_id") == submission_id
                  and payload.get("question_id") == question_id):
                events.append(event)
        return events

    @staticmethod
    def _reconstruction_public(row):
        if row is None:
            return None
        return {
            "id": row.id, "version": row.version, "status": row.status,
            "answer_text": row.answer_text, "source_sha256": row.source_sha256,
            "context_sha256": row.context_sha256, "output_sha256": row.output_sha256,
            "artifact_ref": _public_artifact_ref(row.artifact_ref), "origin": (row.model_identity or {}).get("origin"),
            "created_at": _iso(row.created_at),
        }

    def _question_detail(self, test: Test, sub: StudentSubmission, q: TestQuestion, rubric, context_builder):
        current_recon, recon_history = self._reconstruction(sub.id, q.id)
        jobs = self._jobs(test.id, sub.id, q.id)
        result, decision, model, decisions = self._resolve(test.id, sub.id, q.id, jobs)
        bundle = _bundle_from_model(model, jobs)
        warning_codes = self._warnings(current_recon, recon_history, jobs, model, bundle)
        # A persisted teacher decision resolves model review output for the
        # target.  Keep those model warnings in the audit trail, but do not
        # block finalization after the teacher has adjudicated the question.
        review_flags = [] if decision else [code for code in warning_codes if code in REVIEW_CODES]
        model_answer = self.s.scalar(select(ModelAnswer).where(
            ModelAnswer.test_id == test.id, ModelAnswer.question_id == q.id,
            ModelAnswer.is_current.is_(True)).order_by(ModelAnswer.version.desc()))
        entry = None
        if rubric and isinstance(rubric.rubric_json, dict):
            entry = next((value for value in rubric.rubric_json.get("questions", [])
                          if isinstance(value, dict) and value.get("question_id") == q.id), None)
        try:
            context = context_builder.build(q.id)
        except (ContextError, ValueError):
            context = {"question_id": q.id, "test_id": test.id, "effective_text": q.question_text or "",
                       "context_sha256": q.content_sha256, "max_points": q.max_points, "assets": []}
        normalized_result = (model or {}).get("result") or {}
        criteria = (decision or {}).get("criterion_scores") if decision else normalized_result.get("criteria", [])
        feedback = normalized_result.get("feedback") or normalized_result.get("reasoning") or normalized_result.get("review_reasons") or []
        teacher_reason = (decision or {}).get("teacher_reason") if decision else None
        visual_assets = bundle.get("visual_assets") or []
        feedback_events = [event for event in self.s.scalars(select(DomainEvent).where(
            DomainEvent.entity_type == "teacher_feedback_override",
            DomainEvent.event_type == "teacher_feedback_override"))
            if (event.payload or {}).get("test_id") == test.id
            and (event.payload or {}).get("submission_id") == sub.id
            and (event.payload or {}).get("question_id") == q.id]
        feedback_override = None
        if feedback_events:
            event = max(feedback_events, key=lambda value: (value.created_at, value.id))
            payload = event.payload or {}
            feedback_override = {"id": event.id, "feedback": payload.get("feedback", ""),
                                 "teacher_note": payload.get("teacher_note", ""),
                                 "created_at": _iso(event.created_at)}
        history = []
        for row in jobs:
            history.append({k: row.get(k) for k in (
                "id", "item_id", "state", "score", "max_score", "needs_review", "completed_at",
                "snapshot_sha256", "bundle_sha256", "artifact_ref", "error_type", "error_message")})
        history.extend(decisions)
        action_events = self._action_events(test.id, sub.id, q.id, [row["id"] for row in decisions])
        history.extend({"id": event.id, "source": "AUDIT", "event_type": event.event_type,
                        "status": (event.payload or {}).get("status"),
                        "created_at": _iso(event.created_at), "payload": event.payload}
                       for event in action_events)
        completed_request_ids = {
            (event.payload or {}).get("request_id")
            for event in self.s.scalars(select(DomainEvent).where(
                DomainEvent.event_type == "regrade_completed"))
        }
        regrade_requests = []
        for event in action_events:
            if event.event_type != "regrade_requested":
                continue
            payload = dict(event.payload or {})
            payload["status"] = (
                "REGRADING_COMPLETED"
                if payload.get("request_id") in completed_request_ids
                else payload.get("status", "REGRADING_REQUESTED")
            )
            regrade_requests.append({"id": event.id, **payload})
        return {
            "question": {"id": q.id, "label": q.display_label or q.question_number,
                         "question_number": q.question_number, "title": q.title,
                         "text": q.question_text, "stable_key": q.stable_question_key,
                         "max_points": q.max_points, "context": context},
            "authoritative": ({"score": result.score, "max_score": result.max_score,
                                "source": result.source, "result_id": result.result_id,
                                "notes": list(result.notes)} if result else None),
            "criteria": criteria,
            "feedback": feedback,
            "teacher_reason": teacher_reason,
            "student_feedback_override": feedback_override,
            "model_answer": ({"id": model_answer.id, "version": model_answer.version,
                              "content": model_answer.answer_text,
                              "sha256": canonical_hash(model_answer.answer_text)} if model_answer else None),
            "rubric": ({"id": rubric.id, "version": rubric.version, "status": rubric.status,
                        "entry": entry, "entry_sha256": canonical_hash(entry) if entry else None} if rubric else None),
            "student_answer": {"submission_id": (bundle.get("student_answer") or {}).get("submission_id") or sub.id,
                               "reconstruction": self._reconstruction_public(current_recon),
                               "source": (bundle.get("student_answer") or {}).get("source"),
                               "answer_text": (bundle.get("student_answer") or {}).get("answer_text")
                               or (self._reconstruction_public(current_recon) or {}).get("answer_text"),
                               "page_ids": (bundle.get("student_answer") or {}).get("page_ids", []),
                               "source_pages": (bundle.get("student_answer") or {}).get("source_pages", []),
                               "bundle_sha256": bundle.get("bundle_sha256")},
            "visual_assets": [self._asset_public(asset) for asset in visual_assets],
            "reconstruction_history": [self._reconstruction_public(row) for row in recon_history],
            "history": history,
            "historical_grading_count": len(jobs) + len(decisions),
            "regrade_requests": regrade_requests,
            "warnings": warning_codes,
            "review_flags": review_flags,
            "jobs": jobs,
        }

    @staticmethod
    def _asset_public(asset):
        return {key: asset.get(key) for key in (
            "asset_id", "role", "sha256", "mime_type", "bbox", "pixel_bbox", "artifact_ref",
            "question_id", "source_sha256", "provenance") if key in asset}

    def detail(self, test_id: str, submission_id: str) -> dict[str, Any]:
        test = self.s.get(Test, test_id)
        sub = self.s.get(StudentSubmission, submission_id)
        if test is None or sub is None or sub.test_id != test_id:
            raise KeyError("NOT_FOUND")
        student = self.s.get(Student, sub.student_id)
        identity = self._student_identity(sub)
        rubric = self._rubric(test_id)
        builder = self._context_builder(test_id)
        questions = [self._question_detail(test, sub, q, rubric, builder) for q in self._questions(test_id)]
        score = sum(row["authoritative"]["score"] for row in questions if row["authoritative"])
        review = sorted({code for row in questions for code in row["review_flags"]})
        teacher_count = sum(bool(row["authoritative"] and row["authoritative"]["source"] == "TEACHER_ADJUDICATION") for row in questions)
        audit_history = []
        for row in questions:
            for entry in row["history"]:
                if entry.get("source") == "AUDIT":
                    event_type = entry.get("event_type") or "audit_event"
                elif entry.get("source") == "TEACHER_ADJUDICATION":
                    event_type = "teacher_grading_decision_created"
                elif str(entry.get("state") or "").lower() == "completed":
                    event_type = "grading_completed"
                elif str(entry.get("state") or "").lower() in {"failed", "item_error"}:
                    event_type = "grading_failed"
                elif entry.get("needs_review"):
                    event_type = "grading_review_required"
                else:
                    event_type = "grading_event"
                audit_history.append({"question_id": row["question"]["id"],
                                      "question": row["question"]["label"],
                                      "event_type": event_type, **entry})
            for revision in row["reconstruction_history"]:
                audit_history.append({
                    "question_id": row["question"]["id"],
                    "question": row["question"]["label"],
                    "event_type": "reconstruction_correction" if revision.get("version", 1) > 1
                    else "reconstruction_created",
                    "source": "RECONSTRUCTION", "id": revision.get("id"),
                    "status": revision.get("status"), "created_at": revision.get("created_at"),
                    "version": revision.get("version"),
                })
        finalized = any((event.payload or {}).get("test_id") == test.id and (
            (event.payload or {}).get("submission_id") == sub.id
            or sub.id in (event.payload or {}).get("submission_ids", []))
                        for event in self.s.scalars(select(DomainEvent).where(
                            DomainEvent.event_type.in_(["grading_finalized", "test_grading_finalized"]))))
        regrade_requests = [request for row in questions for request in row.get("regrade_requests", [])]
        for event in self.s.scalars(select(DomainEvent).where(
                DomainEvent.event_type.in_(["grading_finalized", "test_grading_finalized"]))):
            payload = event.payload or {}
            if payload.get("test_id") == test.id and (
                    payload.get("submission_id") == sub.id
                    or sub.id in payload.get("submission_ids", [])):
                audit_history.append({"id": event.id, "source": "AUDIT",
                                      "event_type": event.event_type,
                                      "status": payload.get("status"),
                                      "created_at": _iso(event.created_at),
                                      "payload": payload})
        audit_history.sort(key=lambda entry: str(entry.get("created_at") or ""))
        return {"test": {"id": test.id, "name": test.name, "total_points": test.total_points},
                "submission": {"id": sub.id, "student_ref": student.student_identifier if student else None,
                               "student_number": identity.get("student_number", ""),
                               "student_name": identity.get("student_name", ""),
                               "student_display_label": identity.get("display_label", "学生情報未確認"),
                               "student_identity_review_required": bool(identity.get("review_required")),
                               "status": sub.status, "score": score, "max": test.total_points,
                               "percentage": round(score / test.total_points * 100, 2) if test.total_points else None,
                               "warnings": sorted({code for row in questions for code in row["warnings"]}),
                "review_flags": review, "teacher_adjudicated_count": teacher_count,
                "finalized": finalized, "regrade_requests": regrade_requests},
                "audit_history": audit_history,
                "questions": questions}

    def overview(self, test_id: str) -> dict[str, Any]:
        test = self.s.get(Test, test_id)
        if test is None:
            raise KeyError("NOT_FOUND")
        from .publishing import ResultPublicationService
        publication = ResultPublicationService(self.s, root=self.root)
        rows = []
        questions = self._questions(test_id)
        for sub in self.s.scalars(select(StudentSubmission).where(
            StudentSubmission.test_id == test_id).order_by(StudentSubmission.created_at, StudentSubmission.id)):
            detail = self.detail(test_id, sub.id)
            warnings = detail["submission"]["review_flags"]
            complete = sum(1 for q in detail["questions"] if q["authoritative"] is not None) == len(questions)
            source_teacher = detail["submission"]["teacher_adjudicated_count"]
            pending_regrade = any(
                request.get("status") == "REGRADING_REQUESTED"
                for request in detail["submission"].get("regrade_requests", [])
            )
            publication_state = publication.publication_state(test_id, sub.id)
            rows.append({"submission_id": sub.id, "student_ref": detail["submission"]["student_ref"],
                         "student_number": detail["submission"].get("student_number", ""),
                         "student_name": detail["submission"].get("student_name", ""),
                         "student_display_label": detail["submission"].get("student_display_label", "学生情報未確認"),
                         "student_identity_review_required": detail["submission"].get("student_identity_review_required", True),
                         "score": detail["submission"]["score"], "max": test.total_points,
                         "percentage": detail["submission"]["percentage"],
                         "status": "REGRADING_REQUESTED" if pending_regrade else "REVIEW_REQUIRED" if warnings else "COMPLETE" if complete else "INCOMPLETE",
                         "review_flags": warnings, "teacher_adjudicated_count": source_teacher,
                         "finalized": bool(detail["submission"].get("finalized")),
                         "regrade_requested": pending_regrade,
                         "published": publication_state.get("published", False),
                         "published_at": publication_state.get("published_at"),
                         "publication_status": publication_state.get("status", "UNPUBLISHED")})
        rows.sort(key=lambda row: (
            not bool(row.get("student_number")),
            row.get("student_number") or "",
            row.get("submission_id") or "",
        ))
        return {"test": {"id": test.id, "name": test.name, "total_points": test.total_points},
                "totals": {"question_count": len(questions), "student_count": len(rows),
                           "completed_students": sum(row["status"] == "COMPLETE" for row in rows),
                           "review_required_count": sum(bool(row["review_flags"]) for row in rows),
                           "teacher_adjudicated_count": sum(row["teacher_adjudicated_count"] > 0 for row in rows)},
                "students": rows}


def _bundle_from_model(model, jobs):
    if model:
        for job in jobs:
            if job.get("id") == model.get("id"):
                return model.get("bundle") or {}
    if jobs:
        return jobs[-1].get("bundle") or {}
    return {}
