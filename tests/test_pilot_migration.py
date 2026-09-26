"""Migration safety checks use isolated databases and no model runtimes."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import CheckConstraint, Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.exc import IntegrityError

spec = importlib.util.spec_from_file_location('pilot_migration', Path(__file__).parents[1] / 'scripts/migrate_q5_sqlite_to_postgres.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PilotMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.db'
        self.target = create_engine(f'sqlite:///{self.root / "target.db"}')
        self.s = create_engine(f'sqlite:///{self.source}')
        for engine, checked in [(self.s, False), (self.target, True)]:
            m = MetaData()
            t = Table('tests', m, Column('id', String, primary_key=True))
            v = Table('values', m, Column('id', String, primary_key=True), Column('score', Integer),
                      *([CheckConstraint('score >= 0')] if checked else []))
            m.create_all(engine)
            if not checked:
                with engine.begin() as c:
                    c.execute(t.insert().values(id='pilot'))
                    c.execute(v.insert().values(id='value', score=1))
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir()
        (self.artifacts / 'evidence').write_text('immutable')

    def tearDown(self):
        self.s.dispose()
        self.target.dispose()
        self.tmp.cleanup()

    def run_import(self, apply=False):
        return module.migrate(self.source, self.target.url, self.artifacts, self.artifacts, 'pilot', apply)

    def test_dry_run_then_idempotent_apply(self):
        self.assertEqual(self.run_import()['tables']['tests']['insert'], 1)
        with self.target.connect() as c:
            self.assertEqual(c.exec_driver_sql('select count(*) from tests').scalar(), 0)
        self.assertEqual(self.run_import(True)['status'], 'PASS')
        second = self.run_import(True)
        self.assertEqual(sum(t['insert'] for t in second['tables'].values()), 0)
        self.assertEqual(sum(t['already_present'] for t in second['tables'].values()), 2)

    def test_conflicting_existing_row_is_not_overwritten(self):
        self.run_import(True)
        with self.target.begin() as c:
            c.exec_driver_sql('update "values" set score=2')
        self.assertEqual(self.run_import(True)['status'], 'CONFLICT')
        with self.target.connect() as c:
            self.assertEqual(c.exec_driver_sql('select score from "values"').scalar(), 2)

    def test_insert_failure_rolls_back_all_rows(self):
        with self.s.begin() as c:
            c.exec_driver_sql('update "values" set score=-1')
        with self.assertRaises(IntegrityError):
            self.run_import(True)
        m = MetaData()
        m.reflect(self.target)
        with self.target.connect() as c:
            for t in m.tables.values():
                self.assertEqual(list(c.execute(select(t))), [])

    def test_changed_destination_artifact_blocks_import(self):
        other = self.root / 'other'
        other.mkdir()
        (other / 'evidence').write_text('different')
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'):
            module.migrate(self.source, self.target.url, self.artifacts, other, 'pilot', True)
