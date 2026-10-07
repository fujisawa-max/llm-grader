"""Domain-authorized whole-test drafts and reversible Test management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func

from ..db.models import (Test, CourseOffering, Course,
    TestArchive, GradingJob, DomainEvent)
from ..test_authoring import (AuthoringError, projection, latest, create_draft,
    save_draft, preflight, archive_impact, baseline_hash)


class SaveAuthoring(BaseModel):
    expected_edit_version: int = Field(ge=1)
    snapshot: dict


class ArchiveRequest(BaseModel):
    test_name: str
    impact_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def router(db):
    r = APIRouter(prefix='/api/v1')

    def owned(test_id, s, allow_archived=False):
        test = s.get(Test, test_id)
        if not test:
            raise HTTPException(404, 'TEST_NOT_FOUND')
        offering = s.get(CourseOffering, test.course_offering_id)
        course = s.get(Course, offering.course_id)
        actor = s.info.get('auth_user')
        if not actor or (actor.role != 'admin' and course.owner_user_id != actor.id):
            raise HTTPException(403, 'COURSE_ACCESS_DENIED')
        if not allow_archived and s.get(TestArchive, test_id):
            raise HTTPException(410, 'TEST_ARCHIVED')
        return test

    def view(row):
        return {k: getattr(row, k) for k in ('id', 'test_id', 'revision', 'edit_version', 'state',
            'snapshot', 'snapshot_sha256', 'baseline_sha256')}

    def error(exc, s):
        s.rollback()
        raise HTTPException(409, {'error': {'code': exc.code, 'message': str(exc)}}) from exc

    @r.get('/tests/{test_id}/authoring')
    def get_authoring(test_id: str, s=Depends(db)):
        test = owned(test_id, s)
        row = latest(s, test_id)
        return {'revision': view(row) if row else None, 'legacy': projection(s, test),
            'publication_available': False}

    @r.post('/tests/{test_id}/authoring/revisions')
    def begin(test_id: str, s=Depends(db)):
        test = owned(test_id, s)
        try:
            row = create_draft(s, test, s.info['auth_user'].id)
            s.commit()
            return view(row)
        except AuthoringError as exc:
            error(exc, s)

    @r.put('/tests/{test_id}/authoring')
    def save(test_id: str, v: SaveAuthoring, s=Depends(db)):
        test = owned(test_id, s)
        try:
            row = save_draft(s, test, v.snapshot, v.expected_edit_version, s.info['auth_user'].id)
            s.commit()
            return view(row)
        except AuthoringError as exc:
            error(exc, s)

    @r.get('/tests/{test_id}/authoring/review')
    def review(test_id: str, s=Depends(db)):
        test = owned(test_id, s)
        row = latest(s, test_id)
        snapshot = row.snapshot if row else projection(s, test)
        result = preflight(snapshot)
        if row and row.baseline_sha256 != baseline_hash(projection(s, test)):
            result['issues'].append({'question_key': None, 'section': 'source',
                'message': '元の正式内容が変更されています。出典付きレビューを確認してください。'})
        return result

    @r.post('/tests/{test_id}/authoring/confirm')
    def confirm(test_id: str, s=Depends(db)):
        owned(test_id, s)
        # Publishing requires atomic domain adapters + submission/job revision
        # pins. Never silently freeze only a JSON draft or individual sections.
        raise HTTPException(409, {'error': {'code': 'AUTHORING_PUBLICATION_NOT_READY',
            'message': 'この画面からの試験内容確定は現在利用できません。'}})

    @r.get('/tests/{test_id}/archive-impact')
    def impact(test_id: str, s=Depends(db)):
        return archive_impact(s, owned(test_id, s))

    @r.post('/tests/{test_id}/archive')
    def archive(test_id: str, v: ArchiveRequest, s=Depends(db)):
        test = owned(test_id, s)
        s.scalar(select(Test).where(Test.id == test_id).with_for_update())
        impact = archive_impact(s, test)
        if v.test_name != test.name or v.impact_sha256 != impact['impact_sha256']:
            raise HTTPException(409, 'ARCHIVE_CONFIRMATION_CHANGED')
        if s.scalar(select(GradingJob.id).where(GradingJob.test_id == test_id,
                GradingJob.state.in_(['queued', 'running', 'paused']))):
            raise HTTPException(409, 'ACTIVE_GRADING_JOB')
        s.add(TestArchive(test_id=test.id, archived_by=s.info['auth_user'].id,
            previous_status=test.status, impact=impact))
        s.add(DomainEvent(entity_type='test', entity_id=test.id,
            event_type='test_archived', actor_user_id=s.info['auth_user'].id, payload=impact))
        s.commit()
        return {'archived': True, 'test_id': test.id}

    @r.post('/tests/{test_id}/restore')
    def restore(test_id: str, s=Depends(db)):
        owned(test_id, s, allow_archived=True)
        s.execute(delete(TestArchive).where(TestArchive.test_id == test_id))
        s.add(DomainEvent(entity_type='test', entity_id=test_id,
            event_type='test_restored', actor_user_id=s.info['auth_user'].id))
        s.commit()
        return {'restored': True, 'test_id': test_id}

    @r.get('/courses/{course_id}/recent-tests')
    def recent(course_id: str, s=Depends(db)):
        course = s.get(Course, course_id)
        actor = s.info.get('auth_user')
        if not course:
            raise HTTPException(404, 'COURSE_NOT_FOUND')
        if not actor or (actor.role != 'admin' and actor.id != course.owner_user_id):
            raise HTTPException(403, 'COURSE_ACCESS_DENIED')
        from ..db.models import TestAuthoringRevision
        edits = select(TestAuthoringRevision.test_id,
            func.max(TestAuthoringRevision.updated_at).label('last_saved')).group_by(TestAuthoringRevision.test_id).subquery()
        values = s.scalars(select(Test).join(CourseOffering).outerjoin(edits, edits.c.test_id == Test.id).where(CourseOffering.course_id == course_id,
            ~Test.id.in_(select(TestArchive.test_id))).order_by(func.coalesce(edits.c.last_saved, Test.updated_at).desc(), Test.id).limit(3))
        result = []
        for test in values:
            row = latest(s, test.id)
            result.append({'id': test.id, 'name': test.name,
                'authoring_state': row.state if row else 'legacy', 'status': test.status})
        return {'tests': result}
    return r
