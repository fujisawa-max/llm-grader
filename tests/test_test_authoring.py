"""Authoring foundations never mutate existing formal/source/grading data."""
from copy import deepcopy
from types import SimpleNamespace
import importlib

import pytest
from sqlalchemy import select, func, inspect
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations

from scoring.api import create_app
from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import (TestQuestion as Question, ModelAnswer, RubricVersion,
    TestAuthoringRevision as Revision, TestArchive as Archive, GradingJob, Test as Exam)
from scoring.domain import DomainService
from scoring.test_authoring import validate_snapshot, AuthoringError


@pytest.fixture
def workspace(tmp_path):
    engine, sf = create_session_factory(f'sqlite:///{tmp_path / "db.sqlite"}')
    init_database(engine)
    with sf() as s:
        d = DomainService(s)
        teacher = d.user(display_name='Author', email='author@example.invalid', role='teacher',
            password_hash=hash_password('authoring-test-password'), is_active=True)
        other = d.user(display_name='Other', email='other@example.invalid', role='teacher',
            password_hash=hash_password('authoring-test-password'), is_active=True)
        course = d.course(teacher.id, name='Authoring')
        offering = d.offering(course.id, academic_year=2026, term='fall')
        legacy = d.test(offering.id, name='Legacy Q5', total_points=10)
        fresh = d.test(offering.id, name='New test', total_points=10)
        q = d.question(legacy.id, question_number='1', question_text='Original\nsecond line', max_points=10)
        a = d.model_answer(legacy.id, question_id=q.id, answer_text='Original answer',
            provenance_json={'source_sha256':'f'*64, 'diagrams':[]})
        rub = d.rubric(legacy.id, {'questions':[{'question_id':q.id,'max_points':10,
            'criteria':[{'id':'c1','description':'Original criterion','points':10}]}]})
        d.approve_rubric(rub.id, teacher.id)
        foreign_course = d.course(other.id, name='Other course')
        fo = d.offering(foreign_course.id, academic_year=2026, term='fall')
        foreign = d.test(fo.id, name='Foreign')
        s.commit()
        ids = dict(legacy=legacy.id, fresh=fresh.id, foreign=foreign.id, course=course.id,
            offering=offering.id, question=q.id, answer=a.id, rubric=rub.id)
    client = TestClient(create_app(sf, question_import_root=tmp_path/'artifacts', allowed_roots=[tmp_path]))
    assert client.post('/api/v1/auth/login', json={'email':'author@example.invalid',
        'password':'authoring-test-password'}).status_code == 200
    yield SimpleNamespace(client=client, sf=sf, engine=engine, **ids)
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(GradingJob)) == 0
    client.close()
    engine.dispose()


def base(w, target='legacy'):
    return f'/api/v1/tests/{getattr(w,target)}'


def begin(w, target='legacy'):
    result=w.client.post(base(w,target)+'/authoring/revisions')
    assert result.status_code == 200, result.text
    return result.json()


def test_read_is_side_effect_free_and_resume_creates_no_duplicate(workspace):
    w=workspace
    assert w.client.get(base(w)+'/authoring').json()['revision'] is None
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(Revision)) == 0
    row=begin(w)
    assert begin(w)['id']==row['id']
    assert w.client.get(base(w)+'/authoring').json()['revision']==row
    assert row['snapshot']['source_provenance']['model_answers'][0]['id']==w.answer


