"""One synthetic H.3-A submission through the production H.3-B job worker.

Run with --execute only after inspecting the fixture. Existing reconstruction
and source artifacts are never edited. No OCR/reconstruction adapters imported.
"""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy import select

from scoring.db import create_session_factory
from scoring.db import models as m
from scoring.db.worker import JobWorker
from scoring.domain import DomainService
from scoring.grading_context import GradingReadinessService
from scoring.grading_execution import create_execution_job, GradingExecutionRunner
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import canonical_hash, sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile


def rows_hash(session, model, predicate=None):
    query = select(model).order_by(model.id)
    if predicate is not None:
        query = query.where(predicate)
    return canonical_hash([{c.name: str(getattr(row, c.key)) for c in model.__table__.columns}
                           for row in session.scalars(query)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--submission-id', required=True)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--question-import-root', default='artifacts/question-imports')
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit('Explicit --execute required')
    root = Path.cwd().resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output/'report.json'
    if report_path.exists():
        raise SystemExit('A report already exists; do not create a duplicate official result')
    engine, sf = create_session_factory(os.environ['LLM_GRADER_DATABASE_URL'])
    registry = json.loads(Path(args.registry).read_text())
    model = next(x for x in registry['models'] if x['name'] == args.model_id)
    profile = RuntimeProfile.from_mapping('grader', {
        'runtime_type': 'managed', 'model_id': model['name'], 'model_path': model['model'],
        'mmproj_path': model['mmproj'], 'server_binary': model['server'],
        'context_size': model['context'], 'batch_size': model['batch'], 'ubatch_size': model['ubatch'],
        'startup_timeout_seconds': 180, 'stop_timeout_seconds': 10,
        'log_path': str(output/'grader.log'), 'additional_args': ['--reasoning-budget', '0']})
    manager = RuntimeManager({'grader': profile})
    config_path = output/'config.json'
    config_path.write_text(json.dumps({'models': {'grader': {
        'model_id': model['name'], 'base_url': profile.endpoint, 'request_timeout_seconds': 300}},
        'generation': profile.generation}))
    with sf() as s:
        sub = s.get(m.StudentSubmission, args.submission_id)
        test = s.get(m.Test, sub.test_id)
        if test.name != 'H.3-A.2 runtime validation':
            raise ValueError('Synthetic H.3-A.2 validation fixture only')
        questions = list(s.scalars(select(m.TestQuestion).where(m.TestQuestion.test_id == test.id)))
        if len(questions) != 1:
            raise ValueError('One question only')
        q = questions[0]
        recon = s.scalar(select(m.StudentAnswerReconstruction).where(
            m.StudentAnswerReconstruction.submission_id == sub.id))
        if not recon or '2 + 2 = 5' not in recon.answer_text or recon.status != 'COMPLETE':
            raise ValueError('Expected actual wrong-answer reconstruction not found')
        protected_ids = list(s.scalars(select(m.Test.id).where(m.Test.name.like('%sampleQ%'))))
        def protected():
            return {cls.__tablename__: rows_hash(s, cls) for cls in (
                m.TestQuestionCorrection, m.TestQuestionAsset, m.QuestionImportConfirmation,
                m.QuestionImportReviewRevision)} | {
                'sample_questions': rows_hash(s, m.TestQuestion, m.TestQuestion.test_id.in_(protected_ids))}
        # The fixture's old secret-token associations cannot serve as an approved grading rubric.
        # Create explicit teacher-specified reference/rubric versions for this synthetic question.
        before_protected = protected()
        recon_before = rows_hash(s, m.StudentAnswerReconstruction)
        source = s.get(m.TestMaterial, sub.material_id)
        source_sha = sha256_file(Path(source.storage_ref))
        q.max_points = 1
        test.total_points = 1
        d = DomainService(s)
        answer = d.model_answer(test.id, question_id=q.id, answer_text='2 + 2 = 4')
        rubric = d.rubric(test.id, {'questions': [{'question_id': q.id, 'max_points': 1,
            'criteria': [{'id': 'final-answer', 'points': 1,
                'description': '最終回答が4なら1点。それ以外は0点。途中式への部分点はない。',
                'levels': [{'score': 0, 'condition': '最終回答が4ではない。'},
                           {'score': 1, 'condition': '最終回答が4である。'}]}]}]})
        owner = s.get(m.Course, s.get(m.CourseOffering, test.course_offering_id).course_id).owner_user_id
        d.approve_rubric(rubric.id, owner)
        s.commit()
        s.refresh(q)
        baseline = {'question': rows_hash(s, m.TestQuestion, m.TestQuestion.id == q.id),
            'reconstruction': rows_hash(s, m.StudentAnswerReconstruction),
            'model_answer': rows_hash(s, m.ModelAnswer, m.ModelAnswer.test_id == test.id),
            'rubric': rows_hash(s, m.RubricVersion, m.RubricVersion.test_id == test.id),
            'source_sha256': source_sha}
        assert baseline['reconstruction'] == recon_before
        preview = GradingInputAssembler(s, test.id, root=root, allowed_roots=[root]).evaluate(sub.id)
        assert preview['can_build_all_inputs'], preview
        job = create_execution_job(s, test.id, sub.id, q.id, run_path=output/'run',
            config_path=config_path, root=root, allowed_roots=[root])
        s.add(m.GradingJobEvent(job_id=job.id, event_type='job_created', new_state='queued'))
        s.commit()
        job_id = job.id
        assert job.metadata_json['grading_execution']['bundle'] == preview['questions'][0]['bundle']
        report = {'job_id': job_id, 'test_id': test.id, 'question_id': q.id, 'submission_id': sub.id,
            'reconstruction_id': recon.id, 'reconstruction_sha256': recon.output_sha256,
            'model_answer_id': answer.id, 'model_answer_version': answer.version,
            'rubric_id': rubric.id, 'before': baseline, 'protected_before': before_protected,
            'preview': preview, 'source_page_sha256': preview['questions'][0]['bundle']['student_answer']['source_pages'],
            'calls': {'ricoh': 0, 'unimumer': 0, 'ornith_reconstruction': 0},
            'status': 'created'}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    worker = JobWorker(sf, grading_runner_factory=lambda: GradingExecutionRunner(manager))
    try:
        worker.run_once(job_id)
    finally:
        report['runtime'] = manager.status('grader')
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    with sf() as s:
        job = s.get(m.GradingJob, job_id)
        item = job.items[0]
        report.update(status=job.state, item_id=item.id, score=item.score, max_points=item.max_score,
            normalized_result_hash=item.normalized_result_hash, result=item.metadata_json,
            snapshot=job.metadata_json['grading_execution'])
        report['after'] = {'question': rows_hash(s, m.TestQuestion, m.TestQuestion.id == q.id),
            'reconstruction': rows_hash(s, m.StudentAnswerReconstruction),
            'model_answer': rows_hash(s, m.ModelAnswer, m.ModelAnswer.test_id == test.id),
            'rubric': rows_hash(s, m.RubricVersion, m.RubricVersion.test_id == test.id),
            'source_sha256': sha256_file(Path(source.storage_ref))}
        report['protected_after'] = protected()
        report['sample_readiness'] = [GradingReadinessService(s, root=Path(args.question_import_root)).evaluate(tid)
                                      for tid in protected_ids]
        report['calls']['ornith_grading'] = len(list((output/'run').rglob('grading.*.raw.json')))
        assert report['before'] == report['after']
        assert report['protected_before'] == report['protected_after']
        assert job.state == 'completed' and item.score == 0 and item.max_score == 1
        assert worker.run_once(job_id) is None
        # Exercise the completed artifact resume path without another model call.
        GradingExecutionRunner(manager).run(job)
        s.rollback()
        report['resume'] = 'same snapshot, no further model call'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:report[k] for k in ['job_id','status','score','max_points','calls','resume']}, indent=2))


if __name__ == '__main__':
    main()
