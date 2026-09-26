"""Add native question PDF extraction records."""

from alembic import op
import sqlalchemy as sa


revision = "0005_question_import_extraction"
down_revision = "0004_domain_events"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # 0004 uses Base.metadata.create_all; on a fresh upgrade it may already
    # have created tables introduced by the current model metadata.
    if "question_import_extractions" in inspector.get_table_names():
        return
    op.create_table(
        "question_import_extractions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("test_id", sa.String(length=36), sa.ForeignKey("tests.id"), nullable=False),
        sa.Column("material_id", sa.String(length=36), sa.ForeignKey("test_materials.id"), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parser_backend", sa.String(length=64), nullable=False),
        sa.Column("parser_library", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("extraction_config_hash", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_question_import_extractions_test_id", "question_import_extractions", ["test_id"])
    op.create_index("ix_question_import_extractions_material_id", "question_import_extractions", ["material_id"])
    op.create_index("ix_question_import_extractions_state", "question_import_extractions", ["state"])
    op.create_index("ix_question_import_extractions_source_sha256", "question_import_extractions", ["source_sha256"])


def downgrade():
    op.drop_index("ix_question_import_extractions_source_sha256", table_name="question_import_extractions")
    op.drop_index("ix_question_import_extractions_state", table_name="question_import_extractions")
    op.drop_index("ix_question_import_extractions_material_id", table_name="question_import_extractions")
    op.drop_index("ix_question_import_extractions_test_id", table_name="question_import_extractions")
    op.drop_table("question_import_extractions")
