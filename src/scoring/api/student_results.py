"""Student-owned, published result projections."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from ..publishing import PublicationError, ResultPublicationService
from ..auth import student_guard


def router(db, *, root=None, answer_root=None, student_portal_enabled=True):
    def student_auth(request: Request,
                     x_role: str | None = Header(None, alias="X-Role"),
                     x_student_id: str | None = Header(None, alias="X-Student-ID"),
                     query_student_id: str | None = Query(None, alias="student_id"),
                     query_role: str | None = Query(None, alias="role")):
        if not student_portal_enabled:
            raise HTTPException(404, {"error": {"code": "STUDENT_PORTAL_DISABLED",
                                                  "message": "STUDENT_PORTAL_DISABLED"}})
        return student_guard(request, role=x_role or query_role,
                             student_id=x_student_id or query_student_id)

    r = APIRouter(prefix="/api/v1/student", dependencies=[Depends(student_auth)])

    def service(session):
        return ResultPublicationService(session, root=root, answer_root=answer_root)

    def identity(student_id, header_student_id):
        return header_student_id or student_id

    def error(exc):
        code = str(exc)
        status = 404 if code in {"RESULT_NOT_PUBLISHED", "SUBMISSION_NOT_FOUND",
                                 "PUBLISHED_VISUAL_ASSET_NOT_FOUND"} else 403 if code in {
                                     "STUDENT_ID_REQUIRED", "STUDENT_ACCESS_DENIED"} else 409
        return HTTPException(status, {"error": {"code": code, "message": code}})

    @r.get("/results/{submission_id}")
    def result(submission_id: str, student_id: str | None = Query(None),
               x_student_id: str | None = Header(None, alias="X-Student-ID"), s=Depends(db)):
        try:
            return service(s).student_result(
                submission_id, requester_student_id=identity(student_id, x_student_id))
        except PublicationError as exc:
            raise error(exc) from exc

    @r.get("/results/{submission_id}/pdf")
    def result_pdf(submission_id: str, student_id: str | None = Query(None),
                   x_student_id: str | None = Header(None, alias="X-Student-ID"), s=Depends(db)):
        try:
            data = service(s).result_pdf_bytes(
                "", submission_id, requester_student_id=identity(student_id, x_student_id), student=True)
            return Response(content=data, media_type="application/pdf",
                            headers={"Content-Disposition": 'inline; filename="result.pdf"'})
        except PublicationError as exc:
            raise error(exc) from exc

    @r.get("/result-assets/{token}")
    def visual(token: str, student_id: str | None = Query(None),
               x_student_id: str | None = Header(None, alias="X-Student-ID"), s=Depends(db)):
        try:
            path, mime = service(s).visual_path_for_student_token(
                token, requester_student_id=identity(student_id, x_student_id))
            return FileResponse(path, media_type=mime)
        except PublicationError as exc:
            raise error(exc) from exc

    # Compatibility route for clients that already hold the question-scoped
    # URL.  New DTOs use the opaque `/result-assets/{token}` route above.
    @r.get("/results/{submission_id}/questions/{question_id}/visual/{token}")
    def visual_legacy(submission_id: str, question_id: str, token: str,
                      student_id: str | None = Query(None),
                      x_student_id: str | None = Header(None, alias="X-Student-ID"), s=Depends(db)):
        try:
            path, mime = service(s).visual_path_by_token(
                submission_id, question_id, token,
                requester_student_id=identity(student_id, x_student_id))
            return FileResponse(path, media_type=mime)
        except PublicationError as exc:
            raise error(exc) from exc

    return r
