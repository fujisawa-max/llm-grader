"""Hierarchical authoritative question import confirmations."""

from alembic import op
import sqlalchemy as sa

revision = "0009_question_import_confirm"
down_revision = "0008_question_import_review"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("test_questions")}
    additions = [
        ("parent_id", sa.String(36), True),
        ("stable_question_key", sa.String(128), True),
        ("display_label", sa.String(200), True),
        ("node_type", sa.String(32), False, "standalone"),
        ("is_gradable", sa.Boolean(), False, True),
        ("content", sa.JSON(), True),
        ("content_sha256", sa.String(64), True),
        ("provenance", sa.JSON(), True),
    ]
    for item in additions:
        name, typ, nullable, *default = item
        if name not in cols:
            kw = {"nullable": nullable}
            if default:
                kw["server_default"] = sa.text("true") if name == "is_gradable" else str(default[0])
            op.add_column("test_questions", sa.Column(name, typ, **kw))
    indexes = {i["name"] for i in insp.get_indexes("test_questions")}
    if "ix_test_questions_parent_id" not in indexes:
        op.create_index(
            "ix_test_questions_parent_id", "test_questions", ["parent_id"], unique=False
        )
    if "uq_test_questions_stable_key" not in indexes:
        op.create_index(
            "uq_test_questions_stable_key",
            "test_questions",
            ["test_id", "stable_question_key"],
            unique=True,
        )
    if not any(
        f["constrained_columns"] == ["parent_id"] for f in insp.get_foreign_keys("test_questions")
    ):
        with op.batch_alter_table("test_questions") as batch:
            batch.create_foreign_key(
                "fk_test_questions_parent", "test_questions", ["parent_id"], ["id"]
            )
    tables = set(insp.get_table_names())
    if "question_import_confirmations" not in tables:
        op.create_table(
            "question_import_confirmations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("test_id", sa.String(36), sa.ForeignKey("tests.id"), nullable=False),
            sa.Column(
                "review_id",
                sa.String(36),
                sa.ForeignKey("question_import_reviews.id"),
                nullable=False,
            ),
            sa.Column("review_revision_number", sa.Integer, nullable=False),
            sa.Column("review_revision_sha256", sa.String(64), nullable=False),
            sa.Column("source_draft_sha256", sa.String(64), nullable=False),
            sa.Column("import_plan_sha256", sa.String(64), nullable=False),
            sa.Column("import_schema_version", sa.String(64), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("artifact_ref", sa.String(512), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "review_id", "review_revision_number", name="uq_import_confirmation_revision"
            ),
            if_not_exists=True,
        )
        op.create_index(
            "ix_question_import_confirmations_test_id", "question_import_confirmations", ["test_id"]
        )
        op.create_index(
            "ix_question_import_confirmations_review_id",
            "question_import_confirmations",
            ["review_id"],
        )
    if "question_import_confirmation_items" not in tables:
        op.create_table(
            "question_import_confirmation_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "confirmation_id",
                sa.String(36),
                sa.ForeignKey("question_import_confirmations.id"),
                nullable=False,
            ),
            sa.Column("review_node_id", sa.String(128), nullable=False),
            sa.Column("source_draft_stable_key", sa.String(128)),
            sa.Column("test_question_id", sa.String(36), sa.ForeignKey("test_questions.id")),
            sa.Column("stable_question_key", sa.String(128)),
            sa.Column("imported_order", sa.Integer, nullable=False),
            sa.Column("excluded", sa.Boolean, nullable=False),
            sa.UniqueConstraint(
                "confirmation_id", "review_node_id", name="uq_import_confirmation_node"
            ),
        )
        op.create_index(
            "ix_question_import_confirmation_items_confirmation_id",
            "question_import_confirmation_items",
            ["confirmation_id"],
        )
        op.create_index(
            "ix_question_import_confirmation_items_test_question_id",
            "question_import_confirmation_items",
            ["test_question_id"],
        )
    if "test_question_assets" not in tables:
        op.create_table(
            "test_question_assets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "question_id", sa.String(36), sa.ForeignKey("test_questions.id"), nullable=False
            ),
            sa.Column("asset_type", sa.String(32), nullable=False),
            sa.Column("artifact_ref", sa.String(512), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False),
            sa.Column("provenance", sa.JSON),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_test_question_assets_question_id", "test_question_assets", ["question_id"]
        )
    # deterministic backfill for existing manual rows
    bind.execute(
        sa.text(
            "UPDATE test_questions SET stable_question_key = 'legacy-' || id WHERE stable_question_key IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE test_questions SET display_label = question_number WHERE display_label IS NULL"
        )
    )
    bind.execute(
        sa.text("UPDATE test_questions SET node_type = 'standalone' WHERE node_type IS NULL")
    )
    bind.execute(sa.text("UPDATE test_questions SET is_gradable = TRUE WHERE is_gradable IS NULL"))
    if (
        next(c for c in insp.get_columns("test_questions") if c["name"] == "max_points")["nullable"]
        is False
    ):
        with op.batch_alter_table("test_questions") as batch:
            batch.alter_column("max_points", existing_type=sa.Float(), nullable=True)


def downgrade():
    op.drop_table("test_question_assets")
    op.drop_table("question_import_confirmation_items")
    op.drop_table("question_import_confirmations")
    op.drop_index("uq_test_questions_stable_key", table_name="test_questions")
    op.drop_index("ix_test_questions_parent_id", table_name="test_questions")
    foreign = next(
        (
            f
            for f in sa.inspect(op.get_bind()).get_foreign_keys("test_questions")
            if f["constrained_columns"] == ["parent_id"]
        ),
        None,
    )
    with op.batch_alter_table(
        "test_questions", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        if foreign:
            batch.drop_constraint(
                foreign["name"] or "fk_test_questions_parent_id", type_="foreignkey"
            )
        for name in (
            "provenance",
            "content_sha256",
            "content",
            "is_gradable",
            "node_type",
            "display_label",
            "stable_question_key",
            "parent_id",
        ):
            batch.drop_column(name)
