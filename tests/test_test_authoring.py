"""Authoring foundations never mutate existing formal/source/grading data."""
from copy import deepcopy
from types import SimpleNamespace
import importlib

import pytest
from sqlalchemy import select, func, inspect, create_engine, MetaData, Table, Column, String
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations

from scoring.api import create_app
from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import (TestQuestion as Question, ModelAnswer, RubricVersion,
    TestAuthoringRevision as Revision, TestArchive as Archive, GradingJob, Test as Exam,
    ConfirmedAuthoringRevision)
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
    client = TestClient(create_app(sf, question_import_root=tmp_path/'artifacts', allowed_roots=[tmp_path]),
        raise_server_exceptions=False)
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
    saved_snapshot=w.client.get(base(w)+'/authoring').json()['revision']['snapshot']
    assert saved_snapshot['nodes']==value['nodes']
    assert saved_snapshot['answers']==value['answers']
    assert saved_snapshot['rubrics'][w.question][0]['description']=='Changed rubric'
    assert saved_snapshot['domains']['rubric']['entries'][0]['criteria'][0]['description']=='Changed rubric'
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
    row=begin(w)
    review=w.client.get(base(w)+'/authoring/review').json()
    assert review['can_confirm']
    confirmed=w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert confirmed.status_code==200,confirmed.text
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(Question))==1
        assert s.scalar(select(func.count()).select_from(ModelAnswer))==2
        assert s.scalar(select(func.count()).select_from(RubricVersion))==2
        assert s.scalar(select(Revision.state))=='confirmed'
        basis=s.scalar(select(ConfirmedAuthoringRevision))
        from scoring.pdf_native import canonical_hash
        assert canonical_hash(basis.snapshot)==basis.snapshot_sha256==row['snapshot_sha256']
        assert basis.snapshot==row['snapshot']
        formal_question=s.get(Question,w.question)
        assert formal_question.question_text==basis.snapshot['nodes'][0]['body_text']
        current_answer=s.scalar(select(ModelAnswer).where(ModelAnswer.test_id==w.legacy,ModelAnswer.is_current.is_(True)))
        assert current_answer.answer_text==basis.snapshot['answers'][w.question]['primary']
        current_rubric=s.scalar(select(RubricVersion).where(RubricVersion.test_id==w.legacy,RubricVersion.status=='approved'))
        assert current_rubric.rubric_json['questions'][0]['criteria']==basis.snapshot['rubrics'][w.question]
        with pytest.raises(ValueError,match='TEST_CONFIRMED_REVISION_READ_ONLY'):
            formal_question.question_text='attempted post-confirm edit'
            s.commit()
        s.rollback()
        with pytest.raises(ValueError,match='CONFIRMED_AUTHORING_REVISION_IMMUTABLE'):
            basis.snapshot={'mutated':True}
            s.commit()
        s.rollback()
    duplicate=w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert duplicate.status_code==200 and duplicate.json()['id']==confirmed.json()['id']
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(ConfirmedAuthoringRevision))==1


def test_confirmed_projection_keeps_review_clean_without_snapshot_mutation(workspace):
    from scoring.test_authoring import baseline_hash, projection
    w = workspace
    row = begin(w)
    assert w.client.get(base(w)+'/authoring/review').json()['issues'] == []
    body = {'revision_id': row['id'], 'expected_edit_version': row['edit_version'],
            'expected_snapshot_sha256': row['snapshot_sha256']}
    confirmed = w.client.post(base(w)+'/authoring/confirm', json=body)
    assert confirmed.status_code == 200, confirmed.text
    with w.sf() as session:
        working = session.get(Revision, row['id'])
        assert working.baseline_sha256 == baseline_hash(projection(session, session.get(Exam, w.legacy)))
        assert working.snapshot == row['snapshot']
        assert working.edit_version == row['edit_version']
    for method in ('get', 'post'):
        kwargs = {'json': {'snapshot': row['snapshot'], 'expected_edit_version': row['edit_version']}} if method == 'post' else {}
        review = getattr(w.client, method)(base(w)+'/authoring/review', **kwargs)
        assert review.status_code == 200, review.text
        assert review.json()['issues'] == []
        assert review.json()['can_confirm'] is False
    duplicate = w.client.post(base(w)+'/authoring/confirm', json=body)
    assert duplicate.json()['id'] == confirmed.json()['id']
    assert w.client.get(base(w)+'/authoring/review').json()['issues'] == []
    with w.sf() as session:
        from scoring.db.models import DomainEvent
        assert session.get(Revision, row['id']).baseline_sha256 == baseline_hash(projection(session, session.get(Exam, w.legacy)))
        assert session.scalar(select(func.count()).select_from(DomainEvent).where(
            DomainEvent.entity_id == w.legacy, DomainEvent.event_type == 'authoring_revision_confirmed')) == 1


