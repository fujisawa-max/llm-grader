"""Add native model-answer import drafts and answer provenance."""
from alembic import op
import sqlalchemy as sa


revision = "0015_model_answer_import_review"
down_revision = "0014_setup_lock"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "model_answers" in tables:
        columns = {column["name"] for column in inspector.get_columns("model_answers")}
        if "provenance_json" not in columns:
            op.add_column("model_answers", sa.Column("provenance_json", sa.JSON(), nullable=True))
    if "model_answer_import_drafts" not in tables:
        op.create_table(
            "model_answer_import_drafts",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("test_id", sa.String(length=36), sa.ForeignKey("tests.id"), nullable=False),
            sa.Column("material_id", sa.String(length=36), sa.ForeignKey("test_materials.id"), nullable=False),
            sa.Column("source_sha256", sa.String(length=64), nullable=False),
            sa.Column("artifact_ref", sa.String(length=512), nullable=False),
            sa.Column("state", sa.String(length=24), nullable=False, server_default="editing"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_model_answer_import_drafts_test_id", "model_answer_import_drafts", ["test_id"])
        op.create_index("ix_model_answer_import_drafts_material_id", "model_answer_import_drafts", ["material_id"])
        op.create_index("ix_model_answer_import_drafts_source_sha256", "model_answer_import_drafts", ["source_sha256"])
        op.create_index("ix_model_answer_import_drafts_state", "model_answer_import_drafts", ["state"])


def downgrade():
    bind = op.get_bind()
    if "model_answer_import_drafts" in sa.inspect(bind).get_table_names():
        for name in ("test_id", "material_id", "source_sha256", "state"):
            index = f"ix_model_answer_import_drafts_{name}"
            if index in {item["name"] for item in sa.inspect(bind).get_indexes("model_answer_import_drafts")}:
                op.drop_index(index, table_name="model_answer_import_drafts")
        op.drop_table("model_answer_import_drafts")
    if "model_answers" in sa.inspect(bind).get_table_names():
        columns = {column["name"] for column in sa.inspect(bind).get_columns("model_answers")}
        if "provenance_json" in columns:
            op.drop_column("model_answers", "provenance_json")
