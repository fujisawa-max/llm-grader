"""Append-only authoritative formula corrections."""

from alembic import op
import sqlalchemy as sa

revision = "0010_test_question_correction"
down_revision = "0009_question_import_confirm"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "test_question_corrections" in insp.get_table_names():
        return
    op.create_table(
        "test_question_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("test_question_id", sa.String(36), sa.ForeignKey("test_questions.id"), nullable=False),
        sa.Column("correction_version", sa.Integer, nullable=False),
        sa.Column("correction_type", sa.String(64), nullable=False),
        sa.Column("source_region_ids", sa.JSON, nullable=False),
        sa.Column("previous_content_sha256", sa.String(64), nullable=False),
        sa.Column("new_content_sha256", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.JSON, nullable=False),
        sa.Column("new_value", sa.JSON, nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("source_confirmation_id", sa.String(36), sa.ForeignKey("question_import_confirmations.id")),
        sa.Column("source_review_id", sa.String(36), sa.ForeignKey("question_import_reviews.id")),
        sa.Column("source_revision_number", sa.Integer),
        sa.Column("artifact_ref", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("test_question_id", "correction_version", name="uq_question_correction_version"),
    )
    op.create_index("ix_question_corrections_question", "test_question_corrections", ["test_question_id"])
    op.create_index("ix_test_question_corrections_source_confirmation_id", "test_question_corrections", ["source_confirmation_id"])
    op.create_index("ix_test_question_corrections_source_review_id", "test_question_corrections", ["source_review_id"])


def downgrade():
    op.drop_index("ix_test_question_corrections_source_review_id", table_name="test_question_corrections")
    op.drop_index("ix_test_question_corrections_source_confirmation_id", table_name="test_question_corrections")
    op.drop_index("ix_question_corrections_question", table_name="test_question_corrections")
    op.drop_table("test_question_corrections")