def test_legacy_confirmed_baseline_is_attested_read_only(workspace):
    w = workspace
    row = begin(w)
    body = {'revision_id': row['id'], 'expected_edit_version': row['edit_version'],
            'expected_snapshot_sha256': row['snapshot_sha256']}
    assert w.client.post(base(w)+'/authoring/confirm', json=body).status_code == 200
    with w.sf() as session:
        session.get(Revision, row['id']).baseline_sha256 = row['baseline_sha256']
        session.commit()
    assert w.client.get(base(w)+'/authoring/review').json()['issues'] == []
    assert w.client.post(base(w)+'/authoring/confirm', json=body).status_code == 200
    with w.sf() as session:
        assert session.get(Revision, row['id']).baseline_sha256 == row['baseline_sha256']
        assert session.get(Revision, row['id']).snapshot == row['snapshot']


@pytest.mark.parametrize('legacy_basis', [False, True])
@pytest.mark.parametrize('domain', ['question', 'answer', 'rubric', 'asset'])
def test_confirmed_genuine_formal_drift_requires_revision(workspace, domain, legacy_basis):
    from sqlalchemy import update
    w = workspace
    row = begin(w)
    body = {'revision_id': row['id'], 'expected_edit_version': row['edit_version'],
            'expected_snapshot_sha256': row['snapshot_sha256']}
    assert w.client.post(base(w)+'/authoring/confirm', json=body).status_code == 200
    with w.sf() as session:
        if legacy_basis:
            session.get(Revision, row['id']).baseline_sha256 = row['baseline_sha256']
        # Direct SQL is a controlled test seam, not a production edit path.
        if domain == 'question':
            session.execute(update(Question).where(Question.id == w.question).values(question_text='External drift'))
        elif domain == 'answer':
            session.execute(update(ModelAnswer).where(ModelAnswer.test_id == w.legacy, ModelAnswer.is_current.is_(True)).values(answer_text='External drift'))
        elif domain == 'rubric':
            session.execute(update(RubricVersion).where(RubricVersion.test_id == w.legacy, RubricVersion.status == 'approved').values(
                rubric_json={'questions': [{'question_id': w.question, 'criteria': [{'id': 'changed', 'description': 'External drift', 'points': 10}]}]}))
        else:
            from sqlalchemy import insert
            from uuid import uuid4
            from scoring.db.models import TestQuestionAsset
            session.execute(insert(TestQuestionAsset).values(id=str(uuid4()), question_id=w.question,
                asset_type='diagram', artifact_ref='controlled-test-only-drift.png', sha256='a'*64,
                provenance={'source': 'controlled_external_change'}))
        session.commit()
    review = w.client.get(base(w)+'/authoring/review').json()
    stale = next(issue for issue in review['issues'] if issue.get('code') == 'formal_review_stale')
    assert stale['action_label'] == '修正版を作成'
    assert '確定済みの内容は変更できません' in stale['current_state']
    assert '修正版を作成' in stale['expected_state']
    assert '保存' not in stale['expected_state']
    assert not review['can_confirm']
    assert w.client.get(base(w)+'/authoring').json()['confirmed_revision']['snapshot'] == row['snapshot']


