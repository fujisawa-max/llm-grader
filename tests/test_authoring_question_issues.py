"""Source-review guidance preserves independent requirements and exact targets."""
from copy import deepcopy
from pathlib import Path

from tests.test_test_authoring import workspace as authoring_workspace
from scoring.test_authoring import preflight

workspace = authoring_workspace


def source_snapshot():
    node = {'stable_key': 'accuracy', 'parent_key': None, 'included': True,
            'source_draft_stable_key': 'accuracy', 'body_text': 'Accuracy（正解率）',
            'score_points': 10, 'formula_decisions': {}, 'figure_decisions': {}}
    warnings = [{'id': f'node:accuracy:{code}', 'code': code, 'owner': 'accuracy',
                 'scope': 'node', 'source_id': 'accuracy', 'blocking': True}
                for code in ('ambiguous_geometric_order', 'reasoning_output_requires_review')]
    return {'nodes': [node], 'metadata': {'total_points': 10},
            'answers': {'accuracy': {'primary': 'answer'}},
            'rubrics': {'accuracy': [{'id': 'criterion', 'points': 10, 'description': 'criterion',
                'levels': [{'score': 0, 'condition': 'No credit'}, {'score': 10, 'condition': 'Complete response'}]}]},
            'source_provenance': {}, 'domains': {'question': {
                'document': {'id': 'review', 'material_id': 'material',
                             'source_pdf_sha256': 'a'*64, 'warnings': warnings, 'regions': []},
                'snapshot': {'warning_states': {}}}}}


def test_two_distinct_source_warnings_have_exact_targets():
    snap = source_snapshot()
    issues = preflight(snap)['issues']
    assert len(issues) == 2
    assert len({i['message'] for i in issues}) == 2
    assert len({i['warning_id'] for i in issues}) == 2
    assert len({i['current_state'] for i in issues}) == 2
    for issue in issues:
        assert issue['question_key'] == 'accuracy'
        assert issue['domain'] == 'question'
        assert issue['code'] == 'question_source_warning'
        assert issue['correction_type'] == 'source_warning'
        assert issue['source_review_id'] == 'review'
        assert issue['source_material_id'] == 'material'
        assert issue['source_sha256'] == 'a'*64
        assert issue['action_label'] == '出典確認へ'
        assert '確認済み' in issue['expected_state']


def test_same_warning_identity_deduplicated_but_other_condition_survives():
    snap = source_snapshot()
    warnings = snap['domains']['question']['document']['warnings']
    warnings.append(deepcopy(warnings[0]))
    assert len(preflight(snap)['issues']) == 2
    snap['domains']['question']['snapshot']['warning_states'][warnings[0]['id']] = {'state': 'acknowledged'}
    issues = preflight(snap)['issues']
    assert len(issues) == 1 and issues[0]['warning_id'] == warnings[1]['id']
    assert snap['nodes'][0]['body_text'] == 'Accuracy（正解率）'


def test_raw_body_source_difference_is_separate_and_not_acknowledged_away():
    snap = source_snapshot()
    snap['nodes'][0]['ordered_content'] = [{'type': 'text', 'text': 'Accuracy（正解率）'}]
    snap['question_text_buffers'] = {'accuracy': 'Changed body'}
    snap['domains']['question']['snapshot']['warning_states'] = {
        w['id']: {'state': 'acknowledged'} for w in snap['domains']['question']['document']['warnings']}
    issues = preflight(snap)['issues']
    assert len(issues) == 1
    assert issues[0]['code'] == 'authoring_text_source_unresolved'
    assert issues[0]['correction_type'] == 'text_source_review'
    assert issues[0]['action_label'] == '本文と出典を確認'


def test_formula_requirement_and_warning_are_independent():
    snap = source_snapshot()
    snap['nodes'][0]['formula_decisions'] = {'formula1': {'decision': 'unreviewed'}}
    issues = preflight(snap)['issues']
    assert len(issues) == 3
    formula = next(i for i in issues if i['code'] == 'question_formula_review')
    assert formula['region_id'] == 'formula1'
    assert formula['action_label'] == '出典確認へ'


