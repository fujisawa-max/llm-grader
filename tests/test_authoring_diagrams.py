from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch

from tests.test_diagram_review_api import workspace as source_workspace, clean

workspace = source_workspace


def begin(w, test_id):
    path = f'/api/v1/tests/{test_id}/authoring'
    response = w.client.post(path+'/revisions')
    assert response.status_code == 200, response.text
    return path, response.json()


def save(w, path, row, snapshot):
    result = w.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert result.status_code == 200, result.text
    return result.json()


def manual(key):
    return {'id': f'teacher-entry-{uuid4()}', 'authoring_question_key': key, 'question_id': None,
        'disposition': 'include', 'answer_kind': 'primary', 'mapping_state': 'manual_mapped', 'answer_text': '',
        'source': {'kind': 'teacher_manual', 'material_id': None, 'source_sha256': None, 'segments': []}}


def test_question_diagram_preview_decision_roundtrip_no_legacy_mutation(workspace):
    w = workspace
    path, row = begin(w, w.data['test_id'])
    endpoint = path+'/nodes/q1/diagrams'
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version']})
    assert result.status_code == 200, result.text
    record = result.json()['diagrams'][0]
    assert record['automatic_bbox'] == [70, 80, 230, 240]
    assert w.client.get(record['preview_url']).status_code == 200
    snapshot = deepcopy(row['snapshot'])
    snapshot['nodes'][0]['diagram_records'] = [{**clean(record), 'state': 'accepted'}]
    saved = save(w, path, row, snapshot)
    assert saved['snapshot']['nodes'][0]['diagram_records'][0]['state'] == 'accepted'
    assert w.client.get(path).json()['revision'] == saved
    assert w.client.get(f'/api/v1/question-import-reviews/{w.data["id"]}').json() == w.data


