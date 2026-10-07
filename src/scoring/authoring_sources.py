"""Read-only adapters for saved domain reviews. Never infer or publish."""
from copy import deepcopy
import json
from pathlib import Path

from sqlalchemy import select

from .db.models import (QuestionImportReview, QuestionImportDraft, QuestionImportExtraction,
    ModelAnswerImportDraft, TestMaterial, TestQuestion)
from .pdf_native import canonical_hash, sha256_file
from .question_reviews import QuestionReviewService, ReviewError


def source_tokens(session, test_id):
    """Include latest persisted revisions, even if their source is now stale."""
    question = session.scalar(select(QuestionImportReview).join(QuestionImportDraft)
        .join(QuestionImportExtraction).where(QuestionImportExtraction.test_id == test_id)
        .order_by(QuestionImportReview.updated_at.desc(), QuestionImportReview.id.desc()))
    answer = session.scalar(select(ModelAnswerImportDraft).where(ModelAnswerImportDraft.test_id == test_id)
        .order_by(ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.id.desc()))
    return {'question': {'id': question.id, 'revision': question.current_revision,
        'sha256': question.current_revision_sha256} if question else None,
        'answer': {'id': answer.id, 'revision': answer.revision,
            'sha256': canonical_hash(answer.snapshot), 'source_sha256': answer.source_sha256} if answer else None}


def _answer_valid(session, draft, root):
    material = session.get(TestMaterial, draft.material_id)
    if not material or material.test_id != draft.test_id or material.sha256 != draft.source_sha256:
        raise ValueError('model_answer_source_stale')
    root = Path(root).resolve()
    pdf = Path(material.storage_ref)
    pdf = (pdf if pdf.is_absolute() else root / pdf).resolve()
    ir_path = (root / draft.artifact_ref).resolve()
    if not pdf.is_relative_to(root) or not ir_path.is_relative_to(root):
        raise ValueError('model_answer_source_foreign')
    if sha256_file(pdf) != draft.source_sha256:
        raise ValueError('model_answer_source_stale')
    ir = json.loads(ir_path.read_text())
    if ir['source']['sha256'] != draft.source_sha256:
        raise ValueError('model_answer_source_stale')


def answer_alternatives(entries):
    result = []
    for entry in entries:
        if entry.get('answer_kind') == 'alternative':
            result.append(entry.get('answer_text', ''))
        alternatives = entry.get('manual_alternative_answers')
        if alternatives is None:
            classification = entry.get('semantic_classification') or {}
            alternatives = classification.get('manual_alternative_answers', classification.get('alternative_answers', []))
        result.extend(a['text'] for a in alternatives)
    return result


def has_rubric_state(entry):
    classification = entry.get('semantic_classification') or {}
    return 'rubric_edits' in entry or any(s.get('category') == 'rubric' for s in classification.get('segments', []))


def rubric_projection(entry):
    """Project saved native grouping decisions; never reclassify on resume."""
    if 'rubric_edits' in entry:
        return [deepcopy(c) for c in entry['rubric_edits'] if not c.get('excluded')]
    classification = entry.get('semantic_classification') or {}
    segments = {s['id']: s for s in classification.get('segments', [])}
    return [{'id': group['id'], 'description': group['description'], 'points': group['points'],
        'source_text': group.get('source_text', ''), 'segment_ids': group['segment_ids'],
        'grouping_confirmed': not group.get('needs_teacher_review', False),
        'points_conflict': group.get('points_conflict', False), 'points_confirmed': False,
        'grouping_method': group.get('merge_type')}
        for group in classification.get('rubric_groups', []) if group.get('kind') == 'rubric'
        and all(segments.get(identifier, {}).get('category') == 'rubric' for identifier in group['segment_ids'])]


