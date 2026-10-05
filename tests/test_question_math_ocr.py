from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scoring.api import create_app
from scoring.question_math_source import question_math_source, item_reference
from scoring.review_document import ReviewError
from scoring.math_region_grouping import source_regions
from tests import test_question_vision as vision_fixture


@pytest.fixture
def workspace():
    fixture = vision_fixture.VisionApiTests()
    fixture.setUp()
    fixture.client.close()
    fixture.client = TestClient(create_app(fixture.sf, question_import_root=fixture.root,
        model_answer_classifier=SimpleNamespace(manager=object())))
    fixture.client.post('/api/v1/auth/login', json={'email': 'vision-fixture@example.invalid', 'password': 'isolated-fixture-password'})
    data = fixture.client.post(f'/api/v1/question-import-drafts/{fixture.draft_id}/reviews').json()
    yield fixture, data
    fixture.tearDown()


def body_and_url(data, index=1):
    node = data['snapshot']['nodes'][0]
    item = node['ordered_content'][index]
    return f"/api/v1/question-import-reviews/{data['id']}/nodes/{node['stable_key']}/items/{index}/math-ocr", {
        'text': 'x=1\nx=2', 'expected_revision': data['current_revision'], 'expected_source': item_reference(item)}


def proposal(path, segments, text, **kwargs):
    from scoring.math_region_grouping import union_box
    assert path.name == 'source.pdf' and path.is_file()
    assert kwargs == {'alignment_mode': 'source_fragment'}
    assert len(segments) == 2 and all(s['id'] and s['page_index'] == 0 and s['bbox'] for s in segments)
    box = union_box(segments)
    return {'status': 'ambiguous', 'original_text': text, 'normalized_text': '$x=1$\n$x=2$',
        'profile': 'math_ocr', 'model': 'managed-fixture', 'warnings': [], 'changes': [], 'math_regions': [{
            'page_index': 0, 'bbox': box, 'crop_bbox': [box[0]-6, box[1]-6, box[2]+6, box[3]+6],
            'segment_ids': [s['id'] for s in segments], 'original_text': '\n'.join(s['original_text'] for s in segments),
            'grouping_method': 'geometry', 'normalization_method': 'deterministic', 'ornith_used': False,
            'validation': 'accepted'}]}


