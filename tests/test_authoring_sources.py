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


def test_replaced_question_source_remains_saved_but_tools_require_reanalysis(workspace):
    from scoring.db.models import TestMaterial
    fixture, data = workspace
    path, row = start(fixture, data)
    with fixture.sf() as session:
        old = TestMaterial(test_id=data['test_id'], material_type='question_sheet', original_filename='old.pdf', storage_ref='old.pdf', sha256=data['source_pdf_sha256'])
        new = TestMaterial(test_id=data['test_id'], material_type='question_sheet', original_filename='new.pdf', storage_ref='new.pdf', sha256='b'*64)
        session.add_all([old, new])
        session.flush()
        refs = [{'id': m.id, 'role': m.material_type, 'sha256': m.sha256} for m in (old, new)]
        refs[1]['replaces_material_id'] = old.id
        session.commit()
    snapshot = deepcopy(row['snapshot'])
    snapshot['materials'].extend(refs)
    result = fixture.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert result.status_code == 200, result.text
    restored = fixture.client.get(path).json()
    assert {'domain': 'question', 'code': 'authoring_material_replaced'} in restored['source_problems']
    assert restored['revision']['snapshot']['nodes'] == snapshot['nodes']
    assert fixture.client.get(path+'/nodes/q1/diagrams').status_code == 409
    assert fixture.client.get(f'/api/v1/question-import-reviews/{data["id"]}').json() == data


def test_source_import_keeps_prior_question_copy_when_requested(workspace):
    from scoring.db.models import TestAuthoringRevision
    fixture, data = workspace
    path, row = start(fixture, data)
    result = fixture.client.post(path+'/source-import', json={'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert result.status_code == 200, result.text
    new = result.json()
    assert new['id'] != row['id']
    assert new['edit_version'] == row['edit_version']+1
    with fixture.sf() as session:
        old = session.get(TestAuthoringRevision, row['id'])
        assert old.snapshot == row['snapshot']
        assert old.state == 'analysis_backup'
    assert fixture.client.get(f'/api/v1/question-import-reviews/{data["id"]}').json() == data


def test_analysis_marker_requires_selected_question_source_sha(workspace):
    from scoring.db.models import TestMaterial
    fixture, data = workspace
    path, row = start(fixture, data)
    with fixture.sf() as session:
        material = TestMaterial(test_id=data['test_id'], material_type='question_sheet',
            original_filename='different.pdf', storage_ref='different.pdf', sha256='b'*64)
        session.add(material)
        session.flush()
        material_id = material.id
        session.commit()
    response = fixture.client.post(path+'/source-import', json={
        'expected_edit_version': row['edit_version'], 'preserve_previous': True,
        'analysis_material_id': material_id})
    assert response.status_code == 409
    assert 'AUTHORING_ANALYSIS_SOURCE_CHANGED' in response.text
    assert fixture.client.get(path).json()['revision'] == row


def test_question_analysis_marker_survives_resume(workspace):
    from scoring.db.models import TestMaterial
    fixture, data = workspace
    path, row = start(fixture, data)
    with fixture.sf() as session:
        material = TestMaterial(test_id=data['test_id'], material_type='question_sheet',
            original_filename='question.pdf', storage_ref='question.pdf', sha256=data['source_pdf_sha256'])
        session.add(material)
        session.flush()
        ref = {'id': material.id, 'sha256': material.sha256}
        session.commit()
    response = fixture.client.post(path+'/source-import', json={
        'expected_edit_version': row['edit_version'], 'preserve_previous': True,
        'analysis_material_id': ref['id']})
    assert response.status_code == 200, response.text
    assert response.json()['snapshot']['source_provenance']['analysis_materials'] == [ref]
    assert fixture.client.get(path).json()['revision'] == response.json()
