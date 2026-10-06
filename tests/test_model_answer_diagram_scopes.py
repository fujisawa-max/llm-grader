"""Split/shared answers exercise real authorized APIs and the shared extractor."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from scoring.db.models import ModelAnswerImportDraft, TestQuestion, GradingJob
from scoring.domain import DomainService
from tests.test_diagram_review_api import workspace as _workspace_fixture, clean


@pytest.fixture
def workspace(tmp_path, monkeypatch, request):
    yield from _workspace_fixture.__wrapped__(tmp_path, monkeypatch, request)


@pytest.fixture
def shared(workspace):
    w = workspace
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        children = list(s.scalars(select(TestQuestion).where(TestQuestion.test_id == draft.test_id).order_by(TestQuestion.sort_order)))
        parent = DomainService(s).question(draft.test_id, question_number='parent3', display_label='問題3',
            sort_order=3, max_points=None, is_gradable=False)
        for n, child in enumerate(children, 1):
            child.parent_id, child.display_label, child.sort_order = parent.id, f'({n})', n
        snap = deepcopy(draft.snapshot)
        snap['question_regions'] = [{'question_id': parent.id, 'page_index': 0,
            'left': 20, 'top': 50, 'right': 250, 'bottom': 280, 'depth': 1}]
        draft.snapshot = snap
        s.commit()
        w.parent, w.children = parent.id, [q.id for q in children]
    w.base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    w.answer = w.client.get(w.base).json()
    return w


def target(w, qid=None):
    eid = f'teacher-entry-{uuid4()}'
    return eid, f'{w.base}/entries/{eid}/diagrams', {'question_id': qid or w.children[0]}


def discover(w, path, params, scope='exact'):
    return w.client.post(path, params={**params, 'scope': scope}, json={'expected_revision': w.answer['revision']})


def edits(w):
    return [{'id': e['id'], 'question_id': e['question_id'], 'answer_text': e['answer_text'],
             'disposition': 'excluded'} for e in w.answer['entries']]


def test_parent_is_offered_only_after_empty_exact_and_never_assigned_automatically(shared):
    w = shared
    _, path, params = target(w)
    response = discover(w, path, params)
    assert response.status_code == 200, response.text
    assert response.json()['diagrams'] == []
    assert response.json()['fallback'] == {'scope': 'parent', 'source_question_id': w.parent, 'source_question_path': '問題3'}
    parent = discover(w, path, params, 'parent').json()['diagrams'][0]
    assert parent['scope'] == 'parent' and parent['state'] == 'candidate'
    assert parent['target_key'] == parent['source_question_id'] == w.parent
    assert parent['assigned_question_id'] == w.children[0]
    assert parent['automatic_bbox'] == [70, 80, 230, 240] and not parent['ricoh_used']
    assert w.client.get(parent['preview_url']).status_code == 200
    assert discover(w, path, params, 'pdf').status_code == 422
    assert w.client.get(w.base).json()['revision'] == 1


@pytest.mark.parametrize('state', ['candidate', 'excluded', 'accepted'])
def test_shared_assignments_save_reload_and_formal_provenance(shared, state):
    w = shared
    updates = edits(w)
    records, paths = [], []
    for qid in w.children:
        eid, path, params = target(w, qid)
        record = discover(w, path, params, 'parent').json()['diagrams'][0]
        records.append(record)
        paths.append(path)
        updates.append({'id': eid, 'question_id': qid, 'answer_text': '', 'disposition': 'include',
                        'diagram_records': [{**clean(record), 'state': state}]})
    assert records[0]['id'] == records[1]['id']
    assert records[0]['artifact_ref'] == records[1]['artifact_ref']
    assert records[0]['crop_sha256'] == records[1]['crop_sha256']
    saved = w.client.put(w.base, json={'expected_revision': 1, 'entries': updates})
    assert saved.status_code == 200, saved.text
    for path, qid in zip(paths, w.children, strict=True):
        restored = w.client.get(path).json()['diagrams'][0]
        assert restored['state'] == state and restored['source_question_id'] == w.parent
        assert restored['assigned_question_id'] == qid and restored['scope'] == 'parent'
    response = w.client.post(w.base+'/confirm', json={'expected_revision': 2})
    if state != 'accepted':
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'EMPTY_ANSWER_TEXT'
    else:
        assert response.status_code == 200, response.text
        answers = response.json()['model_answers']
        assert len(answers) == 2
        for answer in answers:
            assert answer['answer_text'] == ''
            diagram = answer['provenance_json']['diagrams'][0]
            assert diagram['source_question_id'] == w.parent
            assert diagram['assigned_question_id'] == answer['question_id']
            assert w.client.get(f'/api/v1/model-answers/{answer["id"]}/diagrams/{diagram["id"]}/crop').status_code == 200
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(GradingJob)) == 0


def test_shared_manual_bounds_are_assignment_specific(shared):
    w = shared
    first = []
    for i, qid in enumerate(w.children):
        _, path, params = target(w, qid)
        record = discover(w, path, params, 'parent').json()['diagrams'][0]
        response = w.client.post(path+f'/{record["id"]}/crop-preview', params={**params, 'scope': 'parent'},
            json={'expected_revision': 1, 'final_bbox': [65, 75, 235, 245] if i == 0 else [70, 80, 230, 240]})
        assert response.status_code == 200, response.text
        first.append(response.json())
    assert first[0]['id'] == first[1]['id'] and first[0]['crop_sha256'] != first[1]['crop_sha256']
    assert first[0]['teacher_adjusted'] and not first[1]['teacher_adjusted']


def test_pdf_fallback_is_explicit_after_all_ancestors_empty(shared):
    w = shared
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        snap = deepcopy(draft.snapshot)
        snap['question_regions'] = []
        draft.snapshot = snap
        s.commit()
    eid, path, params = target(w)
    exact = discover(w, path, params).json()
    assert exact['diagrams'] == [] and exact['fallback'] == {'scope': 'pdf'}
    assert discover(w, path, params, 'parent').status_code == 422
    broad = discover(w, path, params, 'pdf')
    assert broad.status_code == 200, broad.text
    records = broad.json()['diagrams']
    assert len(records) == 2 and all(r['state'] == 'candidate' and r['scope'] == 'pdf' for r in records)
    assert all(r['source_question_id'] is None and r['assigned_question_id'] == w.children[0] for r in records)
    assert all(r['crop_height'] < 400 and not r['ricoh_used'] for r in records)
    updates = edits(w) + [{'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include',
                          'diagram_records': [{**clean(records[0]), 'state': 'accepted'}]}]
    saved = w.client.put(w.base, json={'expected_revision': 1, 'entries': updates})
    assert saved.status_code == 200, saved.text
    assert w.client.get(path).json()['diagrams'][0]['state'] == 'accepted'
    assert w.client.post(w.base+'/confirm', json={'expected_revision': 2}).status_code == 200


@pytest.mark.parametrize('field,value', [('assigned_question_id', 'foreign-question'),
    ('source_question_id', 'foreign-owner'), ('source_sha256', '0'*64), ('scope', 'pdf'), ('id', 'diagram-'+'0'*24)])
def test_forged_assignment_rejected(shared, field, value):
    w = shared
    eid, path, params = target(w)
    record = discover(w, path, params, 'parent').json()['diagrams'][0]
    forged = {**clean(record), 'state': 'accepted', field: value}
    response = w.client.put(w.base, json={'expected_revision': 1,
        'entries': edits(w)+[{'id': eid, 'question_id': w.children[0], 'answer_text': '',
                             'disposition': 'include', 'diagram_records': [forged]}]})
    assert response.status_code == 422, response.text


def test_exact_exists_forbids_parent_and_pdf(workspace):
    w = workspace
    entry = w.answer['entries'][0]
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}/entries/{entry["id"]}/diagrams'
    response = w.client.post(base, json={'expected_revision': 1})
    assert response.status_code == 200 and response.json()['fallback'] is None
    for scope in ('parent', 'pdf'):
        assert w.client.post(base, params={'scope': scope}, json={'expected_revision': 1}).status_code == 422


@pytest.mark.parametrize('near_has_diagram', [True, False])
def test_nearest_parent_then_ancestor(shared, near_has_diagram):
    w = shared
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        near = DomainService(s).question(draft.test_id, question_number='3.near', display_label='(中)',
            sort_order=1, parent_id=w.parent, max_points=None, is_gradable=False)
        s.get(TestQuestion, w.children[0]).parent_id = near.id
        snap = deepcopy(draft.snapshot)
        snap['question_regions'].append({'question_id': near.id, 'page_index': 0,
            'left': 20, 'right': 250, 'top': 50 if near_has_diagram else 10,
            'bottom': 280 if near_has_diagram else 65, 'depth': 2})
        draft.snapshot = snap
        s.commit()
        owner = near.id if near_has_diagram else w.parent
    _, path, params = target(w)
    result = discover(w, path, params)
    assert result.json()['fallback']['source_question_id'] == owner
    record = discover(w, path, params, 'parent').json()['diagrams'][0]
    assert record['source_question_id'] == owner


def test_concurrent_parent_discovery_reuses_atomic_artifacts(shared):
    from concurrent.futures import ThreadPoolExecutor
    w = shared
    requests = [target(w, w.children[i % 2]) for i in range(8)]
    def run(item):
        _, path, params = item
        result = discover(w, path, params, 'parent')
        assert result.status_code == 200, result.text
        record = result.json()['diagrams'][0]
        assert w.client.get(record['preview_url']).status_code == 200
        return record
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(run, requests))
    assert len({r['id'] for r in records}) == len({r['crop_sha256'] for r in records}) == 1


def test_pdf_manual_expansion_cannot_swallow_another_diagram(shared):
    w = shared
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        draft.snapshot = {**draft.snapshot, 'question_regions': []}
        s.commit()
    _, path, params = target(w)
    record = discover(w, path, params, 'pdf').json()['diagrams'][0]
    response = w.client.post(path+f'/{record["id"]}/crop-preview', params={**params, 'scope': 'pdf'},
        json={'expected_revision': 1, 'final_bbox': [65, 75, 235, 465]})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'diagram_source_boundary'


def test_pdf_malformed_saved_bounds_are_structured_rejection(shared):
    w = shared
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        draft.snapshot = {**draft.snapshot, 'question_regions': []}
        s.commit()
    eid, path, params = target(w)
    record = discover(w, path, params, 'pdf').json()['diagrams'][0]
    record = {**clean(record), 'state': 'accepted', 'final_bbox': 'not-a-bbox'}
    result = w.client.put(w.base, json={'expected_revision': 1, 'entries': edits(w)+[{
        'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include', 'diagram_records': [record]}]})
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'diagram_invalid_bbox'


def test_foreign_material_provenance_is_not_relabelled(shared):
    w = shared
    eid, path, params = target(w)
    record = {**clean(discover(w, path, params, 'parent').json()['diagrams'][0]),
              'state': 'accepted', 'material_id': str(uuid4())}
    result = w.client.put(w.base, json={'expected_revision': 1, 'entries': edits(w)+[{
        'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include', 'diagram_records': [record]}]})
    assert result.status_code == 422 and result.json()['error']['code'] == 'diagram_source_stale'


def test_geometry_and_resume_never_invoke_vision(shared, monkeypatch):
    from scoring.diagram_review import DiagramReview
    def forbidden(*args, **kwargs):
        raise AssertionError('No vision on confident geometry, Save, resume or formal registration')
    monkeypatch.setattr(DiagramReview, 'discover', forbidden)
    w = shared
    eid, path, params = target(w)
    assert discover(w, path, params).json()['diagrams'] == []
    record = discover(w, path, params, 'parent').json()['diagrams'][0]
    result = w.client.put(w.base, json={'expected_revision': 1, 'entries': edits(w)+[{
        'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include',
        'diagram_records': [{**clean(record), 'state': 'accepted'}]}]})
    assert result.status_code == 200, result.text
    assert w.client.get(path).json()['diagrams'][0]['state'] == 'accepted'
    assert w.client.post(w.base+'/confirm', json={'expected_revision': 2}).status_code == 200


def test_parent_candidate_identity_stable_under_region_reorder(shared):
    w = shared
    _, path, params = target(w)
    before = discover(w, path, params, 'parent').json()['diagrams'][0]
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        snap = deepcopy(draft.snapshot)
        # A disjoint competing Question boundary is legitimate persisted data.
        snap['question_regions'].append({'question_id': w.children[1], 'page_index': 0,
            'left': 20, 'right': 250, 'top': 310, 'bottom': 470, 'depth': 2})
        draft.snapshot = snap
        s.commit()
    first = discover(w, path, params, 'parent').json()['diagrams'][0]
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        snap = deepcopy(draft.snapshot)
        snap['question_regions'].reverse()
        draft.snapshot = snap
        s.commit()
    second = discover(w, path, params, 'parent').json()['diagrams'][0]
    assert before['id'] == first['id'] == second['id']
    assert first['context_sha256'] == second['context_sha256']


@pytest.mark.parametrize('scope', ['exact', 'parent', 'pdf'])
def test_teacher_confirmed_detection_failure_save_resume_and_formal(shared, monkeypatch, scope):
    from scoring.diagram_regions import DiagramRegionExtractor
    from scoring.diagram_vision import RicohDiagramGrouping
    w = shared
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        snap = deepcopy(draft.snapshot)
        if scope == 'exact':
            snap['question_regions'][0]['question_id'] = w.children[0]
        elif scope == 'pdf':
            snap['question_regions'] = []
        draft.snapshot = snap
        s.commit()
    original = DiagramRegionExtractor.candidates
    calls = []
    def truncated(_self, _elements):
        calls.append(1)
        raise ValueError('diagram_ricoh_output_truncated')
    # Let the shared engine's real error handling preserve the source component.
    def detected(self, **kwargs):
        values = original(self, **{k: v for k, v in kwargs.items() if k != 'grouping'})
        for value in values:
            value.update(status='unresolved', reason_code='diagram_geometry_ambiguous')
            if kwargs.get('grouping'):
                try:
                    kwargs['grouping']([])
                except ValueError as exc:
                    value.update(reason_code=str(exc), ricoh_used=True)
        return values
    monkeypatch.setattr(DiagramRegionExtractor, 'candidates', detected)
    monkeypatch.setattr(RicohDiagramGrouping, '__call__', truncated)
    eid, path, params = target(w)
    response = discover(w, path, params, scope)
    assert response.status_code == 200, response.text
    record = response.json()['diagrams'][0]
    assert record['trust_state'] == 'teacher_confirmable'
    assert record['reason_code'] == 'diagram_ricoh_output_truncated'
    preview = w.client.post(path+f'/{record["id"]}/crop-preview', params={**params, 'scope': scope},
        json={'expected_revision': 1, 'final_bbox': [68, 78, 232, 242]})
    assert preview.status_code == 200, preview.text
    corrected = clean(preview.json())
    updates = edits(w)+[{'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include',
        'diagram_records': [{**corrected, 'state': 'accepted'}]}]
    assert w.client.put(w.base, json={'expected_revision': 1, 'entries': updates}).status_code == 422
    updates[-1]['diagram_records'][0]['teacher_confirmed'] = True
    saved = w.client.put(w.base, json={'expected_revision': 1, 'entries': updates})
    assert saved.status_code == 200, saved.text
    call_count = len(calls)
    restored = w.client.get(path).json()['diagrams'][0]
    assert restored['state'] == 'accepted' and restored['teacher_confirmed']
    assert restored['teacher_adjusted'] and restored['trust_state_at_accept'] == 'teacher_confirmable'
    result = w.client.post(w.base+'/confirm', json={'expected_revision': 2})
    assert result.status_code == 200, result.text
    answer = result.json()['model_answers'][0]
    assert answer['answer_text'] == ''
    assert answer['provenance_json']['diagrams'][0]['confirmation_reason_code'] == 'diagram_ricoh_output_truncated'
    assert len(calls) == call_count
