"""Production visual path tests use isolated synthetic SQLite fixtures only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import select
from scoring.core import LocalClient, write_json
from scoring.db import create_session_factory, init_database
from scoring.db.models import GradingJob, DomainEvent
from scoring.db.models import TestQuestionAsset as QuestionAsset
from scoring.grading_execution import create_execution_job, GradingExecutionRunner, validate_bundle
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import canonical_hash, sha256_file
from scoring.student_answer_runtime import normalize_ricoh_regions, RuntimeStudentAnswerStages
from scoring.student_visual import StudentVisualAssetService, EVENT
from tests.mapping_fixture import create_mapping_fixture


class CoordinateRepairTests(unittest.TestCase):
    def test_declared_units_never_inferred_and_every_kind_checked(self):
        for kind in ('text_blocks', 'formula_regions', 'visual_regions'):
            for bbox in ([100, 500, 300, 650], [0, 0, 1.01, 1], [0, 0, float('nan'), 1], [0, 0, 0, 1], [-1e-10, 0, 1, 1]):
                with self.subTest(kind=kind, bbox=bbox), self.assertRaises(ValueError):
                    normalize_ricoh_regions({'coordinate_space': 'normalized', kind: [{'bbox': bbox}]})
        with self.assertRaises(ValueError):
            normalize_ricoh_regions({'formula_regions': []})
        explicit = {'coordinate_space': 'normalized_1000', 'formula_regions': [{'bbox': [100, 200, 300, 650]}]}
        with self.assertRaises(ValueError):
            normalize_ricoh_regions(explicit)
        self.assertEqual(normalize_ricoh_regions(explicit, allow_explicit_1000=True)['formula_regions'][0]['bbox'], [.1, .2, .3, .65])
        self.assertEqual(explicit['formula_regions'][0]['bbox'], [100, 200, 300, 650])

    def test_retry_exactly_once_and_invalid_layout_never_returned(self):
        stages = RuntimeStudentAnswerStages(None, {})
        invalid = {'coordinate_space': 'normalized', 'formula_regions': [{'bbox': [100, 500, 300, 650]}]}
        with patch.object(stages, '_structured_request', return_value=invalid) as request:
            with self.assertRaisesRegex(ValueError, 'INVALID_RICOH_COORDINATES'):
                stages.ricoh_regions(Path('unused'), [{'question_id': 'q'}])
            self.assertEqual(request.call_count, 2)
        valid = {'coordinate_space': 'normalized', 'formula_regions': [], 'visual_regions': [], 'warnings': []}
        with patch.object(stages, '_structured_request', side_effect=[invalid, valid]) as request:
            _, result = stages.ricoh_regions(Path('unused'), [{'question_id': 'q'}])
            self.assertEqual(request.call_count, 2)
            self.assertEqual(result['formula_regions'], [])


class VisualPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine, self.sf = create_session_factory('sqlite:///:memory:')
        init_database(self.engine)
        self.s = self.sf()
        self.f = create_mapping_fixture(self.s, self.root)
        self.qid = self.f['questions']['A1'].id
        self.sub = self.f['submission']
        self.source = self.root / 'A1.png'
        self.f['material'].storage_ref = str(self.source)
        self.f['material'].mime_type = 'image/png'
        self.f['material'].sha256 = sha256_file(self.source)
        self.f['models']['A1'].material_id = self.f['material'].id
        rubric = deepcopy(self.f['rubric'].rubric_json)
        for q in rubric['questions']:
            for c in q['criteria']:
                c['levels'] = [{'score': 0, 'condition': 'absent'}, {'score': 10, 'condition': 'present'}]
                c['criterion_type'] = 'visual_geometry'
        rubric['teacher_review'] = {'reference_assets': [{'asset_id': 'ref-graph',
            'owner_question_id': self.qid, 'source_document_id': self.f['material'].id,
            'sha256': sha256_file(self.root / 'B1.png'), 'mime_type': 'image/png', 'artifact_ref': 'B1.png'}]}
        self.f['rubric'].rubric_json = rubric
        (self.root / 'question-assets').mkdir()
        blank = self.root / 'question-assets/blank.png'
        blank.write_bytes((self.root / 'A2.png').read_bytes())
        self.s.add(QuestionAsset(id='question-blank', question_id=self.qid, asset_type='figure',
            artifact_ref='blank.png', sha256=sha256_file(blank), mime_type='image/png',
            provenance={'extraction_id': 'question-assets'}))
        self.f['questions']['A1'].content = {'schema_version': 'test-question-content.v1',
            'items': [{'type': 'figure', 'asset_id': 'question-blank'}]}
        self.f['questions']['A1'].content_sha256 = canonical_hash(self.f['questions']['A1'].content)
        self.service = StudentVisualAssetService(self.s, self.root)
        self.asset = self.service.register(self.sub.id, self.qid, [.1, .1, .9, .9],
            source_sha=sha256_file(self.source), provenance={'synthetic': True}, verified=True)
        self.s.commit()
        self.cap = {'model_id': 'ornith-test', 'vision': True, 'props': {'modalities': {'vision': True}}}
        self.config = self.root / 'config.json'
        write_json(self.config, {'models': {'grader': {'model_id': 'ornith-test'}}})

    def tearDown(self):
        self.s.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def assembler(self, capability=True):
        return GradingInputAssembler(self.s, self.f['test'].id, root=self.root,
            allowed_roots=[self.root], visual_capability=self.cap if capability else None)

    def preview(self, capability=True):
        return self.assembler(capability).execution_preview(self.sub.id, self.qid)

    def test_crop_immutable_idempotent_and_exact_ownership(self):
        before = sha256_file(self.source)
        again = self.service.register(self.sub.id, self.qid, [.1, .1, .9, .9],
            source_sha=before, provenance={'synthetic': True}, verified=True)
        self.assertEqual(again, self.asset)
        self.assertEqual(before, sha256_file(self.source))
        self.assertEqual(len(list(self.s.scalars(select(DomainEvent).where(DomainEvent.event_type == EVENT)))), 1)
        with self.assertRaises(ValueError):
            self.service.get(self.asset['asset_id'], self.sub.id, self.f['questions']['A2'].id)
        with self.assertRaises(ValueError):
            self.service.register(self.sub.id, self.f['parents']['A'].id, [.1,.1,.9,.9], source_sha=before, provenance={})
        with self.assertRaises(ValueError):
            self.service.register(self.sub.id, self.qid, [100,100,900,900], source_sha=before, provenance={})
        self.assertEqual(len(list(self.s.scalars(select(GradingJob)))), 0)

    def test_preview_ready_only_with_capability_and_valid_rubric(self):
        self.assertEqual(self.preview()['execution_state'], 'READY')
        self.assertIn('VISUAL_GRADING_MODEL_UNSUPPORTED', str(self.preview(False)))
        rubric = deepcopy(self.f['rubric'].rubric_json)
        next(q for q in rubric['questions'] if q['question_id'] == self.qid)['criteria'][0].pop('levels')
        self.f['rubric'].rubric_json = rubric
        self.s.flush()
        self.assertEqual(self.preview()['execution_state'], 'BLOCKED')
        self.assertEqual(len(list(self.s.scalars(select(GradingJob)))), 0)

    def test_roles_owner_hash_and_tampering_blocked(self):
        bundle = self.preview()['bundle']
        validate_bundle(bundle)
        for field, value in [('question_id', 'other'), ('submission_id', 'other'), ('role', 'question_context'), ('review_required', True), ('pixel_bbox', [0,0,1,1])]:
            bad = deepcopy(bundle)
            bad['visual_assets'][-1][field] = value
            bad['bundle_sha256'] = canonical_hash({k:v for k,v in bad.items() if k != 'bundle_sha256'})
            with self.assertRaises(ValueError):
                validate_bundle(bad)
        (self.root / self.asset['artifact_ref']).write_bytes(b'tamper')
        with self.assertRaises(ValueError):
            self.preview()

    def test_worker_passes_actual_images_and_sealed_roles_without_current_resolution(self):
        preview = self.preview()['bundle']
        job = create_execution_job(self.s, self.f['test'].id, self.sub.id, self.qid,
            root=self.root, allowed_roots=[self.root], config_path=self.config,
            run_path=self.root/'run', visual_capability=self.cap)
        self.s.commit()
        self.assertEqual(job.metadata_json['grading_execution']['bundle'], preview)
        manager = Mock()
        manager.status.return_value = {'profile': {'runtime_type': 'managed'}, 'pid': None}
        manager.ensure_running.return_value = {'profile': {'model_id': 'ornith-test'}, 'endpoint': 'http://127.0.0.1:18080/v1'}
        manager.health.return_value = {'ok': True}
        manager.stop.return_value = {'state': 'stopped'}
        requests = []
        qid = self.qid
        class Client(LocalClient):
            def request(self, url, payload=None):
                if payload is None:
                    return {'modalities': {'vision': True}}
                requests.append(payload)
                write_json(self.audit_path, payload)
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                    'question_id': qid, 'criteria': [{'criterion_id': 'criterion-A1', 'score': 0,
                    'max_score': 10, 'evidence': [{'page_id': preview['student_answer']['page_ids'][0],
                    'visual_observation': 'synthetic mark'}], 'reason': 'synthetic'}],
                    'needs_review': False, 'review_reasons': []})}}]}
        self.f['rubric'].rubric_json = {}
        self.s.flush()
        runner = GradingExecutionRunner(manager, Client)
        runner.run(job)
        content = requests[0]['messages'][1]['content']
        self.assertEqual(sum(v['type'] == 'image_url' for v in content), 3)
        self.assertTrue(any(v.get('text', '').startswith('question_context:') for v in content))
        self.assertTrue(any(v.get('text', '').startswith('student_visual_answer:') for v in content))
        self.assertTrue(any(v.get('text', '').startswith('model_answer_reference:') for v in content))
        runner.run(job)
        self.assertEqual(len(requests), 1)
        manager.stop.assert_called_once()

    def test_api_visual_preview_and_asset_do_not_generate_or_expose_host_paths(self):
        from fastapi.testclient import TestClient
        from scoring.api.app import create_app
        app = create_app(self.sf, question_import_root=self.root, allowed_roots=[self.root],
                         grading_visual_config={'visual_capability': self.cap})
        url = f'/api/v1/tests/{self.f["test"].id}/submissions/{self.sub.id}/questions/{self.qid}'
        with TestClient(app) as client:
            response = client.get(url + '/grading-input-preview')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['execution_state'], 'READY')
            self.assertNotIn(str(self.root), response.text)
            response = client.get(url + '/visual-assets/' + self.asset['asset_id'])
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list(self.s.scalars(select(GradingJob)))), 0)
