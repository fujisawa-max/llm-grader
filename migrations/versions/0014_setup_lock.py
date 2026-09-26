"""Add the singleton lock used by the first-run setup wizard."""
from alembic import op
import sqlalchemy as sa

revision = "0014_setup_lock"
down_revision = "0013_authentication"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "setup_lock" not in inspector.get_table_names():
        op.create_table(
            "setup_lock",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.execute("INSERT INTO setup_lock (id, created_at) VALUES (1, CURRENT_TIMESTAMP)")

def downgrade():
    if "setup_lock" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("setup_lock")
