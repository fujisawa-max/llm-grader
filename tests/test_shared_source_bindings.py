from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from tests.test_diagram_review_api import workspace as source_workspace
from tests.test_authoring_diagrams import begin, save
from scoring.authoring_sources import merge_answer_analysis

workspace = source_workspace


def test_existing_source_roles_share_bytes_and_protect_duplicate_and_foreign(workspace):
    w = workspace
    base = f'/api/v1/tests/{w.answer["test_id"]}/materials'
    before = w.client.get(base).json()
    answer = next(m for m in before if m['id'] == w.answer['material_id'])
    files = set(w.root.rglob('*.pdf'))
    with patch('scoring.source_registration.inspect_source') as extraction:
        result = w.client.post(base+f'/{answer["id"]}/reuse', json={'material_type': 'rubric_source'})
    assert result.status_code == 201, result.text
    extraction.assert_not_called()
    rubric = result.json()
    assert rubric['id'] != answer['id']
    assert rubric['storage_ref'] == answer['storage_ref']
    assert rubric['sha256'] == answer['sha256']
    assert set(w.root.rglob('*.pdf')) == files
    assert w.client.post(base+f'/{answer["id"]}/reuse', json={'material_type': 'rubric_source'}).json()['id'] == rubric['id']
    assert len(w.client.get(base).json()) == len(before)+1
    foreign = w.client.post(f'/api/v1/tests/{w.data["test_id"]}/materials/{answer["id"]}/reuse',
        json={'material_type': 'rubric_source'})
    assert foreign.status_code == 422
    Path(answer['storage_ref']).write_bytes(b'changed')
    assert w.client.post(base+f'/{answer["id"]}/reuse', json={'material_type': 'question_sheet'}).status_code == 422


def test_delete_and_role_change_only_remove_role_binding(workspace):
    w = workspace
    base = f'/api/v1/tests/{w.answer["test_id"]}/materials'
    answer = next(m for m in w.client.get(base).json() if m['id'] == w.answer['material_id'])
    rubric = w.client.post(base+f'/{answer["id"]}/reuse', json={'material_type': 'rubric_source'}).json()
    source_path = Path(answer['storage_ref'])
    assert source_path.exists()
    changed = w.client.patch(base+f'/{rubric["id"]}/role', json={'material_type': 'question_sheet'})
    assert changed.status_code == 200, changed.text
    question_binding = changed.json()
    assert question_binding['id'] != rubric['id']
    assert question_binding['sha256'] == answer['sha256']
    assert question_binding['storage_ref'] == answer['storage_ref']
    visible = w.client.get(base).json()
    assert {m['id'] for m in visible} >= {answer['id'], question_binding['id']}
    assert rubric['id'] not in {m['id'] for m in visible}
    assert source_path.exists()
    duplicate = w.client.patch(base+f'/{answer["id"]}/role', json={'material_type': 'question_sheet'})
    assert duplicate.status_code == 409
    deleted = w.client.delete(base+f'/{question_binding["id"]}')
    assert deleted.status_code == 200
    assert w.client.get(base+f'/{question_binding["id"]}/file').status_code == 404
    assert answer['id'] in {m['id'] for m in w.client.get(base).json()}
    assert source_path.exists()


def test_resume_projects_latest_answer_and_rubric_imports_into_separate_domains(workspace):
    from scoring.db.models import ModelAnswerImportDraft, TestMaterial
    from uuid import uuid4
    w = workspace
    test_id = w.answer['test_id']
    path = f'/api/v1/tests/{test_id}/materials'
    rubric_binding = w.client.post(path+f'/{w.answer["material_id"]}/reuse',
        json={'material_type': 'rubric_source'}).json()
    entry = deepcopy(w.answer['entries'][0])
    entry['answer_text'] = 'rubric-like text must not become an Answer'
    entry['rubric_edits'] = [{'id': 'rubric-resume', 'description': 'Explicit rubric criterion', 'points': 4,
                              'segment_ids': [], 'provenance': {'source': 'teacher'}}]
    entry['semantic_classification'] = {'status': 'teacher_reviewed', 'segments': [
        {'id': 'rubric-segment-resume', 'category': 'rubric', 'text': 'Explicit rubric criterion'}],
        'rubric_groups': []}
    with w.sf() as session:
        original_draft = session.get(ModelAnswerImportDraft, w.answer['id'])
        material = session.get(TestMaterial, rubric_binding['id'])
        session.add(ModelAnswerImportDraft(id=str(uuid4()), test_id=test_id, material_id=material.id,
            source_sha256=material.sha256, artifact_ref=original_draft.artifact_ref, revision=1,
            snapshot={'entries': [entry], 'question_regions': original_draft.snapshot.get('question_regions', [])}))
        session.commit()
    # A fresh authoring projection must select one revision per material role.
    resumed = w.client.post(f'/api/v1/tests/{test_id}/authoring/revisions')
    assert resumed.status_code == 200, resumed.text
    snapshot = resumed.json()['snapshot']
    key = snapshot['nodes'][0]['stable_key']
    assert snapshot['answers'][key]['primary'] == w.answer['entries'][0]['answer_text']
    assert snapshot['rubrics'][key][0]['description'] == 'Explicit rubric criterion'
    roles = {source['material_id']: source['material_role']
             for source in snapshot['domains']['answer']['sources'].values()}
    assert roles[w.answer['material_id']] == 'model_answer_source'
    assert roles[rubric_binding['id']] == 'rubric_source'


