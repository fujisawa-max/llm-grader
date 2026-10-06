"""Reuse is explicit, same-Test/tree, source-backed and inference-free."""
from copy import deepcopy

import pytest

from scoring.db.models import ModelAnswerImportDraft, TestQuestion
from scoring.diagram_regions import DiagramRegionExtractor
from tests.test_model_answer_diagram_scopes import (
    workspace as _workspace_fixture, shared as _shared_fixture, target, discover, edits, clean,
)


@pytest.fixture
def shared(tmp_path, monkeypatch, request):
    for w in _workspace_fixture.__wrapped__(tmp_path, monkeypatch, request):
        yield _shared_fixture.__wrapped__(w)


def payload(w):
    return [{k: e[k] for k in ('id', 'question_id', 'answer_text', 'disposition', 'diagram_records') if k in e}
            for e in w.answer['entries']]


def save_origin(w, state='accepted'):
    eid, path, params = target(w)
    record = discover(w, path, params, 'parent').json()['diagrams'][0]
    corrected = w.client.post(path+f'/{record["id"]}/crop-preview', params={**params, 'scope': 'parent'},
        json={'expected_revision': 1, 'final_bbox': [68, 78, 232, 242]}).json()
    entries = edits(w)+[{'id': eid, 'question_id': w.children[0], 'answer_text': '', 'disposition': 'include',
        'diagram_records': [{**clean(corrected), 'state': state}]}]
    saved = w.client.put(w.base, json={'expected_revision': 1, 'entries': entries})
    assert saved.status_code == 200, saved.text
    w.answer = saved.json()
    return eid, w.answer['entries'][-1]['diagram_records'][0]


def reusable(w, qid=None):
    eid, path, params = target(w, qid or w.children[1])
    response = w.client.get(path, params={**params, 'scope': 'reuse'})
    assert response.status_code == 200, response.text
    return eid, path, params, response.json()['reusable_diagrams']


def no_discovery(monkeypatch):
    monkeypatch.setattr(DiagramRegionExtractor, 'candidates', lambda *a, **k: pytest.fail('geometry regrouping'))
    monkeypatch.setattr('scoring.diagram_vision.RicohDiagramGrouping.__call__', lambda *a, **k: pytest.fail('Ricoh'))
    monkeypatch.setattr('scoring.adapters.pdf_region.PyMuPdfRegionRenderer.render', lambda *a, **k: pytest.fail('crop rerender'))


def test_reuse_preview_save_and_formal_are_cached_and_independent(shared, monkeypatch):
    w = shared
    origin_id, origin = save_origin(w)
    no_discovery(monkeypatch)
    eid, path, params, values = reusable(w)
    assert len(values) == 1
    record = values[0]
    assert record['scope'] == 'reuse' and record['state'] == 'candidate'
    assert record['source_question_id'] == w.parent and record['assigned_question_id'] == w.children[1]
    assert record['reused_from_entry_id'] == origin_id and record['reused_from_question_id'] == w.children[0]
    assert record['crop_sha256'] == origin['crop_sha256'] and record['artifact_ref'] == origin['artifact_ref']
    assert record['final_bbox'] == [68, 78, 232, 242]
    assert w.client.get(record['preview_url']).status_code == 200
    entries = payload(w)+[{'id': eid, 'question_id': w.children[1], 'answer_text': '', 'disposition': 'include',
        'diagram_records': [{**clean(record), 'state': 'accepted'}]}]
    result = w.client.put(w.base, json={'expected_revision': 2, 'entries': entries})
    assert result.status_code == 200, result.text
    w.answer = result.json()
    restored = w.client.get(path).json()['diagrams'][0]
    assert restored['state'] == 'accepted' and restored['acceptance_method'] == 'reused_confirmed_diagram'
    assert restored['crop_sha256'] == origin['crop_sha256']
    # A source assignment can be excluded without excluding its saved reuse.
    entries = payload(w)
    entries[-2]['disposition'] = 'excluded'
    entries[-2]['diagram_records'][0]['state'] = 'excluded'
    changed = w.client.put(w.base, json={'expected_revision': 3, 'entries': entries})
    assert changed.status_code == 200, changed.text
    assert w.client.get(path).json()['diagrams'][0]['state'] == 'accepted'
    result = w.client.post(w.base+'/confirm', json={'expected_revision': 4})
    assert result.status_code == 200, result.text
    formal = result.json()['model_answers'][0]
    assert formal['answer_text'] == ''
    assert formal['question_id'] == w.children[1]
    assert formal['provenance_json']['diagrams'][0]['acceptance_method'] == 'reused_confirmed_diagram'


