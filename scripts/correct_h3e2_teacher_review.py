"""Append the explicitly authorized withdrawal and factorization clarification."""
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import select

from scoring.db.database import create_session_factory
from scoring.db import models as m
from scoring.domain import DomainService
from scoring.grading_execution import execution_rubric
from scoring.pdf_native import canonical_hash, sha256_file

TEST = 'e14aeeb5-924c-4c72-b2a2-583f1be9f48e'
BASE = '169af71b-c1ec-4d42-900f-89513d3e1fe3'
OLD_REVIEW = '6581076a-73ee-460f-9367-ac4687cee321'
QID = '02669a76-cb99-4ea1-bfd4-c742ff1617a3'
ROOT = Path('artifacts/h3e1-q4-actual/teacher-review')
REVIEW_ID = str(uuid5(UUID(OLD_REVIEW), 'withdraw-factorization-override.v1'))
CONDITION = '因数分解直前までの式変形は正しいが、最後の因数分解だけを誤った場合'


def fingerprint(session, model):
    return canonical_hash(json.loads(json.dumps([
        {c.name: getattr(row, c.key) for c in model.__table__.columns}
        for row in session.scalars(select(model).order_by(model.id))
    ], default=str)))


def apply(url):
    _, factory = create_session_factory(url)
    path = ROOT / f'{REVIEW_ID}.json'
    with factory() as s:
        # Serialize competing revisions/approvals for this test.
        s.execute(select(m.Test).where(m.Test.id == TEST).with_for_update()).scalar_one()
        existing = s.scalar(select(m.DomainEvent).where(
            m.DomainEvent.entity_id == REVIEW_ID,
            m.DomainEvent.event_type == 'teacher_grading_review_summary'))
        if existing:
            revision = existing.payload['revision']
            if path.exists():
                assert json.loads(path.read_text()) == revision
            else:
                path.write_text(json.dumps(revision, ensure_ascii=False, indent=2))
            return {'reused': True, 'revision': revision}
        old_path = ROOT / f'{OLD_REVIEW}.json'
        old = json.loads(old_path.read_text())
        assert old['revision_sha256'] == canonical_hash({
            k: v for k, v in old.items() if k != 'revision_sha256'})
        protected_models = (m.GradingJob, m.GradingJobItem, m.StudentAnswerReconstruction,
                            m.TestQuestion, m.ModelAnswer, m.StudentSubmission)
        before = {c.__tablename__: fingerprint(s, c) for c in protected_models}
        files = {p: sha256_file(p) for folder in (
            Path('artifacts/h3e1-q4-actual'), Path('artifacts/h3e2-q4-partial-credit'))
            for p in folder.rglob('*') if p.is_file()}
        current = s.scalar(select(m.RubricVersion).where(
            m.RubricVersion.test_id == TEST, m.RubricVersion.status == 'approved'))
        assert current and current.id == BASE, 'STALE_RUBRIC_VERSION'
        old_rubric = deepcopy(current.rubric_json)
        rubric = deepcopy(old_rubric)
        entry = next(q for q in rubric['questions'] if q['question_id'] == QID)
        criterion = next(c for c in entry['criteria'] if c['id'] == 'criterion_1_factorization')
        level = next(value for value in criterion['levels'] if value['score'] == 5)
        previous_condition = level['condition']
        level['condition'] = CONDITION
        criterion['source_kind'] = criterion['provenance'] = 'TEACHER_EDITED'
        criterion['teacher_reviewed'] = True
        criterion['review_required'] = False
        clarification = {
            'base_rubric_version_id': BASE, 'base_rubric_sha256': canonical_hash(old_rubric),
            'teacher_review_id': REVIEW_ID, 'question_id': QID,
            'criterion_id': criterion['id'], 'score': 5,
            'before': previous_condition, 'after': CONDITION,
            'provenance': 'TEACHER_EDITED',
            'interpretation': '因数分解前の式変形に既に誤りがある場合は、この5点条件を満たさない。',
        }
        criterion['teacher_clarification'] = clarification
        execution_rubric({'rubric': {'entry': entry}, 'question': {'max_points': 20}})
        assert sum(c['points'] for c in entry['criteria']) == 20
        for prior in old_rubric['questions']:
            if prior['question_id'] != QID:
                assert prior == next(q for q in rubric['questions'] if q['question_id'] == prior['question_id'])
        teacher = old['teacher_user_id']
        domain = DomainService(s)
        created = domain.rubric(TEST, rubric, source_type='teacher_reviewed',
            rubric_text='Teacher clarification: factorization partial-credit prerequisite',
            generated_by_model=None, generation_metadata=clarification)
        approved = domain.approve_rubric(created.id, teacher)
        revision = deepcopy(old)
        revision.update(review_id=REVIEW_ID, revision_number=2,
            supersedes_review_id=OLD_REVIEW, previous_revision_sha256=old['revision_sha256'],
            created_at=datetime.now(timezone.utc).isoformat(),
            clarification_rubric_version_id=approved.id,
            clarification_rubric_version=approved.version,
            clarification_rubric_sha256=canonical_hash(approved.rubric_json),
            teacher_clarification=clarification)
        revision.pop('revision_sha256')
        for decision in revision['decisions']:
            item = s.get(m.GradingJobItem, decision['item_id'])
            assert item.job_id == decision['job_id'] and item.score == 10
            assert sha256_file(Path(item.normalized_result_path)) == decision['original_result_sha256']
            events = list(s.scalars(select(m.DomainEvent).where(
                m.DomainEvent.entity_type == 'grading_job_item',
                m.DomainEvent.entity_id == item.id,
                m.DomainEvent.event_type == 'teacher_grading_review_revision')))
            assert len(events) == 1 and events[0].payload['review_id'] == OLD_REVIEW, 'STALE_REVIEW'
            if decision['question_id'] == QID:
                decision.pop('audit', None)
                decision.update(decision='EDIT', teacher_score=10, previous_teacher_score=15,
                    teacher_reason='因数分解前の式変形が既に誤っているため、0→5点のoverrideを撤回する。',
                    withdrawn_override={'review_id': OLD_REVIEW, 'before': 0, 'after': 5})
                decision['criterion_overrides'] = [
                    {'criterion_id': 'criterion_1_factorization', 'before': 5, 'after': 0,
                     'max_score': 10, 'reason': decision['teacher_reason']},
                    {'criterion_id': 'criterion_2_completing_square', 'before': 10, 'after': 10,
                     'max_score': 10, 'reason': '変更なし。'}]
            else:
                decision['previous_teacher_score'] = 10
        revision['summary'].update(problem2_1_teacher_score=10, problem2_teacher_total=20)
        revision['revision_sha256'] = canonical_hash(revision)
        for decision in revision['decisions']:
            s.add(m.DomainEvent(entity_type='grading_job_item', entity_id=decision['item_id'],
                event_type='teacher_grading_review_revision', actor_user_id=teacher,
                payload={'review_id': REVIEW_ID, 'revision_number': 2,
                    'supersedes_review_id': OLD_REVIEW,
                    'previous_revision_sha256': old['revision_sha256'],
                    'revision_sha256': revision['revision_sha256'],
                    'artifact_ref': f'teacher-review/{REVIEW_ID}.json',
                    'question_id': decision['question_id'], 'decision': decision['decision'],
                    'teacher_score': decision['teacher_score'], 'original_score': decision['original_score'],
                    'provenance': 'TEACHER_EDITED'}))
        s.add(m.DomainEvent(entity_type='grading_review', entity_id=REVIEW_ID,
            event_type='teacher_grading_review_summary', actor_user_id=teacher,
            payload={'revision': revision, 'revision_sha256': revision['revision_sha256'],
                     'problem2_teacher_total': 20, 'supersedes_review_id': OLD_REVIEW}))
        s.flush()
        s.refresh(current)
        assert current.rubric_json == old_rubric
        assert all(fingerprint(s, c) == before[c.__tablename__] for c in protected_models)
        assert all(sha256_file(p) == h for p, h in files.items())
        s.commit()
        # The committed event includes the full revision for safe artifact recovery.
        with path.open('x') as f:
            json.dump(revision, f, ensure_ascii=False, indent=2)
        return {'reused': False, 'revision': revision, 'protected_unchanged': True,
                'old_rubric_content_unchanged': True,
                'old_rubric_status': current.status, 'new_rubric_status': approved.status,
                'model_calls': 0, 'new_grading_jobs': 0}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', default='postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader')
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url), ensure_ascii=False, indent=2))