def test_question_api_is_proposal_only_and_source_backed(workspace):
    fixture, data = workspace
    url, body = body_and_url(data)
    with patch('scoring.source_math_ocr.SourceMathOCR.propose', side_effect=proposal) as engine:
        response = fixture.client.post(url, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['source']['kind'] == 'question_review'
    assert result['source']['node_key'] == 'q1'
    assert result['source']['source_sha256'] == data['source_pdf_sha256']
    assert result['source']['source_ir_sha256'] == data['source_ir_sha256']
    assert engine.call_count == 1
    assert 'raw_response' not in json.dumps(result['apply_provenance'])
    assert fixture.client.get(f"/api/v1/question-import-reviews/{data['id']}").json() == data


@pytest.mark.parametrize('change, status, code', [
    ({'expected_revision': 99}, 409, 'revision_conflict'),
    ({'expected_source': {'source_element_ids': ['neighbor']}}, 409, 'math_question_source_stale'),
    ({'path': '/etc/passwd'}, 422, None),
])
def test_question_invalid_source_and_revision_do_not_start_runtime(workspace, change, status, code):
    fixture, data = workspace
    url, body = body_and_url(data)
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        response = fixture.client.post(url, json={**body, **change})
    assert response.status_code == status
    if code:
        assert response.json()['error']['code'] == code
    engine.assert_not_called()


def test_question_missing_node_and_figure_not_supported(workspace):
    fixture, data = workspace
    url, body = body_and_url(data)
    assert fixture.client.post(url.replace('/nodes/q1/', '/nodes/missing/'), json=body).status_code == 404
    assert fixture.client.post(url.replace('/items/1/', '/items/2/'), json=body).status_code == 422


def test_source_pdf_tamper_rejected_before_inference(workspace):
    fixture, data = workspace
    url, body = body_and_url(data)
    pdf = next(fixture.root.rglob('source.pdf'))
    pdf.write_bytes(pdf.read_bytes()+b'changed')
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        response = fixture.client.post(url, json=body)
    assert response.status_code == 409
    engine.assert_not_called()


def test_unauthenticated_and_student_rejected_before_inference(workspace):
    fixture, data = workspace
    from scoring.domain import DomainService
    from scoring.auth import hash_password
    with fixture.sf() as session:
        domain = DomainService(session)
        domain.user(display_name='Student', email='math-student@example.invalid', role='student',
            password_hash=hash_password('isolated-student-password'), is_active=True)
        session.commit()
    url, body = body_and_url(data)
    fixture.client.cookies.clear()
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        assert fixture.client.post(url, json=body).status_code == 401
        fixture.client.post('/api/v1/auth/login', json={'email': 'math-student@example.invalid', 'password': 'isolated-student-password'})
        assert fixture.client.post(url, json=body).status_code == 403
    engine.assert_not_called()


def test_other_teacher_cannot_access_question_source(workspace):
    fixture, data = workspace
    from scoring.domain import DomainService
    from scoring.auth import hash_password
    with fixture.sf() as session:
        DomainService(session).user(display_name='Other teacher', email='other-math@example.invalid', role='teacher',
            password_hash=hash_password('isolated-teacher-password'), is_active=True)
        session.commit()
    fixture.client.post('/api/v1/auth/login', json={'email': 'other-math@example.invalid', 'password': 'isolated-teacher-password'})
    url, body = body_and_url(data)
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        assert fixture.client.post(url, json=body).status_code == 403
    engine.assert_not_called()


def adapter_fixture():
    observed = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_production_observation.json').read_text())
    spans = observed['production_segments'][1:8]
    item = {'type': 'text', 'order': 0, 'text': observed['complete_math_text'], 'source_element_ids': [s['id'] for s in spans]}
    node = {'stable_key': 'q1', 'review_node_id': 'q1', 'source_draft_stable_key': 'q1',
            'included': True, 'parent_key': None, 'ordered_content': [item]}
    automatic = {'nodes': [node], 'formula_regions': [], 'source_ir_sha256': 'b'*64}
    ir = {'source': {'material_id': 'material', 'sha256': 'a'*64}, 'pages': [{'page_index': 0, 'elements': [
        {'element_id': s['id'], 'type': 'text', 'native_text': s['original_text'], 'bbox': s['bbox'], 'reading_order': s['reading_order']} for s in spans]}]}
    current = SimpleNamespace(snapshot={'nodes': [node], 'source_draft_sha256': 'd'*64})
    service = SimpleNamespace(_review=lambda _: SimpleNamespace(id='review', draft_id='draft', current_revision=1),
        _draft=lambda _: (SimpleNamespace(draft_sha256='d'*64, source_ir_sha256='b'*64), SimpleNamespace(path=lambda _: Path('/fixture/source.pdf')), automatic, ir),
        _revision=lambda *args: current)
    return service, observed, item, current


@pytest.mark.parametrize('prefix,suffix', [('次の式を用いる。 ', '\n式の意味を説明せよ。'), ('次の式', 'を用いよ。')])
def test_question_adapter_retains_math_font_ids_duplicate_numbers_and_geometry(prefix, suffix):
    service, observed, item, _ = adapter_fixture()
    path, segments, source, exclusions = question_math_source(service, 'review', 'q1', 0, 1, item_reference(item))
    assert path == Path('/fixture/source.pdf')
    assert exclusions == []
    assert [s['reading_order'] for s in segments] == list(range(34, 41))
    assert segments[1]['original_text'] == '𝑇𝑃'
    assert [s['reading_order'] for s in segments if s['original_text'] == '24'] == [37, 39]
    # Native fragments can occur in a Question's current prose line, retaining
    # exact offsets rather than rewriting the whole Question.
    text = prefix+observed['complete_math_text'].replace('\n', ' ')+suffix
    regions = source_regions(segments, text, alignment_mode='source_fragment')
    assert len(regions) == 1
    assert regions[0]['bbox'] == observed['observed_bbox']
    assert len(regions[0]['segment_ids']) == 7
    assert not regions[0]['ricoh_used']
    assert source['source_sha256'] == 'a'*64
    assert all(text[s['start']:s['end']] == s['original_text'] for s in regions[0]['source_spans'])


@pytest.mark.parametrize('text', ['124', '0.24', 'TP24', 'ax=24'])
def test_question_source_fragment_never_matches_inside_other_numeric_or_math_token(text):
    source = [{'id': 'native-token', 'original_text': '24' if text != 'ax=24' else 'x=24',
               'bbox': [30, 30, 60, 45], 'page_index': 0}]
    assert source_regions(source, text, alignment_mode='source_fragment') == []


@pytest.mark.parametrize('mode', ['shared', 'slice'])
def test_question_partial_or_shared_native_bbox_is_not_borrowed(mode):
    service, _, item, current = adapter_fixture()
    if mode == 'shared':
        other = deepcopy(current.snapshot['nodes'][0])
        other['stable_key'] = 'q2'
        current.snapshot['nodes'].append(other)
    else:
        item['source_slice'] = [0, 10, 30]
    with pytest.raises(ReviewError, match='math_question_source_boundary'):
        question_math_source(service, 'review', 'q1', 0, 1, item_reference(item))


def test_question_native_crop_excludes_adjacent_question_before_runtime(tmp_path):
    import fitz
    from scoring.source_math_ocr import SourceMathOCR
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 55), 'x=1')
        path = tmp_path/'source.pdf'
        document.save(path)
    segments = [{'id': 'q1-math', 'original_text': 'x=1', 'page_index': 0,
                 'bbox': [50, 45, 90, 60], 'reading_order': 1}]
    class NoRuntime:
        def ensure_running(self, _):
            pytest.fail('adjacent Question crop must be rejected before inference')
    with pytest.raises(ValueError, match='math_source_boundary'):
        SourceMathOCR(NoRuntime(), excluded_source_regions=[{'page_index': 0, 'bbox': [94, 50, 110, 60]}]).propose(
            path, segments, '次の式 x=1 を用いよ。', alignment_mode='source_fragment')