@pytest.mark.parametrize('state', ['candidate', 'excluded'])
def test_unaccepted_or_excluded_not_offered(shared, state):
    save_origin(shared, state)
    assert reusable(shared)[3] == []


@pytest.mark.parametrize('field,value', [('source_sha256', '0'*64), ('trust_state', 'hard_invalid'),
    ('id', 'diagram-'+'0'*24), ('context_sha256', '0'*64)])
def test_stale_or_invalid_saved_sources_not_offered(shared, field, value):
    w = shared
    save_origin(w)
    with w.sf() as s:
        draft = s.get(ModelAnswerImportDraft, w.answer['id'])
        snap = deepcopy(draft.snapshot)
        snap['entries'][-1]['diagram_records'][0][field] = value
        draft.snapshot = snap
        s.commit()
    assert reusable(w)[3] == []


def test_missing_artifact_not_offered(shared):
    w = shared
    _, record = save_origin(w)
    candidates = list(w.root.rglob(record['crop_sha256']+'.png'))
    # Artifact names are geometry hashes, not crop hashes.
    for manifest in w.root.rglob('document-ir.json'):
        artifact = manifest.parent / record['artifact_ref']
        if artifact.is_file():
            artifact.unlink()
    assert not candidates
    assert reusable(w)[3] == []


@pytest.mark.parametrize('field,value', [('assigned_question_id', 'foreign'), ('source_question_id', 'foreign'),
    ('source_sha256', '0'*64), ('reuse_ref', '0'*64), ('id', 'diagram-'+'0'*24),
    ('reused_from_entry_id', 'foreign-entry')])
def test_forged_assignment_or_reference_is_rejected(shared, field, value):
    w = shared
    save_origin(w)
    eid, _, _, records = reusable(w)
    record = clean(records[0])
    record.update(state='accepted', teacher_confirmed=True)
    record[field] = value
    entries = payload(w)+[{'id': eid, 'question_id': w.children[1], 'answer_text': '',
        'disposition': 'include', 'diagram_records': [record]}]
    response = w.client.put(w.base, json={'expected_revision': 2, 'entries': entries})
    assert response.status_code == 422, response.text


def test_other_major_question_excluded_even_with_same_label(shared):
    w = shared
    save_origin(w)
    with w.sf() as s:
        child = s.get(TestQuestion, w.children[1])
        child.parent_id = None
        child.display_label = '問題3'
        s.commit()
    assert reusable(w)[3] == []


def test_client_cannot_use_other_draft_attestation(shared):
    w = shared
    save_origin(w)
    eid, path, params, values = reusable(w)
    original = values[0]
    with w.sf() as s:
        row = s.get(ModelAnswerImportDraft, w.answer['id'])
        other = ModelAnswerImportDraft(id='another-draft', test_id=row.test_id, material_id=row.material_id,
            source_sha256=row.source_sha256, artifact_ref=row.artifact_ref, state='editing', revision=1,
            snapshot={'entries': [], 'question_regions': row.snapshot['question_regions']})
        s.add(other)
        s.commit()
    foreign_path = path.replace(w.answer['id'], 'another-draft')
    response = w.client.get(foreign_path+f'/{original["id"]}/crop', params={**params,
        'scope': 'reuse', 'reuse_ref': original['reuse_ref'], 'crop_sha': original['crop_sha256']})
    assert response.status_code == 422


