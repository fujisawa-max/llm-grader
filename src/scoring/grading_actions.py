"""Validated, append-only teacher actions for the I.2 review surface."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .db import models as m
from .grading_context import ContextError
from .grading_review import GradingReviewService, _item_target, _target
from .teacher_grading import create_teacher_grading_decision


def _now():
    return datetime.now(timezone.utc)


class GradingActionService:
    def __init__(self, session, *, artifact_root, mapping_root=None, allowed_roots=None,
                 answer_root=None, reference_root=None, visual_capability=None,
                 grading_config_path=None, execution_job_factory=None):
        self.s = session
        self.artifact_root = Path(artifact_root).resolve()
        self.mapping_root = Path(mapping_root or artifact_root).resolve()
        roots = [Path(root).resolve() for root in (allowed_roots or [self.mapping_root])]
        if self.artifact_root not in roots:
            roots.append(self.artifact_root)
        self.allowed_roots = roots
        self.answer_root = Path(answer_root).resolve() if answer_root else None
        self.reference_root = Path(reference_root).resolve() if reference_root else None
        self.visual_capability = visual_capability
        self.grading_config_path = Path(grading_config_path).resolve() if grading_config_path else None
        self.execution_job_factory = execution_job_factory

    def _target_rows(self, test_id, submission_id, question_id):
        rows = []
        for job in self.s.scalars(select(m.GradingJob).where(m.GradingJob.test_id == test_id)):
            for item in job.items:
                if _item_target(item, job, submission_id, question_id):
                    rows.append((job, item))
        return sorted(rows, key=lambda pair: (pair[0].created_at, pair[0].id))

    def _lock_submission(self, submission_id):
        """Serialize append-only actions for one submission when supported."""
        return self.s.scalar(select(m.StudentSubmission).where(
            m.StudentSubmission.id == submission_id).with_for_update())

    def _lock_test(self, test_id):
        return self.s.scalar(select(m.Test).where(m.Test.id == test_id).with_for_update())

    def _source_snapshot(self, test_id, submission_id, question_id):
        rows = self._target_rows(test_id, submission_id, question_id)
        candidates = [pair for pair in rows
                      if str(pair[0].state).lower() == "completed"
                      and str(pair[1].state).lower() == "completed"
                      and isinstance((pair[0].metadata_json or {}).get("grading_execution"), dict)]
        if not candidates:
            raise ValueError("GRADING_INPUT_SNAPSHOT_MISSING")
        job, item = candidates[-1]
        snapshot = (job.metadata_json or {}).get("grading_execution") or {}
        bundle = snapshot.get("bundle") or {}
        if ((bundle.get("identity") or {}).get("question_id") != question_id
                or (bundle.get("student_answer") or {}).get("submission_id") != submission_id):
            raise ValueError("GRADING_INPUT_SNAPSHOT_IDENTITY_MISMATCH")
        rubric_id = (bundle.get("rubric") or {}).get("id") or job.rubric_version_id
        if not rubric_id:
            raise ValueError("GRADING_INPUT_RUBRIC_MISSING")
        return job, item, snapshot, bundle, rubric_id, [str(pair[0].id) for pair in rows]

    def teacher_decision(self, *, test_id, submission_id, question_id, criterion_scores,
                         teacher_reason, teacher_note=None, teacher_user_id=None):
        self._lock_submission(submission_id)
        question = self.s.get(m.TestQuestion, question_id)
        submission = self.s.get(m.StudentSubmission, submission_id)
        if (question is None or submission is None or question.test_id != test_id
                or submission.test_id != test_id or not question.is_gradable):
            raise ValueError("GRADING_TARGET_NOT_FOUND")
        if not isinstance(criterion_scores, list) or not criterion_scores:
            raise ValueError("TEACHER_GRADING_CRITERIA_REQUIRED")
        normalized = []
        for row in criterion_scores:
            if not isinstance(row, dict) or "criterion_id" not in row or "score" not in row:
                raise ValueError("TEACHER_GRADING_CRITERION_INVALID")
            value = row["score"]
            # Do not coerce floats, booleans, or numeric strings into a score.
            # The rubric validator is the single source of truth for allowed
            # integer score levels.
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("TEACHER_GRADING_SCORE_INVALID")
            normalized.append({"criterion_id": str(row["criterion_id"]), "score": value})
        score = sum(row["score"] for row in normalized)
        job, _item, snapshot, bundle, rubric_id, previous_jobs = self._source_snapshot(
            test_id, submission_id, question_id)
        if int(bundle.get("question", {}).get("max_points", question.max_points)) != int(question.max_points):
            raise ValueError("TEACHER_GRADING_MAX_POINTS_MISMATCH")
        row, created = create_teacher_grading_decision(
            self.s, artifact_root=self.artifact_root, source_grading_job_id=job.id,
            test_id=test_id, submission_id=submission_id, question_id=question_id,
            rubric_version_id=rubric_id, score=score, max_score=int(question.max_points),
            criterion_scores=normalized, teacher_reason=str(teacher_reason or ""),
            teacher_note=teacher_note, teacher_user_id=teacher_user_id,
            previous_job_ids=previous_jobs,
        )
        return row, created

    def _detail(self, test_id, submission_id):
        try:
            return GradingReviewService(self.s, root=self.artifact_root).detail(test_id, submission_id)
        except KeyError as exc:
            raise ValueError("GRADING_TARGET_NOT_FOUND") from exc

    def _regrade_events(self, test_id, submission_id, question_id):
        target = _target(test_id, submission_id, question_id)
        return [event for event in self.s.scalars(select(m.DomainEvent).where(
            m.DomainEvent.event_type == "regrade_requested"))
                if (event.payload or {}).get("target") == target]

    def request_regrade(self, *, test_id, submission_id, question_id, reason, requested_by=None):
        if not str(reason or "").strip():
            raise ValueError("REGRADE_REASON_REQUIRED")
        self._lock_submission(submission_id)
        detail = self._detail(test_id, submission_id)
        if detail["submission"].get("finalized"):
            raise ValueError("REGRADE_AFTER_FINALIZATION")
        row = next((value for value in detail["questions"] if value["question"]["id"] == question_id), None)
        if row is None:
            raise ValueError("GRADING_TARGET_NOT_FOUND")
        current = row.get("authoritative")
        if current is None:
            raise ValueError("AUTHORITATIVE_RESULT_MISSING")
        reconstruction = row.get("student_answer", {}).get("reconstruction") or {}
        request_id = str(uuid4())
        payload = {
            "schema_version": "i2-regrade-request.v1", "request_id": request_id,
            "target": _target(test_id, submission_id, question_id), "test_id": test_id,
            "submission_id": submission_id, "question_id": question_id,
            "requested_by": requested_by, "reason": str(reason).strip(),
            "current_authoritative_result_id": current["result_id"],
            "current_reconstruction_id": reconstruction.get("id"),
            "current_reconstruction_version": reconstruction.get("version"),
            "current_rubric_version_id": (row.get("rubric") or {}).get("id"),
            "current_rubric_version": (row.get("rubric") or {}).get("version"),
            "status": "REGRADING_REQUESTED", "created_at": _now().isoformat(),
        }
        self.s.add(m.DomainEvent(entity_type="regrade_request", entity_id=request_id,
                                 event_type="regrade_requested", actor_user_id=requested_by,
                                 payload=payload))
        self.s.flush()
        return payload

    def _request_event(self, request_id):
        events = list(self.s.scalars(select(m.DomainEvent).where(
            m.DomainEvent.entity_type == "regrade_request").with_for_update()))
        request = next((event for event in events if event.entity_id == request_id
                        and event.event_type == "regrade_requested"), None)
        if request is None:
            request = next((event for event in events
                            if (event.payload or {}).get("request_id") == request_id
                            and event.event_type == "regrade_requested"), None)
        if request is None:
            raise ValueError("REGRADE_REQUEST_NOT_FOUND")
        related = [event for event in events if event.entity_id == request_id
                   or (event.payload or {}).get("request_id") == request_id]
        latest = max(related, key=lambda event: event.created_at) if related else request
        status = {
            "regrade_requested": "PENDING", "regrade_approved": "APPROVED",
            "regrade_rejected": "REJECTED", "regrade_completed": "COMPLETED",
            "regrade_failed": "FAILED",
        }.get(latest.event_type, (latest.payload or {}).get("status", "PENDING"))
        return request, latest, status

    def approve_regrade(self, *, request_id, approved_by=None, test_id=None):
        request, _latest, status = self._request_event(request_id)
        if status != "PENDING":
            raise ValueError("REGRADE_REQUEST_NOT_PENDING")
        payload = dict(request.payload or {})
        request_test_id, submission_id, question_id = (
            payload.get("test_id"), payload.get("submission_id"), payload.get("question_id"))
        if request_test_id is None or (test_id is not None and test_id != request_test_id):
            raise ValueError("REGRADE_REQUEST_NOT_FOUND")
        source_job, _item, _snapshot, _bundle, _rubric_id, _previous = self._source_snapshot(
            request_test_id, submission_id, question_id)
        config_path = self.grading_config_path or Path(source_job.config_path or "").resolve()
        factory = self.execution_job_factory
        if factory is None and not config_path.is_file():
            raise ValueError("GRADING_CONFIG_MISSING")
        run_path = self.artifact_root / "regrades" / request_id
        if factory is None:
            from .grading_execution import create_execution_job
            factory = create_execution_job
        try:
            job = factory(
                self.s, request_test_id, submission_id, question_id,
                run_path=str(run_path), config_path=str(config_path), root=self.mapping_root,
                allowed_roots=self.allowed_roots, answer_root=self.answer_root,
                reference_root=self.reference_root, visual_capability=self.visual_capability,
            )
        except (ContextError, OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        sealed_bundle = (job.metadata_json or {}).get("grading_execution", {}).get("bundle", {})
        sealed_answer = sealed_bundle.get("student_answer") or {}
        if (payload.get("current_reconstruction_id")
                and sealed_answer.get("id") != payload.get("current_reconstruction_id")):
            raise ValueError("REGRADE_INPUT_CHANGED")
        if (payload.get("current_rubric_version_id")
                and (sealed_bundle.get("rubric") or {}).get("id") != payload.get("current_rubric_version_id")):
            raise ValueError("REGRADE_INPUT_CHANGED")
        job.metadata_json = {**(job.metadata_json or {}), "regrade_request_id": request_id}
        approval = {
            "schema_version": "i3-regrade-approval.v1", "request_id": request_id,
            "test_id": request_test_id, "submission_id": submission_id, "question_id": question_id,
            "approved_by": approved_by, "job_id": job.id,
            "snapshot_sha256": (job.metadata_json.get("grading_execution") or {}).get("snapshot_sha256"),
            "current_reconstruction_id": payload.get("current_reconstruction_id"),
            "current_reconstruction_version": payload.get("current_reconstruction_version"),
            "current_rubric_version_id": payload.get("current_rubric_version_id"),
            "preview_status": "PASS", "status": "APPROVED", "created_at": _now().isoformat(),
        }
        self.s.add(m.DomainEvent(entity_type="regrade_request", entity_id=request_id,
                                 event_type="regrade_approved", actor_user_id=approved_by,
                                 payload=approval))
        self.s.flush()
        return approval

    def reject_regrade(self, *, request_id, reason, rejected_by=None, test_id=None):
        if not str(reason or "").strip():
            raise ValueError("REGRADE_REJECTION_REASON_REQUIRED")
        request, _latest, status = self._request_event(request_id)
        if status not in {"PENDING", "FAILED"}:
            raise ValueError("REGRADE_REQUEST_NOT_PENDING")
        request_test_id = (request.payload or {}).get("test_id")
        if request_test_id is None or (test_id is not None and test_id != request_test_id):
            raise ValueError("REGRADE_REQUEST_NOT_FOUND")
        payload = {"schema_version": "i3-regrade-rejection.v1", "request_id": request_id,
                   "test_id": (request.payload or {}).get("test_id"),
                   "submission_id": (request.payload or {}).get("submission_id"),
                   "question_id": (request.payload or {}).get("question_id"),
                   "rejected_by": rejected_by, "reason": str(reason).strip(),
                   "status": "REJECTED", "created_at": _now().isoformat()}
        self.s.add(m.DomainEvent(entity_type="regrade_request", entity_id=request_id,
                                 event_type="regrade_rejected", actor_user_id=rejected_by,
                                 payload=payload))
        self.s.flush()
        return payload

    def _unresolved_regrades(self, test_id, submission_id):
        events = self.s.scalars(select(m.DomainEvent).where(
            m.DomainEvent.event_type == "regrade_requested"))
        resolved = {
            event.payload.get("request_id") for event in self.s.scalars(select(m.DomainEvent).where(
                m.DomainEvent.event_type.in_(["regrade_completed", "regrade_rejected"])))
        }
        return [event for event in events if (event.payload or {}).get("test_id") == test_id
                and (event.payload or {}).get("submission_id") == submission_id
                and (event.payload or {}).get("request_id") not in resolved]

    def _finalized_event(self, test_id, submission_id):
        events = self.s.scalars(select(m.DomainEvent).where(
            m.DomainEvent.event_type.in_(["grading_finalized", "test_grading_finalized"])))
        for event in events:
            payload = event.payload or {}
            if payload.get("test_id") == test_id and (
                    payload.get("submission_id") == submission_id
                    or submission_id in payload.get("submission_ids", [])):
                return event
        return None

    def _validate_finalizable(self, test_id, submission_id):
        detail = self._detail(test_id, submission_id)
        if any(row.get("authoritative") is None for row in detail["questions"]):
            raise ValueError("FINALIZE_MISSING_AUTHORITATIVE_RESULT")
        if any(row.get("review_flags") for row in detail["questions"]):
            raise ValueError("FINALIZE_REVIEW_REQUIRED")
        unresolved = self._unresolved_regrades(test_id, submission_id)
        if unresolved:
            raise ValueError("FINALIZE_REGRADE_REQUEST_PENDING")
        return detail

    def finalize_submission(self, *, test_id, submission_id, actor_user_id=None):
        self._lock_submission(submission_id)
        existing = self._finalized_event(test_id, submission_id)
        if existing:
            return existing.payload, False
        detail = self._validate_finalizable(test_id, submission_id)
        payload = {"schema_version": "i2-grading-finalization.v1", "finalization_id": str(uuid4()),
                   "test_id": test_id, "submission_id": submission_id,
                   "authoritative_result_refs": [
                       {"question_id": row["question"]["id"], "result_id": row["authoritative"]["result_id"],
                        "source": row["authoritative"]["source"]}
                       for row in detail["questions"]],
                   "total_points": detail["test"]["total_points"],
                   "status": "FINALIZED", "created_at": _now().isoformat()}
        self.s.add(m.DomainEvent(entity_type="grading_finalization", entity_id=payload["finalization_id"],
                                 event_type="grading_finalized", actor_user_id=actor_user_id,
                                 payload=payload))
        self.s.flush()
        return payload, True

    def finalize_test(self, *, test_id, actor_user_id=None):
        self._lock_test(test_id)
        submissions = list(self.s.scalars(select(m.StudentSubmission).where(
            m.StudentSubmission.test_id == test_id).order_by(m.StudentSubmission.id)))
        if not submissions:
            raise ValueError("FINALIZE_NO_SUBMISSIONS")
        details = [(sub, self._validate_finalizable(test_id, sub.id)) for sub in submissions]
        existing = [self._finalized_event(test_id, sub.id) for sub, _detail in details]
        refs = [{"submission_id": sub.id, "authoritative_result_refs": [
            {"question_id": row["question"]["id"], "result_id": row["authoritative"]["result_id"],
             "source": row["authoritative"]["source"]} for row in detail["questions"]]}
                for sub, detail in details]
        if all(existing):
            return {"status": "FINALIZED", "test_id": test_id,
                    "submission_ids": [sub.id for sub, _detail in details]}, False
        payload = {"schema_version": "i2-grading-finalization.v1", "finalization_id": str(uuid4()),
                   "test_id": test_id, "submission_ids": [sub.id for sub, _detail in details],
                   "authoritative_result_refs": refs,
                   "total_points": self.s.get(m.Test, test_id).total_points,
                   "status": "FINALIZED", "created_at": _now().isoformat()}
        self.s.add(m.DomainEvent(entity_type="grading_finalization", entity_id=payload["finalization_id"],
                                 event_type="test_grading_finalized", actor_user_id=actor_user_id,
                                 payload=payload))
        self.s.flush()
        return payload, True
