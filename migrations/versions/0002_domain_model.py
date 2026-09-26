"""Add course/test domain entities and bind grading jobs to rubric snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0002_domain_model"
down_revision = "0001_grading_tables"
branch_labels = None
depends_on = None


def upgrade():
    # Domain tables are declared in SQLAlchemy metadata; create them without
    # touching existing artifact/job tables.
    from scoring.db.database import Base
    from scoring.db import models  # noqa: F401
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_columns("grading_jobs") if "grading_jobs" in inspector.get_table_names() else []
    names = {c["name"] for c in existing}
    if "test_id" not in names:
        op.add_column("grading_jobs", sa.Column("test_id", sa.String(36), nullable=True))
    if "rubric_version_id" not in names:
        op.add_column("grading_jobs", sa.Column("rubric_version_id", sa.String(36), nullable=True))
    Base.metadata.create_all(bind)


def downgrade():
    op.drop_column("grading_jobs", "rubric_version_id")
    op.drop_column("grading_jobs", "test_id")
    bind = op.get_bind()
    for table in ["student_submissions", "students", "rubric_versions", "sample_answer_scores", "sample_answers", "grading_policies", "model_answers", "test_materials", "test_questions", "tests", "course_offerings", "courses", "users"]:
        op.drop_table(table)
