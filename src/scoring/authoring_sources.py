"""Read-only adapters for saved domain reviews. Never infer or publish."""
from copy import deepcopy
import json
import math
from pathlib import Path

from sqlalchemy import select

from .db.models import (QuestionImportReview, QuestionImportDraft, QuestionImportExtraction,
    ModelAnswerImportDraft, TestMaterial, TestQuestion, DomainEvent)
from .pdf_native import canonical_hash, sha256_file
from .question_reviews import QuestionReviewService, ReviewError


def source_tokens(session, test_id):
    """Include latest persisted revisions, even if their source is now stale."""
    question = session.scalar(select(QuestionImportReview).join(QuestionImportDraft)
        .join(QuestionImportExtraction).where(QuestionImportExtraction.test_id == test_id)
        .order_by(QuestionImportReview.updated_at.desc(), QuestionImportReview.id.desc()))
    answer_drafts = session.scalars(select(ModelAnswerImportDraft).join(TestMaterial,
        TestMaterial.id == ModelAnswerImportDraft.material_id).where(
        ModelAnswerImportDraft.test_id == test_id, TestMaterial.material_type == 'model_answer_source')
        .order_by(ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.id.desc())).all()
    rubric_drafts = session.scalars(select(ModelAnswerImportDraft).join(TestMaterial,
        TestMaterial.id == ModelAnswerImportDraft.material_id).where(
        ModelAnswerImportDraft.test_id == test_id, TestMaterial.material_type == 'rubric_source')
        .order_by(ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.id.desc())).all()
    deleted = {row.entity_id for row in session.scalars(select(DomainEvent).where(
        DomainEvent.entity_type == 'material', DomainEvent.event_type == 'material_binding_deleted'))
        if row.entity_id and (row.payload or {}).get('test_id') == test_id}
    answer_drafts = [draft for draft in answer_drafts if draft.material_id not in deleted]
    rubric_drafts = [draft for draft in rubric_drafts if draft.material_id not in deleted]
    answer = answer_drafts[0] if answer_drafts else None
    rubric = rubric_drafts[0] if rubric_drafts else None
    return {'question': {'id': question.id, 'revision': question.current_revision,
        'sha256': question.current_revision_sha256} if question else None,
        'answer': {'id': answer.id, 'revision': answer.revision,
            'sha256': canonical_hash(answer.snapshot), 'source_sha256': answer.source_sha256} if answer else None,
        'rubric': {'id': rubric.id, 'revision': rubric.revision,
            'sha256': canonical_hash(rubric.snapshot), 'source_sha256': rubric.source_sha256} if rubric else None}


def _answer_valid(session, draft, root):
    material = session.get(TestMaterial, draft.material_id)
    if not material or material.test_id != draft.test_id or material.sha256 != draft.source_sha256:
        raise ValueError('model_answer_source_stale')
    from .source_registration import deleted_material_ids
    if material.id in deleted_material_ids(session, draft.test_id):
        raise ValueError('model_answer_source_binding_deleted')
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


def recoverable_rubric_segments(entry):
    classification = entry.get('semantic_classification') or {}
    return [segment for segment in classification.get('segments', [])
        if segment.get('category') == 'rubric' or (segment.get('category') == 'uncertain'
        and classification.get('status') in {'classified', 'needs_teacher_review', 'teacher_reviewed'})]


def _empty_rubric_domain():
    return {'entries': [], 'sources': {}, 'analysis_result': None, 'analysis_results': {}}


def rubric_snapshot_projection(domain, keys):
    """Build the legacy preflight map from the RubricDraft only."""
    result = {}
    for key in keys:
        criteria = [deepcopy(criterion) for entry in domain.get('entries', [])
                    if entry.get('authoring_question_key') == key
                    and entry.get('disposition', 'include') == 'include'
                    for criterion in entry.get('criteria', []) if not criterion.get('excluded')]
        if criteria:
            result[key] = criteria
    return result