def test_confirmation_stale_review_is_rejected(workspace):
    w=workspace
    row=begin(w)
    saved=w.client.put(base(w)+'/authoring',json={'expected_edit_version':row['edit_version'],
        'snapshot':row['snapshot']})
    assert saved.status_code==200
    response=w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert response.status_code==409
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(ConfirmedAuthoringRevision))==0
        assert s.scalar(select(Revision.state))=='draft'


def test_confirmation_failure_rolls_back_formal_projection_and_basis(workspace,monkeypatch):
    w=workspace
    row=begin(w)
    import scoring.authoring_confirmation as confirmation
    project=confirmation.project_confirmed_snapshot
    def fail_after_projection(session,test,snapshot,actor):
        project(session,test,snapshot,actor)
        raise RuntimeError('injected confirmation failure')
    monkeypatch.setattr(confirmation,'project_confirmed_snapshot',fail_after_projection)
    response=w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert response.status_code==500
    with w.sf() as s:
        assert s.scalar(select(func.count()).select_from(ConfirmedAuthoringRevision))==0
        assert s.scalar(select(Revision.state))=='draft'
        assert s.get(Exam,w.legacy).active_confirmed_revision_id is None
        assert s.scalar(select(func.count()).select_from(ModelAnswer))==1
        assert s.scalar(select(func.count()).select_from(RubricVersion))==1


def test_confirmation_readiness_blocks_inconsistent_points(workspace):
    w=workspace
    row=begin(w)
    value=deepcopy(row['snapshot'])
    value['nodes'][0]['score_points']=8
    value['metadata']['total_points']=8
    value['rubrics'][w.question][0]['points']=7
    saved=w.client.put(base(w)+'/authoring',json={'expected_edit_version':1,'snapshot':value})
    assert saved.status_code==200,saved.text
    review=w.client.get(base(w)+'/authoring/review').json()
    assert not review['can_confirm']
    assert any(issue['section']=='rubric' for issue in review['issues'])


def test_submission_and_grading_job_pin_confirmed_revision(workspace,monkeypatch):
    w=workspace
    row=begin(w)
    response=w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert response.status_code==200,response.text
    basis_id=response.json()['id']
    with w.sf() as s:
        from scoring.domain import DomainService
        d=DomainService(s)
        student=d.student(w.offering,student_identifier='CONFIRM-1')
        material=d.material(w.legacy,material_type='student_answer_source',storage_ref='/unused/student.pdf',
            original_filename='student.pdf',mime_type='application/pdf',sha256='a'*64)
        submission=d.submission(w.legacy,student.id,submission_key='confirm-submission',material_id=material.id)
        assert submission.confirmed_authoring_revision_id==basis_id
        rubric=s.scalar(select(RubricVersion).where(RubricVersion.test_id==w.legacy,RubricVersion.status=='approved'))
        questions=list(s.scalars(select(Question).where(Question.test_id==w.legacy,Question.is_gradable.is_(True))))
        policy=d.policy(w.legacy,policy_text='policy',is_current=True)
        s.flush()
        import scoring.grading_inputs as grading_inputs
        import scoring.grading_mapping as grading_mapping
        monkeypatch.setattr(grading_inputs,'prepare_inputs',lambda *args,**kwargs:{})
        monkeypatch.setattr(grading_mapping,'prepare_submission_bundles',lambda *args,**kwargs:[])
        from scoring.domain_adapter import DomainGradingJobAdapter
        job,_=DomainGradingJobAdapter(s).create_legacy_job(s.get(Exam,w.legacy),rubric,questions,policy,[submission],
            assignment_path='/unused/a',run_path='/unused/r',config_path='/unused/c')
        assert job.confirmed_authoring_revision_id==basis_id
        assert job.metadata_json['grading_input_manifest']['confirmed_authoring_revision_id']==basis_id


