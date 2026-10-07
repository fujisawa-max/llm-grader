from copy import deepcopy
from unittest.mock import patch

from tests.test_question_math_ocr import workspace as source_workspace, proposal
from scoring.question_math_source import item_reference

workspace = source_workspace


def start(fixture, data):
    path = f'/api/v1/tests/{data["test_id"]}/authoring'
    response = fixture.client.post(path+'/revisions')
    assert response.status_code == 200, response.text
    return path, response.json()


def test_question_saved_review_precedence_preserves_evidence(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    snapshot = row['snapshot']
    assert snapshot['nodes'] == data['snapshot']['nodes']
    assert snapshot['domains']['question']['document']['id'] == data['id']
    origins = snapshot['source_provenance']['authoring_origins']
    assert origins['identities']['q1']['source_review_id'] == data['id']
    assert origins['identities']['q1']['formal_question_id'] is None
    assert snapshot['nodes'][0]['ordered_content'][1]['source_element_ids']
    assert fixture.client.get(path).json()['external_source_change'] is False


def test_authoring_question_math_uses_shared_engine_without_legacy_save(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    expected = {'items': [item_reference(i) for i in row['snapshot']['nodes'][0]['ordered_content']]}
    with patch('scoring.source_math_ocr.SourceMathOCR.propose', side_effect=lambda path, segments, text, **kw: proposal(path, [s for s in segments if s["original_text"].startswith("x=")], text, **kw)) as engine:
        result = fixture.client.post(path+'/nodes/q1/math-ocr', json={'text': 'x=1\nx=2',
            'expected_revision': row['edit_version'], 'expected_source': expected})
    assert result.status_code == 200, result.text
    assert engine.call_count == 1
    assert result.json()['source']['source_sha256'] == data['source_pdf_sha256']
    assert fixture.client.get(f'/api/v1/question-import-reviews/{data["id"]}').json() == data
    assert fixture.client.get(path).json()['revision'] == row


def test_authoring_question_save_roundtrip_is_not_review_or_formal_publication(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    snapshot = deepcopy(row['snapshot'])
    node = snapshot['nodes'][0]
    node['ordered_content'][0]['text'] += '\n教師による追記'
    node['body_text'] += '\n教師による追記'
    result = fixture.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert result.status_code == 200, result.text
    restored = fixture.client.get(path).json()['revision']
    assert restored['snapshot']['nodes'][0]['ordered_content'][0]['text'] == node['ordered_content'][0]['text']
    assert restored['state'] == 'draft'
    assert fixture.client.get(f'/api/v1/question-import-reviews/{data["id"]}').json() == data
    assert fixture.client.get(f'/api/v1/tests/{data["test_id"]}/questions').json() == []


def test_external_review_change_blocks_silent_overwrite_and_explicit_import(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    revised = deepcopy(data['snapshot'])
    revised['nodes'][0]['body_text'] += '旧画面で追記'
    revised['nodes'][0]['ordered_content'][0]['text'] += '旧画面で追記'
    response = fixture.client.post(f'/api/v1/question-import-reviews/{data["id"]}/revisions',
        json={'base_revision': data['current_revision'], 'snapshot': revised})
    assert response.status_code == 200, response.text
    assert fixture.client.get(path).json()['external_source_change'] is True
    result = fixture.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': row['snapshot']})
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'AUTHORING_EXTERNAL_REVIEW_CHANGED'
    assert fixture.client.get(path).json()['revision'] == row
    result = fixture.client.post(path+'/source-import', json={'expected_edit_version': row['edit_version']})
    assert result.status_code == 200, result.text
    assert result.json()['snapshot']['nodes'][0]['ordered_content'][0]['text'] == revised['nodes'][0]['ordered_content'][0]['text']
    assert fixture.client.get(path).json()['external_source_change'] is False


def test_source_tamper_is_actionable_and_no_inference(workspace):
    fixture, data = workspace
    pdf = next(fixture.root.rglob('source.pdf'))
    pdf.write_bytes(pdf.read_bytes()+b'changed')
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as engine:
        _, row = start(fixture, data)
    assert not row['snapshot']['domains'].get('question')
    assert row['snapshot']['source_provenance']['authoring_origins']['diagnostics']
    engine.assert_not_called()


def test_stale_source_is_actionable_on_resume_without_inference(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    pdf = next(fixture.root.rglob('source.pdf'))
    pdf.write_bytes(pdf.read_bytes()+b'changed')
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as inference:
        response = fixture.client.get(path)
        issues = fixture.client.get(path+'/review')
    assert response.status_code == 200
    assert response.json()['revision'] == row
    assert response.json()['source_problems'][0]['domain'] == 'question'
    assert any(i['section'] == 'source' for i in issues.json()['issues'])
    inference.assert_not_called()