def normalize_authoring_snapshot(snapshot):
    """Separate legacy nested rubric edits from the Answer candidate list.

    Older authoring revisions used ``domains.answer.entries`` for both roles.
    This deterministic adapter preserves those edits and provenance while
    moving accepted criteria into ``domains.rubric``. Rubric-like Answer
    segments without an explicit teacher edit stay in a separate recovery
    bucket and never become accepted criteria during resume.
    """
    result = deepcopy(snapshot)
    domains = result.setdefault('domains', {})
    answer = domains.get('answer')
    rubric = domains.get('rubric')
    if not isinstance(rubric, dict):
        rubric = _empty_rubric_domain()
        domains['rubric'] = rubric
    rubric.setdefault('entries', [])
    rubric.setdefault('sources', {})
    rubric.setdefault('analysis_result', None)
    rubric.setdefault('analysis_results', {})
    recovery = domains.setdefault('recovery', {})
    recovery.setdefault('rubric_candidates', [])

    # Formal criteria and old manual edits have no source binding. Preserve
    # them as a teacher-owned RubricDraft entry when adapting older snapshots.
    for key, criteria in result.get('rubrics', {}).items():
        existing_ids = {criterion.get('id') for entry in rubric['entries']
                        if entry.get('authoring_question_key') == key for criterion in entry.get('criteria', [])}
        nested_ids = {criterion.get('id') for entry in (answer or {}).get('entries', [])
                      for criterion in entry.get('rubric_edits', []) or []}
        missing = [deepcopy(criterion) for criterion in criteria
                   if not criterion.get('id') or criterion.get('id') not in existing_ids | nested_ids]
        if missing:
            rubric['entries'].append({'id': f'legacy-formal-rubric:{key}',
                'authoring_question_key': key, 'material_role': 'teacher_manual',
                'source_draft_id': None, 'material_id': None, 'source_sha256': None,
                'source': {'kind': 'teacher_manual', 'material_id': None,
                    'source_sha256': None, 'segments': []},
                'criteria': missing,
                'operation_history': deepcopy(result.get('rubric_histories', {}).get(key, []))})

    if answer:
        root_role = answer.get('material_role', 'model_answer_source')
        legacy_results = answer.get('analysis_results', {})
        if legacy_results.get('rubric_source') is not None:
            rubric['analysis_results'].setdefault('rubric_source', deepcopy(legacy_results['rubric_source']))
            rubric.setdefault('analysis_result', deepcopy(legacy_results['rubric_source']))
        if root_role == 'rubric_source' and answer.get('analysis_result') is not None:
            rubric['analysis_result'] = deepcopy(answer['analysis_result'])
            rubric['analysis_results']['rubric_source'] = deepcopy(answer['analysis_result'])
        for identifier, source in answer.get('sources', {}).items():
            source_role = source.get('material_role')
            if source_role is None and identifier == answer.get('draft_id'):
                source_role = root_role
            if source_role == 'rubric_source':
                rubric['sources'][identifier] = deepcopy(source)
        kept_answer_entries = []
        for old_entry in answer.get('entries', []):
            entry = deepcopy(old_entry)
            source_binding = answer.get('sources', {}).get(entry.get('source_draft_id'), {})
            role = entry.get('material_role') or source_binding.get('material_role')
            if role is None:
                role = root_role if entry.get('source_draft_id') in {None, answer.get('draft_id')} else 'model_answer_source'
            legacy_criteria = entry.pop('rubric_edits', None)
            legacy_history = entry.pop('rubric_merge_history', None)
            entry.pop('rubric_consolidated_groups', None)
            question_key = entry.get('authoring_question_key')
            if role == 'rubric_source':
                criteria = legacy_criteria if legacy_criteria is not None else rubric_projection(old_entry)
                if criteria or not question_key:
                    rubric['entries'].append({'id': f"rubric-source:{entry.get('source_draft_id', '')}:{entry['id']}",
                        'source_candidate_id': entry['id'], 'authoring_question_key': question_key,
                        'question_id': entry.get('question_id'), 'material_role': role,
                        'source_draft_id': entry.get('source_draft_id'),
                        'material_id': entry.get('source', {}).get('material_id'),
                        'source_sha256': entry.get('source', {}).get('source_sha256'),
                        'source': deepcopy(entry.get('source', {})),
                        'candidate_text': entry.get('candidate_text', ''),
                        'semantic_classification': deepcopy(entry.get('semantic_classification')),
                        'disposition': entry.get('disposition', 'include'),
                        'criteria': deepcopy(criteria), 'operation_history': deepcopy(legacy_history or [])})
                else:
                    kept_answer_entries.append(entry)
                continue
            if legacy_criteria is not None:
                target = next((candidate for candidate in rubric['entries']
                    if candidate.get('authoring_question_key') == question_key
                    and candidate.get('source_draft_id') == entry.get('source_draft_id')
                    and candidate.get('source_candidate_id') == entry.get('id')), None)
                if not target:
                    rubric['entries'].append({'id': f"legacy-rubric:{entry.get('source_draft_id', '')}:{entry['id']}",
                        'source_candidate_id': entry['id'], 'authoring_question_key': question_key,
                        'question_id': entry.get('question_id'), 'material_role': role,
                        'source_draft_id': entry.get('source_draft_id'),
                        'material_id': entry.get('source', {}).get('material_id'),
                        'source_sha256': entry.get('source', {}).get('source_sha256'),
                        'source': deepcopy(entry.get('source', {})),
                        'candidate_text': entry.get('candidate_text', ''),
                        'criteria': deepcopy(legacy_criteria),
                        'operation_history': deepcopy(legacy_history or [])})
            classification = entry.get('semantic_classification') or {}
            existing_recovery = {(candidate.get('source_draft_id'), candidate.get('segment_id'))
                                 for candidate in recovery['rubric_candidates']}
            for segment in recoverable_rubric_segments(entry):
                identity = (entry.get('source_draft_id'), segment.get('id'))
                if identity in existing_recovery:
                    continue
                recovery['rubric_candidates'].append({'id': f"recovery:{identity[0]}:{identity[1]}",
                    'origin_role': role, 'source_draft_id': entry.get('source_draft_id'),
                    'source_candidate_id': entry.get('id'), 'source_binding_id': None,
                    'source_sha256': entry.get('source', {}).get('source_sha256'),
                    'segment_id': segment.get('id'), 'text': segment.get('text', ''),
                    'category': segment.get('category'), 'classification_status': classification.get('status'),
                    'question_key': question_key, 'provenance': deepcopy(segment.get('provenance') or {})})
                existing_recovery.add(identity)
            entry['material_role'] = 'model_answer_source'
            kept_answer_entries.append(entry)
        answer['entries'] = kept_answer_entries
        answer_sources = {}
        for identifier, source in answer.get('sources', {}).items():
            source_role = source.get('material_role') or (
                root_role if identifier == answer.get('draft_id') else 'model_answer_source')
            if source_role == 'model_answer_source':
                answer_sources[identifier] = {**source, 'material_role': source_role}
        answer['sources'] = answer_sources
        if answer.get('material_role', 'model_answer_source') == 'rubric_source':
            rubric_source = {k: deepcopy(v) for k, v in answer.items()
                             if k not in {'entries', 'sources', 'analysis_result', 'analysis_results'}}
            rubric_source['material_role'] = 'rubric_source'
            rubric['sources'][rubric_source['draft_id']] = rubric_source
            answer_sources = answer.get('sources', {})
            latest_answer = max(answer_sources.values(), key=lambda source: (source.get('revision', 0), source.get('draft_id', '')),
                                default=None)
            if latest_answer:
                answer_results = {key: deepcopy(value) for key, value in legacy_results.items()
                                  if key == 'model_answer_source'}
                domains['answer'] = {**deepcopy(latest_answer), 'material_role': 'model_answer_source',
                    'entries': kept_answer_entries,
                    'sources': {key: deepcopy(source) for key, source in answer_sources.items()
                               if key != latest_answer.get('draft_id')},
                    'analysis_result': answer_results.get('model_answer_source'),
                    'analysis_results': answer_results}
            elif kept_answer_entries:
                domains['answer'] = {'draft_id': None, 'revision': 0, 'material_id': None,
                    'source_sha256': None, 'artifact_ref': None, 'material_role': 'model_answer_source',
                    'entries': kept_answer_entries, 'sources': {}, 'analysis_result': None,
                    'analysis_results': {}}
            else:
                domains.pop('answer', None)
        elif answer:
            answer.setdefault('material_role', 'model_answer_source')
            answer['analysis_results'] = {k: v for k, v in answer.get('analysis_results', {}).items()
                                          if k == 'model_answer_source'}
            if answer.get('analysis_result') and answer.get('material_role') == 'model_answer_source':
                answer['analysis_results'].setdefault('model_answer_source', answer['analysis_result'])

    # Stable-ID deduplication makes normalization idempotent when an older
    # snapshot already contains both a top-level projection and nested edits.
    seen = set()
    for entry in rubric['entries']:
        unique = []
        for criterion in entry.get('criteria', []):
            identifier = criterion.get('id')
            if identifier and identifier in seen:
                continue
            if identifier:
                seen.add(identifier)
            unique.append(criterion)
        entry['criteria'] = unique
    valid_keys = {node.get('stable_key') for node in result.get('nodes', [])}
    result['rubrics'] = rubric_snapshot_projection(rubric, valid_keys)
    result['rubric_histories'] = {entry['authoring_question_key']: deepcopy(entry.get('operation_history', []))
        for entry in rubric['entries'] if entry.get('authoring_question_key') and entry.get('operation_history')}
    return result


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
    from .source_registration import deleted_material_ids
    deleted = deleted_material_ids(session, test.id)
    latest_by_role = {}
    for draft in drafts:
        material = session.get(TestMaterial, draft.material_id)
        if not material or material.id in deleted or material.material_type not in {'model_answer_source', 'rubric_source'}:
            continue
        try:
            _answer_valid(session, draft, answer_root)
        except (OSError, ValueError, KeyError, TypeError):
            diagnostics.append({'domain': 'answer' if material.material_type == 'model_answer_source' else 'rubric',
                'id': draft.id, 'code': 'source_unavailable'})
            continue
        latest_by_role.setdefault(material.material_type, (draft, material))

    # Import drafts share one storage model, but their authoring projections
    # are separate. The physical source can be shared; candidate ownership
    # cannot.
    answer_entries, answer_sources = [], {}
    rubric_entries, rubric_sources = [], {}
    recovery_candidates = []
    answer_source = latest_by_role.get('model_answer_source')
    rubric_source = latest_by_role.get('rubric_source')
    for role_name, pair in (('model_answer_source', answer_source), ('rubric_source', rubric_source)):
        if not pair:
            continue
        draft, material = pair
        binding = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'material_role': role_name,
            'question_regions': deepcopy(draft.snapshot.get('question_regions', []))}
        source_entries = deepcopy(draft.snapshot.get('entries', []))
        for source_entry in source_entries:
            question_key = formal_to_key.get(source_entry.get('question_id'))
            entry = deepcopy(source_entry)
            entry['authoring_question_key'] = question_key
            entry['source_draft_id'] = draft.id
            entry['material_role'] = role_name
            classification = entry.get('semantic_classification') or {}
            if role_name == 'model_answer_source':
                # Legacy imports may contain rubric_edits. Treat only explicit
                # teacher edits as accepted legacy criteria; classifier-only
                # rubric text stays in the recovery bucket.
                legacy_criteria = entry.pop('rubric_edits', None)
                legacy_history = entry.pop('rubric_merge_history', [])
                entry.pop('rubric_consolidated_groups', None)
                if legacy_criteria:
                    rubric_entries.append({'id': f'legacy-rubric:{draft.id}:{entry["id"]}',
                        'source_candidate_id': entry['id'], 'authoring_question_key': question_key,
                        'question_id': entry.get('question_id'), 'material_role': role_name,
                        'source_draft_id': draft.id, 'material_id': material.id,
                        'source_sha256': draft.source_sha256, 'source': deepcopy(entry.get('source', {})),
                        'candidate_text': entry.get('candidate_text', ''),
                        'criteria': deepcopy(legacy_criteria), 'operation_history': deepcopy(legacy_history)})
                if question_key:
                    answer_entries.append(entry)
                for segment in recoverable_rubric_segments(entry):
                    recovery_candidates.append({'id': f'recovery:{draft.id}:{segment.get("id")}',
                        'origin_role': role_name, 'source_draft_id': draft.id,
                        'source_candidate_id': entry['id'], 'source_binding_id': material.id,
                        'source_sha256': draft.source_sha256, 'segment_id': segment.get('id'),
                        'text': segment.get('text', ''), 'category': segment.get('category'),
                        'classification_status': classification.get('status'),
                        'question_key': question_key,
                        'provenance': deepcopy(segment.get('provenance') or {})})
            else:
                criteria = rubric_projection(entry)
                rubric_entries.append({'id': f'rubric-source:{draft.id}:{entry["id"]}',
                    'source_candidate_id': entry['id'], 'authoring_question_key': question_key,
                    'question_id': entry.get('question_id'), 'material_role': role_name,
                    'source_draft_id': draft.id, 'material_id': material.id,
                    'source_sha256': draft.source_sha256, 'source': deepcopy(entry.get('source', {})),
                    'candidate_text': entry.get('candidate_text', ''),
                    'semantic_classification': classification,
                    'disposition': entry.get('disposition', 'include'),
                    'criteria': criteria, 'operation_history': []})
                covered = {segment_id for criterion in criteria for segment_id in criterion.get('segment_ids', [])}
                for segment in recoverable_rubric_segments(entry):
                    if segment.get('id') in covered:
                        continue
                    recovery_candidates.append({'id': f'recovery:{draft.id}:{segment.get("id")}',
                        'origin_role': role_name, 'source_draft_id': draft.id,
                        'source_candidate_id': entry['id'], 'source_binding_id': material.id,
                        'source_sha256': draft.source_sha256, 'segment_id': segment.get('id'),
                        'text': segment.get('text', ''), 'category': segment.get('category'),
                        'classification_status': classification.get('status'),
                        'question_key': question_key,
                        'provenance': deepcopy(segment.get('provenance') or {})})

            if question_key and entry.get('disposition', 'include') == 'include':
                if role_name == 'model_answer_source':
                    current = [candidate for candidate in answer_entries
                               if candidate.get('authoring_question_key') == question_key
                               and candidate.get('disposition', 'include') == 'include']
                    primary = next((candidate for candidate in current
                                    if candidate.get('answer_kind', 'primary') == 'primary'), None)
                    result['answers'][question_key] = {
                        'primary': primary.get('answer_text', '') if primary else '',
                        'alternatives': answer_alternatives(current),
                        'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
                elif criteria:
                    current = [candidate for candidate in rubric_entries
                               if candidate.get('authoring_question_key') == question_key]
                    result['rubrics'][question_key] = [criterion for candidate in current
                        for criterion in candidate.get('criteria', []) if not criterion.get('excluded')]

        if role_name == 'model_answer_source':
            answer_sources[draft.id] = binding
        else:
            rubric_sources[draft.id] = binding

    if answer_source:
        draft, _material = answer_source
        domains['answer'] = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'question_regions': deepcopy(draft.snapshot.get('question_regions', [])),
            'material_role': 'model_answer_source', 'entries': answer_entries,
            'sources': {k: v for k, v in answer_sources.items() if k != draft.id}}
    if rubric_source:
        draft, _material = rubric_source
        domains['rubric'] = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'material_role': 'rubric_source',
            'entries': rubric_entries, 'sources': {k: v for k, v in rubric_sources.items() if k != draft.id},
            'analysis_result': None, 'analysis_results': {}}
    else:
        domains['rubric'] = _empty_rubric_domain()
    domains['recovery'] = {'rubric_candidates': recovery_candidates}
    result['domains'] = domains
    result['source_provenance']['authoring_origins'] = {'tokens': tokens, 'identities': identities,
        'diagnostics': diagnostics}
    return normalize_authoring_snapshot(result)



