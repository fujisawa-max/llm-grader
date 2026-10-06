from copy import deepcopy
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from scoring.api import create_app
from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import TestQuestionAsset, ModelAnswer, GradingJob
from scoring.domain import DomainService
from scoring.pdf_native import sha256_file


def diagram_pdf(completed=False, embedded=False):
    with pymupdf.open() as doc:
        p = doc.new_page(width=400, height=500)
        for number, y in ((3, 30), (4, 300)):
            p.insert_text((25, y), f'問題{number} (10点)', fontname='japan', fontsize=12)
            p.insert_text((25, y+25), '図の範囲を確認してください。', fontname='japan', fontsize=10)
        p.draw_line((70, 160), (230, 160))
        p.draw_line((150, 80), (150, 240))
        p.insert_text((153, 157), 'O', fontsize=8)
        if completed:
            p.draw_line((80, 220), (210, 95), color=(0, 0, 1))
            p.draw_rect((160, 170, 210, 210), fill=(.6, .8, 1))
        if embedded:
            image = p.get_pixmap(clip=pymupdf.Rect(70,80,230,240))
            p.insert_image(pymupdf.Rect(70,80,230,240), pixmap=image)
        p.draw_line((70, 390), (230, 390))
        p.draw_line((150, 330), (150, 455))
        return doc.tobytes()


@pytest.fixture
def workspace(tmp_path, monkeypatch, request):
    embedded = getattr(request, 'param', False)
    monkeypatch.setenv('LLM_GRADER_ARTIFACT_ROOT', str(tmp_path))
    engine, sf = create_session_factory(f'sqlite:///{tmp_path / "db.sqlite"}')
    init_database(engine)
    with sf() as s:
        d = DomainService(s)
        teacher = d.user(display_name='Diagram teacher', email='diagram@example.invalid', role='teacher',
            password_hash=hash_password('isolated-diagram-password'), is_active=True)
        course = d.course(teacher.id, name='Diagram fixtures')
        offering = d.offering(course.id, academic_year=2026, term='fall')
        question_test = d.test(offering.id, name='Question diagrams', total_points=20)
        answer_test = d.test(offering.id, name='Answer diagrams', total_points=20)
        for number in (3, 4):
            d.question(answer_test.id, question_number=str(number), display_label=f'問題{number}',
                max_points=10, sort_order=number, is_gradable=True, question_text='図の範囲を確認してください。')
        source = tmp_path / 'answer.pdf'
        source.write_bytes(diagram_pdf(True, embedded))
        material = d.material(answer_test.id, material_type='model_answer_source', storage_ref=str(source),
            original_filename='answer.pdf', mime_type='application/pdf', sha256=sha256_file(source))
        s.commit()
        qid, aid, mid = question_test.id, answer_test.id, material.id
    client = TestClient(create_app(sf, question_import_root=tmp_path / 'questions', allowed_roots=[tmp_path]))
    client.post('/api/v1/auth/login', json={'email': 'diagram@example.invalid', 'password': 'isolated-diagram-password'})
    upload = client.post(f'/api/v1/tests/{qid}/question-materials', content=diagram_pdf(embedded=embedded),
        headers={'Content-Type': 'application/pdf', 'x-filename': 'diagram.pdf'})
    assert upload.status_code == 201, upload.text
    draft = client.post(f'/api/v1/question-imports/{upload.json()["id"]}/draft').json()
    data = client.post(f'/api/v1/question-import-drafts/{draft["id"]}/reviews').json()
    answer = client.post(f'/api/v1/tests/{aid}/model-answer-imports', json={'material_id': mid})
    assert answer.status_code == 201, answer.text
    yield SimpleNamespace(client=client, sf=sf, root=tmp_path, data=data, answer=answer.json())
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(GradingJob)) == 0
    client.close()
    engine.dispose()


def qpath(w, key='q1'):
    return f'/api/v1/question-import-reviews/{w.data["id"]}/nodes/{key}/diagrams'


def apath(w):
    entry = next(e for e in w.answer['entries'] if e['question_id'] == w.answer['questions'][0]['id'])
    return f'/api/v1/model-answer-import-drafts/{w.answer["id"]}/entries/{entry["id"]}/diagrams', entry