def test_atomic_draft_save_preserves_formal_entities_and_conflicts(workspace):
    w=workspace
    row=begin(w)
    value=deepcopy(row['snapshot'])
    value['nodes'][0]['body_text']='Joined lines\n日本語'
    value['nodes'][0]['ordered_content'][0]['text']='Joined lines\n日本語'
    value['answers'][w.question]['primary']='Changed answer'
    value['rubrics'][w.question][0]['description']='Changed rubric'
    result=w.client.put(base(w)+'/authoring',json={'expected_edit_version':1,'snapshot':value})
    assert result.status_code==200, result.text
    assert result.json()['edit_version']==2
    assert w.client.get(base(w)+'/authoring').json()['revision']['snapshot']==value
    conflict=w.client.put(base(w)+'/authoring',json={'expected_edit_version':1,'snapshot':row['snapshot']})
    assert conflict.status_code==409
    with w.sf() as s:
        assert s.get(Question,w.question).question_text=='Original\nsecond line'
        assert s.get(ModelAnswer,w.answer).answer_text=='Original answer'
        assert s.get(RubricVersion,w.rubric).rubric_json['questions'][0]['criteria'][0]['description']=='Original criterion'


@pytest.mark.parametrize('mutation',['provenance','cycle','foreign_material','duplicate','points','rubric',
    'malformed_parent','malformed_material'])
def test_unsafe_snapshot_rejected_without_partial_save(workspace,mutation):
    w=workspace
    row=begin(w)
    value=deepcopy(row['snapshot'])
    if mutation=='provenance':
        value['source_provenance']['questions'][0]['content_sha256']='0'*64
    if mutation=='cycle':
        value['nodes'][0]['parent_key']=w.question
    if mutation=='foreign_material':
        value['materials']=[{'id':'foreign','sha256':'0'*64,'role':'question_sheet'}]
    if mutation=='duplicate':
        value['nodes'].append(deepcopy(value['nodes'][0]))
    if mutation=='points':
        value['nodes'][0]['score_points']=-1
    if mutation=='rubric':
        value['rubrics'][w.question][0]['points']=-1
    if mutation=='malformed_parent':
        value['nodes'][0]['parent_key']=[]
    if mutation=='malformed_material':
        value['materials']=[{'id':[], 'sha256':'0'*64, 'role':'question_sheet'}]
    result=w.client.put(base(w)+'/authoring',json={'expected_edit_version':1,'snapshot':value})
    assert result.status_code==409, result.text
    assert w.client.get(base(w)+'/authoring').json()['revision']==row


@pytest.mark.parametrize('points',[True,float('inf'),float('nan')])
def test_non_finite_points_fail_closed(workspace,points):
    row=begin(workspace)
    value=deepcopy(row['snapshot'])
    value['nodes'][0]['score_points']=points
    with pytest.raises(AuthoringError):
        validate_snapshot(value,row['snapshot'])


def test_publication_boundary_never_partially_registers(workspace):
    w=workspace
    begin(w)
    review=w.client.get(base(w)+'/authoring/review').json()
    assert not review['can_confirm']
    assert any(i['section']=='publication' for i in review['issues'])
    assert w.client.post(base(w)+'/authoring/confirm').status_code==409
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(Question))==1
        assert s.scalar(select(func.count()).select_from(ModelAnswer))==1
        assert s.scalar(select(func.count()).select_from(RubricVersion))==1
        assert s.scalar(select(Revision.state))=='draft'


def test_confirmed_record_is_immutable_and_explicit_new_draft(workspace):
    w=workspace
    row=begin(w)
    with w.sf() as s:
        # State-machine fixture only. Publication API cannot manufacture this.
        s.get(Revision,row['id']).state='confirmed'
        s.commit()
    assert w.client.put(base(w)+'/authoring',json={'expected_edit_version':1,'snapshot':row['snapshot']}).status_code==409
    new=begin(w)
    assert new['revision']==2 and new['snapshot']==row['snapshot']
    with w.sf() as s:
        assert s.get(Revision,row['id']).state=='confirmed'


def test_authorization_no_foreign_review_or_archive(workspace):
    w=workspace
    for suffix in ('/authoring','/archive-impact'):
        assert w.client.get(base(w,'foreign')+suffix).status_code==403
    w.client.cookies.clear()
    assert w.client.get(base(w)+'/authoring').status_code==401