def test_confirmed_revision_migration_is_additive_on_sqlite():
    engine=create_engine('sqlite://')
    metadata=MetaData()
    Table('users',metadata,Column('id',String(36),primary_key=True))
    tests=Table('tests',metadata,Column('id',String(36),primary_key=True))
    Table('test_authoring_revisions',metadata,Column('id',String(36),primary_key=True))
    Table('student_submissions',metadata,Column('id',String(36),primary_key=True))
    Table('grading_jobs',metadata,Column('id',String(36),primary_key=True))
    metadata.create_all(engine)
    module=importlib.import_module('migrations.versions.0017_confirmed_authoring_revision')
    with engine.begin() as connection:
        connection.execute(tests.insert().values(id='legacy-test'))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert connection.execute(select(tests.c.id)).scalar_one()=='legacy-test'
        assert 'active_confirmed_revision_id' in {c['name'] for c in inspect(connection).get_columns('tests')}
        assert 'confirmed_authoring_revision_id' in {c['name'] for c in inspect(connection).get_columns('student_submissions')}
        assert 'confirmed_authoring_revision_id' in {c['name'] for c in inspect(connection).get_columns('grading_jobs')}
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        assert 'confirmed_authoring_revisions' not in inspect(connection).get_table_names()
    engine.dispose()


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
    stale = next(i for i in issues if i.get('code') == 'formal_review_stale')
    assert stale['action_label'] == '出典を確認'
    assert '保存済みレビューを取り込む' in stale['expected_state']
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
    saved_snapshot=saved.json()['snapshot']
    assert saved_snapshot['nodes']==value['nodes']
    assert saved_snapshot['answers']==value['answers']
    assert saved_snapshot['rubrics']['teacher-child']==value['rubrics']['teacher-child']
    assert next(entry for entry in saved_snapshot['domains']['rubric']['entries']
                if entry['authoring_question_key']=='teacher-child')['criteria']==value['rubrics']['teacher-child']
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


def test_actionable_review_values_and_specific_targets_preserve_blockers(workspace):
    from scoring.test_authoring import preflight
    row = begin(workspace)
    value = deepcopy(row['snapshot'])
    value['rubrics'][workspace.question][0].update(points=8, grouping_confirmed=False)
    value['domains']['answer'] = {'entries': [{'id': 'classification-entry',
        'authoring_question_key': workspace.question, 'disposition': 'include',
        'answer_text': 'Answer', 'semantic_classification': {'status': 'needs_teacher_review'}},
        {'id': 'unassigned-entry', 'disposition': 'unassigned'}]}
    before = deepcopy(value)
    result = preflight(value)
    by_code = {item.get('code'): item for item in result['issues']}
    assert not result['can_confirm']
    assert by_code['rubric_points']['current_state'] == '設問の配点: 10.0点 / 採点基準の合計: 8点'
    assert '10.0点' in by_code['rubric_points']['expected_state']
    assert by_code['rubric_review']['criterion_id'] == 'c1'
    assert by_code['answer_classification']['entry_id'] == 'classification-entry'
    assert by_code['answer_unassigned']['question_key'] is None
    assert by_code['answer_unassigned']['entry_id'] == 'unassigned-entry'
    assert value == before
    value['rubrics'][workspace.question][0].update(points=10, grouping_confirmed=True)
    after = preflight(value)
    assert len(after['issues']) == len(result['issues']) - 2
    assert any(item.get('code') == 'answer_classification' for item in after['issues'])


