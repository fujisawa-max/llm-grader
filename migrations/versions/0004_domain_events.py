"""Add append-only domain audit events."""
from alembic import op
revision="0004_domain_events"; down_revision="0003_domain_constraints"; branch_labels=None; depends_on=None
def upgrade():
    from scoring.db.database import Base
    from scoring.db import models  # noqa: F401
    Base.metadata.create_all(op.get_bind())
def downgrade(): op.drop_table("domain_events")
