"""Add persistent roles, password state, and opaque browser sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0013_authentication"
down_revision = "0012_teacher_grading_decision"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "role" not in columns:
        op.add_column("users", sa.Column("role", sa.String(32), nullable=False, server_default="teacher"))
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    if "must_change_password" not in columns:
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    indexes = {x["name"] for x in inspector.get_indexes("users")}
    if "ix_users_email" not in indexes:
        # Keep the migration non-destructive for legacy databases that may
        # contain duplicate or placeholder email values.  New admin-created
        # users are checked for duplicates in the API.
        op.create_index("ix_users_email", "users", ["email"], unique=False)
    if "auth_sessions" not in inspector.get_table_names():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        )
        op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "auth_sessions" in inspector.get_table_names():
        op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
        op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
        op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
        op.drop_table("auth_sessions")
    indexes = {x["name"] for x in inspector.get_indexes("users")}
    if "ix_users_email" in indexes:
        op.drop_index("ix_users_email", table_name="users")
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    for name in ("must_change_password", "password_hash", "role"):
        if name in columns:
            op.drop_column("users", name)
