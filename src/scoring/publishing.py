"""Append-only publication and student-facing result projections.

Publication records contain references to the authoritative result snapshot;
they deliberately do not copy scores or feedback into a second mutable table.
The student DTO is built separately so internal grading evidence cannot leak
through the teacher review representation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import base64
import re
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import select

from .db.models import (
    DomainEvent,
    GradingJob,
    Student,
    StudentAnswerReconstruction,
    StudentSubmission,
    Test,
    TeacherGradingDecision,
)
from .grading_review import GradingReviewService
from .pdf_native import canonical_hash
from .student_visual import StudentVisualAssetService, safe_file


PUBLISHED = "PUBLISHED"
UNPUBLISHED = "UNPUBLISHED"
RESULTS_PUBLISHED = "results_published"
RESULTS_UNPUBLISHED = "results_unpublished"
FEEDBACK_OVERRIDE = "teacher_feedback_override"
RESULT_CHANGED_AFTER_PUBLICATION = "RESULT_CHANGED_AFTER_PUBLICATION"

_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_SHA_RE = re.compile(r"\b[0-9a-f]{64}\b", re.I)
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?/(?:[^\s/]+/)+[^\s]+")
_INTERNAL_WORD_RE = re.compile(
    r"\b(?:model\s*answer|rubric|criterion(?:[_ -]?[A-Za-z0-9.-]+)?|"
    r"prompt|raw\s*response|implementation|artifact|sha(?:256)?|uuid)\b",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def sanitize_student_text(value) -> str:
    """Remove internal identifiers and implementation terminology from prose."""

    text = str(value or "")
    text = _UUID_RE.sub("", text)
    text = _SHA_RE.sub("", text)
    text = _PATH_RE.sub("", text)
    text = _INTERNAL_WORD_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _visual_token(submission_id, question_id, asset_id) -> str:
    digest = bytes.fromhex(canonical_hash({"submission_id": submission_id,
                                           "question_id": question_id,
                                           "asset_id": asset_id}))
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class PublicationError(ValueError):
    """Stable service error code returned by publish and student APIs."""


class ResultPublicationService:
    """Resolve final results and manage publication events without mutation."""

    def __init__(self, session, *, root=None, answer_root=None):
        self.s = session
        self.root = Path(root).resolve() if root else None
        self.answer_root = Path(answer_root or root or Path.cwd()).resolve()
        self.review = GradingReviewService(session, root=root)

    def _test(self, test_id: str) -> Test:
        value = self.s.get(Test, test_id)
        if value is None:
            raise PublicationError("TEST_NOT_FOUND")
        return value

    def _submission(self, submission_id: str, *, test_id: str | None = None) -> StudentSubmission:
        value = self.s.get(StudentSubmission, submission_id)
        if value is None or (test_id is not None and value.test_id != test_id):
            raise PublicationError("SUBMISSION_NOT_FOUND")
        return value

    def _lock_submission(self, submission_id: str, *, test_id: str | None = None):
        value = self.s.scalar(select(StudentSubmission).where(
            StudentSubmission.id == submission_id).with_for_update())
        if value is None or (test_id is not None and value.test_id != test_id):
            raise PublicationError("SUBMISSION_NOT_FOUND")
        return value

    def _lock_test(self, test_id: str):
        value = self.s.scalar(select(Test).where(Test.id == test_id).with_for_update())
        if value is None:
            raise PublicationError("TEST_NOT_FOUND")
        return value

    def _detail(self, test_id: str, submission_id: str):
        try:
            return self.review.detail(test_id, submission_id)
        except KeyError as exc:
            raise PublicationError("SUBMISSION_NOT_FOUND") from exc

    def _finalization_event(self, test_id: str, submission_id: str):
        events = self.s.scalars(select(DomainEvent).where(
            DomainEvent.event_type.in_(["grading_finalized", "test_grading_finalized"])))
        matches = []
        for event in events:
            payload = event.payload or {}
            if payload.get("test_id") != test_id:
                continue
            if payload.get("submission_id") == submission_id or submission_id in payload.get("submission_ids", []):
                matches.append(event)
        return max(matches, key=lambda event: (event.created_at, event.id)) if matches else None

    def _unresolved_regrades(self, test_id: str, submission_id: str) -> bool:
        requests = list(self.s.scalars(select(DomainEvent).where(
            DomainEvent.event_type == "regrade_requested")))
        request_ids = {
            (event.payload or {}).get("request_id") or event.entity_id
            for event in requests
            if (event.payload or {}).get("test_id") == test_id
            and (event.payload or {}).get("submission_id") == submission_id
        }
        if not request_ids:
            return False
        resolved = {
            (event.payload or {}).get("request_id") or event.entity_id
            for event in self.s.scalars(select(DomainEvent).where(
                DomainEvent.event_type.in_(["regrade_completed", "regrade_rejected"])))
        }
        return bool(request_ids - resolved)

    def _validate_publishable(self, test_id: str, submission_id: str):
        detail = self._detail(test_id, submission_id)
        if self._finalization_event(test_id, submission_id) is None or not detail["submission"].get("finalized"):
            raise PublicationError("PUBLISH_REQUIRES_FINALIZED")
        if any(row.get("authoritative") is None for row in detail["questions"]):
            raise PublicationError("PUBLISH_MISSING_AUTHORITATIVE_RESULT")
        if any(row.get("review_flags") for row in detail["questions"]):
            raise PublicationError("PUBLISH_REVIEW_REQUIRED")
        if self._unresolved_regrades(test_id, submission_id):
            raise PublicationError("PUBLISH_REGRADE_REQUEST_PENDING")
        refs = self._result_refs(detail, test_id, submission_id)
        return detail, refs

    @staticmethod
    def _current_override(session, test_id, submission_id, question_id):
        events = list(session.scalars(select(DomainEvent).where(
            DomainEvent.entity_type == "teacher_feedback_override",
            DomainEvent.event_type == FEEDBACK_OVERRIDE)))
        matches = [event for event in events if (event.payload or {}).get("test_id") == test_id
                   and (event.payload or {}).get("submission_id") == submission_id
                   and (event.payload or {}).get("question_id") == question_id]
        return max(matches, key=lambda event: (event.created_at, event.id)) if matches else None

    def _result_refs(self, detail, test_id: str, submission_id: str):
        refs = []
        for row in detail["questions"]:
            authoritative = row.get("authoritative")
            if authoritative is None:
                raise PublicationError("PUBLISH_MISSING_AUTHORITATIVE_RESULT")
            ref = {
                "question_id": row["question"]["id"],
                "source": authoritative["source"],
                "result_id": authoritative["result_id"],
                "max_score": authoritative["max_score"],
                "snapshot_sha256": None,
                "bundle_sha256": None,
                "reconstruction_id": (row.get("student_answer", {}).get("reconstruction") or {}).get("id"),
                "visual_asset_ids": [asset.get("asset_id") for asset in row.get("visual_assets", [])
                                     if asset.get("role") == "student_visual_answer"],
            }
            model = next((job for job in row.get("jobs", []) if job.get("id") == authoritative["result_id"]), None)
            if model:
                ref["item_id"] = model.get("item_id")
                ref["snapshot_sha256"] = model.get("snapshot_sha256")
                ref["bundle_sha256"] = model.get("bundle_sha256")
            override = self._current_override(self.s, test_id, submission_id, ref["question_id"])
            ref["feedback_override_id"] = override.id if override else None
            refs.append(ref)
        return refs

    @staticmethod
    def _snapshot_sha(test_id, submission_ids, refs):
        return canonical_hash({"test_id": test_id, "submission_ids": sorted(submission_ids), "result_refs": refs})

    def _publication_events(self, test_id: str, submission_id: str | None = None):
        events = []
        for event in self.s.scalars(select(DomainEvent).where(
                DomainEvent.event_type.in_([RESULTS_PUBLISHED, RESULTS_UNPUBLISHED]))):
            payload = event.payload or {}
            if payload.get("test_id") != test_id:
                continue
            if payload.get("scope") == "submission" and submission_id is not None:
                if submission_id not in payload.get("submission_ids", []):
                    continue
            elif payload.get("scope") == "submission":
                continue
            elif payload.get("scope") == "test" and payload.get("submission_ids") and submission_id is not None:
                if event.event_type == RESULTS_PUBLISHED and submission_id not in payload.get("submission_ids", []):
                    continue
            events.append(event)
        return sorted(events, key=lambda event: (event.created_at, event.id))

    def publication_state(self, test_id: str, submission_id: str):
        self._test(test_id)
        self._submission(submission_id, test_id=test_id)
        events = self._publication_events(test_id, submission_id)
        if not events:
            return {"status": UNPUBLISHED, "published": False, "published_at": None}
        event = events[-1]
        payload = dict(event.payload or {})
        return {
            "status": PUBLISHED if event.event_type == RESULTS_PUBLISHED else UNPUBLISHED,
            "published": event.event_type == RESULTS_PUBLISHED,
            "published_at": payload.get("published_at") if event.event_type == RESULTS_PUBLISHED else None,
            "publication_event_id": event.id,
            "payload": payload,
        }

    def _append_publication(self, *, scope, test_id, submission_ids, refs_by_submission,
                            actor_user_id=None, event_type=RESULTS_PUBLISHED, previous_event_id=None):
        publication_id = str(uuid4())
        published_at = _iso(_now()) if event_type == RESULTS_PUBLISHED else None
        refs = refs_by_submission if scope == "test" else refs_by_submission.get(submission_ids[0], [])
        payload = {
            "schema_version": "i4-results-publication.v1",
            "publication_id": publication_id,
            "scope": scope,
            "test_id": test_id,
            "submission_ids": list(submission_ids),
            "result_refs": refs if scope == "submission" else None,
            "result_refs_by_submission": refs if scope == "test" else None,
            "snapshot_sha256": self._snapshot_sha(test_id, submission_ids, refs),
            "published_at": published_at,
            "previous_publication_event_id": previous_event_id,
            "status": PUBLISHED if event_type == RESULTS_PUBLISHED else UNPUBLISHED,
        }
        entity_type = "test_publication" if scope == "test" else "submission_publication"
        entity_id = test_id if scope == "test" else submission_ids[0]
        event = DomainEvent(entity_type=entity_type, entity_id=entity_id,
                            event_type=event_type, actor_user_id=actor_user_id, payload=payload)
        self.s.add(event)
        self.s.flush()
        return payload, event

    def publish_submission(self, test_id, submission_id, *, actor_user_id=None):
        self._lock_test(test_id)
        self._lock_submission(submission_id, test_id=test_id)
        current = self.publication_state(test_id, submission_id)
        if current["published"]:
            # A publication remains immutable.  If the authoritative result
            # or feedback override changed afterwards, this call is an
            # explicit republish and therefore appends a new snapshot event.
            try:
                changed = self._changed_after_publication(test_id, submission_id, current)
            except PublicationError:
                changed = True
            if not changed:
                return current["payload"], False
        detail, refs = self._validate_publishable(test_id, submission_id)
        payload, _event = self._append_publication(
            scope="submission", test_id=test_id, submission_ids=[submission_id],
            refs_by_submission={submission_id: refs}, actor_user_id=actor_user_id)
        return payload, True

    def publish_test(self, test_id, *, actor_user_id=None):
        test = self._lock_test(test_id)
        submissions = list(self.s.scalars(select(StudentSubmission).where(
            StudentSubmission.test_id == test.id).order_by(StudentSubmission.id)))
        if not submissions:
            raise PublicationError("PUBLISH_NO_SUBMISSIONS")
        refs_by_submission = {}
        for submission in submissions:
            _detail, refs_by_submission[submission.id] = self._validate_publishable(test.id, submission.id)
        all_published = all(self.publication_state(test.id, submission.id).get("published")
                            for submission in submissions)
        def _is_unchanged(submission):
            try:
                return not self._changed_after_publication(
                    test.id, submission.id,
                    self.publication_state(test.id, submission.id))
            except PublicationError:
                return False

        unchanged = all_published and all(_is_unchanged(submission) for submission in submissions)
        if unchanged:
            current_events = self._publication_events(test.id)
            if current_events and current_events[-1].event_type == RESULTS_PUBLISHED:
                return current_events[-1].payload, False
        payload, _event = self._append_publication(
            scope="test", test_id=test.id, submission_ids=[row.id for row in submissions],
            refs_by_submission=refs_by_submission, actor_user_id=actor_user_id)
        return payload, True

    def unpublish_submission(self, test_id, submission_id, *, actor_user_id=None):
        self._lock_test(test_id)
        self._lock_submission(submission_id, test_id=test_id)
        current = self.publication_state(test_id, submission_id)
        if not current["published"]:
            return {"status": UNPUBLISHED, "published": False}, False
        payload, _event = self._append_publication(
            scope="submission", test_id=test_id, submission_ids=[submission_id],
            refs_by_submission={submission_id: []}, actor_user_id=actor_user_id,
            event_type=RESULTS_UNPUBLISHED, previous_event_id=current.get("publication_event_id"))
        return payload, True

    def unpublish_test(self, test_id, *, actor_user_id=None):
        self._lock_test(test_id)
        submission_ids = [row.id for row in self.s.scalars(select(StudentSubmission).where(
            StudentSubmission.test_id == test_id))]
        if not any(self.publication_state(test_id, submission_id).get("published")
                   for submission_id in submission_ids):
            return {"status": UNPUBLISHED, "published": False}, False
        current = self._publication_events(test_id)
        payload, _event = self._append_publication(
            scope="test", test_id=test_id, submission_ids=submission_ids,
            refs_by_submission={}, actor_user_id=actor_user_id,
            event_type=RESULTS_UNPUBLISHED, previous_event_id=current[-1].id)
        return payload, True

    def _current_refs_for_submission(self, test_id, submission_id):
        detail = self._detail(test_id, submission_id)
        return self._result_refs(detail, test_id, submission_id)

    def _published_refs(self, state, submission_id):
        payload = state.get("payload") or {}
        if payload.get("scope") == "submission":
            return payload.get("result_refs") or []
        return (payload.get("result_refs_by_submission") or {}).get(submission_id, [])

    def _changed_after_publication(self, test_id, submission_id, state):
        published = self._published_refs(state, submission_id)
        current = self._current_refs_for_submission(test_id, submission_id)
        def key(ref):
            return (ref.get("question_id"), ref.get("source"), ref.get("result_id"),
                    ref.get("reconstruction_id"), ref.get("feedback_override_id"),
                    tuple(ref.get("visual_asset_ids") or []), ref.get("bundle_sha256"),
                    ref.get("snapshot_sha256"))
        return sorted(map(key, published)) != sorted(map(key, current))

    def _result_from_ref(self, ref):
        source = ref.get("source")
        if source == "TEACHER_ADJUDICATION":
            decision = self.s.get(TeacherGradingDecision, ref.get("result_id"))
            if decision is None:
                raise PublicationError("PUBLISHED_RESULT_HISTORY_MISSING")
            return {
                "score": decision.score, "max_score": decision.max_score,
                "criteria": decision.criterion_scores or [],
                "feedback": (decision.provenance or {}).get("student_feedback", ""),
                "source": "TEACHER_ADJUDICATION", "decision": decision,
            }
        job = self.s.get(GradingJob, ref.get("result_id"))
        if job is None:
            raise PublicationError("PUBLISHED_RESULT_HISTORY_MISSING")
        item = next((item for item in job.items if item.id == ref.get("item_id")), None)
        if item is None:
            raise PublicationError("PUBLISHED_RESULT_HISTORY_MISSING")
        result = (item.metadata_json or {}).get("result") or {}
        return {"score": item.score, "max_score": item.max_score,
                "criteria": result.get("criteria", []),
                "feedback": result.get("feedback") or result.get("reasoning") or "",
                "source": "MODEL", "item": item, "job": job, "result": result}

    def _reconstruction(self, submission_id, question_id, reconstruction_id):
        if not reconstruction_id:
            return None
        row = self.s.get(StudentAnswerReconstruction, reconstruction_id)
        if row is None or row.submission_id != submission_id or row.question_id != question_id:
            raise PublicationError("PUBLISHED_ANSWER_HISTORY_MISSING")
        return row

    def _visual_urls(self, submission_id, question_id, asset_ids):
        assets = []
        if not asset_ids:
            return assets
        service = StudentVisualAssetService(self.s, self.answer_root)
        submission = self._submission(submission_id)
        student = self.s.get(Student, submission.student_id)
        if student is None:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        identity = quote(student.student_identifier, safe="")
        for asset_id in asset_ids:
            try:
                value = service.get(asset_id, submission_id, question_id)
            except ValueError as exc:
                raise PublicationError("PUBLISHED_VISUAL_ASSET_MISSING") from exc
            token = _visual_token(submission_id, question_id, asset_id)
            # Keep internal submission/question/asset identifiers out of the
            # student DTO.  The opaque token is resolved server-side against
            # the immutable publication snapshot and requester ownership.
            assets.append({
                "url": f"/api/v1/student/result-assets/{token}?role=student&student_id={identity}",
                "bbox": value.get("bbox"), "mime_type": value.get("mime_type", "image/png"),
            })
        return assets

    def _feedback_override(self, override_id):
        if not override_id:
            return None
        event = self.s.get(DomainEvent, override_id)
        if event is None or event.event_type != FEEDBACK_OVERRIDE:
            return None
        return event.payload or {}

    def _student_question(self, test_id, submission_id, row, ref):
        result = self._result_from_ref(ref)
        question = row["question"]
        reconstruction = self._reconstruction(submission_id, question["id"], ref.get("reconstruction_id"))
        answer_text = sanitize_student_text(reconstruction.answer_text if reconstruction else "")
        override = self._feedback_override(ref.get("feedback_override_id"))
        if override:
            feedback = sanitize_student_text(override.get("feedback"))
        else:
            feedback = sanitize_student_text(result.get("feedback"))
        criteria = []
        for index, criterion in enumerate(result.get("criteria") or [], 1):
            if not isinstance(criterion, dict):
                continue
            criteria.append({
                "label": f"Criterion {index}",
                "score": criterion.get("score"),
                "max_score": criterion.get("max_score"),
                "feedback": sanitize_student_text(criterion.get("reason") or criterion.get("feedback")),
            })
        visual = self._visual_urls(submission_id, question["id"], ref.get("visual_asset_ids") or [])
        return {
            "label": question["label"], "score": result["score"], "max_score": result["max_score"],
            "feedback": feedback, "criteria": criteria,
            "student_answer": {"text": answer_text, "visual_assets": visual},
        }

    def student_result(self, submission_id, *, requester_student_id=None):
        submission = self._submission(submission_id)
        student = self.s.get(Student, submission.student_id)
        if requester_student_id is None:
            raise PublicationError("STUDENT_ID_REQUIRED")
        if student is None:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        if requester_student_id not in {student.id, student.student_identifier}:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        state = self.publication_state(submission.test_id, submission.id)
        if not state["published"]:
            raise PublicationError("RESULT_NOT_PUBLISHED")
        detail = self._detail(submission.test_id, submission.id)
        refs = self._published_refs(state, submission.id)
        by_question = {row["question"]["id"]: row for row in detail["questions"]}
        questions = [self._student_question(submission.test_id, submission.id, by_question[ref["question_id"]], ref)
                     for ref in refs if ref["question_id"] in by_question]
        try:
            changed = self._changed_after_publication(submission.test_id, submission.id, state)
        except PublicationError:
            # A published historical snapshot remains auditable even if the
            # current result was later retired or became incomplete.
            changed = True
        return {
            "test": {"title": detail["test"]["name"]},
            "score": sum(row["score"] for row in questions),
            "max_score": detail["test"]["total_points"],
            "percentage": round(sum(row["score"] for row in questions) / detail["test"]["total_points"] * 100, 2)
            if detail["test"]["total_points"] else None,
            "questions": questions,
            "published_at": state.get("published_at"),
            "status": RESULT_CHANGED_AFTER_PUBLICATION if changed else PUBLISHED,
            "republish_required": changed,
        }

    def teacher_result(self, test_id, submission_id):
        self._submission(submission_id, test_id=test_id)
        detail = self._detail(test_id, submission_id)
        if not detail["submission"].get("finalized"):
            raise PublicationError("RESULT_REQUIRES_FINALIZED")
        refs = self._current_refs_for_submission(test_id, submission_id)
        state = self.publication_state(test_id, submission_id)
        if state["published"]:
            refs = self._published_refs(state, submission_id)
        by_question = {row["question"]["id"]: row for row in detail["questions"]}
        questions = [self._student_question(test_id, submission_id, by_question[ref["question_id"]], ref)
                     for ref in refs if ref["question_id"] in by_question]
        return {"test": {"title": detail["test"]["name"]}, "score": sum(row["score"] for row in questions),
                "max_score": detail["test"]["total_points"], "questions": questions,
                "published_at": state.get("published_at"),
                "status": state.get("status", UNPUBLISHED)}

    def feedback_override(self, test_id, submission_id, question_id, feedback, *, teacher_note=None, actor_user_id=None):
        if not str(feedback or "").strip():
            raise PublicationError("FEEDBACK_REQUIRED")
        self._lock_test(test_id)
        self._lock_submission(submission_id, test_id=test_id)
        detail = self._detail(test_id, submission_id)
        row = next((value for value in detail["questions"] if value["question"]["id"] == question_id), None)
        if row is None or row.get("authoritative") is None:
            raise PublicationError("AUTHORITATIVE_RESULT_MISSING")
        normalized_feedback = str(feedback).strip()
        normalized_note = str(teacher_note or "")
        existing = self._current_override(self.s, test_id, submission_id, question_id)
        if existing:
            payload = existing.payload or {}
            if (payload.get("feedback") == normalized_feedback
                    and payload.get("teacher_note", "") == normalized_note
                    and payload.get("actor_user_id") == actor_user_id):
                return {"id": existing.id, "status": "COMPLETE", "created": False,
                        "created_at": _iso(existing.created_at)}
        event_id = str(uuid4())
        payload = {
            "schema_version": "i4-teacher-feedback-override.v1", "override_id": event_id,
            "test_id": test_id, "submission_id": submission_id, "question_id": question_id,
            "feedback": normalized_feedback, "teacher_note": normalized_note,
            "actor_user_id": actor_user_id, "created_at": _iso(_now()),
        }
        self.s.add(DomainEvent(entity_type="teacher_feedback_override", entity_id=event_id,
                               event_type=FEEDBACK_OVERRIDE, actor_user_id=actor_user_id,
                               payload=payload))
        self.s.flush()
        return {"id": event_id, "status": "COMPLETE", "created": True,
                "created_at": payload["created_at"]}

    def visual_path_by_token(self, submission_id, question_id, token, *, requester_student_id):
        token = str(token).split("?", 1)[0]
        submission = self._submission(submission_id)
        student = self.s.get(Student, submission.student_id)
        if student is None:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        if requester_student_id not in {student.id, student.student_identifier}:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        state = self.publication_state(submission.test_id, submission.id)
        if not state["published"]:
            raise PublicationError("RESULT_NOT_PUBLISHED")
        for ref in self._published_refs(state, submission.id):
            if ref.get("question_id") != question_id:
                continue
            for asset_id in ref.get("visual_asset_ids") or []:
                expected = _visual_token(submission_id, question_id, asset_id)
                if expected == token:
                    try:
                        value = StudentVisualAssetService(self.s, self.answer_root).get(
                            asset_id, submission_id, question_id)
                        return safe_file(self.answer_root, value["artifact_ref"], value["sha256"]), value["mime_type"]
                    except ValueError as exc:
                        raise PublicationError("PUBLISHED_VISUAL_ASSET_MISSING") from exc
        raise PublicationError("PUBLISHED_VISUAL_ASSET_NOT_FOUND")

    def visual_path_for_student_token(self, token, *, requester_student_id):
        """Resolve an opaque visual capability within the requester's results."""
        if requester_student_id is None:
            raise PublicationError("STUDENT_ID_REQUIRED")
        students = list(self.s.scalars(select(Student).where(
            (Student.id == requester_student_id) |
            (Student.student_identifier == requester_student_id))))
        if not students:
            raise PublicationError("STUDENT_ACCESS_DENIED")
        student_ids = {student.id for student in students}
        submissions = self.s.scalars(select(StudentSubmission).where(
            StudentSubmission.student_id.in_(student_ids)))
        for submission in submissions:
            state = self.publication_state(submission.test_id, submission.id)
            if not state["published"]:
                continue
            for ref in self._published_refs(state, submission.id):
                question_id = ref.get("question_id")
                for asset_id in ref.get("visual_asset_ids") or []:
                    if _visual_token(submission.id, question_id, asset_id) != token:
                        continue
                    return self.visual_path_by_token(
                        submission.id, question_id, token,
                        requester_student_id=requester_student_id)
        raise PublicationError("PUBLISHED_VISUAL_ASSET_NOT_FOUND")

    def result_pdf_bytes(self, test_id, submission_id, *, requester_student_id=None, student=False):
        if student:
            data = self.student_result(submission_id, requester_student_id=requester_student_id)
        else:
            data = self.teacher_result(test_id, submission_id)
        submission = self._submission(submission_id)
        import pymupdf
        document = pymupdf.open()
        page = document.new_page()
        y = 48
        page.insert_text((48, y), str(data["test"]["title"]), fontsize=16)
        y += 26
        student = self.s.get(Student, submission.student_id)
        if student is not None:
            # A human-facing report may identify the student, but never uses
            # the internal submission/student UUIDs.
            identifier = sanitize_student_text(student.student_identifier)
            name = sanitize_student_text(student.display_name)
            page.insert_text((48, y), f"Student: {identifier} {name}".strip(), fontsize=10)
            y += 20
        page.insert_text((48, y), f"Score: {data['score']} / {data['max_score']}", fontsize=12)
        y += 24
        state = self.publication_state(submission.test_id, submission.id)
        refs = self._published_refs(state, submission.id) if state["published"] else self._current_refs_for_submission(submission.test_id, submission.id)
        visual_service = StudentVisualAssetService(self.s, self.answer_root)
        for question, ref in zip(data["questions"], refs):
            if y > page.rect.height - 100:
                page = document.new_page()
                y = 48
            page.insert_text((48, y), f"{question['label']}: {question['score']} / {question['max_score']}", fontsize=11)
            y += 18
            for line in (question.get("student_answer", {}).get("text") or "").splitlines() or [""]:
                page.insert_textbox((64, y, page.rect.width - 48, y + 30), line, fontsize=9)
                y += 14
            feedback = question.get("feedback") or ""
            if feedback:
                page.insert_textbox((64, y, page.rect.width - 48, y + 42), f"Feedback: {feedback}", fontsize=9)
                y += 30
            for criterion in question.get("criteria", []):
                page.insert_textbox((64, y, page.rect.width - 48, y + 30),
                                    f"{criterion['label']}: {criterion['score']} / {criterion['max_score']} {criterion['feedback']}",
                                    fontsize=8)
                y += 20
            for asset_id in ref.get("visual_asset_ids") or []:
                value = visual_service.get(asset_id, submission.id, ref["question_id"])
                path = safe_file(self.answer_root, value["artifact_ref"], value["sha256"])
                if y > page.rect.height - 150:
                    page = document.new_page()
                    y = 48
                page.insert_image(pymupdf.Rect(64, y, min(page.rect.width - 48, 260), y + 120), filename=str(path))
                y += 130
        return document.tobytes()