def test_answer_draft_precedence_and_manual_diagram_roundtrip(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    bound = row['snapshot']['domains']['answer']
    assert bound['draft_id'] == w.answer['id']
    assert len(bound['entries']) == len(w.answer['entries'])
    key = row['snapshot']['nodes'][0]['stable_key']
    entry = manual(key)
    endpoint = path+f'/entries/{entry["id"]}/diagrams?question_id={key}'
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version']})
    assert result.status_code == 200, result.text
    record = result.json()['diagrams'][0]
    assert record['domain'] == 'model_answer'
    snapshot = deepcopy(row['snapshot'])
    for old in snapshot['domains']['answer']['entries']:
        if old['authoring_question_key'] == key:
            old['disposition'] = 'ignored'
    entry['diagram_records'] = [{**clean(record), 'state': 'accepted'}]
    snapshot['domains']['answer']['entries'].append(entry)
    saved = save(w, path, row, snapshot)
    assert saved['snapshot']['answers'][key]['primary'] == ''
    assert saved['snapshot']['answers'][key]['diagram_records'][0]['state'] == 'accepted'
    assert w.client.get(path).json()['revision'] == saved
    assert w.client.get(f'/api/v1/model-answer-import-drafts/{w.answer["id"]}').json() == w.answer
    assert not any(i['question_key'] == key and i['section'] == 'answer' for i in w.client.get(path+'/review').json()['issues'])


def test_split_children_share_confirmed_parent_diagram_without_formal_ids(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    parent = snapshot['nodes'][0]
    parent['score_semantics'], parent['score_points'] = 'sum_children', None
    children = []
    for index in range(2):
        child = deepcopy(parent)
        child.update(stable_key=f'teacher-{uuid4()}', review_node_id=str(uuid4()), parent_key=parent['stable_key'],
            node_type='subquestion', depth=1, sort_order=index, score_semantics='direct', score_points=5,
            label={'raw': f'({index+1})', 'normalized': f'({index+1})'})
        children.append(child)
    snapshot['nodes'].extend(children)
    first, second = [manual(c['stable_key']) for c in children]
    snapshot['domains']['answer']['entries'].extend([first, second])
    row = save(w, path, row, snapshot)
    endpoint = path+f'/entries/{first["id"]}/diagrams?question_id={children[0]["stable_key"]}'
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version']})
    assert result.status_code == 200, result.text
    assert result.json()['diagrams'] == []
    assert result.json()['fallback']['scope'] == 'parent'
    result = w.client.post(endpoint+'&scope=parent', json={'expected_revision': row['edit_version']})
    assert result.status_code == 200, result.text
    source = result.json()['diagrams'][0]
    snapshot = deepcopy(row['snapshot'])
    next(e for e in snapshot['domains']['answer']['entries'] if e['id'] == first['id'])['diagram_records'] = [{**clean(source), 'state': 'accepted'}]
    row = save(w, path, row, snapshot)
    with patch('scoring.diagram_regions.DiagramRegionExtractor.candidates') as discovery:
        result = w.client.get(path+f'/entries/{second["id"]}/diagrams?question_id={children[1]["stable_key"]}&scope=reuse')
    assert result.status_code == 200, result.text
    discovery.assert_not_called()
    reused = result.json()['reusable_diagrams'][0]
    assert reused['crop_sha256'] == source['crop_sha256']
    assert reused['source_question_id'] == parent['stable_key']
    assert reused['assigned_question_id'] == children[1]['stable_key']
    snapshot = deepcopy(row['snapshot'])
    next(e for e in snapshot['domains']['answer']['entries'] if e['id'] == second['id'])['diagram_records'] = [{**clean(reused), 'state': 'accepted'}]
    row = save(w, path, row, snapshot)
    assert w.client.get(path).json()['revision'] == row
    assert len(w.client.get(f'/api/v1/tests/{w.answer["test_id"]}/questions').json()) == 2

    # The latest import can be a Rubric over the same PDF. New manual Answer
    # entries must still bind to the Answer source, not the latest Rubric draft.
    material_base = f'/api/v1/tests/{w.answer["test_id"]}/materials'
    rubric = w.client.post(material_base+f'/{w.answer["material_id"]}/reuse',
        json={'material_type': 'rubric_source'})
    assert rubric.status_code == 201, rubric.text
    result = w.client.post(path+'/analyze-answer', json={'material_id': rubric.json()['id'],
        'expected_edit_version': row['edit_version']})
    assert result.status_code == 200, result.text
    row = result.json()
    fresh = manual(children[1]['stable_key'])
    with patch('scoring.diagram_regions.DiagramRegionExtractor.candidates') as discovery:
        result = w.client.get(path+f'/entries/{fresh["id"]}/diagrams?question_id={children[1]["stable_key"]}&scope=reuse')
    assert result.status_code == 200, result.text
    discovery.assert_not_called()
    assert result.json()['reusable_diagrams'][0]['crop_sha256'] == source['crop_sha256']
    fresh['source_draft_id'] = w.answer['id']
    fresh['diagram_records'] = [{**clean(result.json()['reusable_diagrams'][0]), 'state': 'accepted'}]
    value = deepcopy(row['snapshot'])
    value['domains']['answer']['entries'].append(fresh)
    row = save(w, path, row, value)
    assert w.client.get(path).json()['revision'] == row


def test_explicit_analysis_uses_working_questions_without_formal_publication(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    formal = w.client.get(f'/api/v1/tests/{w.answer["test_id"]}/questions').json()
    result = w.client.post(path+'/analyze-answer', json={'material_id': w.answer['material_id'],
        'expected_edit_version': row['edit_version']})
    assert result.status_code == 200, result.text
    analyzed = result.json()
    assert analyzed['state'] == 'draft'
    assert analyzed['snapshot']['nodes'] == row['snapshot']['nodes']
    assert analyzed['snapshot']['domains']['answer']['draft_id'] != w.answer['id']
    assert w.client.get(f'/api/v1/tests/{w.answer["test_id"]}/questions').json() == formal
    bound = analyzed['snapshot']['domains']['answer']
    blocked = w.client.post(f'/api/v1/model-answer-import-drafts/{bound["draft_id"]}/confirm',
        json={'expected_revision': 1, 'entry_ids': []})
    assert blocked.status_code in {409, 422}
    assert w.client.get(path).json()['external_source_change'] is False


def test_browser_number_roundtrip_preserves_native_diagram_context(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    key = row['snapshot']['nodes'][0]['stable_key']
    entry = manual(key)
    result = w.client.post(path+f'/entries/{entry["id"]}/diagrams?question_id={key}',
        json={'expected_revision': row['edit_version']})
    assert result.status_code == 200
    entry['diagram_records'] = [{**clean(result.json()['diagrams'][0]), 'state': 'accepted'}]
    snapshot = deepcopy(row['snapshot'])
    snapshot['domains']['answer']['entries'].append(entry)

    def browser_numbers(value):
        if isinstance(value, dict):
            return {k: browser_numbers(v) for k, v in value.items()}
        if isinstance(value, list):
            return [browser_numbers(v) for v in value]
        return int(value) if isinstance(value, float) and value.is_integer() else value

    saved = save(w, path, row, browser_numbers(snapshot))
    assert saved['snapshot']['domains']['answer']['question_regions'] == row['snapshot']['domains']['answer']['question_regions']
    assert saved['snapshot']['domains']['answer']['entries'][-1]['diagram_records'][0]['state'] == 'accepted'


def test_foreign_diagram_and_source_context_cannot_be_forged(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    snapshot['domains']['answer']['question_regions'][0]['left'] += 1
    result = w.client.put(path, json={'snapshot': snapshot, 'expected_edit_version': row['edit_version']})
    assert result.status_code == 409
    assert w.client.get(path).json()['revision'] == row
    other_path, other = begin(w, w.data['test_id'])
    candidate = w.client.post(other_path+'/nodes/q1/diagrams', json={'expected_revision': other['edit_version']}).json()['diagrams'][0]
    snapshot = deepcopy(row['snapshot'])
    key = snapshot['nodes'][0]['stable_key']
    entry = manual(key)
    entry['diagram_records'] = [{**clean(candidate), 'state': 'accepted', 'teacher_confirmed': True}]
    snapshot['domains']['answer']['entries'].append(entry)
    result = w.client.put(path, json={'snapshot': snapshot, 'expected_edit_version': row['edit_version']})
    assert result.status_code == 409
    assert w.client.get(path).json()['revision'] == row


def test_local_review_and_alternative_edits_do_not_save_or_publish(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    key = snapshot['nodes'][0]['stable_key']
    entry = manual(key)
    entry['answer_text'] = '教師の解答'
    entry['manual_alternative_answers'] = [{'id': f'teacher-alternative-{uuid4()}', 'text': '別解'}]
    snapshot['domains']['answer']['entries'].append(entry)
    result = w.client.post(path+'/review', json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert result.status_code == 200, result.text
    assert w.client.get(path).json()['revision'] == row
    saved = save(w, path, row, snapshot)
    assert '別解' in saved['snapshot']['answers'][key]['alternatives']


def test_split_preserves_saved_diagram_as_unassigned_not_child_ownership(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    key = snapshot['nodes'][0]['stable_key']
    entry = manual(key)
    found = w.client.post(path+f'/entries/{entry["id"]}/diagrams?question_id={key}',
        json={'expected_revision': row['edit_version']})
    assert found.status_code == 200, found.text
    entry['diagram_records'] = [{**clean(found.json()['diagrams'][0]), 'state': 'accepted'}]
    snapshot['domains']['answer']['entries'].append(entry)
    row = save(w, path, row, snapshot)
    snapshot = deepcopy(row['snapshot'])
    parent = snapshot['nodes'][0]
    parent.update(score_semantics='sum_children', score_points=None)
    child = deepcopy(parent)
    child.update(stable_key=f'teacher-{uuid4()}', review_node_id=str(uuid4()),
        parent_key=key, depth=1, sort_order=0, node_type='subquestion', score_semantics='direct', score_points=10)
    snapshot['nodes'].append(child)
    row = save(w, path, row, snapshot)
    persisted = next(e for e in row['snapshot']['domains']['answer']['entries'] if e['id'] == entry['id'])
    assert persisted['authoring_question_key'] is None
    assert persisted['disposition'] == 'unassigned'
    record = persisted['diagram_records'][0]
    assert record['state'] == 'candidate'
    assert record['trust_state'] == 'hard_invalid'
    assert record['crop_sha256'] == entry['diagram_records'][0]['crop_sha256']
    assert row['snapshot']['answers'][key]['diagram_records'] == []
    assert w.client.get(f'/api/v1/model-answer-import-drafts/{w.answer["id"]}').json() == w.answer


def test_manual_rubric_consolidation_uses_current_criteria_without_saving(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    entry = manual(row['snapshot']['nodes'][0]['stable_key'])
    response = w.client.post(path+f'/entries/{entry["id"]}/rubric-consolidate', json={
        'expected_revision': row['edit_version'], 'criteria': [
            {'id': f'teacher-rubric-{uuid4()}', 'description': 'teacher criterion', 'points': 5}]})
    assert response.status_code == 200, response.text
    assert response.json()['groups'][0]['points'] == 5
    assert 'teacher criterion' in response.json()['groups'][0]['description']
    assert w.client.get(path).json()['revision'] == row
    assert w.client.get(f'/api/v1/model-answer-import-drafts/{w.answer["id"]}').json() == w.answer


def test_answer_only_draft_keeps_approved_formal_rubric_fallback(workspace):
    from sqlalchemy import select
    from scoring.domain import DomainService
    from scoring.db.models import User
    w = workspace
    question_id = w.answer['entries'][0]['question_id']
    with w.sf() as session:
        service = DomainService(session)
        rubric = service.rubric(w.answer['test_id'], {'questions': [{'question_id': identifier,
            'max_points': 10, 'criteria': [{'id': 'approved-c1', 'description': 'approved fallback', 'points': 10}]}
            for identifier in {e['question_id'] for e in w.answer['entries']}]})
        service.approve_rubric(rubric.id, session.scalar(select(User).where(User.role == 'teacher')).id)
        session.commit()
    path, row = begin(w, w.answer['test_id'])
    key = next(e['authoring_question_key'] for e in row['snapshot']['domains']['answer']['entries'] if e['question_id'] == question_id)
    assert row['snapshot']['rubrics'][key][0]['description'] == 'approved fallback'
    snapshot = deepcopy(row['snapshot'])
    snapshot['rubrics'][key][0]['description'] = 'edited fallback, still draft'
    row = save(w, path, row, snapshot)
    assert row['snapshot']['rubrics'][key][0]['description'] == 'edited fallback, still draft'


def test_replaced_answer_source_keeps_evidence_but_rejects_diagram_operations(workspace):
    from scoring.db.models import TestMaterial
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    bound = snapshot['domains']['answer']
    with w.sf() as session:
        new = TestMaterial(test_id=w.answer['test_id'], material_type='model_answer_source', original_filename='replacement.pdf', storage_ref='replacement.pdf', sha256='b'*64)
        session.add(new)
        session.flush()
        snapshot['materials'].append({'id': new.id, 'role': new.material_type, 'sha256': new.sha256, 'replaces_material_id': bound['material_id']})
        session.commit()
    result = save(w, path, row, snapshot)
    assert result['snapshot']['domains']['answer'] == bound
    assert {'domain': 'answer', 'code': 'authoring_material_replaced'} in w.client.get(path).json()['source_problems']
    entry = bound['entries'][0]
    assert w.client.get(path+f'/entries/{entry["id"]}/diagrams').status_code == 409


def test_reanalysis_retains_prior_working_copy_and_rejects_old_edit_version(workspace):
    from scoring.db.models import TestAuthoringRevision
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    before = deepcopy(row['snapshot'])
    result = w.client.post(path+'/analyze-answer', json={'material_id': w.answer['material_id'],
        'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert result.status_code == 200, result.text
    new = result.json()
    assert new['id'] != row['id']
    assert new['revision'] == row['revision']+1
    assert new['edit_version'] == row['edit_version']+1
    assert new['state'] == 'draft'
    with w.sf() as s:
        previous = s.get(TestAuthoringRevision, row['id'])
        assert previous.snapshot == before
        assert previous.state == 'analysis_backup'
    assert w.client.put(path, json={'snapshot': before, 'expected_edit_version': row['edit_version']}).status_code == 409
    assert w.client.get(path).json()['revision']['id'] == new['id']


def test_analysis_backup_does_not_exist_when_native_analysis_fails(workspace):
    from scoring.db.models import TestAuthoringRevision
    from sqlalchemy import select, func
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    response = w.client.post(path+'/analyze-answer', json={'material_id': 'missing',
        'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert response.status_code == 404
    assert w.client.get(path).json()['revision'] == row
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(TestAuthoringRevision)) == 1


def test_analysis_after_split_maps_unscored_children_and_preserves_tree(workspace):
    import pymupdf
    from scoring.db.models import TestMaterial, TestAuthoringRevision
    from scoring.pdf_native import sha256_file
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    formal_before = w.client.get(f'/api/v1/tests/{w.answer["test_id"]}/questions').json()
    snapshot = deepcopy(row['snapshot'])
    parent = snapshot['nodes'][0]
    parent.update(score_semantics='sum_children', score_points=None, body_text='Teacher retained context')
    for index in range(2):
        child = deepcopy(parent)
        child.update(stable_key=f'teacher-{uuid4()}', review_node_id=str(uuid4()),
            parent_key=parent['stable_key'], node_type='subquestion', depth=1, sort_order=index,
            label={'raw': f'({index+1})', 'normalized': f'({index+1})'},
            body_text=f'Teacher changed child {index}', ordered_content=[{'type': 'text', 'order': 0, 'text': f'Teacher changed child {index}'}],
            score_semantics='unset', score_points=None)
        snapshot['nodes'].append(child)
    row = save(w, path, row, snapshot)
    source = w.root/'split-answer.pdf'
    with pymupdf.open() as doc:
        p = doc.new_page()
        p.insert_text((40, 40), '問題3', fontname='japan')
        p.insert_text((40, 90), '(1) Answer one')
        p.insert_text((40, 180), '(2) Answer two')
        doc.save(source)
    with w.sf() as s:
        material = TestMaterial(test_id=w.answer['test_id'], material_type='model_answer_source',
            original_filename=source.name, mime_type='application/pdf', storage_ref=str(source), sha256=sha256_file(source))
        s.add(material)
        s.commit()
        mid = material.id
    response = w.client.post(path+'/analyze-answer', json={'material_id': mid,
        'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert response.status_code == 200, response.text
    analyzed = response.json()
    assert analyzed['snapshot']['nodes'] == row['snapshot']['nodes']
    bound = analyzed['snapshot']['domains']['answer']
    assert bound['analysis_result']['assigned_count'] == 2
    children = snapshot['nodes'][-2:]
    for index, child in enumerate(children):
        entry = next(e for e in bound['entries'] if e['authoring_question_key'] == child['stable_key'])
        assert ('Answer one' if index == 0 else 'Answer two') in entry['candidate_text']
        assert child['stable_key'] in analyzed['snapshot']['answers']
    with w.sf() as s:
        previous = s.get(TestAuthoringRevision, row['id'])
        assert previous.state == 'analysis_backup'
        assert previous.snapshot == row['snapshot']
    assert w.client.get(path).json()['revision'] == analyzed
    assert w.client.get(f'/api/v1/tests/{w.answer["test_id"]}/questions').json() == formal_before


def test_cross_material_merge_preserves_answer_rubric_sources_and_unresolved():
    from types import SimpleNamespace
    from scoring.authoring_sources import merge_answer_analysis
    snapshot = {'nodes': [{'stable_key': 'leaf', 'parent_key': None, 'included': True,
        'label': {'raw': '問題1'}, 'body_text': 'Teacher text', 'node_type': 'major_question',
        'ordered_content': [], 'sort_order': 0, 'score_semantics': 'unset', 'score_points': None}],
        'source_provenance': {}, 'answers': {}, 'rubrics': {}}
    def draft(identifier, material, entries):
        return SimpleNamespace(id=identifier, material_id=material, revision=1,
            source_sha256=material, artifact_ref=identifier, snapshot={'entries': entries})
    original_nodes = deepcopy(snapshot['nodes'])
    merge_answer_analysis(snapshot, draft('answer', 'pdf-a', [{'id': 'a', 'question_id': 'leaf', 'answer_text': 'correct answer'}]))
    result = merge_answer_analysis(snapshot, draft('rubric', 'pdf-b', [
        {'id': 'r', 'question_id': 'leaf', 'answer_text': '', 'rubric_edits': [{'id': 'c', 'description': 'criterion', 'points': 5}]},
        {'id': 'unresolved', 'question_id': 'foreign', 'answer_text': 'not guessed'}]))
    assert snapshot['nodes'] == original_nodes
    assert snapshot['answers']['leaf']['primary'] == 'correct answer'
    assert snapshot['rubrics']['leaf'][0]['description'] == 'criterion'
    assert result == {'status': 'partial', 'assigned_count': 1, 'unresolved_count': 1, 'candidate_count': 2}
    bound = snapshot['domains']['answer']
    assert bound['sources']['answer']['material_id'] == 'pdf-a'
    assert next(e for e in bound['entries'] if e['id'] == 'a')['source_draft_id'] == 'answer'
    assert next(e for e in bound['entries'] if e['id'] == 'unresolved')['authoring_question_key'] is None
    zero = merge_answer_analysis(snapshot, draft('unknown', 'pdf-c', [{'id': 'u', 'question_id': 'other', 'answer_text': 'unknown'}]))
    assert zero['status'] == 'needs_assignment' and zero['assigned_count'] == 0
    assert snapshot['nodes'] == original_nodes


def test_source_import_after_teacher_structure_change_does_not_restore_legacy_tree(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    first = snapshot['nodes'][0]
    first.update(body_text='Teacher changed text', sort_order=10, score_points=7)
    first['ordered_content'] = [{'type': 'text', 'order': 0, 'text': first['body_text']}]
    child = deepcopy(first)
    child.update(stable_key=f'teacher-{uuid4()}', review_node_id=str(uuid4()),
        parent_key=first['stable_key'], node_type='subquestion', depth=1, sort_order=0,
        label={'raw': '(1)', 'normalized': '(1)'}, score_semantics='unset', score_points=None)
    first.update(score_semantics='sum_children', score_points=None)
    snapshot['nodes'].append(child)
    row = save(w, path, row, snapshot)
    result = w.client.post(path+'/source-import', json={'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert result.status_code == 200, result.text
    assert result.json()['snapshot']['nodes'] == row['snapshot']['nodes']


def test_forged_candidate_source_binding_is_rejected(workspace):
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    snapshot = deepcopy(row['snapshot'])
    snapshot['domains']['answer']['entries'][0]['source_draft_id'] = 'foreign-source'
    result = w.client.put(path, json={'snapshot': snapshot, 'expected_edit_version': row['edit_version']})
    assert result.status_code == 409
    assert w.client.get(path).json()['revision'] == row


def test_retained_material_keeps_authorized_diagram_context_after_other_analysis(workspace):
    from scoring.db.models import TestMaterial
    from scoring.pdf_native import sha256_file
    w = workspace
    path, row = begin(w, w.answer['test_id'])
    entry = next(e for e in row['snapshot']['domains']['answer']['entries'] if e['authoring_question_key'])
    endpoint = path+f'/entries/{entry["id"]}/diagrams'
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version']})
    assert result.status_code == 200, result.text
    record = result.json()['diagrams'][0]
    snapshot = deepcopy(row['snapshot'])
    next(e for e in snapshot['domains']['answer']['entries'] if e['id'] == entry['id'])['diagram_records'] = [{**clean(record), 'state': 'accepted'}]
    row = save(w, path, row, snapshot)
    original_material = row['snapshot']['domains']['answer']['material_id']
    with w.sf() as s:
        old = s.get(TestMaterial, original_material)
        material = TestMaterial(test_id=w.answer['test_id'], material_type='rubric_source',
            original_filename='other-rubric.pdf', mime_type='application/pdf', storage_ref=old.storage_ref,
            sha256=sha256_file(w.root/'answer.pdf'))
        s.add(material)
        s.commit()
        mid = material.id
    result = w.client.post(path+'/analyze-answer', json={'material_id': mid,
        'expected_edit_version': row['edit_version'], 'preserve_previous': True})
    assert result.status_code == 200, result.text
    row = result.json()
    bound = row['snapshot']['domains']['answer']
    retained = next(e for e in bound['entries'] if e['id'] == entry['id'])
    assert bound['material_id'] == mid
    assert bound['sources'][retained['source_draft_id']]['material_id'] == original_material
    result = w.client.get(endpoint)
    assert result.status_code == 200, result.text
    selected = next(r for r in result.json()['diagrams'] if r['id'] == record['id'])
    assert selected['state'] == 'accepted' and selected['material_id'] == original_material
    assert w.client.get(selected['preview_url']).status_code == 200
    saved = save(w, path, row, row['snapshot'])
    assert w.client.get(path).json()['revision'] == saved
