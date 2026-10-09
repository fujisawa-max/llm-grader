"""Add immutable confirmed authoring snapshots and nullable grading pins."""
from alembic import op
import sqlalchemy as sa

revision = "0017_confirmed_authoring_revision"
down_revision = "0016_merge_authoring_review"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _add_reference_column(table, column, constraint, index=False):
    inspector = _inspector()
    columns = {value["name"] for value in inspector.get_columns(table)}
    foreign_keys = inspector.get_foreign_keys(table)
    indexes = {value["name"] for value in inspector.get_indexes(table)}
    with op.batch_alter_table(table) as batch:
        if column not in columns:
            batch.add_column(sa.Column(column, sa.String(36), nullable=True))
        has_reference = any(value.get("referred_table") == "confirmed_authoring_revisions"
            and value.get("constrained_columns") == [column] for value in foreign_keys)
        if not has_reference:
            batch.create_foreign_key(constraint, "confirmed_authoring_revisions", [column], ["id"])
        index_name = f"ix_{table}_{column}"
        if index and index_name not in indexes:
            batch.create_index(index_name, [column])


def upgrade():
    inspector = _inspector()
    tables = set(inspector.get_table_names())
    if "confirmed_authoring_revisions" not in tables:
        op.create_table(
            "confirmed_authoring_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), nullable=False),
            sa.Column("authoring_revision_id", sa.String(36), sa.ForeignKey("test_authoring_revisions.id"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("edit_version", sa.Integer(), nullable=False),
            sa.Column("snapshot_sha256", sa.String(64), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("confirmed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("test_id", "authoring_revision_id", name="uq_confirmed_authoring_source"),
        )
    inspector = _inspector()
    for name, columns in {
        "ix_confirmed_authoring_revisions_test_id": ("confirmed_authoring_revisions", ["test_id"]),
        "ix_confirmed_authoring_revisions_authoring_revision_id": ("confirmed_authoring_revisions", ["authoring_revision_id"]),
    }.items():
        if name not in {index["name"] for index in inspector.get_indexes(columns[0])}:
            op.create_index(name, columns[0], columns[1])
    _add_reference_column("tests", "active_confirmed_revision_id", "fk_tests_active_confirmed_revision")
    _add_reference_column("student_submissions", "confirmed_authoring_revision_id",
                          "fk_student_submissions_confirmed_revision", index=True)
    _add_reference_column("grading_jobs", "confirmed_authoring_revision_id",
                          "fk_grading_jobs_confirmed_revision", index=True)


def downgrade():
    inspector = _inspector()
    tables = set(inspector.get_table_names())
    for table, column, constraint, index in (
        ("grading_jobs", "confirmed_authoring_revision_id", "fk_grading_jobs_confirmed_revision", "ix_grading_jobs_confirmed_authoring_revision_id"),
        ("student_submissions", "confirmed_authoring_revision_id", "fk_student_submissions_confirmed_revision", "ix_student_submissions_confirmed_authoring_revision_id"),
        ("tests", "active_confirmed_revision_id", "fk_tests_active_confirmed_revision", None),
    ):
        if table not in tables:
            continue
        inspector = _inspector()
        columns = {value["name"] for value in inspector.get_columns(table)}
        foreign_keys = {value.get("name") for value in inspector.get_foreign_keys(table)}
        indexes = {value["name"] for value in inspector.get_indexes(table)}
        with op.batch_alter_table(table) as batch:
            if index and index in indexes:
                batch.drop_index(index)
            if constraint in foreign_keys:
                batch.drop_constraint(constraint, type_="foreignkey")
            if column in columns:
                batch.drop_column(column)
    tables = set(_inspector().get_table_names())
    if "confirmed_authoring_revisions" in tables:
        inspector = _inspector()
        indexes = {value["name"] for value in inspector.get_indexes("confirmed_authoring_revisions")}
        for index in ("ix_confirmed_authoring_revisions_authoring_revision_id", "ix_confirmed_authoring_revisions_test_id"):
            if index in indexes:
                op.drop_index(index, table_name="confirmed_authoring_revisions")
        op.drop_table("confirmed_authoring_revisions")
