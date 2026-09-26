"""Apply the explicit Q3 Problem 3 source typo correction append-only."""
import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.domain import DomainService
from scoring.grading_execution import execution_rubric
from scoring.pdf_native import canonical_hash

TEST = '8df4ed72-9297-4082-bb21-1fdb6c500557'
QID = '7fcbd8ee-1eee-4d93-a195-59ea995a0385'
ACTOR = '99d3a635-8c60-47a4-99d8-aa11e4efe176'
ANSWER = r'''答は y = a cos(α(x−β)) + b という形になる。
ここで、yの値の最大最少は +3, −3であるため、y軸方向の移動はなく、b=0である(5点)。また、このことから振幅が3であることがわかり、a=3である(5点)。さらに、周期は2πであるため、α=1である(5点)。そして、本来、y=cos xにおいて、x=0ではy=1となるところがこのグラフではy=0となっていることから、x軸方向のずれについては、β=−π/2と読み取れる(5点)。
以上から関数の式は以下である（20点）。
y = 3 cos(x + π/2)
Teacher correction: source terminal expression omitted the amplitude coefficient 3; a=3 is authoritative.'''


def run(url):
    _, sf = create_session_factory(url)
    with sf() as s:
        q = s.get(m.TestQuestion, QID)
        s.execute(select(m.Test).where(m.Test.id == TEST).with_for_update()).scalar_one()
        old_ma = s.scalar(select(m.ModelAnswer).where(m.ModelAnswer.question_id == QID,
            m.ModelAnswer.is_current.is_(True)))
        old_rubric = s.scalar(select(m.RubricVersion).where(m.RubricVersion.test_id == TEST,
            m.RubricVersion.status == 'approved'))
        old_ma_sha = canonical_hash(old_ma.answer_text)
        old_rubric_sha = canonical_hash(old_rubric.rubric_json)
        domain = DomainService(s)
        new_ma = domain.model_answer(TEST, question_id=QID, material_id=old_ma.material_id,
            answer_text=ANSWER)
        ma_payload = {'old_id': old_ma.id, 'old_sha256': old_ma_sha, 'new_id': new_ma.id,
            'new_version': new_ma.version, 'new_sha256': canonical_hash(ANSWER),
            'source_correction': 'source typo: omitted amplitude coefficient 3',
            'authoritative_formula': 'y = 3 cos(x + π/2)'}
        s.add(m.DomainEvent(entity_type='model_answer', entity_id=new_ma.id,
            event_type='teacher_model_answer_correction', actor_user_id=ACTOR,
            payload=ma_payload))
        rubric = deepcopy(old_rubric.rubric_json)
        entry = next(item for item in rubric['questions'] if item['question_id'] == QID)
        descriptions = [
            '上下移動がなく、b=0であることを正しく読み取っている。',
            'グラフの振幅からa=3を正しく読み取っている。',
            '周期からα=1を正しく読み取っている。',
            'x軸方向の移動からβ=−π/2を正しく読み取っている。',
            '最終式 y = 3 cos(x + π/2) を正しく記述している。',
        ]
        for criterion, description in zip(entry['criteria'], descriptions, strict=True):
            criterion['description'] = description
            criterion['levels'] = [{'score': criterion['points'], 'condition': description},
                                   {'score': 0, 'condition': '当該criterionの満点条件を満たさない。'}]
            criterion['source_kind'] = 'TEACHER_EDITED'
            criterion['provenance'] = 'TEACHER_EDITED'
            criterion['teacher_reviewed'] = True
            criterion['review_required'] = False
        entry['model_answer_sha256'] = canonical_hash(ANSWER)
        entry['teacher_clarification'] = {
            'source_typo_corrected': True, 'source_terminal_expression': 'y = cos(x + π/2)',
            'authoritative_expression': 'y = 3 cos(x + π/2)', 'provenance': 'TEACHER_EDITED',
            'teacher_user_id': ACTOR}
        execution_rubric({'rubric': {'entry': entry}, 'question': {'max_points': q.max_points}})
        new_rubric = domain.rubric(TEST, rubric, source_type='teacher_reviewed',
            rubric_text='Q3 Problem 3 teacher correction of source amplitude typo',
            generated_by_model=None, generation_metadata={
                'phase': 'H.3-F.2', 'teacher_decision': True,
                'base_rubric_version_id': old_rubric.id, 'model_answer_id': new_ma.id})
        domain.approve_rubric(new_rubric.id, ACTOR)
        s.add(m.DomainEvent(entity_type='rubric', entity_id=new_rubric.id,
            event_type='teacher_q3_problem3_correction', actor_user_id=ACTOR,
            payload={'old_rubric_id': old_rubric.id, 'new_rubric_id': new_rubric.id,
                     'old_rubric_sha256': old_rubric_sha, 'new_rubric_sha256': canonical_hash(rubric),
                     'model_answer_id': new_ma.id, 'authoritative_expression': 'y = 3 cos(x + π/2)'}))
        s.commit()
        return {'old_model_answer_id': old_ma.id, 'old_model_answer_sha256': old_ma_sha,
            'new_model_answer_id': new_ma.id, 'new_model_answer_version': new_ma.version,
            'new_model_answer_sha256': canonical_hash(ANSWER), 'old_rubric_id': old_rubric.id,
            'old_rubric_sha256': old_rubric_sha, 'new_rubric_id': new_rubric.id,
            'new_rubric_version': new_rubric.version, 'new_rubric_sha256': canonical_hash(rubric),
            'validator': 'PASS', 'model_calls': 0, 'grading_jobs': 0}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--database-url', default='postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader')
    result = run(p.parse_args().database_url)
    Path('artifacts/h3f2-remediation/q3p3-decision.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
