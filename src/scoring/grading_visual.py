"""Visual input roles shared by preflight, sealed snapshots and the worker."""
from pathlib import Path

from .coordinate import validate_bbox, normalized_to_pixel
from .pdf_native import canonical_hash
from .student_visual import safe_file
from .grading_audit import require_visual_roles


def validate_capability(capability, model_id=None):
    if (not isinstance(capability, dict) or capability.get('vision') is not True
            or capability.get('props', {}).get('modalities', {}).get('vision') is not True
            or not capability.get('model_id')
            or (model_id and capability['model_id'] != model_id)):
        raise ValueError('VISUAL_GRADING_MODEL_UNSUPPORTED')


def reference_assets(rubric, model_answer, root):
    refs = rubric.rubric_json.get('teacher_review', {}).get('reference_assets', [])
    result = []
    for ref in refs:
        if ref.get('owner_question_id') != model_answer.question_id:
            continue
        if ref.get('source_document_id') != model_answer.material_id:
            raise ValueError('MODEL_ANSWER_REFERENCE_OWNERSHIP_MISMATCH')
        safe_file(root, ref['artifact_ref'], ref['sha256'])
        result.append({**ref, 'role': 'model_answer_reference',
                       'question_id': model_answer.question_id, 'model_answer_id': model_answer.id})
    return result


def validate_visual_bundle(bundle):
    refs = bundle.get('visual_assets', [])
    answer = bundle['student_answer']
    qid = bundle['identity']['question_id']
    if answer.get('source') != 'VISUAL_FROM_DOCUMENT':
        if refs:
            raise ValueError('UNEXPECTED_VISUAL_ASSETS')
        return
    if not refs:
        raise ValueError('STUDENT_VISUAL_ASSET_MISSING')
    require_visual_roles(refs)
    seen, student_ids, reference_ids = set(), [], []
    for ref in refs:
        if ref['asset_id'] in seen:
            raise ValueError('DUPLICATE_VISUAL_ASSET')
        seen.add(ref['asset_id'])
        if ref['mime_type'] not in {'image/png', 'image/jpeg'} or len(ref['sha256']) != 64:
            raise ValueError('VISUAL_ASSET_INVALID')
        role = ref.get('role')
        if role == 'student_visual_answer':
            student_ids.append(ref['asset_id'])
            if (ref['question_id'] != qid or ref['submission_id'] != answer['submission_id']
                    or ref['test_id'] != bundle['identity']['test_id']
                    or ref['source_sha256'] != answer['source_sha256']
                    or ref['sha256'] != answer['sha256'] or ref['review_required']):
                raise ValueError('STUDENT_VISUAL_IDENTITY_MISMATCH')
            if ref['metadata_sha256'] != canonical_hash({k: v for k, v in ref.items() if k != 'metadata_sha256'}):
                raise ValueError('STUDENT_VISUAL_METADATA_HASH_MISMATCH')
            validate_bbox(ref['bbox'], ref['coordinate_space'])
            if ref['coordinate_space'] != 'normalized' or normalized_to_pixel(ref['bbox'], *ref['source_dimensions']) != ref['pixel_bbox']:
                raise ValueError('STUDENT_VISUAL_COORDINATES_INVALID')
        elif role == 'model_answer_reference':
            reference_ids.append(ref['asset_id'])
            if ref['question_id'] != qid or ref['model_answer_id'] != bundle['model_answer']['id']:
                raise ValueError('MODEL_ANSWER_REFERENCE_OWNERSHIP_MISMATCH')
        elif role == 'question_context':
            if not any(a['asset_id'] == ref['asset_id'] and a['sha256'] == ref['sha256']
                       and a['source_question_id'] == ref['question_id'] for a in bundle['assets']):
                raise ValueError('QUESTION_ASSET_IDENTITY_MISMATCH')
        else:
            raise ValueError('VISUAL_ASSET_ROLE_INVALID')
    if student_ids != answer['visual_asset_ids'] or not reference_ids:
        raise ValueError('VISUAL_ASSET_MISSING')


def snapshot_visual_assets(session, bundle, *, question_root, answer_root, reference_root):
    from .db.models import TestQuestionAsset
    from .grading_context import asset_path
    rows = []
    for ref in bundle['visual_assets']:
        if ref['role'] == 'question_context':
            path = asset_path(session.get(TestQuestionAsset, ref['asset_id']), question_root)
        else:
            root = answer_root if ref['role'] == 'student_visual_answer' else reference_root
            path = safe_file(root, ref['artifact_ref'], ref['sha256'])
        rows.append({'asset_id': ref['asset_id'], 'sha256': ref['sha256'],
                     'role': ref['role'], 'path': str(Path(path).resolve())})
    return rows
