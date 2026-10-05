from pathlib import Path
from datetime import datetime, timezone
import hashlib
import logging
import re
import shutil
from uuid import UUID
from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text, select
from ..core import load_assignment
from ..db import create_session_factory, JobRepository
from ..db.models import (GradingJob, GradingJobItem, GradingJobEvent, Test,
                         TestMaterial, QuestionImportExtraction, User,
                         DomainEvent, SetupLock)
from ..pdf_native import PyMuPdfNativeExtractor, IR_SCHEMA_VERSION
from .domain import router as domain_router
from .question_drafts import router as question_draft_router
from .question_vision import router as question_vision_router
from .question_reviews import router as question_review_router
from .model_answer_imports import router as model_answer_import_router
from .student_answers import router as student_answer_router
from .grading_review import router as grading_review_router
from .student_results import router as student_results_router
from ..auth import (ADMIN, SESSION_COOKIE, SUPPORTED_ROLES, STAFF_ROLES, create_session,
                    hash_password, normalize_email, public_user, request_user,
                    revoke_session, validate_password, authorize_domain_path,
                    teacher_guard, verify_password)
from .schemas import (LoginRequest, SetupInitializeRequest, AdminUserCreate, AdminUserUpdate,
                      PasswordChangeRequest, PasswordResetRequest)
from ..operations import student_portal_enabled as resolve_student_portal_enabled


class JobCreate(BaseModel):
    execution_mode: str
    assignment_path: str
    run_path: str
    config_path: str
    keep_final_runtime_running: bool = False


def _safe(path, roots):
    value = Path(path).resolve()
    if any(value == root or root in value.parents for root in roots):
        return str(value)
    raise HTTPException(
        400, detail={"error": {"code": "invalid_path", "message": "許可されたroot外です"}}
    )


