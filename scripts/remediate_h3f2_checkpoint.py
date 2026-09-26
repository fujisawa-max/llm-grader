"""Apply authorized H.3-F.2 changes, deferring Q3 Problem 3 to its checkpoint."""
import json
from copy import deepcopy
from pathlib import Path

import pymupdf
from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.domain import DomainService
from scoring.grading_execution import execution_rubric
from scoring.pdf_native import canonical_hash, sha256_file
from remediate_h3f1_rubrics import fingerprint

ACTOR = '99d3a635-8c60-47a4-99d8-aa11e4efe176'
ROOT = Path('artifacts/h3f2-remediation')
SOURCE = Path('testData/SampleQ/modelAnswer/sampleQ3_modelAnswer.pdf')
DESCRIPTIONS = {
    ('sampleQ1', '1.1'): ['汎用型AIが特定の目的に限定されず幅広い課題をこなせることを説明している。',
        '特化型AIが特定の問題・課題を処理することを説明している。',
        '汎用型AIはほぼ存在しない、又は現在のAIのほとんどは特化型AIであることを説明している。'],
    ('sampleQ1', '1.2'): ['強いAIについて説明している。', '弱いAIについて説明している。',
        '強い・弱いAIと汎用型・特化型AIは本来異なる分類軸であることを説明している。',
        'これらの分類には実体として相関があることを説明している。'],
    ('sampleQ1', '2'): ['人間の脳を数学的にモデル化したことを説明している。',
        'ニューロンが入力に重みをかけて次のニューロンへ渡し、それらが組み合わさってネットワークになることを説明している。',
        '深層ニューラルネットワークや生成AI、LLMなどについて記述している。'],
    ('sampleQ1', '3.2'): ['正解ラベルのない入力データから特徴などを抽出することを説明している。',
        'クラスタリングなどの事例を記述している。'],
    ('sampleQ1', '3.3'): ['エージェントが環境に対して行動して報酬を得る循環を説明している。',
        '試行錯誤しながら最終的な報酬を大きくするために行動を変えることを説明している。'],
    ('sampleQ3', '1'): ['指定の公式を正しく使っている。', 'πの計算が正しくできている。',
        '答がsourceの最終解答と一致している。'],
    ('sampleQ3', '2'): ['適切な引き算に変形している。sourceに示された別解も認める。',
        '公式に従って変形している。', '答がsourceの最終解答と一致している。'],
}
TRANSCRIPTIONS = {
    '1': r'''\sin\frac{5\pi}{12}+\sin\frac{\pi}{12}
=2\sin\frac{\frac{5\pi}{12}+\frac{\pi}{12}}{2}\cos\frac{\frac{5\pi}{12}-\frac{\pi}{12}}{2}
=2\sin\frac{\frac{6\pi}{12}}{2}\cos\frac{\frac{4\pi}{12}}{2}=2\sin\frac{\pi}{4}\cos\frac{\pi}{6}
=2\times\frac{\sqrt{2}}{2}\times\frac{\sqrt{3}}{2}=\frac{\sqrt{6}}{2}''',
    '2': r'''\cos\frac{\pi}{12}
=\cos\left(\frac{4\pi}{12}-\frac{3\pi}{12}\right)=\cos\left(\frac{\pi}{3}-\frac{\pi}{4}\right)
=\cos\frac{\pi}{3}\cos\frac{\pi}{4}+\sin\frac{\pi}{3}\sin\frac{\pi}{4}
=\frac{1}{2}\times\frac{\sqrt{2}}{2}+\frac{\sqrt{3}}{2}\times\frac{\sqrt{2}}{2}
=\frac{\sqrt{2}}{4}+\frac{\sqrt{6}}{4}
=\frac{\sqrt{2}+\sqrt{6}}{4}

別解としてsourceに明示された変形:
\cos\frac{\pi}{12}=\cos\left(\frac{9\pi}{12}-\frac{8\pi}{12}\right)=\cos\left(\frac{3\pi}{4}-\frac{2\pi}{3}\right)
\cos\frac{\pi}{12}=\cos\left(\frac{16\pi}{12}-\frac{15\pi}{12}\right)=\cos\left(\frac{4\pi}{3}-\frac{5\pi}{4}\right)''',
}