def test_archive_requires_current_impact_and_retains_all_data(workspace):
    w=workspace
    impact=w.client.get(base(w)+'/archive-impact').json()
    assert impact['questions']==impact['model_answers']==impact['rubrics']==1
    assert w.client.post(base(w)+'/archive',json={'test_name':'wrong','impact_sha256':impact['impact_sha256']}).status_code==409
    result=w.client.post(base(w)+'/archive',json={'test_name':impact['name'],'impact_sha256':impact['impact_sha256']})
    assert result.status_code==200, result.text
    for url in (base(w),base(w)+'/authoring',f'/api/v1/questions/{w.question}'):
        response=w.client.get(url) if not url.endswith(w.question) else w.client.patch(url,json={'question_text':'forged'})
        assert response.status_code==410,response.text
    assert w.legacy not in [v['id'] for v in w.client.get(f'/api/v1/offerings/{w.offering}/tests').json()]
    with w.sf() as s:
        assert s.get(Question,w.question) and s.get(ModelAnswer,w.answer) and s.get(RubricVersion,w.rubric)
    assert w.client.post(base(w)+'/restore').status_code==200
    assert w.client.get(base(w)).status_code==200
    with w.sf() as s:
        assert not s.get(Archive,w.legacy)


def test_recent_shortcuts_use_saved_draft_state(workspace):
    w=workspace
    begin(w)
    values=w.client.get(f'/api/v1/courses/{w.course}/recent-tests').json()['tests']
    assert next(v for v in values if v['id']==w.legacy)['authoring_state']=='draft'


def test_additive_migration_is_repeatable_and_preserves_existing_test(workspace):
    w=workspace
    module=importlib.import_module('migrations.versions.0015_test_authoring')
    with w.engine.begin() as connection:
        Revision.__table__.drop(connection)
        Archive.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
        assert {'test_authoring_revisions','test_archives'}<=set(inspect(connection).get_table_names())
    with w.sf() as s:
        assert s.get(Exam,w.legacy).name=='Legacy Q5'


def test_new_authoring_without_formal_snapshot_rejects_student_submission(workspace):
    w = workspace
    begin(w, 'fresh')
    with w.sf() as s:
        service = DomainService(s)
        student = service.student(w.offering, student_identifier='s1', display_name='Student')
        material = service.material(w.fresh, material_type='student_answer_source', storage_ref='unused.pdf')
        with pytest.raises(ValueError, match='AUTHORING_TEST_NOT_CONFIRMED'):
            service.submission(w.fresh, student.id, submission_key='s1', material_id=material.id)
        s.rollback()


def test_changed_formal_baseline_is_actionable_and_not_overwritten(workspace):
    w = workspace
    begin(w)
    with w.sf() as s:
        s.get(Question, w.question).question_text = 'Separately corrected source'
        s.commit()
    issues = w.client.get(base(w)+'/authoring/review').json()['issues']
    assert any(i['section'] == 'source' for i in issues)
    assert w.client.get(base(w)+'/authoring').json()['revision']['snapshot']['nodes'][0]['body_text'] == 'Original\nsecond line'


def test_status_is_read_only_and_domain_authorized(workspace):
    w = workspace
    assert w.client.get(base(w)+'/authoring/status').json() == {'state': None, 'revision_id': None, 'edit_version': None}
    assert w.client.get(base(w, 'foreign')+'/authoring/status').status_code == 403
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(Revision)) == 0
    row = begin(w)
    assert w.client.get(base(w)+'/authoring/status').json() == {'state': 'draft', 'revision_id': row['id'], 'edit_version': row['edit_version']}
    assert w.client.get(base(w)+'/authoring').json()['revision'] == row


def test_recent_card_selects_one_active_draft_before_newer_legacy_test(workspace):
    from datetime import timedelta
    from scoring.db.models import now
    w = workspace
    row = begin(w)
    with w.sf() as s:
        s.get(Exam, w.fresh).updated_at = now()+timedelta(days=1)
        s.commit()
    values = w.client.get(f'/api/v1/courses/{w.course}/recent-tests').json()['tests']
    assert len(values) == 1
    assert values[0]['id'] == w.legacy
    with w.sf() as s:
        s.get(Revision, row['id']).state = 'confirmed'
        s.commit()
    values = w.client.get(f'/api/v1/courses/{w.course}/recent-tests').json()['tests']
    assert len(values) == 1
    assert values[0]['id'] == w.fresh


