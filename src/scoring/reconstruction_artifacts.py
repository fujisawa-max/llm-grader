"""Append-only teacher reconstruction artifacts and explicit legacy repair."""
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .db import models as m
from .pdf_native import canonical_hash, sha256_file

EVENT = 'reconstruction_artifact_repaired'


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2)
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('RECONSTRUCTION_ARTIFACT_CONFLICT')
    else:
        with path.open('x') as stream:
            stream.write(data)


def binding(revision):
    return {k: getattr(revision, k) for k in (
        'id', 'submission_id', 'question_id', 'version', 'source_sha256',
        'context_sha256', 'status', 'answer_text', 'output_sha256', 'artifact_ref')}


def source_input(session, revision):
    sub = session.get(m.StudentSubmission, revision.submission_id)
    q = session.get(m.TestQuestion, revision.question_id)
    mat = session.get(m.TestMaterial, sub.material_id)
    if q.test_id != sub.test_id or mat.test_id != sub.test_id:
        raise ValueError('RECONSTRUCTION_SOURCE_IDENTITY_MISMATCH')
    if mat.sha256 != revision.source_sha256 or sha256_file(Path(mat.storage_ref)) != mat.sha256:
        raise ValueError('RECONSTRUCTION_SOURCE_HASH_MISMATCH')
    return {'source_answer': {'submission_id': sub.id, 'question_id': q.id,
        'student_id': sub.student_id, 'source_sha256': mat.sha256,
        'source_material_id': mat.id,
        'pages': [{'page_id': f'submission-source-{mat.sha256[:16]}',
                   'sha256': mat.sha256, 'mime_type': mat.mime_type or 'image/png'}]}}


