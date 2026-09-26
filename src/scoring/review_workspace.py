"""Resolver-backed review and regrade queues for the I.3 workspace."""

from __future__ import annotations

from sqlalchemy import select

from .db.models import DomainEvent, StudentSubmission, Test
from .grading_review import GradingReviewService


class ReviewWorkspaceService:
    """Build review queues without duplicating authoritative-result rules."""

    def __init__(self, session, *, root=None, identity_root=None):
        self.s = session
        self.review = GradingReviewService(session, root=root, identity_root=identity_root)

    @staticmethod
    def _pending_requests(rows):
        return [row for row in rows if row.get("status") in {"PENDING", "APPROVED", "FAILED"}]

    def _request_events(self, test_id):
        requests = list(self.s.scalars(select(DomainEvent).where(
            DomainEvent.event_type == "regrade_requested")))
        events = list(self.s.scalars(select(DomainEvent).where(
            DomainEvent.entity_type == "regrade_request")))
        by_id = {}
        for request in requests:
            payload = dict(request.payload or {})
            if payload.get("test_id") != test_id:
                continue
            request_id = payload.get("request_id") or request.entity_id
            related = [event for event in events if event.entity_id == request_id
                       or (event.payload or {}).get("request_id") == request_id]
            latest = max(related, key=lambda event: event.created_at) if related else request
            latest_payload = dict(latest.payload or {})
            event_status = {
                "regrade_requested": "PENDING",
                "regrade_approved": "APPROVED",
                "regrade_rejected": "REJECTED",
                "regrade_completed": "COMPLETED",
                "regrade_failed": "FAILED",
            }.get(latest.event_type, latest_payload.get("status", "PENDING"))
            by_id[request_id] = {
                **payload, "request_id": request_id, "status": event_status,
                "latest_event_id": latest.id,
                "latest_event_type": latest.event_type,
                "latest_event_at": latest.created_at.isoformat()
                if hasattr(latest.created_at, "isoformat") else latest.created_at,
                "latest_event_payload": latest_payload,
            }
        return list(by_id.values())

    def _all_rows(self, test_id):
        rows = []
        requests = self._request_events(test_id)
        request_by_target = {}
        for request in requests:
            request_by_target.setdefault(request.get("target"), []).append(request)
        submissions = list(self.s.scalars(select(StudentSubmission).where(
            StudentSubmission.test_id == test_id).order_by(StudentSubmission.id)))
        for submission in submissions:
            detail = self.review.detail(test_id, submission.id)
            for question in detail["questions"]:
                target = f"{test_id}/{submission.id}/{question['question']['id']}"
                target_requests = request_by_target.get(target, [])
                pending = self._pending_requests(target_requests)
                authoritative = question.get("authoritative")
                score = authoritative.get("score") if authoritative else None
                maximum = question["question"].get("max_points")
                status = ("REGRADING_REQUESTED" if pending else
                          "REVIEW_REQUIRED" if question.get("review_flags") else "REVIEWED")
                rows.append({
                    "target": target,
                    "test_id": test_id,
                    "submission_id": submission.id,
                    "student_ref": detail["submission"].get("student_ref"),
                    "student_number": detail["submission"].get("student_number", ""),
                    "student_name": detail["submission"].get("student_name", ""),
                    "student_display_label": detail["submission"].get("student_display_label", "学生情報未確認"),
                    "student_identity_review_required": detail["submission"].get("student_identity_review_required", True),
                    "question_id": question["question"]["id"],
                    "question_label": question["question"]["label"],
                    "score": score,
                    "max_score": maximum,
                    "percentage": round(score / maximum * 100, 2)
                    if score is not None and maximum else None,
                    "authoritative": authoritative,
                    "flags": question.get("warnings", []),
                    "review_flags": question.get("review_flags", []),
                    "regrade_requests": target_requests,
                    "regrade_pending": bool(pending),
                    "status": status,
                    "teacher_adjudicated": bool(authoritative and
                                                authoritative.get("source") == "TEACHER_ADJUDICATION"),
                    "reconstruction_history": question.get("reconstruction_history", []),
                    "visual_assets": question.get("visual_assets", []),
                    "question_review": question,
                })
        rows.sort(key=lambda row: (
            not bool(row.get("student_number")),
            row.get("student_number") or "",
            row.get("submission_id") or "",
            row.get("question_id") or "",
        ))
        return rows

    @staticmethod
    def _matches(row, filter_key):
        if filter_key in (None, "", "unresolved"):
            return bool(row["review_flags"] or row["regrade_pending"])
        return {
            "warnings": bool(row["flags"]),
            "regrade": row["regrade_pending"],
            "adjudicated": row["teacher_adjudicated"],
            "reconstruction": len(row["reconstruction_history"]) > 1,
            "visual": any(asset.get("role") == "student_visual_answer"
                          for asset in row["visual_assets"]),
            "zero": row["score"] == 0,
            "partial": row["score"] is not None and row["max_score"] is not None
            and 0 < row["score"] < row["max_score"],
            "full": row["score"] is not None and row["max_score"] is not None
            and row["score"] == row["max_score"],
            "all": True,
        }.get(filter_key, False)

    def review_queue(self, test_id, *, filter_key=None):
        if self.s.get(Test, test_id) is None:
            raise KeyError("NOT_FOUND")
        rows = self._all_rows(test_id)
        filtered = [row for row in rows if self._matches(row, filter_key)]
        reviewed = sum(not row["review_flags"] and not row["regrade_pending"] for row in rows)
        return {
            "test_id": test_id,
            "filter": filter_key or "unresolved",
            "items": filtered,
            "progress": {
                "reviewed": reviewed, "total": len(rows), "remaining": len(rows) - reviewed,
                "warnings": sum(bool(row["flags"]) for row in rows),
                "regrade_pending": sum(row["regrade_pending"] for row in rows),
                "teacher_adjudicated": sum(row["teacher_adjudicated"] for row in rows),
            },
        }

    def regrade_queue(self, test_id, *, include_completed=False):
        if self.s.get(Test, test_id) is None:
            raise KeyError("NOT_FOUND")
        rows = self._all_rows(test_id)
        by_target = {row["target"]: row for row in rows}
        requests = self._request_events(test_id)
        if not include_completed:
            requests = [request for request in requests if request["status"] != "COMPLETED"
                        and request["status"] != "REJECTED"]
        result = []
        for request in requests:
            row = by_target.get(request.get("target"), {})
            authoritative = row.get("authoritative")
            result.append({
                **request,
                "student_ref": row.get("student_ref"),
                "student_number": row.get("student_number", ""),
                "student_name": row.get("student_name", ""),
                "student_display_label": row.get("student_display_label", "学生情報未確認"),
                "question_label": row.get("question_label"),
                "score": authoritative.get("score") if authoritative else None,
                "max_score": authoritative.get("max_score") if authoritative else row.get("max_score"),
                "reconstruction": (row.get("question_review", {}).get("student_answer", {})
                                    .get("reconstruction") or {}),
                "warnings": row.get("flags", []),
            })
        return {"test_id": test_id, "requests": result,
                "pending_count": sum(request["status"] in {"PENDING", "APPROVED", "FAILED"}
                                      for request in result)}
