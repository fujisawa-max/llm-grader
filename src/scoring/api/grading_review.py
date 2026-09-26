"""Read-only endpoints for the teacher grading review UI."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db.models import StudentSubmission, TestQuestion
from ..grading_actions import GradingActionService
from ..grading_review import GradingReviewService
from ..review_workspace import ReviewWorkspaceService
from ..publishing import PublicationError, ResultPublicationService
from ..auth import teacher_guard
from ..student_identity import StudentIdentityService


class TeacherDecisionRequest(BaseModel):
    criterion_scores: list[dict]
    teacher_reason: str = Field(min_length=1)
    teacher_note: str | None = None
    teacher_user_id: str | None = None


class RegradeRequest(BaseModel):
    reason: str = Field(min_length=1)
    requested_by: str | None = None


class FinalizeRequest(BaseModel):
    actor_user_id: str | None = None


class RegradeApprovalRequest(BaseModel):
    approved_by: str | None = None


class RegradeRejectionRequest(BaseModel):
    reason: str = Field(min_length=1)
    rejected_by: str | None = None


class PublicationRequest(BaseModel):
    actor_user_id: str | None = None


class FeedbackOverrideRequest(BaseModel):
    feedback: str = Field(min_length=1)
    teacher_note: str | None = None
    actor_user_id: str | None = None


def build_grading_csv(session, test_id: str, *, root=None, identity_root=None) -> str:
    """Build the authoritative export without introducing a second resolver."""
    overview = GradingReviewService(session, root=root, identity_root=identity_root).overview(test_id)
    questions = list(session.scalars(select(TestQuestion).where(
        TestQuestion.test_id == test_id, TestQuestion.is_gradable.is_(True)
    ).order_by(TestQuestion.sort_order, TestQuestion.id)))
    submissions = list(session.scalars(select(StudentSubmission).where(
        StudentSubmission.test_id == test_id)))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    question_columns = [q.question_number for q in questions]
    header = ["student_id", "student_ref", "student_name"]
    header += [f"{number}_score" for number in question_columns]
    header += ["total_score", "max_score", "percentage", "finalized",
               "teacher_adjudication_count", "warning_count", "published", "published_at"]
    writer.writerow(header)
    rows_by_submission = {row["submission_id"]: row for row in overview["students"]}
    service = GradingReviewService(session, root=root, identity_root=identity_root)
    identity_service = StudentIdentityService(session, root=identity_root) if identity_root else None
    for sub in submissions:
        detail = service.detail(test_id, sub.id)
        by_q = {row["question"]["id"]: row for row in detail["questions"]}
        try:
            identity = identity_service.load(sub.id) if identity_service else None
        except (OSError, ValueError, TypeError):
            identity = None
        summary = rows_by_submission.get(sub.id, {})
        publication = ResultPublicationService(session, root=root).publication_state(test_id, sub.id)
        scores = []
        for question in questions:
            result = by_q[question.id]["authoritative"]
            scores.append(result["score"] if result else "")
        writer.writerow([sub.student_id, (identity or {}).get("student_number", ""),
                         (identity or {}).get("student_name", ""), *scores,
                         summary.get("score", ""), overview["test"]["total_points"],
                         summary.get("percentage", ""),
                         "YES" if detail["submission"].get("finalized") else "NO",
                         detail["submission"].get("teacher_adjudicated_count", 0),
                         len(detail["submission"].get("warnings", [])),
                         "YES" if publication.get("published") else "NO",
                         publication.get("published_at") or ""])
    return "\ufeff" + output.getvalue()


def router(db, *, root=None, action_root=None, allowed_roots=None,
           visual_options=None, grading_config_path=None):
    def teacher_auth(test_id: str, request: Request,
                     query_role: str | None = Query(None, alias="role"),
                     query_user_id: str | None = Query(None, alias="user_id"),
                     s=Depends(db)):
        user = teacher_guard(test_id, request, s, role=query_role, user_id=query_user_id)
        # Bind audit actor fields to the authenticated owner.  Request bodies
        # are data, not credentials, so a caller cannot impersonate another
        # teacher by sending an arbitrary ``*_by``/``*_user_id`` value.
        request.state.teacher_user_id = user.id
        return user

    r = APIRouter(prefix="/api/v1", dependencies=[Depends(teacher_auth)])

    @r.get("/tests/{test_id}/grading", summary="Read-only grading overview")
    def overview(test_id: str, s=Depends(db)):
        try:
            return GradingReviewService(s, root=root, identity_root=action_root).overview(test_id)
        except KeyError:
            raise HTTPException(404, {"error": {"code": "test_not_found", "message": "testがありません"}})

    def actions(s):
        options = visual_options or {}
        return GradingActionService(
            s, artifact_root=action_root or root or "artifacts", mapping_root=root,
            allowed_roots=allowed_roots, answer_root=options.get("answer_root"),
            reference_root=options.get("reference_root"),
            visual_capability=options.get("visual_capability"),
            grading_config_path=grading_config_path,
        )

    def publisher(s):
        options = visual_options or {}
        return ResultPublicationService(
            s, root=root, answer_root=options.get("answer_root") or action_root or root,
        )

    def action_error(exc):
        return HTTPException(409, {"error": {"code": str(exc), "message": str(exc)}})

    @r.post("/tests/{test_id}/grading/{submission_id}/questions/{question_id}/teacher-decision")
    def teacher_decision(test_id: str, submission_id: str, question_id: str,
                         value: TeacherDecisionRequest, request: Request, s=Depends(db)):
        try:
            row, created = actions(s).teacher_decision(
                test_id=test_id, submission_id=submission_id, question_id=question_id,
                criterion_scores=value.criterion_scores, teacher_reason=value.teacher_reason,
                teacher_note=value.teacher_note,
                teacher_user_id=request.state.teacher_user_id)
            s.commit()
            return {"id": row.id, "decision_version": row.decision_version, "score": row.score,
                    "max_score": row.max_score, "status": row.status, "created": created,
                    "criterion_scores": row.criterion_scores, "artifact_ref": row.artifact_ref}
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/{submission_id}/questions/{question_id}/regrade-request")
    def regrade_request(test_id: str, submission_id: str, question_id: str,
                        value: RegradeRequest, request: Request, s=Depends(db)):
        try:
            result = actions(s).request_regrade(test_id=test_id, submission_id=submission_id,
                                                question_id=question_id, reason=value.reason,
                                                requested_by=request.state.teacher_user_id)
            s.commit()
            return result
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/{submission_id}/finalize")
    def finalize_submission(test_id: str, submission_id: str,
                            value: FinalizeRequest | None = None, request: Request = None,
                            s=Depends(db)):
        try:
            result, created = actions(s).finalize_submission(
                test_id=test_id, submission_id=submission_id,
                actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**result, "created": created}
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/finalize")
    def finalize_test(test_id: str, value: FinalizeRequest | None = None,
                     request: Request = None, s=Depends(db)):
        try:
            result, created = actions(s).finalize_test(
                test_id=test_id, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**result, "created": created}
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/publish")
    def publish_test(test_id: str, value: PublicationRequest | None = None,
                     request: Request = None, s=Depends(db)):
        try:
            payload, created = publisher(s).publish_test(
                test_id, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**payload, "created": created}
        except PublicationError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/unpublish")
    def unpublish_test(test_id: str, value: PublicationRequest | None = None,
                       request: Request = None, s=Depends(db)):
        try:
            payload, created = publisher(s).unpublish_test(
                test_id, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**payload, "created": created}
        except PublicationError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/{submission_id}/publish")
    def publish_submission(test_id: str, submission_id: str,
                            value: PublicationRequest | None = None, request: Request = None,
                            s=Depends(db)):
        try:
            payload, created = publisher(s).publish_submission(
                test_id, submission_id, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**payload, "created": created}
        except PublicationError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/{submission_id}/unpublish")
    def unpublish_submission(test_id: str, submission_id: str,
                              value: PublicationRequest | None = None, request: Request = None,
                              s=Depends(db)):
        try:
            payload, created = publisher(s).unpublish_submission(
                test_id, submission_id, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return {**payload, "created": created}
        except PublicationError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/{submission_id}/questions/{question_id}/feedback-override")
    def feedback_override(test_id: str, submission_id: str, question_id: str,
                          value: FeedbackOverrideRequest, request: Request, s=Depends(db)):
        try:
            result = publisher(s).feedback_override(
                test_id, submission_id, question_id, value.feedback,
                teacher_note=value.teacher_note, actor_user_id=request.state.teacher_user_id)
            s.commit()
            return result
        except PublicationError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.get("/tests/{test_id}/grading/review")
    def review_queue(test_id: str, filter: str | None = None, s=Depends(db)):
        try:
            return ReviewWorkspaceService(s, root=root, identity_root=action_root).review_queue(test_id, filter_key=filter)
        except KeyError as exc:
            raise HTTPException(404, "test_not_found") from exc

    @r.get("/tests/{test_id}/grading/regrade-queue")
    def regrade_queue(test_id: str, include_completed: bool = False, s=Depends(db)):
        try:
            return ReviewWorkspaceService(s, root=root, identity_root=action_root).regrade_queue(
                test_id, include_completed=include_completed)
        except KeyError as exc:
            raise HTTPException(404, "test_not_found") from exc

    @r.post("/tests/{test_id}/grading/regrade-requests/{request_id}/approve")
    def approve_regrade(test_id: str, request_id: str,
                        value: RegradeApprovalRequest | None = None, request: Request = None,
                        s=Depends(db)):
        try:
            # The request payload is authoritative for its target; the service
            # verifies that it belongs to this Test before creating a job.
            result = actions(s).approve_regrade(
                request_id=request_id, test_id=test_id,
                approved_by=request.state.teacher_user_id)
            s.commit()
            return result
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.post("/tests/{test_id}/grading/regrade-requests/{request_id}/reject")
    def reject_regrade(test_id: str, request_id: str, value: RegradeRejectionRequest,
                       request: Request, s=Depends(db)):
        try:
            result = actions(s).reject_regrade(
                request_id=request_id, test_id=test_id,
                reason=value.reason, rejected_by=request.state.teacher_user_id)
            s.commit()
            return result
        except ValueError as exc:
            s.rollback()
            raise action_error(exc) from exc

    @r.get("/tests/{test_id}/grading/export.csv")
    def export_csv(test_id: str, s=Depends(db)):
        try:
            content = build_grading_csv(s, test_id, root=root, identity_root=action_root)
        except KeyError as exc:
            raise HTTPException(404, "test_not_found") from exc
        return Response(content=content, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="grading-{test_id}.csv"'})

    @r.get("/tests/{test_id}/grading/{submission_id}/result.pdf")
    def teacher_result_pdf(test_id: str, submission_id: str, s=Depends(db)):
        try:
            content = publisher(s).result_pdf_bytes(test_id, submission_id)
            return Response(content=content, media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="result-{submission_id}.pdf"'})
        except PublicationError as exc:
            raise action_error(exc) from exc

    @r.get("/tests/{test_id}/grading/{submission_id}", summary="Read-only student grading detail")
    def detail(test_id: str, submission_id: str, s=Depends(db)):
        try:
            return GradingReviewService(s, root=root, identity_root=action_root).detail(test_id, submission_id)
        except KeyError:
            raise HTTPException(404, {"error": {"code": "submission_not_found", "message": "答案がありません"}})

    return r
