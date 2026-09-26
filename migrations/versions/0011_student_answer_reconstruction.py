"""Append-only student answer extraction and reconstruction records."""

from alembic import op
import sqlalchemy as sa

revision = "0011_student_answer_recon"
down_revision = "0010_test_question_correction"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "student_answer_extraction_runs" not in tables:
        op.create_table(
            "student_answer_extraction_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("submission_id", sa.String(36), sa.ForeignKey("student_submissions.id"), nullable=False),
            sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("pipeline_version", sa.String(64), nullable=False),
            sa.Column("config_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("artifact_ref", sa.String(512), nullable=False),
            sa.Column("selected", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_student_answer_extraction_runs_submission", "student_answer_extraction_runs", ["submission_id"])
    if "student_answer_extraction_results" not in tables:
        op.create_table(
            "student_answer_extraction_results",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("student_answer_extraction_runs.id"), nullable=False),
            sa.Column("submission_id", sa.String(36), sa.ForeignKey("student_submissions.id"), nullable=False),
            sa.Column("question_id", sa.String(36), sa.ForeignKey("test_questions.id"), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("artifact_ref", sa.String(512), nullable=False),
            sa.Column("normalized_sha256", sa.String(64)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "question_id", name="uq_student_answer_extraction_result"),
        )
    if "student_answer_reconstructions" not in tables:
        op.create_table(
            "student_answer_reconstructions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("extraction_result_id", sa.String(36), sa.ForeignKey("student_answer_extraction_results.id"), nullable=False),
            sa.Column("submission_id", sa.String(36), sa.ForeignKey("student_submissions.id"), nullable=False),
            sa.Column("question_id", sa.String(36), sa.ForeignKey("test_questions.id"), nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False),
            sa.Column("context_sha256", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("answer_text", sa.Text),
            sa.Column("output_sha256", sa.String(64)),
            sa.Column("artifact_ref", sa.String(512), nullable=False),
            sa.Column("model_identity", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("submission_id", "question_id", "version", name="uq_student_answer_reconstruction_version"),
        )


def downgrade():
    op.drop_table("student_answer_reconstructions")
    op.drop_table("student_answer_extraction_results")
    op.drop_index("ix_student_answer_extraction_runs_submission", table_name="student_answer_extraction_runs")
    op.drop_table("student_answer_extraction_runs")