def merge_question_analysis(current, analyzed):
    """Apply a Question-source projection without replacing Answer/Rubric state.

    Question analysis may intentionally refresh the question tree. The other
    authoring domains, their source bindings, and teacher operations remain the
    current revision's authoritative state. Candidates whose target no longer
    exists are kept for teacher recovery as unassigned candidates.
    """
    current = normalize_authoring_snapshot(current)
    analyzed = normalize_authoring_snapshot(analyzed)
    result = deepcopy(current)
    result['nodes'] = deepcopy(analyzed['nodes'])
    result.pop('question_text_buffers', None)
    result['domains'] = deepcopy(current.get('domains', {}))
    analyzed_question = analyzed.get('domains', {}).get('question')
    if analyzed_question is not None:
        result['domains']['question'] = deepcopy(analyzed_question)

    keys = {node['stable_key'] for node in result['nodes']}
    answer_domain = result['domains'].get('answer')
    if answer_domain:
        for entry in answer_domain.get('entries', []):
            target = entry.get('authoring_question_key')
            if target is not None and target not in keys:
                entry['authoring_question_key'] = None
                entry['disposition'] = 'unassigned'
                entry['mapping_state'] = 'needs_review'
    rubric_domain = result['domains'].get('rubric')
    if rubric_domain:
        for entry in rubric_domain.get('entries', []):
            target = entry.get('authoring_question_key')
            if target is not None and target not in keys:
                entry['authoring_question_key'] = None
                entry['disposition'] = 'unassigned'
    for candidate in result['domains'].get('recovery', {}).get('rubric_candidates', []):
        if candidate.get('question_key') is not None and candidate['question_key'] not in keys:
            candidate['question_key'] = None
    result['answers'] = {key: deepcopy(value) for key, value in current.get('answers', {}).items()
                         if key in keys}
    result['rubrics'] = {key: deepcopy(value) for key, value in current.get('rubrics', {}).items()
                         if key in keys}
    if 'rubric_histories' in current:
        result['rubric_histories'] = {key: deepcopy(value) for key, value in current['rubric_histories'].items()
                                      if key in keys}

    # Keep source identity for Answer and update only the explicitly analyzed
    # Question review token/identity map. The returned projection may have
    # selected a globally recent Answer import, which is irrelevant here.
    current_origins = deepcopy(current.get('source_provenance', {}).get('authoring_origins', {}))
    analyzed_origins = analyzed.get('source_provenance', {}).get('authoring_origins', {})
    if analyzed_origins.get('identities') is not None:
        current_origins['identities'] = deepcopy(analyzed_origins['identities'])
    if analyzed_origins.get('tokens', {}).get('question') is not None:
        current_origins.setdefault('tokens', {})['question'] = deepcopy(analyzed_origins['tokens']['question'])
        current_origins.pop('pending_question_review', None)
    diagnostics = [item for item in current_origins.get('diagnostics', []) if item.get('domain') != 'question']
    diagnostics.extend(item for item in analyzed_origins.get('diagnostics', []) if item.get('domain') == 'question')
    if diagnostics or 'diagnostics' in current_origins:
        current_origins['diagnostics'] = diagnostics
    result.setdefault('source_provenance', {})['authoring_origins'] = current_origins
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
                if original and any(e.get(k) != original.get(k) for k in ('source', 'candidate_text', 'extraction_method', 'source_draft_id')):
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '候補の元資料は編集できません。')
                if not original:
                    from uuid import UUID
                    try:
                        if not e['id'].startswith('teacher-entry-'):
                            raise ValueError()
                        UUID(e['id'].removeprefix('teacher-entry-'))
                        if e.get('source_draft_id', old[name]['draft_id']) not in {old[name]['draft_id'], *old[name].get('sources', {})}:
                            raise ValueError()
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
                if any(field in e for field in ('rubric_edits', 'rubric_merge_history',
                                                 'rubric_consolidated_groups')):
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '採点基準は解答候補から独立して編集してください。')
        elif name == 'rubric':
            new = domains[name]
            if (not isinstance(new, dict) or
                    {k: v for k, v in new.items() if k != 'entries'} !=
                    {k: v for k, v in old[name].items() if k != 'entries'} or
                    not isinstance(new.get('entries'), list)):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', '採点基準の出典情報は編集できません。')
            for field, source_value in old[name].items():
                if field != 'entries':
                    new[field] = deepcopy(source_value)
            originals = {entry['id']: entry for entry in old[name].get('entries', [])}
            submitted = [entry.get('id') for entry in new['entries'] if isinstance(entry, dict)]
            if (len(submitted) != len(new['entries']) or len(set(submitted)) != len(submitted)
                    or not set(originals) <= set(submitted)):
                raise AuthoringError('AUTHORING_INVALID_RUBRIC', '採点基準の識別子を確認してください。')
            keys = {node['stable_key'] for node in value['nodes']}
            for entry in new['entries']:
                original = originals.get(entry['id'])
                if entry.get('authoring_question_key') is not None and entry['authoring_question_key'] not in keys:
                    raise AuthoringError('AUTHORING_INVALID_TARGET', '採点基準の対応先を確認してください。')
                if original and any(entry.get(field) != original.get(field) for field in
                                    ('source', 'candidate_text', 'source_draft_id', 'source_candidate_id',
                                     'source_sha256', 'material_id', 'material_role')):
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '採点基準の元資料は編集できません。')
                if original is None:
                    from uuid import UUID
                    try:
                        if (entry.get('material_role') != 'teacher_manual'
                                or not entry['id'].startswith(('teacher-rubric-', 'teacher-entry-', 'legacy-formal-rubric:'))):
                            raise ValueError()
                        if entry['id'].startswith('legacy-formal-rubric:'):
                            if entry['id'] != f"legacy-formal-rubric:{entry.get('authoring_question_key')}":
                                raise ValueError()
                        else:
                            UUID(entry['id'].removeprefix('teacher-rubric-').removeprefix('teacher-entry-'))
                        source = entry.get('source', {})
                        if (source.get('kind') != 'teacher_manual' or source.get('material_id') is not None
                                or source.get('source_sha256') is not None or source.get('segments') != []
                                or set(source) - {'kind', 'material_id', 'source_sha256', 'segments'}):
                            raise ValueError()
                    except (ValueError, KeyError, AttributeError) as exc:
                        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '追加した採点基準の出典情報を確認してください。') from exc
                criteria = entry.get('criteria')
                if not isinstance(criteria, list) or len(criteria) > 500:
                    raise AuthoringError('AUTHORING_INVALID_RUBRIC', '採点基準を確認してください。')
                for criterion in criteria:
                    if (not isinstance(criterion, dict) or not isinstance(criterion.get('id'), str)
                            or not isinstance(criterion.get('description'), str)
                            or type(criterion.get('points')) not in (int, float)
                            or not math.isfinite(criterion['points']) or criterion['points'] < 0):
                        raise AuthoringError('AUTHORING_INVALID_RUBRIC', '採点基準の内容と配点を確認してください。')
            value['rubrics'] = rubric_snapshot_projection(new, keys)
            value['rubric_histories'] = {entry['authoring_question_key']: deepcopy(entry.get('operation_history', []))
                for entry in new['entries'] if entry.get('authoring_question_key') and entry.get('operation_history')}
        elif name == 'recovery':
            submitted = domains[name].get('rubric_candidates') if isinstance(domains[name], dict) else None
            originals = {entry['id']: entry for entry in old[name].get('rubric_candidates', [])}
            if not isinstance(submitted, list) or {entry.get('id') for entry in submitted if isinstance(entry, dict)} != set(originals):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', '未割当候補の出典情報は編集できません。')
            for entry in submitted:
                original = originals[entry['id']]
                if any(entry.get(key) != original.get(key) for key in original if key not in {'dismissed', 'promoted'}):
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '未割当候補の出典情報は編集できません。')
                if type(entry.get('dismissed', False)) is not bool or type(entry.get('promoted', False)) is not bool:
                    raise AuthoringError('AUTHORING_SOURCE_CHANGED', '未割当候補の状態を確認してください。')


