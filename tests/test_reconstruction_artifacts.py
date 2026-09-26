import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select
from scoring.db import create_session_factory, init_database
from scoring.db import models as m
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.reconstruction_artifacts import (
    create_teacher_transcription, create_teacher_revision,
    ensure_reconstruction_artifact, load_repaired)
from tests.mapping_fixture import create_mapping_fixture


class TeacherArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine, factory = create_session_factory('sqlite:///:memory:')
        init_database(self.engine)
        self.s = factory()
        self.f = create_mapping_fixture(self.s, self.root)
        mat = self.f['material']
        mat.storage_ref = str(self.root / 'A1.png')
        mat.mime_type = 'image/png'
        mat.sha256 = sha256_file(Path(mat.storage_ref))
        rubric = deepcopy(self.f['rubric'].rubric_json)
        for q in rubric['questions']:
            for c in q['criteria']:
                c['levels'] = [{'score': 0, 'condition': 'absent'}, {'score': 10, 'condition': 'present'}]
        self.f['rubric'].rubric_json = rubric
        self.s.flush()

    def tearDown(self):
        self.s.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def create(self):
        return create_teacher_transcription(self.s, self.root, self.f['submission'].id,
            self.f['questions']['A1'].id, '2 + 2 = 5',
            source_sha256=self.f['material'].sha256, bbox=[.1, .1, .9, .9], decision_id='teacher-1')

    def preview(self):
        return GradingInputAssembler(self.s, self.f['test'].id, root=self.root,
            answer_root=self.root, allowed_roots=[self.root]).execution_preview(self.f['submission'].id, self.f['questions']['A1'].id)

    def test_teacher_v1_artifact_and_production_preview(self):
        r = self.create()
        self.assertEqual(r.version, 1)
        self.assertTrue((self.root / r.artifact_ref / 'manifest.json').is_file())
        self.assertEqual(self.preview()['execution_state'], 'READY')
        inp = (self.root / r.artifact_ref / 'reconstruction-input.json').read_text()
        for secret in ('max_points', 'MODEL_TOKEN', 'RUBRIC_TOKEN'):
            self.assertNotIn(secret, inp)
        self.assertEqual(self.create().id, r.id)

    def test_edit_creates_new_artifact_preserves_old(self):
        old = self.create()
        path = self.root / old.artifact_ref / 'reconstruction.json'
        before = path.read_bytes()
        r = create_teacher_revision(self.s, self.root, old.id, '2 + 2 = 6', action='EDIT', reason='explicit')
        self.assertEqual(r.version, 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(r.artifact_ref, old.artifact_ref)
        self.assertEqual(self.preview()['execution_state'], 'READY')
        self.assertEqual(create_teacher_revision(self.s,self.root,old.id,'2 + 2 = 6',action='EDIT',reason='explicit').id,r.id)

    def test_valid_artifact_is_not_duplicated(self):
        r = self.create()
        _, changed = ensure_reconstruction_artifact(self.s, r.id, self.root)
        self.assertFalse(changed)
        self.assertIsNone(load_repaired(self.s, r, self.root))

    def test_original_image_transcription_revision_seals_crop_and_preserves_history(self):
        old = self.create()
        before = (self.root / old.artifact_ref / 'reconstruction.json').read_bytes()
        r = create_teacher_revision(self.s, self.root, old.id, 'unchanged student error',
            action='EDIT', reason='authorized image transcription',
            transcription_bbox=[.1, .2, .8, .9])
        self.assertEqual(r.model_identity['origin'], 'TEACHER_TRANSCRIPTION')
        folder = self.root / r.artifact_ref
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(manifest['files']['source-crop.png'], sha256_file(folder / 'source-crop.png'))
        self.assertEqual((self.root / old.artifact_ref / 'reconstruction.json').read_bytes(), before)
        self.assertEqual(self.preview()['execution_state'], 'READY')

    def test_missing_artifact_detected_repaired_idempotently(self):
        r = self.create()
        (self.root / r.artifact_ref / 'reconstruction-input.json').unlink()
        self.assertEqual(self.preview()['execution_state'], 'BLOCKED')
        original = (r.answer_text, r.output_sha256, r.version)
        a, changed = ensure_reconstruction_artifact(self.s, r.id, self.root)
        self.assertTrue(changed)
        b, changed = ensure_reconstruction_artifact(self.s, r.id, self.root)
        self.assertFalse(changed)
        self.assertEqual(a,b)
        self.assertEqual(original,(r.answer_text,r.output_sha256,r.version))
        self.assertEqual(self.preview()['execution_state'], 'READY')

    def test_repair_cannot_select_unresolved_revision(self):
        r = self.create()
        ex = self.s.get(m.StudentAnswerExtractionResult,r.extraction_result_id)
        run = self.s.get(m.StudentAnswerExtractionRun,ex.run_id)
        run.selected = False
        (self.root / r.artifact_ref / 'reconstruction-input.json').unlink()
        ensure_reconstruction_artifact(self.s,r.id,self.root)
        self.assertFalse(run.selected)
        self.assertEqual(len(list(self.s.scalars(select(m.StudentAnswerExtractionRun).where(m.StudentAnswerExtractionRun.selected.is_(True))))),0)

    def test_repair_tampering_rejected(self):
        r = self.create()
        (self.root / r.artifact_ref / 'reconstruction-input.json').unlink()
        ensure_reconstruction_artifact(self.s,r.id,self.root)
        p = self.root / 'reconstruction-repairs' / r.id / 'artifact.json'
        value = json.loads(p.read_text())
        value['normalized']['answer_text'] = 'tampered'
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):
            load_repaired(self.s,r,self.root)