def test_shared_roles_merge_independently_and_replacement_is_binding_local(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    original = snapshot['nodes']
    key = original[0]['stable_key']
    snapshot['answers'][key] = {'primary': 'Teacher answer', 'alternatives': [], 'diagram_records': []}
    snapshot['rubrics'][key] = [{'id': 'teacher-rubric', 'description': 'Teacher criterion', 'points': 7}]
    entry = deepcopy(w.answer['entries'][0])
    entry['question_id'] = key
    entry['answer_text'] = 'New source answer'
    entry['rubric_edits'] = [{'id': 'new-rubric', 'description': 'New criterion', 'points': 8,
        'segment_ids': [], 'provenance': {'source': 'teacher_manual'}}]
    draft = SimpleNamespace(id='new-answer-draft', revision=1, material_id=w.answer['material_id'],
        source_sha256=w.answer['source_sha256'], artifact_ref=row['snapshot']['domains']['answer']['artifact_ref'],
        snapshot={'entries': [entry], 'question_regions': []})
    merge_answer_analysis(snapshot, draft, 'model_answer_source')
    assert snapshot['rubrics'][key][0]['description'] == 'Teacher criterion'
    answer_outcome = deepcopy(snapshot['domains']['answer']['analysis_results']['model_answer_source'])
    answer_before = deepcopy(snapshot['answers'])
    draft.id, draft.material_id = 'rubric-draft', 'rubric-binding'
    merge_answer_analysis(snapshot, draft, 'rubric_source')
    assert snapshot['answers'] == answer_before
    assert snapshot['rubrics'][key][0]['description'] == 'New criterion'
    assert snapshot['domains']['answer']['analysis_results']['model_answer_source'] == answer_outcome
    assert 'rubric_source' in snapshot['domains']['answer']['analysis_results']
    assert snapshot['nodes'] == original
    rubric_before = deepcopy(snapshot['rubrics'])
    draft.id, draft.material_id = 'answer-again', w.answer['material_id']
    merge_answer_analysis(snapshot, draft, 'model_answer_source')
    assert snapshot['rubrics'] == rubric_before

    base = f'/api/v1/tests/{w.answer["test_id"]}/materials'
    rubric = w.client.post(base+f'/{w.answer["material_id"]}/reuse', json={'material_type': 'rubric_source'}).json()
    source = next(m for m in w.client.get(base).json() if m['id'] == w.answer['material_id'])
    value = deepcopy(row['snapshot'])
    value['materials'].append({'id': rubric['id'], 'role': 'rubric_source', 'sha256': rubric['sha256']})
    row = save(w, path, row, value)
    assert row['analysis_readiness'][rubric['id']]['analyzed'] is False
    value = deepcopy(row['snapshot'])
    # A new Answer binding replaces only the old Answer ID, never the shared SHA.
    uploaded = w.client.post(base+'/upload', content=Path(source['storage_ref']).read_bytes()+b'\n',
        headers={'Content-Type': 'application/pdf', 'X-Source-Role': 'model_answer_source', 'X-Filename': 'v2.pdf'})
    assert uploaded.status_code == 201, uploaded.text
    replacement = uploaded.json()
    value['materials'].append({'id': replacement['id'], 'role': 'model_answer_source',
        'sha256': replacement['sha256'], 'replaces_material_id': source['id']})
    row = save(w, path, row, value)
    assert w.client.get(base+f'/{rubric["id"]}/file').status_code == 200
    assert next(m for m in row['snapshot']['materials'] if m['id'] == rubric['id'])['sha256'] == source['sha256']


def test_same_material_reanalysis_retains_verified_diagram_context(workspace):
    w = workspace
    _, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    domain = snapshot['domains']['answer']
    entry = domain['entries'][0]
    record = {'state': 'accepted', 'crop_sha256': 'verified-crop', 'artifact_ref': 'crop.png'}
    entry['diagram_records'] = [record]
    old_id = domain['draft_id']
    draft = SimpleNamespace(id='reanalyzed-draft', revision=2, material_id=domain['material_id'],
        source_sha256=domain['source_sha256'], artifact_ref=domain['artifact_ref'],
        snapshot={'entries': [], 'question_regions': []})
    before = deepcopy(snapshot['nodes'])
    merge_answer_analysis(snapshot, draft, 'model_answer_source')
    retained = snapshot['domains']['answer']['entries'][0]
    assert retained['source_draft_id'] == old_id
    assert retained['diagram_records'] == [record]
    assert retained['semantic_classification'] is None
    assert snapshot['domains']['answer']['sources'][old_id]['material_id'] == draft.material_id
    assert snapshot['nodes'] == before
    # Explicit import of the same native candidate must not duplicate its ID.
    collision = deepcopy(snapshot)
    draft.snapshot['entries'] = [deepcopy(retained)]
    merge_answer_analysis(collision, draft, 'model_answer_source')
    assert len(collision['domains']['answer']['entries']) == 1
    assert collision['domains']['answer']['entries'][0]['diagram_records'] == [record]
    draft.snapshot['entries'] = []
    # A different SHA cannot retain old verified geometry as current-source state.
    draft.id, draft.source_sha256 = 'replacement-draft', 'different-sha'
    merge_answer_analysis(snapshot, draft, 'model_answer_source')
    assert snapshot['domains']['answer']['entries'] == []