def _install_normalized(snapshot):
    normalized = normalize_authoring_snapshot(snapshot)
    snapshot.clear()
    snapshot.update(normalized)
    return snapshot


def _candidate_result(entries, role):
    if role == 'rubric_source':
        candidates = [(entry, segment) for entry in entries
            for segment in (entry.get('semantic_classification') or {}).get('segments', [])
            if segment.get('category') == 'rubric' or
            (segment.get('category') == 'uncertain' and
             (entry.get('semantic_classification') or {}).get('status') in
             {'classified', 'needs_teacher_review', 'teacher_reviewed'})]
        candidate_count = len(candidates)
        assigned = sum(bool(entry.get('authoring_question_key')) for entry, _ in candidates)
    else:
        candidate_count = len(entries)
        assigned = sum(bool(entry.get('authoring_question_key')) for entry in entries)
    fallback_count = sum(1 for entry in entries if
        (entry.get('semantic_classification') or {}).get('status') in {'fallback', 'needs_teacher_review'}
        or (entry.get('semantic_classification') or {}).get('retry_error'))
    return {'status': 'no_candidates' if not candidate_count else
            'assigned' if assigned == candidate_count else 'partial' if assigned else 'needs_assignment',
            'assigned_count': assigned, 'unresolved_count': candidate_count-assigned,
            'fallback_count': fallback_count, 'candidate_count': candidate_count}