def load_repaired(session, revision, root):
    event = session.scalar(select(m.DomainEvent).where(
        m.DomainEvent.entity_id == revision.id, m.DomainEvent.event_type == EVENT))
    if event is None:
        return None
    meta = event.payload
    if meta['binding'] != binding(revision):
        raise ValueError('RECONSTRUCTION_REPAIR_BINDING_MISMATCH')
    path = (Path(root).resolve() / meta['artifact_ref']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or sha256_file(path) != meta['sha256']:
        raise ValueError('RECONSTRUCTION_REPAIR_HASH_MISMATCH')
    value = json.loads(path.read_text())
    if value['binding'] != meta['binding']:
        raise ValueError('RECONSTRUCTION_REPAIR_BINDING_MISMATCH')
    return value


def ensure_reconstruction_artifact(session, revision_id, root):
    """Seal missing legacy evidence in a new sidecar; never rewrite old files."""
    r = session.get(m.StudentAnswerReconstruction, revision_id)
    if r is None:
        raise ValueError('RECONSTRUCTION_NOT_FOUND')
    existing = load_repaired(session, r, root)
    if existing:
        return existing, False
    folder = Path(root) / r.artifact_ref
    try:
        normalized = json.loads((folder / 'reconstruction.json').read_text())
        inp = json.loads((folder / 'reconstruction-input.json').read_text())
        if (normalized.get('output_sha256') == r.output_sha256
                == canonical_hash({k: v for k, v in normalized.items() if k != 'output_sha256'})
                and normalized.get('answer_text') == r.answer_text
                and normalized.get('question_id') == r.question_id
                and normalized.get('status') == r.status
                and inp.get('source_answer') == source_input(session, r)['source_answer']):
            return {'binding': binding(r), 'input': inp, 'normalized': normalized,
                    'source_provenance': {'source_sha256': r.source_sha256,
                        'base_artifact_ref': r.artifact_ref}}, False
    except (OSError, ValueError, KeyError):
        pass
    # Legacy model-produced revisions can also be missing their sidecar after
    # an interrupted import.  Repair seals the existing immutable revision;
    # it must not be limited to teacher-origin records.  Teacher-origin is a
    # requirement for *creating* a new transcription, not for repairing the
    # artifact invariant of an already persisted revision.
    identity = r.model_identity or {}
    inp = source_input(session, r)
    folder = Path(root) / r.artifact_ref
    old_files = {p.name: sha256_file(p) for p in folder.glob('*.json')}
    regions = []
    for p in (Path(root) / 'student-answer/page-extraction' / r.submission_id).glob('*.json'):
        try:
            doc = json.loads(p.read_text())
            for region in doc.get('regions', []):
                if region.get('question_ref') == r.question_id:
                    regions.append({'bbox': region.get('bbox'), 'coordinate_space': 'normalized',
                                    'evidence_artifact': str(p.relative_to(root)),
                                    'evidence_sha256': sha256_file(p), 'verified_by_repair': False})
        except (ValueError, TypeError):
            continue
    normalized = {'schema_version': 'student-answer-reconstruction.v1',
        'question_id': r.question_id, 'answer_text': r.answer_text, 'status': r.status,
        'segments': [], 'uncertainties': [], 'source_refs': [],
        'origin': identity.get('origin', identity.get('provenance')),
        'revision_id': r.id, 'version': r.version,
        'historical_output_sha256': r.output_sha256}
    normalized['output_sha256'] = canonical_hash(normalized)
    value = {'binding': binding(r), 'input': inp, 'normalized': normalized,
        'source_provenance': {'material_id': inp['source_answer']['source_material_id'],
            'source_sha256': r.source_sha256, 'region_evidence': regions,
            'bbox_status': 'HISTORICAL_EVIDENCE_ONLY' if regions else 'NOT_RECORDED',
            'historical_files': old_files}, 'repair_reason': 'teacher_legacy_artifact_invariant'}
    ref = f'reconstruction-repairs/{r.id}/artifact.json'
    path = Path(root) / ref
    write_once(path, value)
    session.add(m.DomainEvent(entity_type='reconstruction', entity_id=r.id,
        event_type=EVENT, payload={'binding': binding(r), 'artifact_ref': ref,
                                  'sha256': sha256_file(path)}))
    session.flush()
    return value, True


def create_teacher_revision(session, root, base_id, text, *, action, reason,
                            transcription_bbox=None):
    """Create a fully sealed, selected teacher revision from an explicit decision."""
    base = session.get(m.StudentAnswerReconstruction, base_id)
    if not text or action not in {'EDIT', 'ACCEPT'} or not reason:
        raise ValueError('TEACHER_DECISION_REQUIRED')
    if action == 'ACCEPT' and text != base.answer_text:
        raise ValueError('ACCEPT_TEXT_CHANGED')
    repaired, _ = ensure_reconstruction_artifact(session, base.id, root)
    provenance = {'origin': 'TEACHER_EDIT' if action == 'EDIT' else 'TEACHER_ACCEPT',
                  'base_reconstruction_id': base.id, 'action': action, 'reason': reason}
    if transcription_bbox is not None:
        from .coordinate import validate_bbox
        if action != 'EDIT':
            raise ValueError('TRANSCRIPTION_REQUIRES_EDIT')
        provenance.update(origin='TEACHER_TRANSCRIPTION',
                          bbox=validate_bbox(transcription_bbox, 'normalized'),
                          coordinate_space='normalized')
    # Retrying the exact approved decision reuses its committed revision.
    for candidate in session.scalars(select(m.StudentAnswerReconstruction).where(
            m.StudentAnswerReconstruction.submission_id == base.submission_id,
            m.StudentAnswerReconstruction.question_id == base.question_id)):
        if candidate.model_identity == provenance and candidate.answer_text == text:
            return candidate
    version = max(session.scalars(select(m.StudentAnswerReconstruction.version).where(
        m.StudentAnswerReconstruction.submission_id == base.submission_id,
        m.StudentAnswerReconstruction.question_id == base.question_id))) + 1
    run_id, rid = str(uuid4()), str(uuid4())
    ref = f'student-answer/{base.submission_id}/reconstruction/{run_id}/questions/{base.question_id}'
    normalized = {'schema_version': 'student-answer-reconstruction.v1',
        'question_id': base.question_id, 'answer_text': text, 'segments': [],
        'uncertainties': [], 'status': 'COMPLETE', 'source_refs': [],
        'teacher_decision': provenance, 'revision_id': rid, 'version': version}
    normalized['output_sha256'] = canonical_hash(normalized)
    folder = Path(root) / ref
    source_provenance = dict(repaired['source_provenance'])
    if transcription_bbox is not None:
        from .regions import crop_image
        mat = session.get(m.TestMaterial, repaired['input']['source_answer']['source_material_id'])
        source_input(session, base)
        source_provenance.update(provenance)
        source_provenance['crop'] = crop_image(Path(mat.storage_ref), provenance['bbox'],
            folder / 'source-crop.png', padding=0, coordinate_space='normalized')
    write_once(folder / 'reconstruction.json', normalized)
    write_once(folder / 'reconstruction-input.json', repaired['input'])
    write_once(folder / 'teacher-provenance.json', source_provenance)
    manifest = {'revision_id': rid, 'files': {p.name: sha256_file(p) for p in folder.iterdir() if p.is_file()}}
    write_once(folder / 'manifest.json', manifest)
    sub = session.get(m.StudentSubmission, base.submission_id)
    run = m.StudentAnswerExtractionRun(id=run_id, submission_id=sub.id, test_id=sub.test_id,
        source_sha256=base.source_sha256, pipeline_version='teacher-review.v2',
        config_sha256=canonical_hash(provenance), status='completed',
        artifact_ref=str(Path(ref).parent.parent), selected=True)
    session.add(run)
    session.flush()
    ex = m.StudentAnswerExtractionResult(id=str(uuid4()), run_id=run_id, submission_id=sub.id,
        question_id=base.question_id, source_sha256=base.source_sha256, status='COMPLETE',
        artifact_ref=ref, normalized_sha256=normalized['output_sha256'])
    session.add(ex)
    session.flush()
    rev = m.StudentAnswerReconstruction(id=rid, extraction_result_id=ex.id, submission_id=sub.id,
        question_id=base.question_id, version=version, source_sha256=base.source_sha256,
        context_sha256=base.context_sha256, status='COMPLETE', answer_text=text,
        output_sha256=normalized['output_sha256'], artifact_ref=ref, model_identity=provenance)
    session.add(rev)
    for old in session.scalars(select(m.StudentAnswerExtractionRun).join(
            m.StudentAnswerExtractionResult, m.StudentAnswerExtractionResult.run_id == m.StudentAnswerExtractionRun.id).where(
            m.StudentAnswerExtractionRun.submission_id == sub.id,
            m.StudentAnswerExtractionResult.question_id == base.question_id,
            m.StudentAnswerExtractionRun.id != run_id)):
        old.selected = False
    session.flush()
    return rev


def create_teacher_transcription(session, root, submission_id, question_id, text, *,
                                 source_sha256, bbox, decision_id):
    """Create v1 only from an explicit teacher text and exact source provenance."""
    from .coordinate import validate_bbox
    from .regions import crop_image
    if not text.strip() or not decision_id:
        raise ValueError('TEACHER_DECISION_REQUIRED')
    box = validate_bbox(bbox, 'normalized')
    sub = session.get(m.StudentSubmission, submission_id)
    q = session.get(m.TestQuestion, question_id)
    if sub is None or q is None or q.test_id != sub.test_id or not q.is_gradable:
        raise ValueError('RECONSTRUCTION_SOURCE_IDENTITY_MISMATCH')
    mat = session.get(m.TestMaterial, sub.material_id)
    if mat.sha256 != source_sha256 or sha256_file(Path(mat.storage_ref)) != source_sha256:
        raise ValueError('RECONSTRUCTION_SOURCE_HASH_MISMATCH')
    provenance = {'origin': 'TEACHER_TRANSCRIPTION', 'decision_id': decision_id,
                  'bbox': box, 'coordinate_space': 'normalized'}
    old = session.scalar(select(m.StudentAnswerReconstruction).where(
        m.StudentAnswerReconstruction.submission_id == sub.id,
        m.StudentAnswerReconstruction.question_id == q.id))
    if old:
        if old.model_identity == provenance and old.answer_text == text:
            return old
        raise ValueError('EXISTING_RECONSTRUCTION_REQUIRES_EDIT')
    run_id, rid = str(uuid4()), str(uuid4())
    ref = f'student-answer/{sub.id}/reconstruction/{run_id}/questions/{q.id}'
    folder = Path(root) / ref
    crop = crop_image(Path(mat.storage_ref), box, folder / 'source-crop.png',
                      padding=0, coordinate_space='normalized')
    normalized = {'schema_version': 'student-answer-reconstruction.v1',
        'question_id': q.id, 'answer_text': text, 'segments': [], 'uncertainties': [],
        'status': 'COMPLETE', 'source_refs': [], 'origin': 'TEACHER_TRANSCRIPTION',
        'revision_id': rid, 'version': 1, 'teacher_decision': provenance}
    normalized['output_sha256'] = canonical_hash(normalized)
    run = m.StudentAnswerExtractionRun(id=run_id, submission_id=sub.id, test_id=sub.test_id,
        source_sha256=mat.sha256, pipeline_version='teacher-transcription.v2',
        config_sha256=canonical_hash(provenance), status='completed',
        artifact_ref=str(Path(ref).parent.parent), selected=True)
    session.add(run)
    session.flush()
    ex = m.StudentAnswerExtractionResult(id=str(uuid4()), run_id=run_id, submission_id=sub.id,
        question_id=q.id, source_sha256=mat.sha256, status='COMPLETE', artifact_ref=ref,
        normalized_sha256=normalized['output_sha256'])
    session.add(ex)
    session.flush()
    r = m.StudentAnswerReconstruction(id=rid, extraction_result_id=ex.id, submission_id=sub.id,
        question_id=q.id, version=1, source_sha256=mat.sha256,
        context_sha256=canonical_hash({'question_id': q.id, 'source_sha256': mat.sha256}),
        status='COMPLETE', answer_text=text, output_sha256=normalized['output_sha256'],
        artifact_ref=ref, model_identity=provenance)
    session.add(r)
    session.flush()
    write_once(folder / 'reconstruction.json', normalized)
    write_once(folder / 'reconstruction-input.json', source_input(session, r))
    write_once(folder / 'teacher-provenance.json', {**provenance, 'crop': crop,
        'source_material_id': mat.id, 'source_sha256': mat.sha256})
    write_once(folder / 'manifest.json', {'revision_id': rid,
        'files': {p.name: sha256_file(p) for p in folder.iterdir() if p.is_file()}})
    return r