def test_reused_corrected_assignment_becomes_independent_source(shared, monkeypatch):
    w = shared
    save_origin(w)
    eid, path, params, values = reusable(w)
    candidate = values[0]
    corrected = w.client.post(path+f'/{candidate["id"]}/crop-preview',
        params={**params, 'scope': 'reuse', 'reuse_ref': candidate['reuse_ref']},
        json={'expected_revision': 2, 'final_bbox': [70, 80, 230, 240]})
    assert corrected.status_code == 200, corrected.text
    entries = payload(w)+[{'id': eid, 'question_id': w.children[1], 'answer_text': '',
        'disposition': 'include', 'diagram_records': [{**clean(corrected.json()), 'state': 'accepted'}]}]
    saved = w.client.put(w.base, json={'expected_revision': 2, 'entries': entries})
    assert saved.status_code == 200, saved.text
    w.answer = saved.json()
    # Exclude the first assignment; B still offers its own corrected crop to C.
    entries = payload(w)
    entries[-2]['disposition'] = 'excluded'
    saved = w.client.put(w.base, json={'expected_revision': 3, 'entries': entries})
    assert saved.status_code == 200, saved.text
    w.answer = saved.json()
    no_discovery(monkeypatch)
    _, _, _, values = reusable(w, w.children[0])
    assert len(values) == 1
    assert values[0]['reused_from_question_id'] == w.children[1]
    assert values[0]['source_question_id'] == w.parent
    assert values[0]['final_bbox'] == [70, 80, 230, 240]
    assert values[0]['crop_sha256'] != candidate['crop_sha256']


def test_teacher_confirmed_legacy_source_reuses_without_inference(shared, monkeypatch):
    import json
    w = shared
    _, original = save_origin(w)
    cached = next(w.root.rglob(original['context_sha256']+'.json'))
    value = json.loads(cached.read_text())
    value.pop('context_candidates', None)  # Existing 10d cache compatibility.
    value['candidates'][0].update(status='unresolved', reason_code='diagram_ricoh_output_truncated',
        ricoh_used=True, ricoh_finish_reason='length')
    cached.write_text(json.dumps(value))
    entries = payload(w)
    entries[-1]['diagram_records'][0]['teacher_confirmed'] = True
    saved = w.client.put(w.base, json={'expected_revision': 2, 'entries': entries})
    assert saved.status_code == 200, saved.text
    w.answer = saved.json()
    no_discovery(monkeypatch)
    eid, _, _, values = reusable(w)
    assert values[0]['source_teacher_confirmed'] is True
    assert values[0]['source_confirmation_reason_code'] == 'diagram_ricoh_output_truncated'
    # Explicit reuse confirmation still belongs to the new child assignment.
    entries = payload(w)+[{'id': eid, 'question_id': w.children[1], 'answer_text': '',
        'disposition': 'include', 'diagram_records': [{**clean(values[0]), 'state': 'accepted',
            'teacher_confirmed': True}]}]
    saved = w.client.put(w.base, json={'expected_revision': 3, 'entries': entries})
    assert saved.status_code == 200, saved.text
    assert saved.json()['entries'][-1]['diagram_records'][0]['teacher_confirmed']


def test_old_offer_cannot_create_new_assignment_after_source_excluded(shared):
    w = shared
    save_origin(w)
    eid, _, _, values = reusable(w)
    offer = clean(values[0])
    entries = payload(w)
    entries[-1]['disposition'] = 'excluded'
    saved = w.client.put(w.base, json={'expected_revision': 2, 'entries': entries})
    assert saved.status_code == 200, saved.text
    w.answer = saved.json()
    entries = payload(w)+[{'id': eid, 'question_id': w.children[1], 'answer_text': '',
        'disposition': 'include', 'diagram_records': [{**offer, 'state': 'accepted'}]}]
    response = w.client.put(w.base, json={'expected_revision': 3, 'entries': entries})
    assert response.status_code == 422, response.text