def test_manual_assignment_preserves_lazy_recovery_evidence_and_rejects_tampering(workspace):
    from scoring.authoring_sources import normalize_authoring_snapshot
    previous = deepcopy(begin(workspace)['snapshot'])
    previous['domains']['answer'] = {'draft_id': 'answer-import', 'entries': [{
        'id': 'unassigned-answer', 'source_draft_id': 'answer-import',
        'authoring_question_key': None, 'disposition': 'unassigned',
        'answer_text': 'Source answer', 'source': {'segments': []},
        'semantic_classification': {'status': 'classified', 'candidate_text': 'Source answer',
            'segments': [{'id': 'uncertain-source', 'category': 'uncertain', 'text': 'Source answer'}]}}]}
    previous['domains'].pop('recovery', None)
    original = deepcopy(previous)
    submitted = deepcopy(previous)
    entry = submitted['domains']['answer']['entries'][0]
    entry.update(authoring_question_key=workspace.question, disposition='include', mapping_state='manual_mapped',
                 teacher_correction={'confirmation_origin': 'manual_edit', 'teacher_confirmed': True})
    entry['semantic_classification']['status'] = 'teacher_reviewed'
    saved = validate_snapshot(submitted, previous)
    evidence = normalize_authoring_snapshot(previous)['domains']['recovery']['rubric_candidates']
    assert saved['domains']['recovery']['rubric_candidates'] == evidence
    assert evidence[0]['question_key'] is None
    assert evidence[0]['classification_status'] == 'classified'
    assert saved['domains']['answer']['entries'][0]['semantic_classification']['status'] == 'teacher_reviewed'
    assert previous == original
    tampered = deepcopy(saved)
    tampered['domains']['recovery']['rubric_candidates'][0]['text'] = 'Forged source'
    with pytest.raises(AuthoringError, match='未割当候補の出典情報'):
        validate_snapshot(tampered, saved)
    removed = deepcopy(saved)
    removed['domains']['recovery']['rubric_candidates'] = []
    with pytest.raises(AuthoringError, match='未割当候補の出典情報'):
        validate_snapshot(removed, saved)


def test_manual_routing_confirmation_does_not_create_recovery_from_fallback(workspace):
    previous = deepcopy(begin(workspace)['snapshot'])
    previous['domains']['answer'] = {'draft_id': 'answer-import', 'entries': [{
        'id': 'unassigned-answer', 'source_draft_id': 'answer-import',
        'authoring_question_key': None, 'disposition': 'unassigned',
        'answer_text': 'Source answer', 'source': {'segments': []},
        'semantic_classification': {'status': 'fallback', 'candidate_text': 'Source answer',
            'segments': [{'id': 'uncertain-source', 'category': 'uncertain', 'text': 'Source answer'}]}}]}
    previous['domains']['recovery'] = {'rubric_candidates': []}
    submitted = deepcopy(previous)
    entry = submitted['domains']['answer']['entries'][0]
    entry.update(authoring_question_key=workspace.question, disposition='include', mapping_state='manual_mapped')
    entry['semantic_classification']['status'] = 'teacher_reviewed'
    saved = validate_snapshot(submitted, previous)
    assert saved['domains']['recovery']['rubric_candidates'] == []
    assert saved['domains']['answer']['entries'][0]['semantic_classification']['status'] == 'teacher_reviewed'


def test_duplicate_confirmation_rejects_corrupt_prior_payload_without_repair(workspace):
    from sqlalchemy import update

    w = workspace
    row = begin(w)
    body = {'revision_id': row['id'], 'expected_edit_version': row['edit_version'],
            'expected_snapshot_sha256': row['snapshot_sha256']}
    result = w.client.post(base(w)+'/authoring/confirm', json=body)
    assert result.status_code == 200, result.text
    identifier = result.json()['id']
    corrupted = deepcopy(row['snapshot'])
    corrupted['metadata']['description'] = 'Controlled historical corruption fixture'
    # Model a pre-fix persisted mismatch without disabling the ORM immutability
    # guard or introducing a production repair/migration path.
    with w.engine.begin() as connection:
        connection.execute(update(ConfirmedAuthoringRevision).where(
            ConfirmedAuthoringRevision.id == identifier).values(snapshot=corrupted))
    retry = w.client.post(base(w)+'/authoring/confirm', json=body)
    assert retry.status_code == 409, retry.text
    assert retry.json()['error']['code'] == 'AUTHORING_CONFIRMED_INTEGRITY_FAILED'
    with w.sf() as session:
        prior = session.get(ConfirmedAuthoringRevision, identifier)
        assert prior.snapshot == corrupted
        assert prior.snapshot_sha256 == row['snapshot_sha256']
        assert session.get(Exam, w.legacy).active_confirmed_revision_id == identifier
        assert session.scalar(select(func.count()).select_from(ConfirmedAuthoringRevision)) == 1


