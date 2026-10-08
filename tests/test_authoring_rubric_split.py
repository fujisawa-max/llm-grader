from unittest.mock import patch
from uuid import uuid4

from tests.test_diagram_review_api import workspace as source_workspace
from tests.test_authoring_diagrams import begin, save

workspace = source_workspace


def test_rubric_text_split_does_not_require_answer_artifact_and_preserves_revision(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    entry_id = row['snapshot']['domains']['answer']['entries'][0]['id']
    before = w.client.get(path).json()['revision']
    with patch('scoring.authoring_answers.AuthoringAnswers', side_effect=ValueError('authoring_material_replaced')):
        result = w.client.post(path+f'/entries/{entry_id}/rubric-split', json={
            'expected_revision': row['edit_version'], 'candidate_id': 'current-local-criterion',
            'text': 'First criterion. Second criterion.', 'offset': 17})
    assert result.status_code == 200, result.text
    parts = result.json()['parts']
    assert [p['description'] for p in parts] == ['First criterion.', 'Second criterion.']
    assert all(p['points'] == 0 and p['points_conflict'] for p in parts)
    assert w.client.get(path).json()['revision'] == before
    stale = w.client.post(path+f'/entries/{entry_id}/rubric-split', json={
        'expected_revision': row['edit_version']+1, 'candidate_id': 'c', 'text': 'a b', 'offset': 1})
    assert stale.status_code == 409


def test_unsaved_manual_rubric_and_formal_fallback_targets_are_authorized(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    key = row['snapshot']['nodes'][0]['stable_key']
    for entry in [f'teacher-entry-{uuid4()}', 'formal-entry:'+key]:
        result = w.client.post(path+f'/entries/{entry}/rubric-split', json={
            'expected_revision': row['edit_version'], 'candidate_id': 'c', 'question_key': key,
            'text': '5 points: First. 5 points: Second.', 'offset': 17})
        assert result.status_code == 200, result.text
        assert sum(p['points'] for p in result.json()['parts']) == 10
    result = w.client.post(path+f'/entries/teacher-entry-{uuid4()}/rubric-split', json={
        'expected_revision': row['edit_version'], 'candidate_id': 'c', 'question_key': 'foreign-key',
        'text': 'first second', 'offset': 5})
    assert result.status_code == 404
    result = w.client.post(path+f'/entries/formal-entry:{key}/rubric-split', json={
        'expected_revision': row['edit_version'], 'candidate_id': 'c', 'text': 'first ', 'offset': 5})
    assert result.status_code == 422
    assert result.json()['error']['message']


def test_assisted_split_proposal_and_failure_are_explicit_without_saving(workspace):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from fastapi.testclient import TestClient
    from scoring.api.app import create_app
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    key = row['snapshot']['nodes'][0]['stable_key']
    suggest = Mock(return_value={'candidate_id': 'c', 'split': True, 'confidence': 1,
        'reason': 'independent_criteria', 'parts': [{'start': 0, 'end': 17}, {'start': 17, 'end': 34}]})
    client = TestClient(create_app(w.sf, question_import_root=w.root/'questions', allowed_roots=[w.root],
        model_answer_classifier=SimpleNamespace(suggest_rubric_split=suggest)))
    client.post('/api/v1/auth/login', json={'email': 'diagram@example.invalid', 'password': 'isolated-diagram-password'})
    url = path+f'/entries/formal-entry:{key}/rubric-split'
    body = {'expected_revision': row['edit_version'], 'candidate_id': 'c',
        'text': '5 points: First. 5 points: Second.'}
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert len(result.json()['parts']) == 2
    assert sum(p['points'] for p in result.json()['parts']) == 10
    suggest.assert_called_once()
    assert client.get(path).json()['revision'] == row
    suggest.side_effect = RuntimeError('model offline')
    failed = client.post(url, json=body)
    assert failed.status_code == 503
    assert failed.json()['error']['code'] == 'RUBRIC_SPLIT_FAILED'
    assert '再試行' in failed.json()['error']['message']
    assert client.get(path).json()['revision'] == row


def test_saved_unassigned_criterion_can_be_split_before_assignment(workspace):
    from copy import deepcopy
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    value = deepcopy(row['snapshot'])
    entry = value['domains']['answer']['entries'][0]
    entry.update(authoring_question_key=None, disposition='unassigned', mapping_state='needs_review')
    row = save(w, path, row, value)
    result = w.client.post(path+f'/entries/{entry["id"]}/rubric-split', json={
        'expected_revision': row['edit_version'], 'candidate_id': 'c', 'text': 'first second', 'offset': 6})
    assert result.status_code == 200, result.text
    assert len(result.json()['parts']) == 2
    assert w.client.get(path).json()['revision'] == row
