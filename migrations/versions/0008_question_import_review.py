"""Immutable teacher review snapshots."""
from alembic import op
from scoring.db.models import QuestionImportReview, QuestionImportReviewRevision

revision = "0008_question_import_review"
down_revision = "0007_question_import_vision"
branch_labels = None
depends_on = None

def upgrade():
    QuestionImportReview.__table__.create(op.get_bind(), checkfirst=True)
    QuestionImportReviewRevision.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    QuestionImportReviewRevision.__table__.drop(op.get_bind(), checkfirst=True)
    QuestionImportReview.__table__.drop(op.get_bind(), checkfirst=True)