def test_revision_fork_exact_lineage_and_second_confirmation(workspace, monkeypatch):
    from scoring.pdf_native import canonical_hash
    w = workspace
    def confirm(row):
        result = w.client.post(base(w)+'/authoring/confirm', json={
            'revision_id': row['id'], 'expected_edit_version': row['edit_version'],
            'expected_snapshot_sha256': row['snapshot_sha256']})
        assert result.status_code == 200, result.text
        return result.json()
    first = confirm(begin(w))
    assert first['label'] == '第1版'
    draft_response = w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id': first['id']})
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft['snapshot'] == first['snapshot']
    assert canonical_hash(draft['snapshot']) == first['snapshot_sha256']
    assert draft['parent_confirmed_revision_id'] == first['id']
    assert draft['edit_version'] > first['edit_version']
    assert w.client.get(base(w)+'/authoring/review').json()['issues'] == []
    assert w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id': first['id']}).json()['id'] == draft['id']
    assert w.client.get(base(w)+'/authoring/history').json()['active_confirmed_revision_id'] == first['id']
    edited = deepcopy(draft['snapshot'])
    edited['metadata']['description'] = 'Revised teacher description'
    saved = w.client.put(base(w)+'/authoring', json={'expected_edit_version':draft['edit_version'], 'snapshot':edited})
    assert saved.status_code == 200, saved.text
    assert w.client.get(base(w)+'/authoring/confirmed/'+first['id']).json()['snapshot'] == first['snapshot']
    # A clock correction must never renumber an already-issued edition.
    from datetime import datetime, timezone
    monkeypatch.setattr("scoring.db.models.now", lambda: datetime(2000, 1, 1, tzinfo=timezone.utc))
    second = confirm(saved.json())
    assert second['label'] == '第2版'
    assert second['parent_confirmed_revision_id'] == first['id']
    history = w.client.get(base(w)+'/authoring/history').json()
    assert history['active_confirmed_revision_id'] == second['id']
    assert [r['label'] for r in history['revisions']] == ['第2版', '第1版']
    assert history['draft'] is None
    assert w.client.get(base(w)+'/authoring/confirmed/'+first['id']).json()['snapshot'] == first['snapshot']
    assert w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id': first['id']}).status_code == 200
    assert w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id': second['id']}).status_code == 409


def test_revision_lineage_migration_roundtrip():
    engine = create_engine('sqlite://')
    metadata = MetaData()
    Table('confirmed_authoring_revisions',metadata,Column('id',String(36),primary_key=True))
    working = Table('test_authoring_revisions',metadata,Column('id',String(36),primary_key=True))
    metadata.create_all(engine)
    module = importlib.import_module('migrations.versions.0018_revision_lineage')
    assert len(module.revision) <= 32
    with engine.begin() as connection:
        connection.execute(working.insert().values(id='retained-working'))
        for action in (module.upgrade, module.downgrade, module.upgrade):
            with Operations.context(MigrationContext.configure(connection)):
                action()
            assert connection.execute(select(working.c.id)).scalar_one() == 'retained-working'
    engine.dispose()


