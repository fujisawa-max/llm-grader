"""Read existing, server-attested historical crops without mutable review state."""
from pathlib import Path
import re

from .db.models import (ModelAnswerImportDraft, QuestionImportReview, QuestionImportDraft,
    QuestionImportExtraction, TestMaterial)
from .pdf_native import sha256_file


def confirmed_crop_path(session, confirmed, owner, identifier, question_root, answer_root):
    snapshot = confirmed.snapshot
    answer = snapshot.get('domains', {}).get('answer') or {}
    for entry in answer.get('entries', []):
        if entry['id'] != owner:
            continue
        record = _record(entry, identifier)
        source_id = entry.get('source_draft_id') or answer.get('draft_id')
        bound = ({answer.get('draft_id'): answer, **answer.get('sources', {})}).get(source_id)
        draft = session.get(ModelAnswerImportDraft, source_id)
        if (not record or not bound or not draft or draft.test_id != confirmed.test_id
                or draft.material_id != bound['material_id'] or draft.source_sha256 != bound['source_sha256']
                or draft.artifact_ref != bound['artifact_ref']):
            raise ValueError('historical_diagram_source_invalid')
        root = Path(answer_root).resolve()
        ir = (root / draft.artifact_ref).resolve()
        if not ir.is_relative_to(root) or not ir.is_file():
            raise ValueError('historical_diagram_source_invalid')
        return _path(session, confirmed.test_id, record, draft.material_id, draft.source_sha256, ir.parent, root)
    for node in snapshot['nodes']:
        if node['stable_key'] != owner:
            continue
        record = _record(node, identifier)
        question = snapshot.get('domains', {}).get('question') or {}
        review = session.get(QuestionImportReview, question.get('document', {}).get('id'))
        draft = session.get(QuestionImportDraft, review.draft_id) if review else None
        extraction = session.get(QuestionImportExtraction, draft.extraction_id) if draft else None
        if not record or not extraction or extraction.test_id != confirmed.test_id:
            raise ValueError('historical_diagram_source_invalid')
        root = Path(question_root).resolve()
        return _path(session, confirmed.test_id, record, extraction.material_id,
            extraction.source_sha256, root / extraction.id, root)
    raise ValueError('historical_diagram_not_found')


def _record(container, identifier):
    return next((value for value in container.get('diagram_records', [])
        if value['id'] == identifier and value.get('state') == 'accepted'), None)


def _path(session, test_id, record, material_id, source_sha, directory, root):
    # Logical retirement of a binding does not erase immutable historical
    # content. Current reuse/confirmation still apply their normal live-source
    # filters. This route only reads an already-confirmed crop, never rebuilds it.
    material = session.get(TestMaterial, material_id)
    if (not material or material.test_id != test_id or record.get('material_id') != material_id
            or record.get('source_sha256') != source_sha):
        raise ValueError('historical_diagram_source_invalid')
    ref = record.get('artifact_ref')
    digest = record.get('crop_sha256')
    if (not isinstance(ref, str) or not ref.startswith('diagrams/') or not ref.endswith('.png')
            or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
        raise ValueError('historical_diagram_artifact_invalid')
    directory = directory.resolve()
    path = (directory / ref).resolve()
    if not directory.is_relative_to(root) or not path.is_relative_to(directory) or not path.is_file():
        raise ValueError('historical_diagram_artifact_invalid')
    if sha256_file(path) != digest:
        raise ValueError('historical_diagram_artifact_invalid')
    return path