def test_material_replacement_preserves_source_refs_and_requires_rebinding():
    from scoring.test_authoring import replacement_problems, validate_material_replacements, AuthoringError
    old = {'id': 'old', 'role': 'model_answer_source', 'sha256': 'before'}
    new = {'id': 'new', 'role': 'model_answer_source', 'sha256': 'after', 'replaces_material_id': 'old'}
    value = {'materials': [old, new], 'domains': {'answer': {'material_id': 'old', 'source_sha256': 'before'}}}
    validate_material_replacements(value)
    assert replacement_problems(value) == [{'domain': 'answer', 'code': 'authoring_material_replaced'}]
    assert value['materials'][0] == old  # old source evidence is never rewritten
    value['domains']['answer'] = {'material_id': 'new', 'source_sha256': 'after'}
    assert replacement_problems(value) == []
    for patch in ({'replaces_material_id': 'foreign'}, {'replaces_material_id': 'new'},
                  {'role': 'question_sheet'}, {'sha256': 'before'}, {'replaces_material_id': []}):
        with pytest.raises(AuthoringError):
            validate_material_replacements({'materials': [old, {**new, **patch}]})


def test_material_replacement_roundtrips_without_formal_or_legacy_mutation(workspace):
    from scoring.db.models import TestMaterial
    w = workspace
    row = begin(w)
    with w.sf() as s:
        first = TestMaterial(test_id=w.legacy, material_type='question_sheet', original_filename='old.pdf', storage_ref='old.pdf', sha256='a'*64)
        second = TestMaterial(test_id=w.legacy, material_type='question_sheet', original_filename='new.pdf', storage_ref='new.pdf', sha256='b'*64)
        s.add_all([first, second])
        s.flush()
        refs = [{'id': m.id, 'sha256': m.sha256, 'role': m.material_type} for m in (first, second)]
        refs[1]['replaces_material_id'] = first.id
        s.commit()
    row['snapshot']['materials'] = refs
    saved = w.client.put(base(w)+'/authoring', json={'snapshot': row['snapshot'], 'expected_edit_version': row['edit_version']})
    assert saved.status_code == 200, saved.text
    assert w.client.get(base(w)+'/authoring').json()['revision']['snapshot']['materials'] == refs
    assert saved.json()['state'] == 'draft'
    with w.sf() as s:
        assert s.get(TestMaterial, refs[0]['id']).sha256 == 'a'*64
        assert s.scalar(select(func.count()).select_from(Exam)) == 3


def test_simultaneous_initial_open_resumes_single_draft(workspace):
    from concurrent.futures import ThreadPoolExecutor
    w = workspace
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: begin(w, 'fresh'), range(2)))
    assert rows[0]['id'] == rows[1]['id']
    with w.sf() as session:
        assert session.scalar(select(func.count()).select_from(Revision).where(
            Revision.test_id == w.fresh, Revision.state == 'draft')) == 1
    assert begin(w, 'fresh')['id'] == rows[0]['id']


def test_resume_prefers_active_saved_revision_over_backups_and_readonly(workspace):
    w = workspace
    row = begin(w)
    with w.sf() as session:
        for number, state in [(2, 'confirmed'), (3, 'analysis_backup')]:
            session.add(Revision(test_id=w.legacy, revision=number, edit_version=99,
                state=state, snapshot=deepcopy(row['snapshot']), snapshot_sha256=row['snapshot_sha256'],
                baseline_sha256=row['baseline_sha256']))
        session.commit()
    assert w.client.get(base(w)+'/authoring').json()['revision'] == row
    assert begin(w)['id'] == row['id']
    value = deepcopy(row['snapshot'])
    value['nodes'][0]['score_points'] = 7
    value['nodes'][0]['body_text'] = 'Saved active revision'
    value['nodes'][0]['ordered_content'][0]['text'] = 'Saved active revision'
    saved = w.client.put(base(w)+'/authoring', json={'snapshot': value, 'expected_edit_version': row['edit_version']})
    assert saved.status_code == 200, saved.text
    assert w.client.get(base(w)+'/authoring').json()['revision'] == saved.json()
    with w.sf() as session:
        session.get(Revision, row['id']).state = 'analysis_backup'
        session.commit()
    assert w.client.get(base(w)+'/authoring').json()['revision']['state'] == 'confirmed'
    assert w.client.put(base(w)+'/authoring', json={'snapshot': value, 'expected_edit_version': 99}).status_code == 409