def run(url):
    source_sha = sha256_file(SOURCE)
    assert source_sha == '4d467b25503a94d6a9fbb66501639df179abbfcdbe99c37dcd23951609fc9d9d'
    prior = json.loads(Path('artifacts/h3f1-remediation/report.json').read_text())
    targets = [q for q in prior['reaudit']['questions'] if q['final'] == 'BLOCKED'
               and (q['sample'], q['label']) != ('sampleQ3', '3')]
    ROOT.mkdir(exist_ok=True)
    doc = pymupdf.open(SOURCE)
    page = doc[0]
    evidence = {}
    for label, box in [('1',(105,230,520,340)), ('2',(105,411,520,574))]:
        crop = ROOT / f'q3-p{label}-source.png'
        if not crop.exists():
            page.get_pixmap(matrix=pymupdf.Matrix(2,2),clip=pymupdf.Rect(box)).save(crop)
        evidence[label] = {'source_sha256': source_sha,'source_filename':SOURCE.name,'page':1,
            'bbox':[box[0]/page.rect.width,box[1]/page.rect.height,box[2]/page.rect.width,box[3]/page.rect.height],
            'coordinate_space':'normalized','crop_sha256':sha256_file(crop),
            'native_text':page.get_text(clip=pymupdf.Rect(box)),
            'method':'source_visual_verified_latex_transcription',
            'scoring_notes_separate':True,'model_calls':0}
    _,sf = create_session_factory(url)
    with sf() as s:
        protected=(m.TestQuestion,m.GradingJob,m.GradingJobItem,m.StudentAnswerReconstruction,m.StudentSubmission)
        before={c.__tablename__:fingerprint(s,c) for c in protected}
        old_rubrics={r.id:canonical_hash(r.rubric_json) for r in s.scalars(select(m.RubricVersion))}
        old_answers={r.id:canonical_hash(r.answer_text) for r in s.scalars(select(m.ModelAnswer))}
        changes=[]
        for q in targets:
            question=s.get(m.TestQuestion,q['id'])
            s.execute(select(m.Test).where(m.Test.id==question.test_id).with_for_update()).scalar_one()
            previous=s.scalar(select(m.DomainEvent).where(m.DomainEvent.entity_id==q['id'],m.DomainEvent.event_type=='h3f2_checkpoint_remediated'))
            if previous:
                changes.append({**previous.payload,'reused':True})
                continue
            domain=DomainService(s)
            ma_change=None
            if q['sample']=='sampleQ3':
                old=s.scalar(select(m.ModelAnswer).where(m.ModelAnswer.question_id==q['id'],m.ModelAnswer.is_current.is_(True)))
                answer=TRANSCRIPTIONS[q['label']]
                assert '\\\\' not in answer
                new=domain.model_answer(question.test_id,question_id=q['id'],material_id=old.material_id,answer_text=answer)
                ma_change={'old':old.id,'old_sha256':canonical_hash(old.answer_text),'new':new.id,
                    'version':new.version,'sha256':canonical_hash(new.answer_text),'source':evidence[q['label']]}
                s.add(m.DomainEvent(entity_type='model_answer',entity_id=new.id,event_type='h3f2_source_extraction_repaired',
                    actor_user_id=ACTOR,payload=ma_change))
            current=s.scalar(select(m.RubricVersion).where(m.RubricVersion.test_id==question.test_id,m.RubricVersion.status=='approved'))
            data=deepcopy(current.rubric_json)
            entry=next(e for e in data['questions'] if e['question_id']==q['id'])
            desc=DESCRIPTIONS.get((q['sample'],q['label']))
            for i,c in enumerate(entry['criteria']):
                if desc:
                    c['description']=desc[i]
                assert not c.get('partial_credit_conditions'), 'UNEXPECTED_EXPLICIT_PARTIAL_CREDIT'
                c['levels']=[{'score':c['points'],'condition':c['description']},
                             {'score':0,'condition':'当該criterionの満点条件を満たさない。'}]
                c['source_kind']='TEACHER_EDITED'
                c['provenance']='TEACHER_EDITED'
                c['teacher_reviewed']=True
                c['review_required']=False
                c['teacher_clarification']={'phase':'H.3-F.2','policy':'sourceにcriterion内の部分点指定がない場合、満点／0点の二値採点。',
                    'base_rubric_version_id':current.id,'description_source':'original model-answer PDF scoring memo'}
            if ma_change:
                entry['model_answer_sha256']=ma_change['sha256']
            if q['sample']=='sampleQ3' and q['label']=='2':
                entry['source_format_note']='分母に混合が残っていてもよいものとする'
                entry['source_format_note_interpretation']='原文維持。誤記と推定して別の文言に変更していない。'
            execution_rubric({'rubric':{'entry':entry},'question':{'max_points':question.max_points}})
            created=domain.rubric(question.test_id,data,source_type='teacher_reviewed',
                rubric_text='H.3-F.2 source criterion and authorized binary levels',
                generated_by_model=None,generation_metadata={'phase':'H.3-F.2','base_rubric_version_id':current.id,'question_id':q['id']})
            domain.approve_rubric(created.id,ACTOR)
            change={'sample':q['sample'],'question':q['label'],'question_id':q['id'],'old_rubric':current.id,
                'new_rubric':created.id,'version':created.version,'criteria':len(entry['criteria']),
                'levels':[[level['score'] for level in c['levels']] for c in entry['criteria']],
                'model_answer':ma_change,'validator':'PASS'}
            s.add(m.DomainEvent(entity_type='question',entity_id=q['id'],event_type='h3f2_checkpoint_remediated',actor_user_id=ACTOR,payload=change))
            s.flush()
            changes.append(change)
        assert all(fingerprint(s,c)==before[c.__tablename__] for c in protected)
        assert all(canonical_hash(s.get(m.RubricVersion,rid).rubric_json)==h for rid,h in old_rubrics.items())
        assert all(canonical_hash(s.get(m.ModelAnswer,rid).answer_text)==h for rid,h in old_answers.items())
        assert sha256_file(SOURCE)==source_sha
        s.commit()
        return {'changes':changes,'old_contents_unchanged':True,'protected_unchanged':True,
            'q3_problem3':'DEFERRED_TEACHER_DECISION','model_calls':0,'new_jobs':0}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--database-url',default='postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader')
    result=run(p.parse_args().database_url)
    (ROOT/'checkpoint.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