def merge_answer_analysis(snapshot, draft, material_role='model_answer_source'):
    """Merge one Answer import into AnswerDraft; never writes RubricDraft."""
    if material_role != 'model_answer_source':
        raise ValueError('answer_analysis_role_mismatch')
    _install_normalized(snapshot)
    from .authoring_answers import authoring_questions
    aliases, questions = authoring_questions(snapshot)
    gradable = {q.id for q in questions if q.is_gradable}
    inverse = {identifier: key for key, identifier in aliases.items() if identifier in gradable}
    entries = deepcopy(draft.snapshot.get('entries', []))
    for entry in entries:
        for field in ('rubric_edits', 'rubric_merge_history', 'rubric_consolidated_groups'):
            entry.pop(field, None)
        entry['authoring_question_key'] = inverse.get(entry.get('question_id'))
        entry['source_draft_id'] = draft.id
        entry['material_role'] = 'model_answer_source'
        if not entry['authoring_question_key']:
            entry.update(disposition='unassigned', mapping_state='needs_review')

    domains = snapshot.setdefault('domains', {})
    old = domains.get('answer') or {}
    sources = deepcopy(old.get('sources', {}))
    if old:
        sources[old['draft_id']] = {k: deepcopy(v) for k, v in old.items()
            if k not in {'entries', 'sources', 'analysis_result', 'analysis_results'}}
        sources[old['draft_id']].setdefault('material_role', 'model_answer_source')
    retained, incoming_by_id = [], {entry['id']: entry for entry in entries}
    for entry in old.get('entries', []):
        source_id = entry.get('source_draft_id', old.get('draft_id'))
        source = sources.get(source_id, {})
        if source.get('material_id') != draft.material_id:
            retained.append({**deepcopy(entry), 'source_draft_id': source_id})
            continue
        if source.get('source_sha256') != draft.source_sha256:
            continue
        incoming = incoming_by_id.get(entry['id'])
        accepted_diagrams = any(r.get('state') == 'accepted' for r in entry.get('diagram_records', []))
        classification = entry.get('semantic_classification') or {}
        teacher_answer_work = bool(entry.get('teacher_correction')) or (
            classification.get('status') == 'teacher_reviewed' and any(
                segment.get('category') in {'model_answer', 'alternative_answer'}
                for segment in classification.get('segments', [])))
        incoming_classification = (incoming or {}).get('semantic_classification') or {}
        if incoming is not None and teacher_answer_work and incoming_classification.get('status') == 'fallback':
            incoming['answer_text'] = entry.get('answer_text', '')
            incoming['answer_kind'] = entry.get('answer_kind', 'primary')
            if entry.get('teacher_correction'):
                incoming['teacher_correction'] = deepcopy(entry['teacher_correction'])
            if classification.get('status') == 'teacher_reviewed':
                incoming['semantic_classification'] = deepcopy(classification)
        if incoming is not None and accepted_diagrams:
            incoming['diagram_records'] = deepcopy(entry['diagram_records'])
        elif incoming is None and (accepted_diagrams or teacher_answer_work):
            preserved = {**deepcopy(entry), 'source_draft_id': source_id}
            if not teacher_answer_work:
                preserved.update(answer_text='', answer_kind='alternative')
                preserved.pop('manual_alternative_answers', None)
                preserved['diagram_records'] = deepcopy(entry.get('diagram_records', []))
            retained.append(preserved)
    answer_entries = retained + entries
    used_sources = {entry['source_draft_id'] for entry in retained}
    sources = {key: value for key, value in sources.items() if key in used_sources}
    result = _candidate_result(entries, 'model_answer_source')
    answer_results = {key: deepcopy(value) for key, value in old.get('analysis_results', {}).items()
                      if key == 'model_answer_source'}
    if old.get('analysis_result'):
        answer_results.setdefault('model_answer_source', deepcopy(old['analysis_result']))
    answer_results['model_answer_source'] = result
    domains['answer'] = {'draft_id': draft.id, 'revision': draft.revision,
        'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
        'artifact_ref': draft.artifact_ref,
        'question_regions': deepcopy(draft.snapshot.get('question_regions', [])),
        'material_role': 'model_answer_source', 'entries': answer_entries,
        'sources': sources, 'analysis_result': result, 'analysis_results': answer_results}

    recovery = domains.setdefault('recovery', {}).setdefault('rubric_candidates', [])
    recovery = [candidate for candidate in recovery
                if not (candidate.get('origin_role') == 'model_answer_source'
                        and candidate.get('source_binding_id') == draft.material_id)]
    for entry in entries:
        classification = entry.get('semantic_classification') or {}
        for segment in recoverable_rubric_segments(entry):
            recovery.append({'id': f"recovery:{draft.id}:{segment.get('id')}",
                'origin_role': 'model_answer_source', 'source_draft_id': draft.id,
                'source_candidate_id': entry['id'], 'source_binding_id': draft.material_id,
                'source_sha256': draft.source_sha256, 'segment_id': segment.get('id'),
                'text': segment.get('text', ''), 'category': segment.get('category'),
                'classification_status': classification.get('status'),
                'question_key': entry.get('authoring_question_key'),
                'provenance': deepcopy(segment.get('provenance') or {})})
    domains['recovery']['rubric_candidates'] = recovery

    for key in {entry.get('authoring_question_key') for entry in answer_entries if entry.get('authoring_question_key')}:
        current = [entry for entry in answer_entries if entry.get('authoring_question_key') == key
                   and entry.get('disposition', 'include') == 'include']
        answer_rows = [entry for entry in current if entry.get('answer_text', '').strip() or
                       any(record.get('state') == 'accepted' for record in entry.get('diagram_records', []))]
        primary = next((entry for entry in answer_rows if entry.get('answer_kind', 'primary') == 'primary'), None)
        if answer_rows:
            snapshot['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                'alternatives': answer_alternatives(answer_rows),
                'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
    snapshot['rubrics'] = rubric_snapshot_projection(domains['rubric'],
        {node['stable_key'] for node in snapshot.get('nodes', [])})
    snapshot['rubric_histories'] = {entry['authoring_question_key']: deepcopy(entry.get('operation_history', []))
        for entry in domains['rubric'].get('entries', [])
        if entry.get('authoring_question_key') and entry.get('operation_history')}
    return result


def merge_rubric_analysis(snapshot, draft):
    """Merge one Rubric import into RubricDraft; never writes AnswerDraft."""
    _install_normalized(snapshot)
    from .authoring_answers import authoring_questions
    aliases, questions = authoring_questions(snapshot)
    gradable = {question.id for question in questions if question.is_gradable}
    inverse = {identifier: key for key, identifier in aliases.items() if identifier in gradable}
    incoming = deepcopy(draft.snapshot.get('entries', []))
    for entry in incoming:
        entry['authoring_question_key'] = inverse.get(entry.get('question_id'))
        entry['source_draft_id'] = draft.id
        entry['material_role'] = 'rubric_source'
        if not entry['authoring_question_key']:
            entry.update(disposition='unassigned', mapping_state='needs_review')

    domains = snapshot.setdefault('domains', {})
    rubric = domains.setdefault('rubric', _empty_rubric_domain())
    old_entries = deepcopy(rubric.get('entries', []))
    old_sources = deepcopy(rubric.get('sources', {}))
    if rubric.get('draft_id'):
        old_sources[rubric['draft_id']] = {key: deepcopy(value) for key, value in rubric.items()
            if key not in {'entries', 'sources', 'analysis_result', 'analysis_results'}}
    new_entries, recoveries = [], []
    incoming_ids = set()
    for candidate in incoming:
        criteria = rubric_projection(candidate)
        question_key = candidate.get('authoring_question_key')
        source_id = candidate['id']
        incoming_ids.add(source_id)
        old = next((value for value in old_entries if value.get('source_candidate_id') == source_id
                    and value.get('source_draft_id') == draft.id), None)
        if old:
            # Preserve teacher-modified fields by criterion identity when the
            # source analysis regenerates the same native groups.
            old_by_id = {criterion.get('id'): criterion for criterion in old.get('criteria', [])}
            criteria = [{**criterion, **({key: deepcopy(value) for key, value in old_by_id[criterion.get('id')].items()
                if key not in {'id', 'segment_ids', 'source_text'}} if criterion.get('id') in old_by_id else {})}
                for criterion in criteria]
        if criteria and question_key:
            new_entries.append({'id': f'rubric-source:{draft.id}:{source_id}',
                'source_candidate_id': source_id, 'authoring_question_key': question_key,
                'question_id': candidate.get('question_id'), 'material_role': 'rubric_source',
                'source_draft_id': draft.id, 'material_id': draft.material_id,
                'source_sha256': draft.source_sha256, 'source': deepcopy(candidate.get('source', {})),
                'candidate_text': candidate.get('candidate_text', ''),
                'semantic_classification': deepcopy(candidate.get('semantic_classification')),
                'disposition': candidate.get('disposition', 'include'), 'criteria': criteria,
                'operation_history': deepcopy(old.get('operation_history', [])) if old else []})
        else:
            classification = candidate.get('semantic_classification') or {}
            for segment in recoverable_rubric_segments(candidate):
                recoveries.append({'id': f"recovery:{draft.id}:{segment.get('id')}",
                    'origin_role': 'rubric_source', 'source_draft_id': draft.id,
                    'source_candidate_id': source_id, 'source_binding_id': draft.material_id,
                    'source_sha256': draft.source_sha256, 'segment_id': segment.get('id'),
                    'text': segment.get('text', ''), 'category': segment.get('category'),
                    'classification_status': classification.get('status'),
                    'question_key': question_key, 'provenance': deepcopy(segment.get('provenance') or {})})

    # Keep manual/legacy criteria and imports from other role bindings. Re-run
    # supersedes only the selected material binding.
    incoming_candidate_ids = {entry.get('id') for entry in incoming}
    def preserve_teacher_rubric(entry):
        return bool(entry.get('operation_history')) or any(
            criterion.get('grouping_method') in {'teacher_manual', 'teacher_recovery'} or
            (criterion.get('provenance') or {}).get('teacher_confirmed') or
            (criterion.get('provenance') or {}).get('teacher_recovered')
            for criterion in entry.get('criteria', []))
    retained = [entry for entry in old_entries
        if entry.get('material_id') != draft.material_id
        or entry.get('material_role') == 'teacher_manual'
        or not new_entries
        or (entry.get('source_candidate_id') not in incoming_candidate_ids and preserve_teacher_rubric(entry))]
    rubric_sources = {key: value for key, value in old_sources.items()
        if value.get('material_id') != draft.material_id}
    result = _candidate_result(incoming, 'rubric_source')
    result['candidate_count'] = sum(1 for entry in incoming
        for segment in (entry.get('semantic_classification') or {}).get('segments', [])
        if segment.get('category') == 'rubric' or (segment.get('category') == 'uncertain'
           and (entry.get('semantic_classification') or {}).get('status') in
           {'classified', 'needs_teacher_review', 'teacher_reviewed'}))
    result['assigned_count'] = sum(1 for entry in incoming
        if entry.get('authoring_question_key') and any(segment.get('category') == 'rubric'
            or (segment.get('category') == 'uncertain' and
                (entry.get('semantic_classification') or {}).get('status') in
                {'classified', 'needs_teacher_review', 'teacher_reviewed'})
            for segment in (entry.get('semantic_classification') or {}).get('segments', [])))
    result['unresolved_count'] = result['candidate_count'] - result['assigned_count']
    rubric_results = {key: deepcopy(value) for key, value in rubric.get('analysis_results', {}).items()
                      if key == 'rubric_source'}
    if rubric.get('analysis_result'):
        rubric_results.setdefault('rubric_source', deepcopy(rubric['analysis_result']))
    rubric_results['rubric_source'] = result
    domains['rubric'] = {'draft_id': draft.id, 'revision': draft.revision,
        'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
        'artifact_ref': draft.artifact_ref, 'material_role': 'rubric_source',
        'entries': retained + new_entries,
        'sources': rubric_sources, 'analysis_result': result, 'analysis_results': rubric_results}
    recovery = domains.setdefault('recovery', {}).setdefault('rubric_candidates', [])
    recovery = [candidate for candidate in recovery
        if not (candidate.get('origin_role') == 'rubric_source'
                and candidate.get('source_binding_id') == draft.material_id)]
    domains['recovery']['rubric_candidates'] = recovery + recoveries
    snapshot['rubrics'] = rubric_snapshot_projection(domains['rubric'],
        {node['stable_key'] for node in snapshot.get('nodes', [])})
    snapshot['rubric_histories'] = {entry['authoring_question_key']: deepcopy(entry.get('operation_history', []))
        for entry in domains['rubric'].get('entries', [])
        if entry.get('authoring_question_key') and entry.get('operation_history')}
    return result