def test_exact_buffers_split_points_answer_rubric_roundtrip(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row['snapshot'])
    root = value['nodes'][0]
    root.update(score_semantics='sum_children', score_points=None)
    child = {**deepcopy(root), 'stable_key': 'teacher-child', 'review_node_id': 'teacher-child',
        'parent_key': root['stable_key'], 'node_type': 'subquestion', 'sort_order': 0,
        'score_semantics': 'direct', 'score_points': 10, 'body_text': 'Japanese\nexact buffer'}
    child['ordered_content'] = [{'type': 'text', 'order': 0, 'text': child['body_text']}]
    value['nodes'].append(child)
    value['question_text_buffers'] = {n['stable_key']: n['body_text'] for n in value['nodes']}
    value['answers']['teacher-child'] = {'primary': 'answer', 'alternatives': ['alternative'], 'diagram_records': []}
    value['rubrics']['teacher-child'] = [{'id': 'manual', 'description': 'criterion', 'points': 10}]
    saved = w.client.put(base(w)+'/authoring', json={'snapshot': value, 'expected_edit_version': row['edit_version']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['snapshot'] == value
    assert w.client.get(base(w)+'/authoring').json()['revision'] == saved.json()
    assert begin(w) == saved.json()
    conflict = w.client.put(base(w)+'/authoring', json={'snapshot': row['snapshot'], 'expected_edit_version': 1})
    assert conflict.status_code == 409
    assert w.client.get(base(w)+'/authoring').json()['revision'] == saved.json()


@pytest.mark.parametrize('state', ['ready', 'unsaved_changes', 'unsupported', 'stale_source', 'busy', 'missing_material', 'readonly'])
def test_analysis_readiness_has_explicit_states(state):
    from scoring.test_authoring import material_analysis_readiness
    material = {'id': 'current', 'role': 'question_sheet', 'sha256': 'hash'}
    snapshot = {'materials': [material], 'source_provenance': {'analysis_materials': [{'id': 'current', 'sha256': 'hash'}]}}
    if state == 'unsupported':
        material['role'] = 'supplementary_source'
    if state == 'stale_source':
        snapshot['materials'].append({'id': 'new', 'replaces_material_id': 'current'})
    result = material_analysis_readiness(snapshot, None if state == 'missing_material' else material,
        dirty=state == 'unsaved_changes', busy=state == 'busy', editable=state != 'readonly')
    assert result['state'] == state
    assert bool(result['reason']) == (state != 'ready')
    if state == 'ready':
        assert result['analyzed'] is True


def test_backup_only_resume_fails_clearly_instead_of_using_formal_projection(workspace):
    w = workspace
    row = begin(w)
    with w.sf() as session:
        stored = session.get(Revision, row['id'])
        stored.snapshot = {**stored.snapshot, 'metadata': {**stored.snapshot['metadata'], 'name': 'Preserved backup'}}
        stored.state = 'analysis_backup'
        session.commit()
    response = w.client.get(base(w)+'/authoring')
    assert response.status_code == 409
    assert 'AUTHORING_RESUME_UNAVAILABLE' in response.text
    restored = begin(w)
    assert restored['snapshot']['metadata']['name'] == 'Preserved backup'
    assert restored['revision'] == row['revision']+1
