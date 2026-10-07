"""Add whole-test working copies and recoverable archive metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0015_test_authoring"
down_revision = "0014_setup_lock"
branch_labels = None
depends_on = None


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "test_authoring_revisions" not in tables:
        op.create_table("test_authoring_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("edit_version", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(24), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("snapshot_sha256", sa.String(64), nullable=False),
            sa.Column("baseline_sha256", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("test_id", "revision", name="uq_test_authoring_revision"))
        op.create_index("ix_test_authoring_revisions_test_id", "test_authoring_revisions", ["test_id"])
    if "test_archives" not in tables:
        op.create_table("test_archives",
            sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), primary_key=True),
            sa.Column("archived_by", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("previous_status", sa.String(32), nullable=False),
            sa.Column("impact", sa.JSON(), nullable=False))


def downgrade():
    # Archiving never deleted Test/dependent records; removing the marker is
    # explicitly a schema rollback, not a physical delete operation.
    op.drop_table("test_archives")
    op.drop_index("ix_test_authoring_revisions_test_id", table_name="test_authoring_revisions")
    op.drop_table("test_authoring_revisions")
