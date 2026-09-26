"""Separate vision evidence runs/results; no changes to native drafts."""
from alembic import op
from scoring.db.models import QuestionImportVisionRun, QuestionImportVisionResult

revision = "0007_question_import_vision"
down_revision = "0006_question_import_draft"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier revisions create current metadata on an empty installation.
    QuestionImportVisionRun.__table__.create(op.get_bind(), checkfirst=True)
    QuestionImportVisionResult.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("question_import_vision_results")
    op.drop_table("question_import_vision_runs")