def clean(record):
    return {k: v for k, v in record.items() if k != 'preview_url'}


def test_vector_only_discovery_correct_question_and_authorized_crop(workspace):
    w = workspace
    assert not any(r['region_type'] == 'figure' for r in w.data['regions'])
    for key, expected in [('q1', [70, 80, 230, 240]), ('q2', [70, 330, 230, 455])]:
        response = w.client.get(qpath(w, key))
        assert response.status_code == 200, response.text
        record = response.json()['diagrams'][0]
        assert record['automatic_bbox'] == expected
        assert record['domain'] == 'question' and record['target_key'] == key
        assert record['state'] == 'candidate' and not record['ricoh_used']
        assert w.client.get(record['preview_url']).headers['content-type'] == 'image/png'
    assert w.client.get(f'/api/v1/question-import-reviews/{w.data["id"]}').json() == w.data


@pytest.mark.parametrize('state', ['accepted', 'excluded'])
def test_question_decision_save_reload_and_resume_without_models(workspace, state):
    w = workspace
    record = w.client.post(qpath(w), json={'expected_revision': 1}).json()['diagrams'][0]
    snap = deepcopy(w.data['snapshot'])
    snap['nodes'][0]['diagram_records'] = [{**clean(record), 'state': state}]
    response = w.client.post(f'/api/v1/question-import-reviews/{w.data["id"]}/revisions',
                            json={'base_revision': 1, 'snapshot': snap})
    assert response.status_code == 200, response.text
    assert response.json()['snapshot']['nodes'][0]['diagram_records'][0]['state'] == state
    resumed = w.client.get(qpath(w)).json()['diagrams'][0]
    assert resumed['state'] == state and resumed['id'] == record['id']
    assert resumed['crop_sha256'] == record['crop_sha256']


def test_manual_preview_preserves_original_and_save_only_persists(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    preview = w.client.post(qpath(w)+f'/{record["id"]}/crop-preview',
        json={'expected_revision': 1, 'final_bbox': [65, 75, 240, 245]})
    assert preview.status_code == 200, preview.text
    corrected = preview.json()
    assert corrected['teacher_adjusted'] and corrected['automatic_bbox'] == record['automatic_bbox']
    assert w.client.get(corrected['preview_url']).status_code == 200
    assert w.client.get(qpath(w)).json()['diagrams'][0]['final_bbox'] == record['final_bbox']
    snap = deepcopy(w.data['snapshot'])
    snap['nodes'][0]['diagram_records'] = [{**clean(corrected), 'state': 'accepted'}]
    response = w.client.post(f'/api/v1/question-import-reviews/{w.data["id"]}/revisions',
                            json={'base_revision': 1, 'snapshot': snap})
    assert response.status_code == 200, response.text
    assert w.client.get(qpath(w)).json()['diagrams'][0]['final_bbox'] == [65, 75, 240, 245]


@pytest.mark.parametrize('box', [[60, 75, 240, 335], [-1, 75, 240, 245], [0, 0, 400, 500]])
def test_manual_sibling_or_page_violation_rejected(workspace, box):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    response = w.client.post(qpath(w)+f'/{record["id"]}/crop-preview', json={'expected_revision': 1, 'final_bbox': box})
    assert response.status_code == 422, response.text


def test_foreign_candidate_not_served(workspace):
    w = workspace
    record = w.client.get(qpath(w, 'q2')).json()['diagrams'][0]
    assert w.client.get(qpath(w)+f'/{record["id"]}/crop').status_code == 404


def test_model_answer_save_reload_formal_only_accepted(workspace):
    w = workspace
    path, entry = apath(w)
    response = w.client.post(path, json={'expected_revision': 1})
    assert response.status_code == 200, response.text
    record = response.json()['diagrams'][0]
    assert record['domain'] == 'model_answer'
    records = [{**clean(record), 'state': 'accepted'}]
    updates = [{'id': e['id'], 'question_id': e['question_id'], 'answer_text': e['answer_text'] or 'Teacher answer',
        **({'diagram_records': records} if e['id'] == entry['id'] else {})} for e in w.answer['entries']]
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    response = w.client.put(base, json={'expected_revision': 1, 'entries': updates})
    assert response.status_code == 200, response.text
    assert w.client.get(path).json()['diagrams'][0]['state'] == 'accepted'
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(ModelAnswer)) == 0
    registered = w.client.post(base+'/confirm', json={'expected_revision': 2})
    assert registered.status_code == 200, registered.text
    with w.sf() as s:
        answer = s.scalar(select(ModelAnswer).where(ModelAnswer.question_id == entry['question_id']))
        diagrams = answer.provenance_json['diagrams']
        assert len(diagrams) == 1 and diagrams[0]['crop_sha256'] == record['crop_sha256']
        assert w.client.get(f'/api/v1/model-answers/{answer.id}/diagrams/{record["id"]}/crop').status_code == 200


