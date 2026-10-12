"""Add explicit working-draft lineage without rewriting confirmed payloads."""
from alembic import op
import sqlalchemy as sa

revision = '0018_revision_lineage'
down_revision = '0017_confirmed_revision'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('test_authoring_revisions')}
    references = inspector.get_foreign_keys('test_authoring_revisions')
    with op.batch_alter_table('test_authoring_revisions') as batch:
        if 'parent_confirmed_revision_id' not in columns:
            batch.add_column(sa.Column('parent_confirmed_revision_id', sa.String(36), nullable=True))
        if not any(reference.get('constrained_columns') == ['parent_confirmed_revision_id']
                and reference.get('referred_table') == 'confirmed_authoring_revisions' for reference in references):
            batch.create_foreign_key('fk_authoring_parent_confirmed', 'confirmed_authoring_revisions',
                ['parent_confirmed_revision_id'], ['id'])


def downgrade():
    references = sa.inspect(op.get_bind()).get_foreign_keys('test_authoring_revisions')
    with op.batch_alter_table('test_authoring_revisions') as batch:
        for reference in references:
            if reference.get('constrained_columns') == ['parent_confirmed_revision_id'] and reference.get('name'):
                batch.drop_constraint(reference['name'], type_='foreignkey')
        batch.drop_column('parent_confirmed_revision_id')
