"""Add append-only teacher grading adjudication records."""

from alembic import op
import sqlalchemy as sa


revision = "0012_teacher_grading_decision"
down_revision = "0011_student_answer_recon"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "teacher_grading_decisions" in inspector.get_table_names():
        return
    op.create_table(
        "teacher_grading_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), nullable=False),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("student_submissions.id"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("test_questions.id"), nullable=False),
        sa.Column("source_grading_job_id", sa.String(36), sa.ForeignKey("grading_jobs.id"), nullable=False),
        sa.Column("rubric_version_id", sa.String(36), sa.ForeignKey("rubric_versions.id"), nullable=False),
        sa.Column("decision_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("max_score", sa.Integer, nullable=False),
        sa.Column("criterion_scores", sa.JSON, nullable=False),
        sa.Column("teacher_reason", sa.Text, nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_ref", sa.String(512), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON, nullable=False),
        sa.Column("teacher_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "submission_id", "question_id", "decision_version",
            name="uq_teacher_grading_decision_version",
        ),
    )
    op.create_index(
        "ix_teacher_grading_decisions_target", "teacher_grading_decisions",
        ["submission_id", "question_id"],
    )
    op.create_index(
        "ix_teacher_grading_decisions_test_id", "teacher_grading_decisions", ["test_id"]
    )
    op.create_index(
        "ix_teacher_grading_decisions_source_grading_job_id",
        "teacher_grading_decisions", ["source_grading_job_id"],
    )
    op.create_index(
        "ix_teacher_grading_decisions_rubric_version_id",
        "teacher_grading_decisions", ["rubric_version_id"],
    )
    op.create_index(
        "ix_teacher_grading_decisions_status", "teacher_grading_decisions", ["status"]
    )


def downgrade():
    op.drop_index("ix_teacher_grading_decisions_status", table_name="teacher_grading_decisions")
    op.drop_index("ix_teacher_grading_decisions_rubric_version_id", table_name="teacher_grading_decisions")
    op.drop_index("ix_teacher_grading_decisions_source_grading_job_id", table_name="teacher_grading_decisions")
    op.drop_index("ix_teacher_grading_decisions_test_id", table_name="teacher_grading_decisions")
    op.drop_index("ix_teacher_grading_decisions_target", table_name="teacher_grading_decisions")
    op.drop_table("teacher_grading_decisions")