def test_actual_sample_q5_source_warning_resolution_without_body_edit(workspace):
    w = workspace
    base = f'/api/v1/tests/{w.fresh}/authoring'
    row = w.client.post(base+'/revisions').json()
    upload = w.client.post(f'/api/v1/tests/{w.fresh}/question-materials',
        content=Path('testData/SampleQ/sampleQ5.pdf').read_bytes(),
        headers={'Content-Type': 'application/pdf', 'x-filename': 'sampleQ5.pdf'})
    assert upload.status_code == 201
    extraction = upload.json()
    material = next(m for m in w.client.get(f'/api/v1/tests/{w.fresh}/materials').json() if m['id'] == extraction['material_id'])
    registered = deepcopy(row['snapshot'])
    registered['materials'].append({'id': material['id'], 'role': material['material_type'], 'sha256': material['sha256']})
    response = w.client.put(base, json={'snapshot': registered, 'expected_edit_version': row['edit_version']})
    assert response.status_code == 200, response.text
    row = response.json()
    draft = w.client.post(f'/api/v1/question-imports/{extraction["id"]}/draft').json()
    assert w.client.post(f'/api/v1/question-import-drafts/{draft["id"]}/reviews').status_code == 201
    imported = w.client.post(base+'/source-import', json={'expected_edit_version': row['edit_version'],
        'analysis_material_id': extraction['material_id']})
    assert imported.status_code == 200, imported.text
    row = imported.json()
    before = deepcopy(row['snapshot']['nodes'])
    issues = w.client.get(base+'/review').json()['issues']
    source = [i for i in issues if i.get('code') == 'question_source_warning']
    assert len(source) >= 2
    first = source[0]
    assert all(i['source_material_id'] == extraction['material_id'] for i in source)
    submitted = deepcopy(row['snapshot'])
    submitted['domains']['question']['snapshot']['warning_states'][first['warning_id']] = {'state': 'acknowledged'}
    saved = w.client.put(base, json={'expected_edit_version': row['edit_version'], 'snapshot': submitted})
    assert saved.status_code == 200, saved.text
    assert saved.json()['snapshot']['nodes'] == before
    after = w.client.get(base+'/review').json()['issues']
    assert first['warning_id'] not in {i.get('warning_id') for i in after}
    assert {i['warning_id'] for i in source[1:]} <= {i.get('warning_id') for i in after}
    assert any(i.get('code') == 'answer_missing' for i in after)


def test_testwide_warning_owner_none_never_attaches_to_split_teacher_child():
    snap = source_snapshot()
    snap['nodes'][0].update(parent_key='q2.2', source_draft_stable_key=None)
    snap['nodes'].insert(0, {'stable_key': 'q2.2', 'parent_key': None, 'included': True,
        'source_draft_stable_key': 'q2.2', 'body_text': 'Evaluation measures',
        'score_points': None, 'formula_decisions': {}, 'figure_decisions': {}})
    warnings = snap['domains']['question']['document']['warnings']
    for warning in warnings:
        warning.update(owner=None, scope='draft', source_id='document')
    # Reproduce the old predicate: None == None selected the split child.
    previous_owners = [next((n['stable_key'] for n in snap['nodes']
                            if n['stable_key'] == warning.get('owner')
                            or n.get('source_draft_stable_key') == warning.get('owner')), None)
                       for warning in warnings]
    assert previous_owners == ['accuracy', 'accuracy']
    issues = preflight(snap)['issues']
    source = [i for i in issues if i.get('code') == 'question_source_warning']
    assert len(source) == 2
    assert all(i['question_key'] is None for i in source)
    assert not any(i['question_key'] == 'accuracy' for i in source)
    assert len({i['warning_id'] for i in source}) == 2