@pytest.mark.parametrize('mode', ['production_spaced', 'formatting_hard'])
def test_question_shared_engine_precision_prose_and_warm_reuse(tmp_path, monkeypatch, mode):
    import fitz
    from scoring.source_math_ocr import SourceMathOCR
    from tests.runtime_fixture import runtime_service
    monkeypatch.setenv('LLM_GRADER_TRUSTED_RUNTIME_HOSTS', '127.0.0.2')
    monkeypatch.setenv('LLM_GRADER_STUB_MATH_RESPONSE_MODE', mode)
    service, observed, item, _ = adapter_fixture()
    _, segments, _, _ = question_math_source(service, 'review', 'q1', 0, 1, item_reference(item))
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        # Render the representative two-dimensional equation inside the actual
        # observed source coordinates; do not let a flat fixture overflow crop.
        page.insert_text((92.664, 514.24), 'Precision=', fontsize=10)
        for x, numerator, denominator, left, right in [
            (155.42, 'TP', 'TP+FP', 148.34, 172.8),
            (189.17, '24', '24+6', 184.61, 204.0),
            (214.85, '24', '30', 214.85, 223.2),
        ]:
            page.insert_text((x, 508.7), numerator, fontsize=6.2)
            page.insert_text((left, 519.6), denominator, fontsize=7)
            page.draw_line((left-1, 511), (right+1, 511))
        for x in (175.8, 206.1, 228):
            page.insert_text((x, 514.24), '=', fontsize=10)
        page.insert_text((245, 514.24), '0.800', fontsize=10)
        path = tmp_path/'source.pdf'
        document.save(path)
    before = '問題2 (2) 2. 次の式を用いて説明せよ。\n'
    after = '\n答えの根拠と図1との関係も説明すること。'
    text = before+observed['complete_math_text']+after
    with runtime_service(tmp_path) as (manager, _, _):
        assert manager.status('math_ocr')['state'] == 'stopped'
        engine = SourceMathOCR(manager)
        result = engine.propose(path, segments, text, alignment_mode='source_fragment')
        assert result['status'] in {'safe', 'ambiguous'}, result['reason_code']
        assert len(result['math_regions']) == 1
        region = result['math_regions'][0]
        assert len(region['segment_ids']) == 7
        assert region['crop_width'] == 380 and region['crop_height'] == 62
        assert region['source_field'] == 'choices[0].message.reasoning_content'
        assert region['validation'] == 'accepted'
        assert region['normalization_method'] == ('deterministic' if mode == 'production_spaced' else 'deterministic_ornith_formatting')
        assert region['ornith_used'] == (mode == 'formatting_hard')
        assert not region['ricoh_used']
        if mode == 'formatting_hard':
            assert region['formatting_validation']['accepted']
        assert result['normalized_text'].startswith(before)
        assert result['normalized_text'].endswith(after)
        assert r'Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=\frac{24}{30}=0.800' in result['normalized_text']
        running = manager.status('math_ocr')
        formatting = manager.status('ornith_rubric_draft')
        warm = engine.propose(path, segments, text, alignment_mode='source_fragment')
        assert warm['normalized_text'] == result['normalized_text']
        assert manager.status('math_ocr')['pid'] == running['pid']
        assert manager.status('math_ocr')['started_at'] == running['started_at']
        if mode == 'production_spaced':
            assert manager.status('ornith_rubric_draft')['state'] == 'stopped'
        else:
            assert manager.status('ornith_rubric_draft')['pid'] == formatting['pid']
            assert manager.status('ornith_rubric_draft')['started_at'] == formatting['started_at']