def test_question_formal_asset_transfer_only_accepted(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    other = w.client.get(qpath(w, 'q2')).json()['diagrams'][0]
    snap = deepcopy(w.data['snapshot'])
    snap['nodes'][0]['diagram_records'] = [{**clean(record), 'state': 'accepted'}]
    snap['nodes'][1]['diagram_records'] = [{**clean(other), 'state': 'excluded'}]
    snap['warning_states'] = {warning['id']: {'state': 'acknowledged'} for warning in w.data['warnings']}
    base = f'/api/v1/question-import-reviews/{w.data["id"]}'
    saved = w.client.post(base+'/revisions', json={'base_revision': 1, 'snapshot': snap})
    assert saved.status_code == 200, saved.text
    marked = w.client.post(base+'/mark-reviewed', json={'base_revision': saved.json()['current_revision']})
    assert marked.status_code == 200, marked.text
    plan = w.client.post(base+'/import-plan').json()
    assert plan['blockers'] == [], plan
    result = w.client.post(base+'/confirm', json={'expected_revision': plan['revision'],
        'expected_revision_sha256': plan['revision_sha256'], 'import_plan_sha256': plan['plan_sha256'], 'mode': 'append'})
    assert result.status_code == 200, result.text
    with w.sf() as s:
        assets = list(s.scalars(select(TestQuestionAsset)))
        assert len(assets) == 1
        assert assets[0].provenance['domain'] == 'question'
        assert assets[0].sha256 == record['crop_sha256']
        assert w.client.get(f'/api/v1/test-question-assets/{assets[0].id}').status_code == 200


@pytest.mark.parametrize('domain', ['question', 'model_answer'])
def test_auth_and_foreign_course_denied(workspace, domain):
    w = workspace
    path = qpath(w) if domain == 'question' else apath(w)[0]
    w.client.cookies.clear()
    assert w.client.get(path).status_code == 401
    with w.sf() as s:
        d = DomainService(s)
        for role in ('student', 'teacher'):
            d.user(display_name=role, email=f'{role}-other@example.invalid', role=role,
                   password_hash=hash_password('isolated-other-password'), is_active=True)
        s.commit()
    for role in ('student', 'teacher'):
        w.client.post('/api/v1/auth/login', json={'email': f'{role}-other@example.invalid', 'password': 'isolated-other-password'})
        assert w.client.get(path).status_code == 403
        assert w.client.post(path, json={'expected_revision': 1}).status_code == 403


def test_save_rejects_fake_artifact_and_stale_context(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    snap = deepcopy(w.data['snapshot'])
    snap['nodes'][0]['diagram_records'] = [{**clean(record), 'state': 'accepted', 'context_sha256': '0'*64}]
    response = w.client.post(f'/api/v1/question-import-reviews/{w.data["id"]}/revisions', json={'base_revision': 1, 'snapshot': snap})
    assert response.status_code == 422 and response.json()['error']['code'] == 'diagram_source_stale'


def test_legacy_ir_geometry_is_derived_without_mutation(workspace):
    w = workspace
    from scoring.diagram_sources import visual_ir
    path = next((w.root/'questions').rglob('source.pdf'))
    ir_path = next((w.root/'questions').rglob('document-ir.json'))
    import json
    ir = json.loads(ir_path.read_text())
    for p in ir['pages']:
        p.pop('vector_elements', None)
    old = deepcopy(ir)
    result = visual_ir(path, ir)
    assert result['pages'][0]['vector_elements']
    assert ir == old


def test_split_save_reload_vector_ownership_and_sibling_exclusion(workspace):
    w = workspace
    snapshot = deepcopy(w.data['snapshot'])
    parent = snapshot['nodes'][0]
    # Move the complete owned source body to a reviewed child. No string equality
    # or guessed geometry is used to establish transformation-aware ownership.
    child = {**deepcopy(parent), 'stable_key': 'teacher-diagram-child', 'review_node_id': 'teacher-diagram-child',
        'source_draft_stable_key': None, 'source_draft_node_id': None, 'parent_key': parent['stable_key'],
        'node_type': 'subquestion', 'sort_order': 0, 'review_flags': []}
    parent.update(ordered_content=[{'type': 'text', 'text': '教師が追加した親設問', 'order': 0}],
        score_semantics='sum_children', score_points=None)
    snapshot['nodes'].append(child)
    base = f'/api/v1/question-import-reviews/{w.data["id"]}'
    response = w.client.post(base+'/revisions', json={'base_revision': 1, 'snapshot': snapshot})
    assert response.status_code == 200, response.text
    persisted = w.client.get(base).json()
    actual = next(n for n in persisted['snapshot']['nodes'] if n['stable_key'] == child['stable_key'])
    assert actual['source_review_owner'] == parent['stable_key']
    diagrams = w.client.get(qpath(w, child['stable_key'])).json()['diagrams']
    assert len(diagrams) == 1 and diagrams[0]['automatic_bbox'] == [70,80,230,240]
    assert w.client.get(qpath(w)).json()['diagrams'] == []
    bad = w.client.post(qpath(w, child['stable_key'])+f'/{diagrams[0]["id"]}/crop-preview',
        json={'expected_revision': 2, 'final_bbox': [65,75,235,450]})
    assert bad.status_code == 422


def test_model_answer_manual_bounds_cannot_expand_to_sibling(workspace):
    w = workspace
    path, _ = apath(w)
    record = w.client.get(path).json()['diagrams'][0]
    bad = w.client.post(path+f'/{record["id"]}/crop-preview',
        json={'expected_revision': 1, 'final_bbox': [65,75,235,450]})
    assert bad.status_code == 422
    good = w.client.post(path+f'/{record["id"]}/crop-preview',
        json={'expected_revision': 1, 'final_bbox': [65,75,235,245]})
    assert good.status_code == 200, good.text
    assert good.json()['teacher_adjusted']
    assert good.json()['automatic_bbox'] == record['automatic_bbox']


def test_preview_and_decision_do_not_trust_client_artifact_path(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    snap = deepcopy(w.data['snapshot'])
    snap['nodes'][0]['diagram_records'] = [{**clean(record), 'state': 'accepted', 'artifact_ref': '/etc/passwd', 'crop_sha256': '0'*64}]
    saved = w.client.post(f'/api/v1/question-import-reviews/{w.data["id"]}/revisions', json={'base_revision': 1, 'snapshot': snap})
    assert saved.status_code == 200, saved.text
    actual = saved.json()['snapshot']['nodes'][0]['diagram_records'][0]
    assert actual['artifact_ref'].startswith('diagrams/') and actual['crop_sha256'] == record['crop_sha256']


def test_changed_source_pdf_rejects_existing_crop(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    source = next((w.root/'questions').rglob('source.pdf'))
    source.write_bytes(source.read_bytes()+b'changed')
    response = w.client.get(qpath(w)+f'/{record["id"]}/crop')
    assert response.status_code in (409, 422)


@pytest.mark.parametrize('workspace', [True], indirect=True)
def test_historical_figure_decisions_compatible_and_excluded_not_blocking(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    assert record['legacy_region_ids']
    snapshot = deepcopy(w.data['snapshot'])
    snapshot['nodes'][0]['diagram_records'] = [{**clean(record), 'state': 'excluded'}]
    for rid in record['legacy_region_ids']:
        snapshot['nodes'][0]['figure_decisions'][rid] = {'decision': 'excluded'}
    snapshot['warning_states'] = {warning['id']: {'state': 'acknowledged'} for warning in w.data['warnings']}
    base = f'/api/v1/question-import-reviews/{w.data["id"]}'
    saved = w.client.post(base+'/revisions', json={'base_revision': 1, 'snapshot': snapshot})
    assert saved.status_code == 200, saved.text
    marked = w.client.post(base+'/mark-reviewed', json={'base_revision': 2})
    assert marked.status_code == 200, marked.text
    plan = w.client.post(base+'/import-plan').json()
    assert plan['blockers'] == [], plan
    assert not any(item['type'] == 'figure' for q in plan['nodes'] for item in q['content']['items'])


def test_changed_ownership_lists_old_decision_without_serving_old_crop(workspace):
    w = workspace
    record = w.client.get(qpath(w)).json()['diagrams'][0]
    from scoring.diagram_review import question_diagram_review
    from scoring.question_reviews import QuestionReviewService
    with w.sf() as session:
        service = QuestionReviewService(session, w.root/'questions')
        snapshot = deepcopy(w.data['snapshot'])
        snapshot['nodes'][0]['ordered_content'] = [{'type': 'text', 'text': '教師が追加した内容', 'order': 0}]
        review = question_diagram_review(service, w.data['id'], 'q1', 1, snapshot_override=snapshot)
        listed = review.records([{**clean(record), 'state': 'accepted'}])
        assert len(listed) == 1
        assert listed[0]['reason_code'] == 'diagram_source_stale'
        assert 'crop_sha256' not in listed[0] and 'artifact_ref' not in listed[0]


@pytest.mark.parametrize('state', ['accepted', 'candidate', 'excluded', None])
def test_manual_diagram_only_content_and_transient_discovery(workspace, state):
    from uuid import uuid4
    w = workspace
    _, automatic = apath(w)
    entry_id = f'teacher-entry-{uuid4()}'
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    path = f'{base}/entries/{entry_id}/diagrams'
    params = {'question_id': automatic['question_id']}
    response = w.client.post(path, params=params, json={'expected_revision': 1})
    assert response.status_code == 200, response.text
    record = response.json()['diagrams'][0]
    assert record['automatic_bbox'] == [70, 80, 230, 240]
    assert not record['ricoh_used']
    assert w.client.get(record['preview_url']).status_code == 200
    untouched = w.client.get(base).json()
    assert untouched['revision'] == 1 and not any(e['id'] == entry_id for e in untouched['entries'])
    updates = [{'id': e['id'], 'question_id': e['question_id'], 'answer_text': e['answer_text'],
                'disposition': 'excluded'} for e in w.answer['entries']]
    manual = {'id': entry_id, 'question_id': automatic['question_id'], 'answer_text': '',
              'disposition': 'include', 'answer_kind': 'primary'}
    if state:
        manual['diagram_records'] = [{**clean(record), 'state': state}]
    updates.append(manual)
    saved = w.client.put(base, json={'expected_revision': 1, 'entries': updates})
    assert saved.status_code == 200, saved.text
    restored = next(e for e in w.client.get(base).json()['entries'] if e['id'] == entry_id)
    assert restored['answer_text'] == ''
    if state:
        assert w.client.get(path).json()['diagrams'][0]['state'] == state
    registered = w.client.post(base+'/confirm', json={'expected_revision': 2})
    if state != 'accepted':
        assert registered.status_code == 422, registered.text
        assert registered.json()['error']['code'] == 'EMPTY_ANSWER_TEXT'
    else:
        assert registered.status_code == 200, registered.text
        answer = registered.json()['model_answers'][0]
        assert answer['answer_text'] == ''
        assert answer['material_id'] == w.answer['material_id']
        assert answer['provenance_json']['diagrams'][0]['state'] == 'accepted'
        assert w.client.get(f'/api/v1/model-answers/{answer["id"]}/diagrams/{record["id"]}/crop').status_code == 200
        assert w.client.get(base).json()['saved_answers'][0]['diagram_count'] == 1


def test_manual_diagram_mapping_missing_and_stale_record_rejected(workspace):
    from uuid import uuid4
    w = workspace
    _, entry = apath(w)
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    eid = f'teacher-entry-{uuid4()}'
    path = f'{base}/entries/{eid}/diagrams'
    assert w.client.post(path, json={'expected_revision': 1}).status_code == 422
    record = w.client.post(path, params={'question_id': entry['question_id']}, json={'expected_revision': 1}).json()['diagrams'][0]
    updates = [{'id': e['id'], 'question_id': e['question_id'], 'answer_text': e['answer_text'], 'disposition': 'excluded'} for e in w.answer['entries']]
    updates.append({'id': eid, 'question_id': entry['question_id'], 'answer_text': '', 'disposition': 'include',
                    'diagram_records': [{**clean(record), 'state': 'accepted', 'context_sha256': '0'*64}]})
    assert w.client.put(base, json={'expected_revision': 1, 'entries': updates}).status_code == 422


def test_manual_candidate_sibling_scope_and_auth(workspace):
    from uuid import uuid4
    w = workspace
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    eid = f'teacher-entry-{uuid4()}'
    path = f'{base}/entries/{eid}/diagrams'
    for question in w.answer['questions']:
        records = w.client.post(path, params={'question_id': question['id']}, json={'expected_revision': 1}).json()['diagrams']
        assert len(records) == 1
        expected = [70, 80, 230, 240] if question['id'] == w.answer['questions'][0]['id'] else [70, 330, 230, 455]
        assert records[0]['automatic_bbox'] == expected
    assert w.client.post(path, params={'question_id': str(uuid4())}, json={'expected_revision': 1}).status_code == 422
    w.client.post('/api/v1/auth/logout')
    assert w.client.get(path, params={'question_id': w.answer['questions'][0]['id']}).status_code == 401


def test_diagram_only_registration_revalidates_stale_saved_evidence(workspace):
    from scoring.db.models import ModelAnswerImportDraft
    from uuid import uuid4
    w = workspace
    _, original = apath(w)
    base = f'/api/v1/model-answer-import-drafts/{w.answer["id"]}'
    eid = f'teacher-entry-{uuid4()}'
    path = f'{base}/entries/{eid}/diagrams'
    record = w.client.post(path, params={'question_id': original['question_id']}, json={'expected_revision': 1}).json()['diagrams'][0]
    corrected = w.client.post(path+f'/{record["id"]}/crop-preview', params={'question_id': original['question_id']},
        json={'expected_revision': 1, 'final_bbox': [65, 75, 235, 245]})
    assert corrected.status_code == 200, corrected.text
    accepted = {**clean(corrected.json()), 'state': 'accepted'}
    updates = [{'id': e['id'], 'question_id': e['question_id'], 'answer_text': e['answer_text'], 'disposition': 'excluded'} for e in w.answer['entries']]
    updates.append({'id': eid, 'question_id': original['question_id'], 'answer_text': '', 'disposition': 'include', 'diagram_records': [accepted]})
    assert w.client.put(base, json={'expected_revision': 1, 'entries': updates}).status_code == 200
    assert w.client.get(path).json()['diagrams'][0]['teacher_adjusted']
    # Simulate a historical/corrupted record after Save: formal registration must
    # independently check it, not trust accepted state from persisted JSON.
    with w.sf() as session:
        draft = session.get(ModelAnswerImportDraft, w.answer['id'])
        snapshot = deepcopy(draft.snapshot)
        next(e for e in snapshot['entries'] if e['id'] == eid)['diagram_records'][0]['source_sha256'] = '0'*64
        draft.snapshot = snapshot
        session.commit()
    stale = w.client.get(path).json()['diagrams'][0]
    assert stale['status'] == 'unresolved' and stale['state'] == 'candidate'
    response = w.client.post(base+'/confirm', json={'expected_revision': 2})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'diagram_source_stale'
    with w.sf() as session:
        assert session.scalar(select(func.count()).select_from(ModelAnswer)) == 0
