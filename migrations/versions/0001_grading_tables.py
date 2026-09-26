"""create grading job tables"""

from alembic import op

revision = "0001_grading_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from scoring.db.database import Base
    from scoring.db import models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade():
    from scoring.db.database import Base
    from scoring.db import models  # noqa: F401

    Base.metadata.drop_all(op.get_bind())
