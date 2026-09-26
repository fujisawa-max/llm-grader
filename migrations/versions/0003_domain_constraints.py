"""Enforce version/current invariants for domain entities."""
from alembic import op
revision = "0003_domain_constraints"
down_revision = "0002_domain_model"
branch_labels = None
depends_on = None

def upgrade():
    op.create_index("uq_policy_version", "grading_policies", ["test_id", "version"], unique=True)
    op.create_index("uq_model_answer_version", "model_answers", ["test_id", "question_id", "version"], unique=True)
    op.create_index("uq_model_answer_current", "model_answers", ["test_id", "question_id"], unique=True,
                    postgresql_where=__import__('sqlalchemy').text("is_current = true"),
                    sqlite_where=__import__('sqlalchemy').text("is_current = 1"))
    op.create_index("uq_rubric_approved", "rubric_versions", ["test_id"], unique=True,
                    postgresql_where=__import__('sqlalchemy').text("status = 'approved'"),
                    sqlite_where=__import__('sqlalchemy').text("status = 'approved'"))
    op.create_index("uq_policy_current", "grading_policies", ["test_id"], unique=True,
                    postgresql_where=__import__('sqlalchemy').text("is_current = true"),
                    sqlite_where=__import__('sqlalchemy').text("is_current = 1"))

def downgrade():
    for n,t in [("uq_policy_current","grading_policies"),("uq_rubric_approved","rubric_versions"),
                ("uq_model_answer_current","model_answers"),("uq_model_answer_version","model_answers"),("uq_policy_version","grading_policies")]: op.drop_index(n, table_name=t)