def test_revised_draft_discard_and_stale_actions(workspace):
    w = workspace
    first_working = begin(w)
    first_body = {'revision_id':first_working['id'], 'expected_edit_version':first_working['edit_version'],
        'expected_snapshot_sha256':first_working['snapshot_sha256']}
    first_response = w.client.post(base(w)+'/authoring/confirm', json=first_body)
    assert first_response.status_code == 200
    first = first_response.json()
    fork = w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id':first['id']}).json()
    body = {'revision_id':fork['id'], 'expected_edit_version':fork['edit_version'],
        'expected_snapshot_sha256':fork['snapshot_sha256']}
    assert w.client.post(base(w)+'/authoring/revisions/discard', json={**body,'expected_edit_version':fork['edit_version']+1}).status_code == 409
    discarded = w.client.post(base(w)+'/authoring/revisions/discard', json=body)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()['id'] == first_working['id']
    assert w.client.get(base(w)+'/authoring/history').json()['active_confirmed_revision_id'] == first['id']
    replacement = w.client.post(base(w)+'/authoring/revisions', json={'confirmed_revision_id':first['id']}).json()
    assert replacement['edit_version'] > fork['edit_version']
    assert w.client.put(base(w)+'/authoring',json={'expected_edit_version':fork['edit_version'],'snapshot':fork['snapshot']}).status_code == 409
    assert w.client.post(base(w)+'/authoring/revisions/discard',json=body).status_code == 409
    assert w.client.post(base(w)+'/authoring/revisions',json={'confirmed_revision_id':w.foreign}).status_code == 409
    assert w.client.get(base(w,'foreign')+'/authoring/confirmed/'+first['id']).status_code == 403


def test_revised_confirmation_rollback_preserves_active_parent(workspace, monkeypatch):
    from scoring import authoring_confirmation
    w = workspace
    row = begin(w)
    first_response = w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert first_response.status_code == 200
    first = first_response.json()
    fork = w.client.post(base(w)+'/authoring/revisions',json={'confirmed_revision_id':first['id']}).json()
    original = authoring_confirmation.project_confirmed_snapshot
    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('AUTHORING_INJECTED_FAILURE')
    monkeypatch.setattr(authoring_confirmation,'project_confirmed_snapshot', failed)
    response = w.client.post(base(w)+'/authoring/confirm',json={'revision_id':fork['id'],
        'expected_edit_version':fork['edit_version'],'expected_snapshot_sha256':fork['snapshot_sha256']})
    assert response.status_code == 409
    history = w.client.get(base(w)+'/authoring/history').json()
    assert history['active_confirmed_revision_id'] == first['id']
    assert len(history['revisions']) == 1
    assert history['draft']['id'] == fork['id']
    assert history['revisions'][0]['snapshot'] == first['snapshot']


def test_historical_submission_allows_fork_but_blocks_activation(workspace):
    w = workspace
    row = begin(w)
    first_response = w.client.post(base(w)+'/authoring/confirm',json={'revision_id':row['id'],
        'expected_edit_version':row['edit_version'],'expected_snapshot_sha256':row['snapshot_sha256']})
    assert first_response.status_code == 200
    first = first_response.json()
    with w.sf() as session:
        service = DomainService(session)
        student = service.student(w.offering, student_identifier='REVISION-HISTORY-SAFETY')
        material = service.material(w.legacy,material_type='student_answer_source',storage_ref='/unused/student.pdf',
            original_filename='student.pdf',mime_type='application/pdf',sha256='a'*64)
        service.submission(w.legacy,student.id,submission_key='revision-history',material_id=material.id)
        session.commit()
    fork_response = w.client.post(base(w)+'/authoring/revisions',json={'confirmed_revision_id':first['id']})
    assert fork_response.status_code == 200
    fork = fork_response.json()
    review = w.client.get(base(w)+'/authoring/review').json()
    assert not review['can_confirm']
    response = w.client.post(base(w)+'/authoring/confirm',json={'revision_id':fork['id'],
        'expected_edit_version':fork['edit_version'],'expected_snapshot_sha256':fork['snapshot_sha256']})
    assert response.status_code == 409
    assert w.client.get(base(w)+'/authoring/history').json()['active_confirmed_revision_id'] == first['id']
