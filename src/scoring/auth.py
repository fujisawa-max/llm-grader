"""Authentication and service-level authorization helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header, HTTPException, Request
from sqlalchemy import select

from .db.models import (AuthSession, Course, CourseOffering, ModelAnswer,
                        QuestionImportConfirmation, QuestionImportDraft,
                        QuestionImportExtraction, QuestionImportReview,
                        QuestionImportVisionRun, RubricVersion, SampleAnswer,
                        StudentAnswerExtractionResult, StudentAnswerExtractionRun,
                        StudentAnswerReconstruction, StudentSubmission, Test,
                        TestQuestion, TestQuestionAsset, User)

TEACHER = "teacher"
ADMIN = "admin"
STUDENT = "student"
STAFF_ROLES = {TEACHER, ADMIN}
SUPPORTED_ROLES = {TEACHER, ADMIN, STUDENT}
SESSION_COOKIE = "llm_grader_session"
SESSION_TTL_SECONDS = int(os.getenv("LLM_GRADER_SESSION_TTL_SECONDS", str(8 * 60 * 60)))


def _auth_error(code: str, status: int):
    return HTTPException(status, {"error": {"code": code, "message": code}})


def normalize_email(value: str) -> str:
    value = str(value or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("invalid email")
    return value


def validate_password(value: str) -> str:
    if not isinstance(value, str) or len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(value) > 512:
        raise ValueError("password is too long")
    return value


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return "scrypt$16384$8$1$%s$%s" % (salt.hex(), digest.hex())


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("scrypt$"):
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            str(password).encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def public_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "display_name": user.display_name, "email": user.email,
            "role": user.role, "is_active": bool(user.is_active),
            "must_change_password": bool(user.must_change_password),
            "created_at": user.created_at, "updated_at": user.updated_at}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _header_auth_enabled() -> bool:
    return os.getenv("LLM_GRADER_ALLOW_HEADER_AUTH", "false").lower() in {"1", "true", "yes"}


def _cookie_user(request: Request, s) -> User | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    session = s.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if not session or session.revoked_at or _utc(session.expires_at) <= datetime.now(timezone.utc):
        return None
    user = s.get(User, session.user_id)
    if not user or not user.is_active:
        return None
    request.state.auth_user = user
    request.state.auth_session_id = session.id
    return user


def request_user(request: Request, s, *, allow_header: bool | None = None) -> User:
    user = _cookie_user(request, s)
    if user:
        return user
    if allow_header is None:
        allow_header = _header_auth_enabled()
    if allow_header:
        user_id = request.headers.get("X-User-ID")
        role = request.headers.get("X-Role")
        if user_id and role:
            user = s.get(User, user_id)
            if user and user.is_active and user.role == role.lower():
                request.state.auth_user = user
                return user
    raise _auth_error("AUTHENTICATION_REQUIRED", 401)


def require_authenticated_user(request: Request, s) -> User:
    return request_user(request, s)


def require_admin_user(request: Request, s) -> User:
    user = request_user(request, s)
    if user.role != ADMIN:
        raise _auth_error("ADMIN_ROLE_REQUIRED", 403)
    return user


def require_staff_user(request: Request, s) -> User:
    user = request_user(request, s)
    if user.role not in STAFF_ROLES:
        raise _auth_error("TEACHER_ROLE_REQUIRED", 403)
    return user


def create_session(s, user: User, *, ttl_seconds: int | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    s.add(AuthSession(token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                      user_id=user.id, created_at=now,
                      expires_at=now + timedelta(seconds=ttl_seconds or SESSION_TTL_SECONDS)))
    return raw


def revoke_session(s, request: Request) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    session = s.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session and not session.revoked_at:
        session.revoked_at = datetime.now(timezone.utc)


def _course_owner_id(s, test_id: str | None = None, course_id: str | None = None,
                     offering_id: str | None = None) -> str | None:
    if course_id:
        course = s.get(Course, course_id)
        return course.owner_user_id if course else None
    if offering_id:
        offering = s.get(CourseOffering, offering_id)
        return _course_owner_id(s, course_id=offering.course_id) if offering else None
    test = s.get(Test, test_id) if test_id else None
    return _course_owner_id(s, offering_id=test.course_offering_id) if test else None


def _test_id_for_resource(s, resource: str, identifier: str) -> str | None:
    """Resolve nested/import/answer resources to their owning Test."""
    if resource == "question-imports":
        value = s.get(QuestionImportExtraction, identifier)
        return value.test_id if value else None
    if resource == "question-import-drafts":
        value = s.get(QuestionImportDraft, identifier)
        extraction = s.get(QuestionImportExtraction, value.extraction_id) if value else None
        return extraction.test_id if extraction else None
    if resource == "question-import-reviews":
        value = s.get(QuestionImportReview, identifier)
        draft = s.get(QuestionImportDraft, value.draft_id) if value else None
        extraction = s.get(QuestionImportExtraction, draft.extraction_id) if draft else None
        return extraction.test_id if extraction else None
    if resource == "question-import-confirmations":
        value = s.get(QuestionImportConfirmation, identifier)
        return value.test_id if value else None
    if resource == "question-import-vision-runs":
        value = s.get(QuestionImportVisionRun, identifier)
        draft = s.get(QuestionImportDraft, value.draft_id) if value else None
        extraction = s.get(QuestionImportExtraction, draft.extraction_id) if draft else None
        return extraction.test_id if extraction else None
    if resource == "test-question-assets":
        value = s.get(TestQuestionAsset, identifier)
        question = s.get(TestQuestion, value.question_id) if value else None
        return question.test_id if question else None
    if resource == "answer-reconstruction-runs":
        value = s.get(StudentAnswerExtractionRun, identifier)
        return value.test_id if value else None
    if resource == "model-answer-import-drafts":
        from .db.models import ModelAnswerImportDraft
        value = s.get(ModelAnswerImportDraft, identifier)
        return value.test_id if value else None
    if resource == "answer-reconstruction-results":
        value = s.get(StudentAnswerExtractionResult, identifier)
        submission = s.get(StudentSubmission, value.submission_id) if value else None
        return submission.test_id if submission else None
    if resource == "answer-reconstructions":
        value = s.get(StudentAnswerReconstruction, identifier)
        submission = s.get(StudentSubmission, value.submission_id) if value else None
        return submission.test_id if submission else None
    return None


def authorize_domain_path(request: Request, s, user: User) -> User:
    """Enforce Course owner isolation for the shared domain router."""
    if user.role == ADMIN:
        return user
    path = request.url.path.removeprefix("/api/v1").strip("/").split("/")
    if not path or path[0] == "users":
        raise _auth_error("ADMIN_ROLE_REQUIRED", 403)
    owner_id = None
    if path[0] == "courses" and len(path) >= 2:
        owner_id = _course_owner_id(s, course_id=path[1])
    elif path[0] == "courses" and len(path) >= 3 and path[2] == "offerings":
        owner_id = _course_owner_id(s, course_id=path[1])
    elif path[0] == "offerings" and len(path) >= 2:
        owner_id = _course_owner_id(s, offering_id=path[1])
    elif path[0] in {"tests", "test-questions"}:
        test_id = path[1] if path[0] == "tests" and len(path) >= 2 else None
        if path[0] == "test-questions" and len(path) >= 2:
            question = s.get(TestQuestion, path[1])
            test_id = question.test_id if question else None
        owner_id = _course_owner_id(s, test_id=test_id)
    elif path[0] in {"questions", "model-answers", "rubrics", "sample-answers"} and len(path) >= 2:
        model_map = {"questions": TestQuestion, "model-answers": ModelAnswer,
                     "rubrics": RubricVersion, "sample-answers": SampleAnswer}
        value = s.get(model_map[path[0]], path[1])
        owner_id = _course_owner_id(s, test_id=getattr(value, "test_id", None)) if value else None
    elif len(path) >= 2 and path[0] in {
        "question-imports", "question-import-drafts", "question-import-reviews",
        "question-import-confirmations", "question-import-vision-runs",
        "model-answer-import-drafts",
        "test-question-assets", "answer-reconstruction-runs",
        "answer-reconstruction-results", "answer-reconstructions",
    }:
        owner_id = _course_owner_id(s, test_id=_test_id_for_resource(s, path[0], path[1]))
    if owner_id is not None and owner_id != user.id:
        raise _auth_error("COURSE_ACCESS_DENIED", 403)
    if owner_id is None and path[0] not in {"courses", "health"}:
        raise _auth_error("RESOURCE_NOT_FOUND", 404)
    return user


def teacher_guard(test_id: str, request: Request, s, *, role: str | None = None,
                  user_id: str | None = None):
    """Authorize a teacher/admin owning the Test's Course."""
    if role is not None and user_id is not None and not request.cookies.get(SESSION_COOKIE):
        # Unit-level callers from the legacy worker pass a synthetic root
        # request.  Keep that compatibility seam without accepting forged
        # role headers on real API paths unless the explicit header-auth flag
        # is enabled.
        if (not _header_auth_enabled() and request.scope.get("type") == "http"
                and request.url.path not in {"", "/"}):
            raise _auth_error("AUTHENTICATION_REQUIRED", 401)
        user = s.get(User, user_id)
        if not user or not user.is_active or user.role != role.lower():
            raise _auth_error("TEACHER_ROLE_REQUIRED", 403)
    else:
        # Legacy in-process worker tests pass a root-path request with the
        # explicit identity headers.  Real HTTP API paths still require a
        # session unless header auth was deliberately enabled.
        allow_header = _header_auth_enabled() or request.url.path in {"", "/"}
        if allow_header and request.url.path in {"", "/"} and not request.cookies.get(SESSION_COOKIE):
            header_id = request.headers.get("X-User-ID")
            header_role = request.headers.get("X-Role")
            if header_id and header_role:
                user = s.get(User, header_id)
                if not user or not user.is_active:
                    raise _auth_error("AUTHENTICATION_REQUIRED", 401)
                if user.role != header_role.lower():
                    raise _auth_error("TEACHER_ROLE_REQUIRED", 403)
            else:
                user = request_user(request, s, allow_header=allow_header)
        else:
            user = request_user(request, s, allow_header=allow_header)
    if user.role not in STAFF_ROLES:
        raise _auth_error("TEACHER_ROLE_REQUIRED", 403)
    owner_id = _course_owner_id(s, test_id=test_id)
    if user.role != ADMIN and owner_id != user.id:
        raise _auth_error("TEACHER_ACCESS_DENIED", 403)
    return user


def require_teacher_headers(request: Request,
                            x_role: str | None = Header(None, alias="X-Role"),
                            x_user_id: str | None = Header(None, alias="X-User-ID")):
    """Compatibility helper; production requests should use the session cookie."""
    if not x_role or not x_user_id or not _header_auth_enabled():
        raise _auth_error("AUTHENTICATION_REQUIRED", 401)
    return x_user_id


def student_guard(request: Request, *, student_id: str | None = None,
                  role: str | None = None):
    """Compatibility boundary for the optional student portal.

    Student identities are submission records rather than staff User accounts;
    the portal therefore continues to require an explicit student identity
    header/query value and lets the publication service enforce ownership.
    """
    resolved_role = role or request.headers.get("X-Role")
    if not resolved_role or resolved_role.lower() != STUDENT:
        raise _auth_error("STUDENT_ROLE_REQUIRED", 401 if not resolved_role else 403)
    resolved = student_id or request.headers.get("X-Student-ID")
    if not resolved:
        raise _auth_error("STUDENT_ID_REQUIRED", 401)
    return resolved