def source_projection(session, test, formal, question_root, answer_root):
    result = deepcopy(formal)
    result["rubric_histories"] = {}
    tokens = source_tokens(session, test.id)
    domains, diagnostics = {}, []
    identities = {n['stable_key']: {'formal_question_id': n['stable_key'],
        'review_node_id': None, 'source_review_id': None} for n in result['nodes']}
    reviews = session.scalars(select(QuestionImportReview).join(QuestionImportDraft)
        .join(QuestionImportExtraction).where(QuestionImportExtraction.test_id == test.id)
        .order_by(QuestionImportReview.updated_at.desc(), QuestionImportReview.id.desc())).all()
    for row in reviews:
        try:
            document = QuestionReviewService(session, question_root).get(row.id)
        except (ReviewError, OSError, ValueError, KeyError) as exc:
            diagnostics.append({'domain': 'question', 'id': row.id,
                'code': getattr(exc, 'code', 'question_source_unavailable')})
            continue
        nodes = deepcopy(document['snapshot']['nodes'])
        identities = {}
        formal_rows = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test.id)))
        mapping = {}
        for node in nodes:
            matches = [q for q in formal_rows if
                (q.stable_question_key == node['stable_key'] and not (q.provenance or {}).get('review_id')) or
                ((q.provenance or {}).get('review_id') == row.id and
                 (q.provenance or {}).get('review_node_id') == node['review_node_id'])]
            formal_id = matches[0].id if len(matches) == 1 else None
            if formal_id:
                mapping[formal_id] = node['stable_key']
            identities[node['stable_key']] = {'formal_question_id': formal_id,
                'review_node_id': node['review_node_id'], 'source_review_id': row.id}
        result['nodes'] = nodes
        result['answers'] = {mapping[k]: v for k, v in result['answers'].items() if k in mapping}
        result['rubrics'] = {mapping[k]: v for k, v in result['rubrics'].items() if k in mapping}
        domains['question'] = {'document': {k: deepcopy(v) for k, v in document.items() if k != 'snapshot'},
            'snapshot': {k: deepcopy(v) for k, v in document['snapshot'].items() if k != 'nodes'}}
        break
    formal_to_key = {i['formal_question_id']: k for k, i in identities.items() if i['formal_question_id']}
    formal_to_key.update({k: k for k in identities})
    drafts = session.scalars(select(ModelAnswerImportDraft).where(ModelAnswerImportDraft.test_id == test.id)
        .order_by(ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.id.desc())).all()
    for draft in drafts:
        try:
            _answer_valid(session, draft, answer_root)
        except (OSError, ValueError, KeyError, TypeError):
            diagnostics.append({'domain': 'answer', 'id': draft.id, 'code': 'model_answer_source_unavailable'})
            continue
        entries = deepcopy(draft.snapshot.get('entries', []))
        for entry in entries:
            entry['authoring_question_key'] = formal_to_key.get(entry.get('question_id'))
        domains['answer'] = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'question_regions': deepcopy(draft.snapshot.get('question_regions', [])),
            'entries': entries}
        # Assigned draft entries are authoritative even when intentionally blank.
        assigned = {e['authoring_question_key'] for e in entries if e['authoring_question_key']}
        for key in assigned:
            current = [e for e in entries if e['authoring_question_key'] == key and
                e.get('disposition', 'include') == 'include']
            primary = next((e for e in current if e.get('answer_kind', 'primary') == 'primary'), None)
            result['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                'alternatives': answer_alternatives(current),
                'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
            if any(has_rubric_state(e) for e in current):
                result['rubrics'][key] = [c for e in current for c in rubric_projection(e)]
        break
    result['domains'] = domains
    result['source_provenance']['authoring_origins'] = {'tokens': tokens, 'identities': identities,
        'diagnostics': diagnostics}
    return result


def validate_domains(value, previous):
    from .test_authoring import AuthoringError
    domains, old = value.get('domains'), previous['domains']
    if not isinstance(domains, dict) or set(domains) != set(old):
        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '出典付きレビューの対応を確認してください。')
    for name in old:
        if name == 'question':
            submitted = domains[name]
            if (not isinstance(submitted, dict) or set(submitted) != set(old[name])
                    or submitted.get('document') != old[name]['document']
                    or {k: v for k, v in submitted.get('snapshot', {}).items() if k != 'warning_states'} !=
                       {k: v for k, v in old[name]['snapshot'].items() if k != 'warning_states'}):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', '元資料の参照情報は編集できません。')
            states = submitted['snapshot'].get('warning_states', {})
            domains[name] = deepcopy(old[name])
            domains[name]['snapshot']['warning_states'] = states
        elif name == 'answer':
            new = domains[name]
            if (not isinstance(new, dict) or {k: v for k, v in new.items() if k != 'entries'} !=
                    {k: v for k, v in old[name].items() if k != 'entries'} or not isinstance(new.get('entries'), list)):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', '解答の出典情報は編集できません。')
            # Restore immutable server geometry after browser JSON number normalization.
            for field, source_value in old[name].items():
                if field != 'entries':
                    new[field] = deepcopy(source_value)
            entries = {e['id']: e for e in old[name]['entries']}
            ids = [e.get('id') for e in new['entries'] if isinstance(e, dict)]
            if len(ids) != len(new['entries']) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not set(entries) <= set(ids):
                raise AuthoringError('AUTHORING_INVALID_TARGET', '候補の識別子を確認してください。')
            keys = {n['stable_key'] for n in value['nodes']}
            for e in new['entries']:
                original = entries.get(e['id'])
                if e.get('authoring_question_key') is not None and e['authoring_question_key'] not in keys:
                    raise AuthoringError('AUTHORING_INVALID_TARGET', '候補の対応先を確認してください。')
                if original and any(e.get(k) != original.get(k) for k in ('source', 'candidate_text', 'extraction_method')):
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '候補の元資料は編集できません。')
                if not original:
                    from uuid import UUID
                    try:
                        if not e['id'].startswith('teacher-entry-'):
                            raise ValueError()
                        UUID(e['id'].removeprefix('teacher-entry-'))
                        source = e.get('source', {})
                        if (source.get('kind') != 'teacher_manual' or source.get('segments') != []
                                or source.get('material_id') or source.get('source_sha256')
                                or set(source) - {'kind', 'segments', 'material_id', 'source_sha256'}):
                            raise ValueError()
                    except (ValueError, AttributeError) as exc:
                        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '追加候補の出典を確認してください。') from exc
                if not isinstance(e.get('answer_text'), str) or len(e['answer_text']) > 100000:
                    raise AuthoringError('AUTHORING_INVALID_TEXT', '模範解答本文を確認してください。')
                alternatives = e.get('manual_alternative_answers')
                if alternatives is not None:
                    classification = (original or {}).get('semantic_classification') or {}
                    known = {a.get('id') or 'source-alternative:' + ':'.join(a.get('segment_ids', [])) for a in classification.get('alternative_answers', []) +
                        classification.get('manual_alternative_answers', []) + (original or {}).get('manual_alternative_answers', [])}
                    if (not isinstance(alternatives, list) or len(alternatives) > 100 or
                            any(not isinstance(a, dict) or not isinstance(a.get('id'), str) or
                                (a['id'] not in known and not a['id'].startswith('teacher-alternative-')) or
                                not isinstance(a.get('text'), str) or len(a['text']) > 100000 for a in alternatives) or
                            len({a['id'] for a in alternatives}) != len(alternatives)):
                        raise AuthoringError('AUTHORING_INVALID_TEXT', '別解の内容を確認してください。')
                if original and e.get('semantic_classification') != original.get('semantic_classification'):
                    from .model_answer_classification import apply_teacher_segment_edits, ClassificationOutputError
                    try:
                        submitted = e.get('semantic_classification') or {}
                        canonical = apply_teacher_segment_edits(original.get('semantic_classification') or {},
                            [{k: segment[k] for k in ('id', 'category', 'text')} for segment in submitted.get('segments', [])])
                        if any(submitted.get(k) != canonical.get(k) for k in ('candidate_text', 'segments')):
                            raise ValueError()
                        if submitted.get('status') == 'teacher_reviewed':
                            canonical['status'] = 'teacher_reviewed'
                        e['semantic_classification'] = canonical
                    except (ValueError, KeyError, TypeError, ClassificationOutputError) as exc:
                        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '分類と元segmentの対応を確認してください。') from exc
