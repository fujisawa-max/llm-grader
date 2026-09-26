"""Selected Q4 s2 preflight only. Never creates a grading job."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from scoring.core import write_json
from scoring.pdf_native import sha256_file
from scoring.student_answer_runtime import RuntimeStudentAnswerStages
import run_h3d0_selected_reconstruction as setup
from sqlalchemy import select
from scoring.db import create_session_factory
from scoring.db import models as m
from scoring.pdf_native import canonical_hash
from scoring.student_answer import SelectedImageStudentAnswerReconstruction
from scoring.student_visual import StudentVisualAssetService, safe_file

OUT = Path('artifacts/h3e0a').resolve()
SUB = 'a3f18d80-78a7-41b1-9b07-9db3fe3056e6'
TEST = 'e14aeeb5-924c-4c72-b2a2-583f1be9f48e'
Q1 = '02669a76-cb99-4ea1-bfd4-c742ff1617a3'
Q2 = '705f1d12-4f19-4c33-b197-39212f24b3ca'
SHA = 'dd89f67075824aff671081c57916f25e21093b92cbf9e66d3d46fe5bd823c9f8'
SOURCE = Path(f'artifacts/student-submissions/{TEST}/{SHA}.png').resolve()
ARTIFACT_ROOT = Path('artifacts').resolve()
QUESTION_ROOT = ARTIFACT_ROOT / 'h2b-verification'


def protected(session):
    return {cls.__tablename__: canonical_hash([
        {c.name: str(getattr(row, c.name)) for c in cls.__table__.columns}
        for row in session.scalars(select(cls).order_by(cls.id))])
        for cls in [m.Test, m.TestQuestion, m.ModelAnswer, m.RubricVersion,
                    m.TestQuestionAsset, m.TestQuestionCorrection, m.QuestionImportConfirmation,
                    m.GradingJob, m.GradingJobItem, m.StudentSubmission]}


def extract(folder, stages, config):
    layout_path = OUT / 'ricoh-72dbc78c-a0ad-4fa9-9b86-5f9f4602fbf0/validated-layout.json'
    layout = json.loads(layout_path.read_text())
    reviewed = json.loads(json.dumps(layout))
    # Original-pixel inspection corrected Ricoh's spatial coverage, not its units.
    # Both crops were inspected before formula OCR: no answer text is edited.
    reviewed['formula_regions'][0]['bbox'] = [0.14, 0.506, 0.445, 0.684]
    reviewed['visual_regions'][0]['bbox'] = [0.50, 0.442, 0.98, 0.68]
    provenance = {'method': 'original_source_visual_coverage_review',
                  'layout_sha256': sha256_file(layout_path), 'original_layout': layout,
                  'reviewed_layout': reviewed,
                  'reason': 'include complete handwriting/axes and exclude Problem 3; no unit conversion',
                  'reviewer': 'assistant_visual_inspection', 'teacher_accepted': False}
    write_json(folder / 'region-coverage-review.json', provenance)
    _, sf = create_session_factory(setup.DATABASE_URL)
    with sf() as session:
        baseline = protected(session)
        write_json(folder / 'baseline.json', baseline)
        sub = session.get(m.StudentSubmission, SUB)
        assert sub.test_id == TEST
        assert session.get(m.TestMaterial, sub.material_id).sha256 == SHA
        for qid in (Q1, Q2):
            q = session.get(m.TestQuestion, qid)
            assert q.test_id == TEST and q.is_gradable
        asset = StudentVisualAssetService(session, ARTIFACT_ROOT).register(
            SUB, Q2, reviewed['visual_regions'][0]['bbox'], source_sha=SHA,
            provenance=provenance, verified=True)
        session.commit()
        write_json(folder / 'student-asset.json', asset)
        def images(payload):
            return [(i['page_id'], safe_file(ARTIFACT_ROOT, i['artifact_ref'], i['sha256']))
                    for i in payload['source_answer']['evidence_images']]
        stages.image_resolver = images
        def cached_ricoh(source, question_id):
            assert question_id == Q1 and sha256_file(source) == SHA
            return json.loads((layout_path.parent / 'raw.json').read_text()), {
                **reviewed, 'visual_regions': [], 'text_blocks': []}
        service = SelectedImageStudentAnswerReconstruction(
            session, artifact_root=ARTIFACT_ROOT, question_root=QUESTION_ROOT)
        run, output = service.run(SUB, Q1, ricoh=cached_ricoh,
            unimumer=stages.unimumer, ornith_reconstruction=stages.ornith_reconstruction,
            config={'phase': 'H.3-E.0a', 'question_id': Q1,
                    'layout_sha256': canonical_hash(reviewed), 'reconstruction_images': 'formula_crops',
                    'generation': config, 'review_provenance': provenance})
        session.commit()
        assert protected(session) == baseline
        recon = session.scalar(select(m.StudentAnswerReconstruction).where(
            m.StudentAnswerReconstruction.submission_id == SUB,
            m.StudentAnswerReconstruction.question_id == Q1).order_by(m.StudentAnswerReconstruction.version.desc()))
        report = {'run_id': run.id, 'reconstruction_id': recon.id, 'version': recon.version,
                  'output': output, 'asset': asset, 'protected_unchanged': True,
                  'source_before_after': SHA}
        write_json(folder / 'extraction.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)


def preview():
    from scoring.grading_mapping import GradingInputAssembler
    from scoring.grading_execution import execution_rubric, validate_bundle
    _, sf = create_session_factory(setup.DATABASE_URL)
    capability = json.loads((OUT / 'capability.json').read_text())
    with sf() as session:
        assembler = GradingInputAssembler(session, TEST, root=QUESTION_ROOT,
            allowed_roots=[ARTIFACT_ROOT], answer_root=ARTIFACT_ROOT,
            reference_root=ARTIFACT_ROOT / 'h3c1-model-answer', visual_capability=capability)
        rows = []
        for qid in (Q1, Q2):
            row = assembler.execution_preview(SUB, qid)
            part = assembler.question_part(qid)
            try:
                execution_rubric(part)
                rubric_validation = 'PASS'
            except ValueError as exc:
                rubric_validation = str(exc)
            bundle_validation = 'NO_BUNDLE'
            if row['bundle']:
                validate_bundle(row['bundle'])
                bundle_validation = 'PASS'
            rows.append({'question_id': qid, 'preview': row, 'rubric_validation': rubric_validation,
                         'bundle_validation': bundle_validation, 'question_part': part})
        baselines = list(OUT.glob('extract-*/baseline.json'))
        unchanged = all(protected(session) == json.loads(p.read_text()) for p in baselines)
        assert unchanged
        report = {'rows': rows, 'protected_unchanged': unchanged, 'source_sha256': sha256_file(SOURCE),
                  'job_created': 0, 'grading_calls': 0}
        write_json(OUT / 'preflight.json', report)
        print(json.dumps([{k: r[k] for k in ('question_id', 'rubric_validation', 'bundle_validation')} |
                         {'state': r['preview']['state'], 'execution_state': r['preview']['execution_state'],
                          'blockers': r['preview']['blockers'],
                          'bundle_sha': (r['preview']['bundle'] or {}).get('bundle_sha256')} for r in rows],
                         ensure_ascii=False), flush=True)


def stages_for(folder):
    setup.AUDIT_DIR = folder
    manager, config = setup.runtime_setup()
    events = []

    def audit(event):
        # Raw source-bearing request artifacts remain private in artifact storage.
        events.append(event)
        write_json(folder / f'event-{len(events):04d}.json', event)

    stages = RuntimeStudentAnswerStages(manager, config, audit=audit)
    return stages, manager, config, events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['ricoh', 'extract', 'preview'])
    args = parser.parse_args()
    assert sha256_file(SOURCE) == SHA
    if args.stage == 'preview':
        preview()
        return
    folder = OUT / f'{args.stage}-{uuid4()}'
    folder.mkdir(parents=True)
    stages, manager, config, events = stages_for(folder)
    try:
        if args.stage == 'extract':
            extract(folder, stages, config)
            return
        raw, normalized = stages.ricoh_regions(SOURCE, [
            {'question_id': Q1, 'label': 'Problem 2 (1)', 'answer_type': 'handwritten calculations'},
            {'question_id': Q2, 'label': 'Problem 2 (2)', 'answer_type': 'student graph canvas'},
        ])
        write_json(folder / 'validated-layout.json', normalized)
        write_json(folder / 'raw.json', raw)
        print(json.dumps({'folder': str(folder), 'layout': normalized}, ensure_ascii=False), flush=True)
    finally:
        assert sha256_file(SOURCE) == SHA
        write_json(folder / 'audit.json', {'calls': [e['role'] for e in events if e['event'] == 'call'],
                   'runtimes': manager.statuses(), 'source_sha256': SHA, 'config': config})


if __name__ == '__main__':
    main()