def test_applied_compact_metadata_save_reload_and_stale_revision(workspace):
    fixture, data = workspace
    url, body = body_and_url(data)
    with patch('scoring.source_math_ocr.SourceMathOCR.propose', side_effect=proposal):
        result = fixture.client.post(url, json=body).json()
    snapshot = deepcopy(data['snapshot'])
    node = snapshot['nodes'][0]
    node['math_ocr_edits'] = [result['apply_provenance']]
    node['formula_decisions']['formula-0001'] = {
        'decision': 'teacher_edit', 'teacher_transcription': r'x=1\quad x=2', 'confirmation_status': 'confirmed'}
    path = f"/api/v1/question-import-reviews/{data['id']}"
    saved = fixture.client.post(path+'/revisions', json={'base_revision': data['current_revision'], 'snapshot': snapshot})
    assert saved.status_code == 200, saved.text
    assert saved.json()['current_revision'] == data['current_revision']+1
    loaded = fixture.client.get(path).json()
    assert loaded == saved.json()
    assert loaded['snapshot']['nodes'][0]['math_ocr_edits'] == [result['apply_provenance']]
    assert loaded['snapshot']['nodes'][0]['formula_decisions']['formula-0001']['teacher_transcription'] == r'x=1\quad x=2'
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        assert fixture.client.post(url, json=body).status_code == 409
        engine.assert_not_called()


@pytest.mark.parametrize('mutation', ['crop_image', 'bbox', 'source_sha256', 'native_text', 'neighbor_id'])
def test_question_math_provenance_cannot_claim_other_source(workspace, mutation):
    fixture, data = workspace
    url, body = body_and_url(data)
    with patch('scoring.source_math_ocr.SourceMathOCR.propose', side_effect=proposal):
        result = fixture.client.post(url, json=body).json()
    edit = result['apply_provenance']
    if mutation == 'crop_image':
        edit['regions'][0]['crop_image'] = 'data:image/png;base64,not-formal-data'
    elif mutation == 'bbox':
        edit['regions'][0]['bbox'] = [0, 0, 99, 99]
    elif mutation == 'source_sha256':
        edit['source_sha256'] = '0'*64
    elif mutation == 'native_text':
        edit['regions'][0]['original_text'] = 'invented source text'
    else:
        edit['regions'][0]['segment_ids'] = ['another-question-id']
    snap = deepcopy(data['snapshot'])
    snap['nodes'][0]['math_ocr_edits'] = [edit]
    response = fixture.client.post(f"/api/v1/question-import-reviews/{data['id']}/revisions",
        json={'base_revision': data['current_revision'], 'snapshot': snap})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'math_question_provenance_invalid'


def test_question_japanese_prose_inside_native_math_span_is_not_removed(tmp_path, monkeypatch):
    import fitz
    from scoring.source_math_ocr import SourceMathOCR
    with fitz.open() as document:
        document.new_page()
        path = tmp_path/'source.pdf'
        document.save(path)
    text = '次の式 x=1 を用いて答えよ。'
    segment = {'id': 'mixed-native-span', 'original_text': text, 'bbox': [30, 30, 300, 50], 'page_index': 0}
    manager = SimpleNamespace(ensure_running=lambda _: {'state': 'ready', 'profile': {
        'model_id': 'managed-fixture', 'endpoint': 'http://127.0.0.1:8080/v1', 'runtime_type': 'managed'}})
    monkeypatch.setattr('scoring.source_math_ocr.LocalClient.request', lambda *_: {
        'choices': [{'message': {'content': 'x=1'}}]})
    result = SourceMathOCR(manager).propose(path, [segment], text,
        alignment_mode='source_fragment')
    assert result['status'] == 'rejected'
    assert result['reason_code'] == 'math_identifier_missing'
    assert result['normalized_text'] == text
    assert result['math_regions'][0]['crop_image']