def create_app(session_factory=None, *, allowed_roots=None, runtime_client=None,
               question_import_root=None, question_import_limits=None,
               vision_config=None, vision_inference=None, grading_visual_config=None,
               student_portal_enabled: bool | None = None,
               model_answer_classifier=None):
    app = FastAPI(title="llm-grader API", version="1.0", openapi_url="/api/v1/openapi.json")
    # The browser UI is served separately during development.  Keep origins
    # explicit and configurable; this does not expose internal runtime APIs.
    import os
    if model_answer_classifier is None and runtime_client is not None:
        from ..model_answer_classification import ModelAnswerSemanticClassifier
        model_answer_classifier = ModelAnswerSemanticClassifier(
            runtime_client,
            profile_id=os.getenv("LLM_GRADER_MODEL_ANSWER_CLASSIFIER_PROFILE", "ornith_rubric_draft"),
            threshold=float(os.getenv("LLM_GRADER_MODEL_ANSWER_CLASSIFIER_CONFIDENCE", "0.82")),
        )
    portal_enabled = resolve_student_portal_enabled(student_portal_enabled)
    cors_origins = [x.strip() for x in os.getenv(
        "LLM_GRADER_CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:13000,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:13000,http://ai-serv2:3001,http://ai-serv2:3000",
    ).split(",") if x.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=True)
    logger = logging.getLogger(__name__)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict) and "error" in exc.detail
            else {"error": {"code": "http_error", "message": str(exc.detail)}}
        )
        return JSONResponse(detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/api/v1/text-tools/latex-normalize":
            logger.warning("latex API invalid request fields=%s", [error["loc"] for error in exc.errors()])
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "入力値が不正です",
                    "details": exc.errors(),
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.exception("API request failed", exc_info=exc)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "内部エラーが発生しました"}},
            status_code=500,
        )

    if session_factory is None:
        session_factory = create_session_factory()[1]
    roots = [Path(x).resolve() for x in (allowed_roots or [Path.cwd()])]
    import_root = Path(question_import_root or os.getenv(
        "LLM_GRADER_QUESTION_IMPORT_ROOT", str(Path.cwd() / "artifacts" / "question-imports")
    )).resolve()
    import_root.mkdir(parents=True, exist_ok=True)
    limits = {"max_bytes": 25 * 1024 * 1024, "max_pages": 200}
    limits.update(question_import_limits or {})

    def db():
        with session_factory() as s:
            yield s

    def authenticated(request: Request, s=Depends(db)):
        user = request_user(request, s)
        s.info["auth_user_id"] = user.id
        s.info["auth_user"] = user
        return user

    def domain_authorized(request: Request, s=Depends(db)):
        user = authenticated(request, s)
        if user.role not in STAFF_ROLES:
            raise HTTPException(403, {"error": {"code": "TEACHER_ROLE_REQUIRED", "message": "TEACHER_ROLE_REQUIRED"}})
        return authorize_domain_path(request, s, user)

    def admin_only(request: Request, s=Depends(db)):
        user = authenticated(request, s)
        if user.role != ADMIN:
            raise HTTPException(403, {"error": {"code": "ADMIN_ROLE_REQUIRED", "message": "ADMIN_ROLE_REQUIRED"}})
        return user

    def setup_required(s):
        return s.scalar(select(User.id).where(User.role == ADMIN, User.is_active.is_(True)).limit(1)) is None

    @app.get("/api/v1/setup/status", summary="Whether first-run setup is required")
    def setup_status(s=Depends(db)):
        return {"setup_required": setup_required(s)}

    @app.post("/api/v1/setup/initialize", status_code=201, summary="Create the first administrator")
    def setup_initialize(value: SetupInitializeRequest, s=Depends(db)):
        # The singleton row is locked on PostgreSQL, making the check and insert
        # atomic across workers. SQLite's serialized write transaction provides
        # the same property for the supported local setup path.
        lock = s.get(SetupLock, 1)
        if lock is None:
            lock = SetupLock(id=1)
            s.add(lock)
            s.flush()
        else:
            s.refresh(lock, with_for_update=True)
        if not setup_required(s):
            s.rollback()
            raise HTTPException(409, {"error": {"code": "SETUP_ALREADY_COMPLETED", "message": "初期設定は完了しています"}})
        try:
            email = normalize_email(value.email)
            validate_password(value.password)
        except ValueError as exc:
            s.rollback()
            raise HTTPException(422, {"error": {"code": "INVALID_SETUP_INPUT", "message": str(exc)}}) from exc
        if s.scalar(select(User.id).where(User.email == email).limit(1)):
            s.rollback()
            raise HTTPException(409, {"error": {"code": "DUPLICATE_EMAIL", "message": "このメールアドレスは既に登録されています"}})
        user = User(display_name=value.display_name.strip(), email=email, role=ADMIN,
                    password_hash=hash_password(value.password), is_active=True,
                    must_change_password=False)
        s.add(user)
        s.flush()
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="admin_setup_completed",
                          payload={"email": email}))
        s.commit()
        return {"user": public_user(user)}

    @app.post("/api/v1/auth/login", summary="Create a browser session")
    def login(value: LoginRequest, response: Response, s=Depends(db)):
        try:
            email = normalize_email(value.email)
        except ValueError:
            raise HTTPException(401, {"error": {"code": "INVALID_CREDENTIALS", "message": "メールアドレスまたはパスワードが正しくありません"}})
        # Legacy databases may contain duplicate placeholder emails.  Refuse
        # an ambiguous login rather than selecting an account arbitrarily.
        matches = list(s.scalars(select(User).where(User.email == email).limit(2)))
        user = matches[0] if len(matches) == 1 else None
        if not user or not user.is_active or not verify_password(value.password, user.password_hash):
            raise HTTPException(401, {"error": {"code": "INVALID_CREDENTIALS", "message": "メールアドレスまたはパスワードが正しくありません"}})
        token = create_session(s, user)
        s.commit()
        response.set_cookie(
            SESSION_COOKIE, token, max_age=int(os.getenv("LLM_GRADER_SESSION_TTL_SECONDS", str(8 * 60 * 60))),
            httponly=True, samesite="lax",
            secure=os.getenv("LLM_GRADER_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
        )
        return {"user": public_user(user), "must_change_password": bool(user.must_change_password)}

    @app.get("/api/v1/auth/me", summary="Current authenticated user")
    def me(request: Request, s=Depends(db)):
        return public_user(authenticated(request, s))

    @app.post("/api/v1/auth/logout", summary="Revoke the current browser session")
    def logout(request: Request, response: Response, s=Depends(db)):
        revoke_session(s, request)
        s.commit()
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.post("/api/v1/auth/change-password", summary="Change the current password")
    def change_password(value: PasswordChangeRequest, request: Request, response: Response, s=Depends(db)):
        user = authenticated(request, s)
        if not verify_password(value.current_password, user.password_hash):
            raise HTTPException(400, {"error": {"code": "CURRENT_PASSWORD_INVALID", "message": "現在のパスワードが正しくありません"}})
        try:
            validate_password(value.new_password)
        except ValueError as exc:
            raise HTTPException(422, {"error": {"code": "WEAK_PASSWORD", "message": str(exc)}}) from exc
        user.password_hash = hash_password(value.new_password)
        user.must_change_password = False
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="password_changed",
                           actor_user_id=user.id))
        s.commit()
        return {"user": public_user(user), "must_change_password": False}

    @app.get("/api/v1/admin/users", summary="List users", dependencies=[Depends(admin_only)])
    def admin_users(s=Depends(db)):
        return [public_user(user) for user in s.scalars(select(User).order_by(User.created_at))]

    @app.post("/api/v1/admin/users", status_code=201, summary="Create a managed user",
              dependencies=[Depends(admin_only)])
    def admin_user_create(value: AdminUserCreate, s=Depends(db)):
        try:
            email = normalize_email(value.email)
            if value.role not in SUPPORTED_ROLES:
                raise ValueError("unsupported role")
            password = value.initial_password or __import__("secrets").token_urlsafe(12)
            validate_password(password)
        except ValueError as exc:
            raise HTTPException(422, {"error": {"code": "INVALID_USER_INPUT", "message": str(exc)}}) from exc
        if s.scalars(select(User).where(User.email == email).limit(1)).first():
            raise HTTPException(409, {"error": {"code": "DUPLICATE_EMAIL", "message": "email already exists"}})
        user = User(display_name=value.display_name.strip(), email=email, role=value.role,
                    password_hash=hash_password(password), is_active=True, must_change_password=True)
        s.add(user)
        s.flush()
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="user_created",
                           actor_user_id=s.info.get("auth_user_id"),
                           payload={"role": user.role, "email": user.email}))
        s.commit()
        result = {"user": public_user(user)}
        if not value.initial_password:
            result["temporary_password"] = password
        return result

    @app.get("/api/v1/admin/users/{user_id}", summary="Get a managed user",
             dependencies=[Depends(admin_only)])
    def admin_user_get(user_id: str, s=Depends(db)):
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "user not found")
        return public_user(user)

    @app.patch("/api/v1/admin/users/{user_id}", summary="Update a managed user",
               dependencies=[Depends(admin_only)])
    def admin_user_update(user_id: str, value: AdminUserUpdate, request: Request, s=Depends(db)):
        actor = authenticated(request, s)
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "user not found")
        updates = value.model_dump(exclude_none=True)
        if actor.id == user.id and updates.get("is_active") is False:
            raise HTTPException(409, "cannot deactivate the current user")
        if "email" in updates:
            try:
                updates["email"] = normalize_email(updates["email"])
            except ValueError as exc:
                raise HTTPException(422, "invalid email") from exc
            duplicate = s.scalars(select(User).where(User.email == updates["email"], User.id != user.id).limit(1)).first()
            if duplicate:
                raise HTTPException(409, "duplicate email")
        if "role" in updates and updates["role"] not in SUPPORTED_ROLES:
            raise HTTPException(422, "unsupported role")
        for key, item in updates.items():
            setattr(user, key, item)
        event_type = "user_activated" if updates.get("is_active") is True else (
            "user_deactivated" if updates.get("is_active") is False else "user_updated")
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type=event_type,
                           actor_user_id=actor.id,
                           payload={k: v for k, v in updates.items() if k != "password_hash"}))
        s.commit()
        return public_user(user)

    @app.post("/api/v1/admin/users/{user_id}/reset-password", summary="Reset a password",
              dependencies=[Depends(admin_only)])
    def admin_user_reset_password(user_id: str, value: PasswordResetRequest, s=Depends(db)):
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "user not found")
        password = value.new_password or __import__("secrets").token_urlsafe(12)
        try:
            validate_password(password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        user.password_hash = hash_password(password)
        user.must_change_password = True
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="password_reset",
                           actor_user_id=s.info.get("auth_user_id"), payload={"user_id": user.id}))
        s.commit()
        result = {"user": public_user(user)}
        if not value.new_password:
            result["temporary_password"] = password
        return result

    @app.post("/api/v1/admin/users/{user_id}/activate", summary="Activate a user",
              dependencies=[Depends(admin_only)])
    def admin_user_activate(user_id: str, s=Depends(db)):
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "user not found")
        user.is_active = True
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="user_activated",
                           actor_user_id=s.info.get("auth_user_id")))
        s.commit()
        return public_user(user)

    @app.post("/api/v1/admin/users/{user_id}/deactivate", summary="Deactivate a user",
              dependencies=[Depends(admin_only)])
    def admin_user_deactivate(user_id: str, request: Request, s=Depends(db)):
        actor = authenticated(request, s)
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "user not found")
        if actor.id == user.id:
            raise HTTPException(409, "cannot deactivate the current user")
        user.is_active = False
        s.add(DomainEvent(entity_type="user", entity_id=user.id, event_type="user_deactivated",
                           actor_user_id=actor.id))
        s.commit()
        return public_user(user)

    def _safe_upload_name(value):
        name = str(value or "upload.pdf")
        if Path(name).name != name or "/" in name or "\\" in name or name in {".", ".."}:
            raise HTTPException(422, detail={"error": {"code": "invalid_filename", "message": "ファイル名が不正です"}})
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip(".") or "upload"
        if not stem.lower().endswith(".pdf"):
            stem += ".pdf"
        return stem[:255]

    def _extraction_public(value):
        return {
            "id": value.id, "test_id": value.test_id, "material_id": value.material_id,
            "state": value.state, "source_sha256": value.source_sha256,
            "page_count": value.page_count,
            "parser": {"backend": value.parser_backend, "library": value.parser_library,
                        "version": value.parser_version, "schema_version": value.schema_version,
                        "config_hash": value.extraction_config_hash},
            "artifact_ref": value.artifact_ref, "error_type": value.error_type,
            "error_message": value.error_message, "created_at": value.created_at,
            "completed_at": value.completed_at,
        }

    def job_or_404(job_id, s):
        try:
            UUID(str(job_id))
        except ValueError:
            raise HTTPException(
                422, detail={"error": {"code": "invalid_job_id", "message": "job idが不正です"}}
            )
        job = s.get(GradingJob, job_id)
        if not job:
            raise HTTPException(
                404, detail={"error": {"code": "job_not_found", "message": "jobがありません"}}
            )
        return job

    def job_auth(request: Request, job_id: str | None = None,
                 x_role: str | None = Header(None, alias="X-Role"),
                 x_user_id: str | None = Header(None, alias="X-User-ID"),
                 s=Depends(db)):
        """Protect legacy job/runtime endpoints at the service boundary.

        Jobs created by the original assignment CLI may not have a Test link;
        those still require an active teacher identity.  Linked jobs additionally
        go through the same Course-owner check as the grading review API.
        """
        try:
            user = request_user(request, s)
        except HTTPException:
            raise
        if user.role not in STAFF_ROLES:
            raise HTTPException(403, {"error": {"code": "TEACHER_ROLE_REQUIRED",
                                                 "message": "TEACHER_ROLE_REQUIRED"}})
        if job_id:
            job = s.get(GradingJob, job_id)
            if job is None:
                raise HTTPException(404, {"error": {"code": "JOB_NOT_FOUND",
                                                     "message": "JOB_NOT_FOUND"}})
            if job.test_id:
                teacher_guard(job.test_id, request, s)
        request.state.teacher_user_id = user.id
        s.info["teacher_user_id"] = user.id
        return user

    def public_job(j):
        return {
            "id": j.id,
            "external_id": j.external_id,
            "state": j.state,
            "current_phase": j.current_phase,
            "execution_mode": j.execution_mode,
            # Filesystem paths remain internal artifact references.
            "pause_requested": bool((j.metadata_json or {}).get("pause_requested")),
            "total_items": j.total_items,
            "completed_items": j.completed_items,
            "item_error_count": j.item_error_count,
            "review_required_count": j.review_required_count,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "completed_at": j.completed_at,
            "error_type": j.error_type,
            "error_message": j.error_message,
        }

    @app.get("/api/v1/health", summary="API health")
    def health(s=Depends(db)):
        try:
            s.execute(text("SELECT 1"))
            jobs = list(s.scalars(select(GradingJob)))
            artifact_root = Path(os.getenv("LLM_GRADER_ARTIFACT_ROOT", str(Path.cwd() / "artifacts"))).resolve()
            return {
                "status": "ok", "database": "ok",
                "student_portal_enabled": portal_enabled,
                "artifact_root": {"path_configured": True, "exists": artifact_root.is_dir(),
                                   "readable": os.access(artifact_root, os.R_OK),
                                   "writable": os.access(artifact_root, os.W_OK)},
                "jobs": {
                    "pending": sum(j.state in {"queued", "pending", "preparing", "running", "paused", "resuming"} for j in jobs),
                    "failed": sum(j.state in {"failed", "error", "item_error"} or j.item_error_count > 0 for j in jobs),
                    "review_required": sum(j.review_required_count for j in jobs),
                },
            }
        except Exception:
            return {"status": "degraded", "database": "error", "student_portal_enabled": portal_enabled}

    @app.post("/api/v1/jobs", status_code=201, summary="Create grading job",
              dependencies=[Depends(job_auth)])
    def create(req: JobCreate, s=Depends(db)):
        if req.execution_mode not in {"resident_serial", "phased_auto"}:
            raise HTTPException(400, "invalid execution_mode")
        assignment = _safe(req.assignment_path, roots)
        run = _safe(req.run_path, roots)
        config = _safe(req.config_path, roots)
        try:
            _, _, subs = load_assignment(assignment)
        except Exception as e:
            raise HTTPException(400, f"invalid assignment: {e}") from e
        r = JobRepository(s)
        j = r.create_job(
            external_id=str(__import__("uuid").uuid4()),
            execution_mode=req.execution_mode,
            assignment_path=assignment,
            run_path=run,
            config_path=config,
            requested_by=s.info.get("teacher_user_id"),
            keep_final_runtime_running=req.keep_final_runtime_running,
            total_items=len(subs),
        )
        for sub in subs:
            r.add_item(j.id, item_key=sub["submission_id"])
        r.append_event(j.id, "job_created", new_state="queued")
        s.commit()
        return public_job(j)

    @app.get("/api/v1/jobs", summary="List jobs", dependencies=[Depends(job_auth)])
    def list_jobs(
        state: str | None = None,
        execution_mode: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        s=Depends(db),
    ):
        q = select(GradingJob).order_by(GradingJob.created_at.desc()).offset(offset).limit(limit)
        if state:
            q = q.where(GradingJob.state == state)
        if execution_mode:
            q = q.where(GradingJob.execution_mode == execution_mode)
        return [public_job(j) for j in s.scalars(q)]

    @app.get("/api/v1/jobs/{job_id}", summary="Get job", dependencies=[Depends(job_auth)])
    def detail(job_id: str, s=Depends(db)):
        return public_job(job_or_404(job_id, s))

    @app.get("/api/v1/jobs/{job_id}/items", summary="List job items",
             dependencies=[Depends(job_auth)])
    def items(
        job_id: str,
        state: str | None = None,
        needs_review: bool | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        s=Depends(db),
    ):
        job_or_404(job_id, s)
        q = (
            select(GradingJobItem)
            .where(GradingJobItem.job_id == job_id)
            .offset(offset)
            .limit(limit)
        )
        if state:
            q = q.where(GradingJobItem.state == state)
        if needs_review is not None:
            q = q.where(GradingJobItem.needs_review == needs_review)
        return [item_dict(i) for i in s.scalars(q)]

    def item_dict(i):
        return {
            "id": i.id,
            "item_key": i.item_key,
            "student_identifier": i.student_identifier,
            "state": i.state,
            "score": i.score,
            "max_score": i.max_score,
            "needs_review": i.needs_review,
            "error_type": i.error_type,
            "error_message": i.error_message,
            "reconstruction_hash": i.reconstruction_hash,
            "grading_hash": i.grading_hash,
            "artifact_available": bool(i.normalized_result_path),
            "normalized_result_hash": i.normalized_result_hash,
        }

    @app.get("/api/v1/jobs/{job_id}/items/{item_id}", summary="Get job item",
             dependencies=[Depends(job_auth)])
    def item(job_id, item_id, s=Depends(db)):
        job_or_404(job_id, s)
        i = s.get(GradingJobItem, item_id)
        if not i or i.job_id != job_id:
            raise HTTPException(404, "item_not_found")
        return item_dict(i)

    @app.get("/api/v1/jobs/{job_id}/events", summary="List events",
             dependencies=[Depends(job_auth)])
    def events(
        job_id, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), s=Depends(db)
    ):
        job_or_404(job_id, s)
        q = (
            select(GradingJobEvent)
            .where(GradingJobEvent.job_id == job_id)
            .order_by(GradingJobEvent.created_at)
            .offset(offset)
            .limit(limit)
        )
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "phase": e.phase,
                "previous_state": e.previous_state,
                "new_state": e.new_state,
                "message": e.message,
                "created_at": e.created_at,
            }
            for e in s.scalars(q)
        ]

    @app.post("/api/v1/jobs/{job_id}/pause", summary="Pause job",
              dependencies=[Depends(job_auth)])
    def pause(job_id, s=Depends(db)):
        j = job_or_404(job_id, s)
        if j.state in {"completed", "failed", "cancelled"}:
            raise HTTPException(409, "invalid state")
        r = JobRepository(s)
        r.pause(job_id)
        s.commit()
        return public_job(j)

    @app.post("/api/v1/jobs/{job_id}/resume", summary="Resume job",
              dependencies=[Depends(job_auth)])
    def resume(job_id, s=Depends(db)):
        j = job_or_404(job_id, s)
        if (j.metadata_json or {}).get("regrade_request_id"):
            raise HTTPException(409, "REGRADE_RESUME_REQUIRES_NEW_TEACHER_APPROVAL")
        if j.state != "paused":
            raise HTTPException(409, "job is not paused")
        r = JobRepository(s)
        r.resume(job_id)
        s.commit()
        return public_job(j)

    @app.post("/api/v1/jobs/{job_id}/retry", summary="Retry job",
              dependencies=[Depends(job_auth)])
    def retry(job_id, s=Depends(db)):
        j = job_or_404(job_id, s)
        if (j.metadata_json or {}).get("regrade_request_id"):
            raise HTTPException(409, "REGRADE_RETRY_REQUIRES_NEW_TEACHER_APPROVAL")
        if j.state not in {"failed", "runtime_failed", "paused"}:
            raise HTTPException(409, "invalid state")
        JobRepository(s).retry(job_id)
        s.commit()
        return public_job(j)

    @app.post("/api/v1/jobs/{job_id}/items/{item_id}/retry", summary="Retry item",
              dependencies=[Depends(job_auth)])
    def retry_item(job_id, item_id, s=Depends(db)):
        job = job_or_404(job_id, s)
        if (job.metadata_json or {}).get("regrade_request_id"):
            raise HTTPException(409, "REGRADE_RETRY_REQUIRES_NEW_TEACHER_APPROVAL")
        i = s.get(GradingJobItem, item_id)
        if not i or i.job_id != job_id:
            raise HTTPException(404, "item_not_found")
        if i.state != "item_error":
            raise HTTPException(409, "item is not retryable")
        JobRepository(s).retry(job_id, item_id)
        s.commit()
        return item_dict(i)

    @app.get("/api/v1/system/runtimes", summary="Runtime status",
             dependencies=[Depends(job_auth)])
    def runtimes():
        if runtime_client is None:
            return []
        values = runtime_client.statuses() if hasattr(runtime_client, "statuses") else []
        return [
            {
                "runtime_id": x.get("profile", {}).get("runtime_id"),
                "model_id": x.get("profile", {}).get("model_id"),
                "runtime_type": x.get("profile", {}).get("runtime_type"),
                "state": x.get("state"),
                "availability": x.get("availability"),
                "error_code": x.get("error_code"),
                "hardware": x.get("hardware", {}),
            }
            for x in values
        ]

    @app.post("/api/v1/tests/{test_id}/question-materials", status_code=201,
              summary="Register and natively extract a question-sheet PDF",
              dependencies=[Depends(domain_authorized)])
    async def question_material(test_id: str, request: Request, s=Depends(db)):
        test = s.get(Test, test_id)
        if not test:
            raise HTTPException(404, detail={"error": {"code": "test_not_found", "message": "テストがありません"}})
        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].lower()
        if content_type not in {"application/pdf", "application/octet-stream", ""}:
            raise HTTPException(422, detail={"error": {"code": "invalid_content_type", "message": "PDFを送信してください"}})
        filename = _safe_upload_name(request.headers.get("x-filename") or "question-sheet.pdf")
        purpose = request.headers.get("x-question-import-purpose", "new_import")
        if purpose not in {"new_import", "correction_comparison"}:
            raise HTTPException(422, detail="invalid_question_import_purpose")
        material_type = "corrected_question_sheet" if purpose == "correction_comparison" else "question_sheet"
        temp_dir = import_root / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"upload-{__import__('uuid').uuid4().hex}.tmp"
        size = 0
        digest = hashlib.sha256()
        extraction_id = None
        try:
            declared_size = request.headers.get("content-length")
            if declared_size and int(declared_size) > int(limits["max_bytes"]):
                raise HTTPException(413, detail={"error": {"code": "file_too_large", "message": "PDFのサイズが上限を超えています"}})
            with temp_path.open("wb") as stream:
                if hasattr(request, "stream"):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > int(limits["max_bytes"]):
                            raise HTTPException(413, detail={"error": {"code": "file_too_large", "message": "PDFのサイズが上限を超えています"}})
                        digest.update(chunk)
                        stream.write(chunk)
                else:  # small direct-call test doubles
                    body = await request.body()
                    size = len(body)
                    if size > int(limits["max_bytes"]):
                        raise HTTPException(413, detail={"error": {"code": "file_too_large", "message": "PDFのサイズが上限を超えています"}})
                    digest.update(body)
                    stream.write(body)
            with temp_path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise HTTPException(422, detail={"error": {"code": "invalid_pdf", "message": "PDFファイルではありません"}})
            source_sha256 = digest.hexdigest()
            duplicate = s.scalar(select(TestMaterial).where(
                TestMaterial.test_id == test_id,
                TestMaterial.material_type == material_type,
                TestMaterial.sha256 == source_sha256,
            ))
            if duplicate:
                existing = s.scalar(select(QuestionImportExtraction).where(
                    QuestionImportExtraction.material_id == duplicate.id
                ).order_by(QuestionImportExtraction.created_at.desc()))
                if existing and existing.state != "failed":
                    return _extraction_public(existing)
                material = duplicate
            else:
                material_id = str(__import__('uuid').uuid4())
                material = TestMaterial(id=material_id, test_id=test_id, material_type=material_type,
                                        storage_ref="", original_filename=filename,
                                        mime_type="application/pdf", sha256=source_sha256)
            material_id = material.id
            extraction_id = str(__import__('uuid').uuid4())
            artifact_rel = f"question-imports/{extraction_id}"
            if not duplicate:
                material.storage_ref = f"{artifact_rel}/source.pdf"
                s.add(material)
            extraction = QuestionImportExtraction(id=extraction_id, test_id=test_id, material_id=material_id,
                                                  state="extracting", source_sha256=source_sha256,
                                                  parser_backend="pymupdf", parser_library="PyMuPDF",
                                                  parser_version="unknown", schema_version=IR_SCHEMA_VERSION,
                                                  extraction_config_hash="pending", artifact_ref=artifact_rel)
            s.flush()
            s.add(extraction)
            s.commit()
            artifact_dir = import_root / extraction_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_path), str(artifact_dir / "source.pdf"))
            extractor = PyMuPdfNativeExtractor(max_pages=int(limits["max_pages"]))
            ir = extractor.extract(artifact_dir / "source.pdf", source_sha256=source_sha256,
                                   material_id=material_id, output_dir=artifact_dir / "native",
                                   options={"max_pages": int(limits["max_pages"])})
            extraction = s.get(QuestionImportExtraction, extraction_id)
            extraction.state = "completed"
            extraction.page_count = len(ir.pages)
            extraction.parser_version = ir.parser["version"]
            extraction.extraction_config_hash = ir.parser["config_hash"]
            extraction.completed_at = datetime.now(timezone.utc)
            s.commit()
            return _extraction_public(extraction)
        except HTTPException:
            s.rollback()
            raise
        except Exception as exc:
            s.rollback()
            extraction = s.get(QuestionImportExtraction, extraction_id) if extraction_id else None
            if extraction:
                extraction.state = "failed"
                extraction.error_type = type(exc).__name__
                extraction.error_message = str(exc)[:1000]
                s.commit()
            raise HTTPException(422, detail={"error": {"code": "pdf_extraction_failed", "message": "PDFの解析に失敗しました"}}) from exc
        finally:
            temp_path.unlink(missing_ok=True)

    @app.get("/api/v1/question-imports/{extraction_id}", summary="Get native extraction status")
    def question_import_status(extraction_id: str, s=Depends(db)):
        value = s.get(QuestionImportExtraction, extraction_id)
        if not value:
            raise HTTPException(404, detail={"error": {"code": "question_import_not_found", "message": "PDF解析がありません"}})
        return _extraction_public(value)

    @app.get("/api/v1/question-imports/{extraction_id}/document", summary="Get Document IR summary or page")
    def question_import_document(extraction_id: str, page: int | None = Query(None, ge=0), s=Depends(db)):
        value = s.get(QuestionImportExtraction, extraction_id)
        if not value:
            raise HTTPException(404, detail={"error": {"code": "question_import_not_found", "message": "PDF解析がありません"}})
        ir_path = import_root / extraction_id / "native" / "document-ir.json"
        if value.state != "completed" or not ir_path.is_file():
            raise HTTPException(409, detail={"error": {"code": "document_not_ready", "message": "Document IRはまだ利用できません"}})
        import json
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        if page is not None:
            if page >= len(ir["pages"]):
                raise HTTPException(404, detail={"error": {"code": "page_not_found", "message": "ページがありません"}})
            return {"schema_version": ir["schema_version"], "coordinate_space": ir.get("coordinate_space", {}), "source": ir["source"],
                    "parser": ir["parser"], "page": ir["pages"][page]}
        return {"schema_version": ir["schema_version"], "coordinate_space": ir.get("coordinate_space", {}), "source": ir["source"],
                "parser": ir["parser"], "pages": [
                    {"page_index": p["page_index"], "width": p["width"], "height": p["height"],
                     "rotation": p["rotation"], "element_count": len(p["elements"]),
                     "quality_signals": p["quality_signals"], "review_flags": p["review_flags"]}
                    for p in ir["pages"]
                ]}

    action_root = Path(os.getenv("LLM_GRADER_ARTIFACT_ROOT", str(Path.cwd() / "artifacts"))).resolve()
    action_root.mkdir(parents=True, exist_ok=True)
    # Keep question-import assets and submission assets on their respective
    # roots.  In production these are often different directories; passing
    # the answer root to the domain routes prevents a question figure from
    # being reported missing merely because submission assets live elsewhere.
    visual_options = dict(grading_visual_config or {})
    visual_options.setdefault("answer_root", str(action_root))
    # Effective question assets are rooted at ``import_root``.  TestMaterial
    # source refs are relative to the unified artifact store, so the domain
    # router receives both roots and resolves each kind exactly once.
    def staff_dependency(request: Request, s=Depends(db)):
        user = authenticated(request, s)
        if user.role not in STAFF_ROLES:
            raise HTTPException(403, {"error": {"code": "TEACHER_ROLE_REQUIRED", "message": "TEACHER_ROLE_REQUIRED"}})
        return authorize_domain_path(request, s, user)
    def staff_only_dependency(request: Request, s=Depends(db)):
        """Generic tools authenticate staff without resolving a domain URL resource."""
        user = authenticated(request, s)
        if user.role not in STAFF_ROLES:
            raise HTTPException(403, {"error": {"code": "TEACHER_ROLE_REQUIRED", "message": "TEACHER_ROLE_REQUIRED"}})
        request.state.teacher_user_id = user.id
        s.info["teacher_user_id"] = user.id
        return user

    app.include_router(domain_router(db, import_root, roots, visual_options,
                                     storage_root=action_root),
                       dependencies=[Depends(domain_authorized)])
    app.include_router(question_draft_router(db, import_root),
                       dependencies=[Depends(staff_dependency)])
    app.include_router(question_review_router(db, import_root, classifier=model_answer_classifier),
                       dependencies=[Depends(staff_dependency)])
    app.include_router(model_answer_import_router(db, action_root, classifier=model_answer_classifier),
                       dependencies=[Depends(staff_dependency)])
    from .text_tools import router as text_tools_router
    app.include_router(text_tools_router(model_answer_classifier), dependencies=[Depends(staff_only_dependency)])
    app.include_router(student_answer_router(db, action_root),
                       dependencies=[Depends(domain_authorized)])
    app.include_router(grading_review_router(
        db, root=import_root, action_root=action_root, allowed_roots=roots,
        visual_options=visual_options,
        grading_config_path=os.getenv("LLM_GRADER_GRADING_CONFIG"),
    ), dependencies=[Depends(staff_dependency)])
    app.include_router(student_results_router(
        db, root=import_root,
        answer_root=visual_options.get("answer_root"),
        student_portal_enabled=portal_enabled,
    ))
    from ..vision_policy import VisionRoutingPolicy
    if vision_config is None and os.getenv("LLM_GRADER_QUESTION_VISION_CONFIG"):
        import json
        vision_config = json.loads(Path(os.environ["LLM_GRADER_QUESTION_VISION_CONFIG"]).read_text())
    vision_config = vision_config or {}
    if vision_inference is None and vision_config.get("models"):
        from ..adapters.question_vision import RuntimeVisionAdapter
        from ..runtime.manager import RuntimeManager, profiles_from_runtime_config
        # Only the two question vision roles can be registered here.
        selected = {"models": {k: v for k, v in vision_config["models"].items() if k in {"math_ocr", "ocr"}}}
        manager = runtime_client or RuntimeManager(profiles_from_runtime_config(selected))
        vision_inference = RuntimeVisionAdapter(manager, vision_config)
    app.include_router(question_vision_router(db, import_root, inference=vision_inference,
                       policy=VisionRoutingPolicy(vision_config.get("policy"))),
                       dependencies=[Depends(staff_dependency)])

    return app
