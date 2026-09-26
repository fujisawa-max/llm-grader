"""Normalize only the IDs and Q2 score levels explicitly authorized in H.3-F.1."""
import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.domain import DomainService
from scoring.grading_execution import execution_rubric
from scoring.pdf_native import canonical_hash

ACTOR = '99d3a635-8c60-47a4-99d8-aa11e4efe176'
PHASE = 'H.3-F.1'


def normalize(entry, sample, label):
    result = deepcopy(entry)
    mapping = {}
    fix_ids = label in {'1.1', '1.2', '3.2', '3.3'} and sample == 'sampleQ1'
    fix_ids |= sample == 'sampleQ2' and label in {'1.1', '1.2'}
    for index, criterion in enumerate(result['criteria'], 1):
        if fix_ids:
            old = criterion['id']
            criterion['id'] = old.replace('.', '_')
            mapping[old] = criterion['id']
        if sample != 'sampleQ2':
            continue
        levels = [{'score': criterion['points'], 'condition': criterion['description']}]
        partial = criterion.get('partial_credit_conditions')
        if partial:
            levels.append({'score': 5 if label in {'1.1', '1.2'} else 10,
                           'condition': partial})
        zero = ('有効な途中過程がない' if label in {'1.1', '1.2'} and index == 1
                else '全ての解が正しいという条件を満たさない' if label in {'1.1', '1.2'}
                else '満点条件・部分点条件のいずれも満たさない')
        levels.append({'score': 0, 'condition': zero})
        criterion['levels'] = levels
    return result, mapping


def fingerprint(session, model):
    return canonical_hash(json.loads(json.dumps([
        {c.name: getattr(r, c.key) for c in model.__table__.columns}
        for r in session.scalars(select(model).order_by(model.id))], default=str)))


def run(url):
    audit = json.loads(Path('artifacts/h3f-readiness-audit/audit.json').read_text())
    targets = [q for q in audit['questions'] if q['sample'] == 'sampleQ2' or
               (q['sample'] == 'sampleQ1' and q['label'] in {'1.1','1.2','3.2','3.3'})]
    _, factory = create_session_factory(url)
    with factory() as s:
        protected = (m.TestQuestion, m.ModelAnswer, m.GradingJob, m.GradingJobItem,
                     m.StudentAnswerReconstruction, m.StudentSubmission)
        before = {c.__tablename__: fingerprint(s, c) for c in protected}
        old_content = {r.id: canonical_hash(r.rubric_json) for r in s.scalars(select(m.RubricVersion))}
        report = []
        for q in targets:
            question = s.get(m.TestQuestion, q['id'])
            s.execute(select(m.Test).where(m.Test.id == question.test_id).with_for_update()).scalar_one()
            prior = s.scalar(select(m.DomainEvent).where(m.DomainEvent.entity_id == q['id'],
                m.DomainEvent.event_type == 'h3f1_rubric_normalized'))
            if prior:
                report.append({**prior.payload, 'reused': True})
                continue
            current = s.scalar(select(m.RubricVersion).where(
                m.RubricVersion.test_id == question.test_id, m.RubricVersion.status == 'approved'))
            data = deepcopy(current.rubric_json)
            index = next(i for i, e in enumerate(data['questions']) if e['question_id'] == q['id'])
            entry, mapping = normalize(data['questions'][index], q['sample'], q['label'])
            data['questions'][index] = entry
            if q['sample'] == 'sampleQ2':
                execution_rubric({'rubric': {'entry': entry}, 'question': {'max_points': question.max_points}})
            metadata = {'phase': PHASE, 'base_rubric_version_id': current.id,
                        'question_id': q['id'], 'id_mapping': mapping,
                        'levels_source': 'existing H.3-C.1 explicit Teacher clarification' if q['sample'] == 'sampleQ2' else None,
                        'new_scoring_policy': False}
            domain = DomainService(s)
            created = domain.rubric(question.test_id, data, source_type='teacher_reviewed',
                rubric_text='H.3-F.1 authorized production normalization',
                generation_metadata=metadata, generated_by_model=None)
            domain.approve_rubric(created.id, ACTOR)
            row = {'sample': q['sample'], 'question': q['label'], 'question_id': q['id'],
                   'old': current.id, 'new': created.id, 'version': created.version,
                   'id_mapping': mapping, 'levels_fix': q['sample'] == 'sampleQ2',
                   'rubric_sha256': canonical_hash(data)}
            s.add(m.DomainEvent(entity_type='question', entity_id=q['id'],
                event_type='h3f1_rubric_normalized', actor_user_id=ACTOR, payload=row))
            s.flush()
            report.append(row)
        assert all(fingerprint(s, c) == before[c.__tablename__] for c in protected)
        assert all(canonical_hash(s.get(m.RubricVersion, rid).rubric_json) == h for rid,h in old_content.items())
        s.commit()
        return {'changes':report,'old_contents_unchanged':True,'protected_unchanged':True,
                'new_versions':sum(not row.get('reused',False) for row in report),'model_calls':0,'new_jobs':0}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--database-url',default='postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader')
    print(json.dumps(run(parser.parse_args().database_url),ensure_ascii=False,indent=2))
