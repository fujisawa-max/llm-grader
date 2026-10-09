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
    assert result.json()['snapshot']['nodes'] == row['snapshot']['nodes']
    assert result.json()['source_warnings'][0]['code'] == 'authoring_question_review_changed'
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


def test_unresolved_raw_text_saves_as_separate_warning_without_source_mutation(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    snapshot = deepcopy(row['snapshot'])
    original = deepcopy(snapshot['nodes'][0]['ordered_content'])
    snapshot['question_text_buffers'] = {'q1': 'Teacher rewrote text across native/formula boundaries\n$$ unfinished'}
    snapshot['nodes'][0]['body_text'] = snapshot['question_text_buffers']['q1']
    snapshot['nodes'][0].update(score_points=7, score_semantics='direct')
    with patch('scoring.source_math_ocr.SourceMathOCR.propose') as inference:
        saved = fixture.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
        assert saved.status_code == 200, saved.text
        resumed = fixture.client.get(path).json()['revision']
        assert resumed == saved.json()
        assert fixture.client.post(path+'/revisions').json() == resumed
    inference.assert_not_called()
    assert resumed['snapshot']['nodes'][0]['ordered_content'] == original
    assert resumed['snapshot']['nodes'][0]['body_text'] == snapshot['question_text_buffers']['q1']
    assert resumed['source_warnings'][0]['question_key'] == 'q1'
    assert '保存されています' in resumed['source_warnings'][0]['message']
    assert fixture.client.get(f'/api/v1/question-import-reviews/{data["id"]}').json() == data
    assert fixture.client.get(f'/api/v1/tests/{data["test_id"]}/questions').json() == []


def test_raw_buffer_does_not_override_invalid_source_anchor(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    snapshot = deepcopy(row['snapshot'])
    snapshot['question_text_buffers'] = {'q1': 'Teacher raw text'}
    snapshot['nodes'][0]['ordered_content'][0]['source_element_ids'] = ['foreign-element']
    saved = fixture.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert saved.status_code == 409
    assert '保存できませんでした' in saved.text
    assert fixture.client.get(path).json()['revision'] == row


def test_explicit_keep_current_copy_acknowledges_external_token_on_save_and_resume(workspace):
    fixture, data = workspace
    path, row = start(fixture, data)
    revised = deepcopy(data['snapshot'])
    revised['nodes'][0]['ordered_content'][0]['text'] += ' Legacy change'
    changed = fixture.client.post(f'/api/v1/question-import-reviews/{data["id"]}/revisions',
        json={'base_revision': data['current_revision'], 'snapshot': revised})
    assert changed.status_code == 200, changed.text
    saved = fixture.client.put(path, json={'snapshot': row['snapshot'],
        'expected_edit_version': row['edit_version'], 'continue_after_external_change': True})
    assert saved.status_code == 200, saved.text
    resumed = fixture.client.get(path).json()
    assert resumed['external_source_change'] is False
    assert resumed['revision'] == saved.json()
    assert resumed['revision']['snapshot']['nodes'] == row['snapshot']['nodes']
    assert resumed['revision']['snapshot']['domains']['question'] == row['snapshot']['domains']['question']
    assert resumed['revision']['snapshot']['source_provenance']['authoring_origins']['kept_authoring_after_external_change']
    again = fixture.client.put(path, json={'snapshot': saved.json()['snapshot'],
        'expected_edit_version': saved.json()['edit_version']})
    assert again.status_code == 200, again.text


def test_question_analysis_merge_preserves_answer_rubric_and_sources():
    from scoring.authoring_sources import merge_question_analysis

    diagram = {'id': 'accepted-diagram', 'state': 'accepted', 'reuse_ref': 'artifact-ref'}
    answer_entry = {'id': 'answer-1', 'authoring_question_key': 'removed-q', 'answer_text': 'Teacher answer',
        'diagram_records': [diagram], 'source_draft_id': 'answer-draft', 'rubric_edits': [
            {'id': 'criterion-1', 'description': 'Teacher rubric', 'points': 5}],
        'rubric_merge_history': [[{'id': 'before-split', 'description': 'Old text', 'points': 5}]]}
    answer_binding = {'draft_id': 'rubric-latest', 'revision': 4, 'material_id': 'rubric-material',
        'source_sha256': 'rubric-sha', 'artifact_ref': 'rubric-artifact', 'material_role': 'rubric_source',
        'entries': [answer_entry], 'sources': {
            'answer-draft': {'draft_id': 'answer-draft', 'material_id': 'answer-material',
                'source_sha256': 'answer-sha', 'artifact_ref': 'answer-artifact'},
            'rubric-latest': {'draft_id': 'rubric-latest', 'material_id': 'rubric-material',
                'source_sha256': 'rubric-sha', 'artifact_ref': 'rubric-artifact'}}}
    current = {'metadata': {'name': 'teacher name'},
        'nodes': [{'stable_key': 'q1', 'body_text': 'old'}, {'stable_key': 'removed-q', 'body_text': 'old target'}],
        'question_text_buffers': {'q1': 'saved teacher question'},
        'answers': {'q1': {'primary': 'Teacher answer', 'alternatives': ['Alternative'],
                           'diagram_records': [diagram]}, 'removed-q': {'primary': 'recover me'}},
        'rubrics': {'q1': answer_entry['rubric_edits'], 'removed-q': [{'id': 'lost', 'description': 'retain candidate', 'points': 2}]},
        'rubric_histories': {'q1': answer_entry['rubric_merge_history'], 'removed-q': [['old']]},
        'domains': {'question': {'document': {'id': 'old-review'}}, 'answer': answer_binding},
        'materials': [{'id': 'answer-material'}, {'id': 'rubric-material'}],
        'source_provenance': {'model_answers': ['formal stays'], 'authoring_origins': {
            'tokens': {'question': {'id': 'old-q'}, 'answer': {'id': 'answer-token'}},
            'identities': {'q1': {'formal_question_id': 'old-q'}},
            'diagnostics': [{'domain': 'answer', 'id': 'answer-draft'}]}}}
    analyzed = {'metadata': {'name': 'projection name'},
        'nodes': [{'stable_key': 'q1', 'body_text': 'newly analyzed'}],
        'answers': {'q1': {'primary': 'projection answer'}}, 'rubrics': {'q1': [{'id': 'projection-rubric'}]},
        'domains': {'question': {'document': {'id': 'new-review'}}},
        'source_provenance': {'authoring_origins': {'tokens': {
            'question': {'id': 'new-q'}, 'answer': {'id': 'wrong-globally-latest-rubric'}},
            'identities': {'q1': {'formal_question_id': 'new-q'}},
            'diagnostics': [{'domain': 'answer', 'id': 'wrong-latest'}]}}}

    result = merge_question_analysis(current, analyzed)
    assert result['nodes'] == analyzed['nodes']
    assert result['metadata'] == current['metadata']
    assert 'question_text_buffers' not in result
    assert result['domains']['question'] == analyzed['domains']['question']
    assert result['domains']['answer']['material_id'] == 'answer-material'
    assert result['domains']['answer']['material_role'] == 'model_answer_source'
    assert result['answers'] == {'q1': current['answers']['q1']}
    assert result['rubrics'] == {}
    assert result['rubric_histories'] == {}
    origins = result['source_provenance']['authoring_origins']
    assert origins['tokens'] == {'question': {'id': 'new-q'}, 'answer': {'id': 'answer-token'}}
    assert origins['diagnostics'] == [{'domain': 'answer', 'id': 'answer-draft'}]
    assert result['source_provenance']['model_answers'] == ['formal stays']

    # A removed Question target becomes recoverable/unassigned without losing
    # its answer, accepted artifact, Rubric edits, or operation history.
    unresolved = result['domains']['answer']['entries'][0]
    assert unresolved['authoring_question_key'] is None
    assert unresolved['disposition'] == 'unassigned'
    assert unresolved['mapping_state'] == 'needs_review'
    assert unresolved['answer_text'] == 'Teacher answer'
    assert unresolved['diagram_records'] == [diagram]
    assert all('rubric_edits' not in entry for entry in result['domains']['answer']['entries'])
    unresolved_rubric = next(entry for entry in result['domains']['rubric']['entries']
                             if entry.get('source_candidate_id') == 'answer-1')
    assert unresolved_rubric['authoring_question_key'] is None
    assert unresolved_rubric['disposition'] == 'unassigned'
    assert unresolved_rubric['criteria'] == answer_entry['rubric_edits']
    assert unresolved_rubric['operation_history'] == answer_entry['rubric_merge_history']
