from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Boolean, JSON, UniqueConstraint, Float, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def now():
    return datetime.now(timezone.utc)


class GradingJob(Base):
    __tablename__ = "grading_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    execution_mode: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    current_phase: Mapped[str | None] = mapped_column(String(40))
    assignment_path: Mapped[str] = mapped_column(Text)
    run_path: Mapped[str] = mapped_column(Text)
    config_path: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(128))
    keep_final_runtime_running: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    item_error_count: Mapped[int] = mapped_column(Integer, default=0)
    review_required_count: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    test_id: Mapped[str | None] = mapped_column(ForeignKey("tests.id"), nullable=True, index=True)
    rubric_version_id: Mapped[str | None] = mapped_column(ForeignKey("rubric_versions.id"), nullable=True)
    items: Mapped[list["GradingJobItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    events: Mapped[list["GradingJobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class GradingJobItem(Base):
    __tablename__ = "grading_job_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("grading_jobs.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(128))
    student_identifier: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    max_score: Mapped[int | None] = mapped_column(Integer)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    reconstruction_hash: Mapped[str | None] = mapped_column(String(64))
    grading_hash: Mapped[str | None] = mapped_column(String(64))
    raw_response_path: Mapped[str | None] = mapped_column(Text)
    normalized_result_path: Mapped[str | None] = mapped_column(Text)
    normalized_result_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job: Mapped[GradingJob] = relationship(back_populates="items")


class TeacherGradingDecision(Base):
    """Append-only authoritative teacher adjudication for a grading target.

    This is deliberately separate from ``GradingJob`` and ``GradingJobItem``:
    an adjudication never mutates the model result or creates a replacement
    execution job.
    """
    __tablename__ = "teacher_grading_decisions"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "question_id", "decision_version",
            name="uq_teacher_grading_decision_version",
        ),
        Index("ix_teacher_grading_decisions_target", "submission_id", "question_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("student_submissions.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("test_questions.id"), index=True)
    source_grading_job_id: Mapped[str] = mapped_column(
        ForeignKey("grading_jobs.id"), nullable=False, index=True
    )
    rubric_version_id: Mapped[str] = mapped_column(
        ForeignKey("rubric_versions.id"), nullable=False, index=True
    )
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="COMPLETE", index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    criterion_scores: Mapped[list] = mapped_column(JSON, nullable=False)
    teacher_reason: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    teacher_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GradingJobEvent(Base):
    __tablename__ = "grading_job_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("grading_jobs.id"), index=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("grading_job_items.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str | None] = mapped_column(String(40))
    previous_state: Mapped[str | None] = mapped_column(String(40))
    new_state: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    job: Mapped[GradingJob] = relationship(back_populates="events")


