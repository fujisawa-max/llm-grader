"""Persist candidate-only question drafts and queryable nodes."""
from alembic import op
import sqlalchemy as sa

revision = "0006_question_import_draft"
down_revision = "0005_question_import_extraction"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier migrations call current metadata.create_all on fresh databases.
    existing = sa.inspect(op.get_bind()).get_table_names()
    if "question_import_drafts" not in existing:
        op.create_table("question_import_drafts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("extraction_id", sa.String(36), sa.ForeignKey("question_import_extractions.id"), nullable=False),
            *[sa.Column(k, sa.String(n), nullable=False) for k, n in [("state",32),("schema_version",64),("parser_name",64),("parser_version",64),("parser_config_hash",64),("source_ir_sha256",64),("artifact_ref",512)]],
            sa.Column("draft_sha256", sa.String(64)), sa.Column("review_required", sa.Boolean(), nullable=False),
            sa.Column("total_points_candidate", sa.Float()), sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("extraction_id", "source_ir_sha256", "parser_version", "parser_config_hash", name="uq_question_draft_input"))
        op.create_index("ix_question_import_drafts_extraction_id", "question_import_drafts", ["extraction_id"])
    if "question_import_draft_nodes" not in existing:
        op.create_table("question_import_draft_nodes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("draft_id", sa.String(36), sa.ForeignKey("question_import_drafts.id"), nullable=False),
            sa.Column("parent_id", sa.String(36), sa.ForeignKey("question_import_draft_nodes.id")),
            sa.Column("stable_key", sa.String(128), nullable=False), sa.Column("node_type", sa.String(32), nullable=False),
            sa.Column("depth", sa.Integer(), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False),
            *[sa.Column(k, sa.Text(), nullable=False) for k in ["label_raw", "label_normalized", "body_text"]],
            sa.Column("score_semantics", sa.String(32), nullable=False),
            *[sa.Column(k, sa.Float()) for k in ["score_points", "effective_points_candidate", "aggregate_points_candidate"]],
            sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("review_required", sa.Boolean(), nullable=False),
            sa.Column("review_flags", sa.JSON(), nullable=False),
            sa.UniqueConstraint("draft_id", "stable_key", name="uq_question_draft_node_key"))
        op.create_index("ix_question_import_draft_nodes_draft_id", "question_import_draft_nodes", ["draft_id"])


def downgrade():
    op.drop_table("question_import_draft_nodes")
    op.drop_table("question_import_drafts")
