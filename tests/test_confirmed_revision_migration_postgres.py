"""Real PostgreSQL migration round-trip on an explicitly disposable database."""
import importlib
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def test_confirmed_revision_identifier_fits_alembic_column():
    module = importlib.import_module('migrations.versions.0017_confirmed_authoring_revision')
    assert len(module.revision) <= 32


@pytest.mark.skipif(not os.environ.get('TEST_POSTGRES_MIGRATION_URL'), reason='disposable PostgreSQL URL not configured')
def test_confirmed_revision_postgres_upgrade_downgrade_upgrade():
    url = os.environ['TEST_POSTGRES_MIGRATION_URL']
    parsed = make_url(url)
    assert parsed.host in {'127.0.0.1', 'localhost'}
    assert parsed.database.startswith('jui12c_migration_')
    engine = create_engine(url)
    assert not inspect(engine).get_table_names(), 'database must be fresh and disposable'
    config = Config('alembic.ini')
    config.set_main_option('sqlalchemy.url', url)
    command.upgrade(config, '0016_merge_authoring_review')
    module = importlib.import_module('migrations.versions.0017_confirmed_authoring_revision')
    with engine.begin() as connection:
        # Historical base migrations use current metadata.create_all(). Remove
        # only the additive 0017 schema in this disposable DB to obtain the real
        # previous schema shape. The Alembic version stays at the previous head.
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        connection.execute(text('CREATE TABLE migration_sentinel (value integer PRIMARY KEY)'))
        connection.execute(text('INSERT INTO migration_sentinel VALUES (12)'))
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0017_confirmed_revision'
        assert connection.scalar(text('SELECT value FROM migration_sentinel')) == 12
    assert 'confirmed_authoring_revisions' in inspect(engine).get_table_names()
    command.downgrade(config, '0016_merge_authoring_review')
    assert 'confirmed_authoring_revisions' not in inspect(engine).get_table_names()
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT value FROM migration_sentinel')) == 12
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == module.revision
    engine.dispose()