class GradingRuntimeSnapshot(Base):
    __tablename__ = "grading_runtime_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("grading_jobs.id"), index=True)
    phase: Mapped[str] = mapped_column(String(40))
    runtime_id: Mapped[str] = mapped_column(String(64))
    runtime_type: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str | None] = mapped_column(String(256))
    model_path: Mapped[str | None] = mapped_column(Text)
    model_sha256: Mapped[str | None] = mapped_column(String(64))
    ftype: Mapped[str | None] = mapped_column(String(64))
    mmproj_path: Mapped[str | None] = mapped_column(Text)
    mmproj_sha256: Mapped[str | None] = mapped_column(String(64))
    llama_cpp_binary: Mapped[str | None] = mapped_column(Text)
    llama_cpp_version: Mapped[str | None] = mapped_column(String(256))
    llama_cpp_build: Mapped[str | None] = mapped_column(String(128))
    llama_cpp_commit: Mapped[str | None] = mapped_column(String(128))
    endpoint: Mapped[str | None] = mapped_column(Text)
    allocated_port: Mapped[int | None] = mapped_column(Integer)
    pid: Mapped[int | None] = mapped_column(Integer)
    runtime_command: Mapped[list | None] = mapped_column(JSON)
    runtime_arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    # Existing users are intentionally allowed to have no password hash.  A
    # migration must never invent a password; such accounts can be enabled by
    # an explicit admin reset/bootstrap operation.
    role: Mapped[str] = mapped_column(String(32), default="teacher", server_default="teacher")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class SetupLock(Base):
    __tablename__ = "setup_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    """Opaque, revocable browser sessions.

    Only a SHA-256 digest of the cookie value is persisted.  The raw value
    remains in the HttpOnly cookie and is never returned by an API response.
    """
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CourseOffering(Base):
    __tablename__ = "course_offerings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    academic_year: Mapped[int] = mapped_column(Integer)
    term: Mapped[str] = mapped_column(String(32))
    term_label: Mapped[str | None] = mapped_column(String(100))
    section: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(200))
    starts_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Test(Base):
    __tablename__ = "tests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_offering_id: Mapped[str] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    test_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    total_points: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TestQuestion(Base):
    __tablename__ = "test_questions"
    __table_args__ = (UniqueConstraint("test_id", "question_number", name="uq_question_number"),
                      Index("uq_test_questions_stable_key", "test_id", "stable_question_key", unique=True))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    question_number: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(200))
    question_text: Mapped[str | None] = mapped_column(Text)
    max_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("test_questions.id"), nullable=True, index=True)
    stable_question_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    node_type: Mapped[str] = mapped_column(String(32), default="standalone", server_default="standalone")
    is_gradable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TestMaterial(Base):
    __tablename__ = "test_materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    material_type: Mapped[str] = mapped_column(String(40))
    storage_ref: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuestionImportExtraction(Base):
    """Native PDF extraction record; raw evidence remains in artifacts."""

    __tablename__ = "question_import_extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("test_materials.id"), index=True)
    state: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_backend: Mapped[str] = mapped_column(String(64))
    parser_library: Mapped[str] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(64))
    extraction_config_hash: Mapped[str] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelAnswer(Base):
    __tablename__ = "model_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("test_questions.id"))
    answer_text: Mapped[str | None] = mapped_column(Text)
    material_id: Mapped[str | None] = mapped_column(ForeignKey("test_materials.id"))
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelAnswerImportDraft(Base):
    """Teacher-editable native PDF extraction mapped to existing questions."""
    __tablename__ = "model_answer_import_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("test_materials.id"), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    artifact_ref: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(24), default="editing", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class GradingPolicy(Base):
    __tablename__ = "grading_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    policy_text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SampleAnswer(Base):
    __tablename__ = "sample_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    sample_key: Mapped[str] = mapped_column(String(100))
    material_id: Mapped[str | None] = mapped_column(ForeignKey("test_materials.id"))
    transcription: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SampleAnswerScore(Base):
    __tablename__ = "sample_answer_scores"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sample_answer_id: Mapped[str] = mapped_column(ForeignKey("sample_answers.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("test_questions.id"))
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    teacher_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RubricVersion(Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (UniqueConstraint("test_id", "version", name="uq_rubric_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    rubric_json: Mapped[dict] = mapped_column(JSON)
    rubric_text: Mapped[str | None] = mapped_column(Text)
    generated_by_model: Mapped[str | None] = mapped_column(String(200))
    generation_metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("course_offering_id", "student_identifier", name="uq_student_offering_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_offering_id: Mapped[str] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    student_identifier: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StudentSubmission(Base):
    __tablename__ = "student_submissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    submission_key: Mapped[str] = mapped_column(String(128))
    material_id: Mapped[str] = mapped_column(ForeignKey("test_materials.id"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StudentAnswerExtractionRun(Base):
    __tablename__ = "student_answer_extraction_runs"
    __table_args__ = (Index("ix_student_answer_extraction_runs_submission", "submission_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    submission_id: Mapped[str] = mapped_column(ForeignKey("student_submissions.id"), nullable=False)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created")
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StudentAnswerExtractionResult(Base):
    __tablename__ = "student_answer_extraction_results"
    __table_args__ = (UniqueConstraint("run_id", "question_id", name="uq_student_answer_extraction_result"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("student_answer_extraction_runs.id"), nullable=False)
    submission_id: Mapped[str] = mapped_column(ForeignKey("student_submissions.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("test_questions.id"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StudentAnswerReconstruction(Base):
    __tablename__ = "student_answer_reconstructions"
    __table_args__ = (UniqueConstraint("submission_id", "question_id", "version", name="uq_student_answer_reconstruction_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_result_id: Mapped[str] = mapped_column(ForeignKey("student_answer_extraction_results.id"), nullable=False)
    submission_id: Mapped[str] = mapped_column(ForeignKey("student_submissions.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("test_questions.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="REVIEW_REQUIRED")
    answer_text: Mapped[str | None] = mapped_column(Text)
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    model_identity: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class DomainEvent(Base):
    __tablename__ = "domain_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuestionImportDraft(Base):
    __tablename__ = "question_import_drafts"
    __table_args__ = (UniqueConstraint("extraction_id", "source_ir_sha256", "parser_version", "parser_config_hash", name="uq_question_draft_input"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    extraction_id: Mapped[str] = mapped_column(ForeignKey("question_import_extractions.id"), index=True)
    state: Mapped[str] = mapped_column(String(32), default="generating")
    schema_version: Mapped[str] = mapped_column(String(64))
    parser_name: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    parser_config_hash: Mapped[str] = mapped_column(String(64))
    source_ir_sha256: Mapped[str] = mapped_column(String(64))
    draft_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    total_points_candidate: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuestionImportDraftNode(Base):
    __tablename__ = "question_import_draft_nodes"
    __table_args__ = (UniqueConstraint("draft_id", "stable_key", name="uq_question_draft_node_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id: Mapped[str] = mapped_column(ForeignKey("question_import_drafts.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("question_import_draft_nodes.id"))
    stable_key: Mapped[str] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(32))
    depth: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    label_raw: Mapped[str] = mapped_column(Text)
    label_normalized: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    score_semantics: Mapped[str] = mapped_column(String(32))
    score_points: Mapped[float | None] = mapped_column(Float)
    effective_points_candidate: Mapped[float | None] = mapped_column(Float)
    aggregate_points_candidate: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    review_required: Mapped[bool] = mapped_column(Boolean)
    review_flags: Mapped[list] = mapped_column(JSON)


class QuestionImportVisionRun(Base):
    __tablename__ = "question_import_vision_runs"
    __table_args__ = (UniqueConstraint("draft_id", "input_sha256", name="uq_vision_run_input"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id: Mapped[str] = mapped_column(ForeignKey("question_import_drafts.id"), index=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="planned")
    policy_version: Mapped[str] = mapped_column(String(64))
    policy_config_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    snapshot: Mapped[dict] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuestionImportVisionResult(Base):
    __tablename__ = "question_import_vision_results"
    __table_args__ = (UniqueConstraint("run_id", "region_id", name="uq_vision_result_region"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("question_import_vision_runs.id"), index=True)
    region_id: Mapped[str] = mapped_column(String(128))
    question_stable_key: Mapped[str | None] = mapped_column(String(128))
    region_type: Mapped[str] = mapped_column(String(32))
    model_role: Mapped[str | None] = mapped_column(String(32))
    routing_decision: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuestionImportReview(Base):
    __tablename__ = "question_import_reviews"
    __table_args__ = (UniqueConstraint("draft_id", name="uq_review_draft"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id: Mapped[str] = mapped_column(ForeignKey("question_import_drafts.id"), index=True)
    source_draft_sha256: Mapped[str] = mapped_column(String(64))
    vision_run_id: Mapped[str | None] = mapped_column(ForeignKey("question_import_vision_runs.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="editing")
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    current_revision_sha256: Mapped[str] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QuestionImportReviewRevision(Base):
    __tablename__ = "question_import_review_revisions"
    __table_args__ = (UniqueConstraint("review_id", "revision_number", name="uq_review_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_id: Mapped[str] = mapped_column(ForeignKey("question_import_reviews.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    parent_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_draft_sha256: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64), default="question-import-review.v1")
    revision_sha256: Mapped[str] = mapped_column(String(64))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    snapshot: Mapped[dict] = mapped_column(JSON)
    change_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class QuestionImportConfirmation(Base):
    __tablename__ = "question_import_confirmations"
    __table_args__ = (UniqueConstraint("review_id", "review_revision_number", name="uq_import_confirmation_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("question_import_reviews.id"), index=True)
    review_revision_number: Mapped[int] = mapped_column(Integer)
    review_revision_sha256: Mapped[str] = mapped_column(String(64))
    source_draft_sha256: Mapped[str] = mapped_column(String(64))
    import_plan_sha256: Mapped[str] = mapped_column(String(64))
    import_schema_version: Mapped[str] = mapped_column(String(64), default="question-import-confirm-v1")
    state: Mapped[str] = mapped_column(String(32), default="completed")
    artifact_ref: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class QuestionImportConfirmationItem(Base):
    __tablename__ = "question_import_confirmation_items"
    __table_args__ = (UniqueConstraint("confirmation_id", "review_node_id", name="uq_import_confirmation_node"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    confirmation_id: Mapped[str] = mapped_column(ForeignKey("question_import_confirmations.id"), index=True)
    review_node_id: Mapped[str] = mapped_column(String(128))
    source_draft_stable_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    test_question_id: Mapped[str | None] = mapped_column(ForeignKey("test_questions.id"), nullable=True, index=True)
    stable_question_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    imported_order: Mapped[int] = mapped_column(Integer, default=0)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)

class TestQuestionAsset(Base):
    __tablename__ = "test_question_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(ForeignKey("test_questions.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    artifact_ref: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100), default="image/png")
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestQuestionCorrection(Base):
    """Append-only authoritative content correction for an imported question."""

    __tablename__ = "test_question_corrections"
    __table_args__ = (
        UniqueConstraint("test_question_id", "correction_version", name="uq_question_correction_version"),
        Index("ix_question_corrections_question", "test_question_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_question_id: Mapped[str] = mapped_column(ForeignKey("test_questions.id"), index=True)
    correction_version: Mapped[int] = mapped_column(Integer)
    correction_type: Mapped[str] = mapped_column(String(64), default="set_formula_transcription")
    source_region_ids: Mapped[list] = mapped_column(JSON)
    previous_content_sha256: Mapped[str] = mapped_column(String(64))
    new_content_sha256: Mapped[str] = mapped_column(String(64))
    previous_value: Mapped[dict] = mapped_column(JSON)
    new_value: Mapped[dict] = mapped_column(JSON)
    reason_code: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_confirmation_id: Mapped[str | None] = mapped_column(
        ForeignKey("question_import_confirmations.id"), nullable=True, index=True
    )
    source_review_id: Mapped[str | None] = mapped_column(
        ForeignKey("question_import_reviews.id"), nullable=True, index=True
    )
    source_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestAuthoringRevision(Base):
    """Whole-test working copy. Formal entities remain separate and untouched."""
    __tablename__ = "test_authoring_revisions"
    __table_args__ = (UniqueConstraint("test_id", "revision", name="uq_test_authoring_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    edit_version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(24), default="draft")
    snapshot: Mapped[dict] = mapped_column(JSON)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    baseline_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TestArchive(Base):
    """Recoverable archive marker; never cascades into grades or source files."""
    __tablename__ = "test_archives"
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), primary_key=True)
    archived_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    previous_status: Mapped[str] = mapped_column(String(32))
    impact: Mapped[dict] = mapped_column(JSON)
