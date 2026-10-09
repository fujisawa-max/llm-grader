"""Read-only adapters for saved domain reviews. Never infer or publish."""
from copy import deepcopy
import json
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

    # Candidate storage is shared by the current editor, while projected Answer
    # and Rubric domains are role-owned. Keep one latest source per role instead
    # of allowing a globally latest import to replace the other role's context.
    combined_entries, source_bindings = [], {}
    answer_source = latest_by_role.get('model_answer_source')
    rubric_source = latest_by_role.get('rubric_source')
    primary_source = answer_source or rubric_source
    for role_name, pair in (('model_answer_source', answer_source), ('rubric_source', rubric_source)):
        if not pair:
            continue
        draft, material = pair
        source_bindings[draft.id] = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'material_role': role_name,
            'question_regions': deepcopy(draft.snapshot.get('question_regions', []))}
        entries = deepcopy(draft.snapshot.get('entries', []))
        for entry in entries:
            entry['authoring_question_key'] = formal_to_key.get(entry.get('question_id'))
            entry['source_draft_id'] = draft.id
            entry['material_role'] = role_name
        combined_entries.extend(entries)
        assigned = {entry['authoring_question_key'] for entry in entries if entry.get('authoring_question_key')}
        for key in assigned:
            current = [entry for entry in entries if entry.get('authoring_question_key') == key
                       and entry.get('disposition', 'include') == 'include']
            if role_name == 'model_answer_source':
                primary = next((entry for entry in current if entry.get('answer_kind', 'primary') == 'primary'), None)
                result['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                    'alternatives': answer_alternatives(current),
                    'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
            elif any(has_rubric_state(entry) for entry in current):
                result['rubrics'][key] = [criterion for entry in current for criterion in rubric_projection(entry)]

    if primary_source:
        draft, _material = primary_source
        domains['answer'] = {'draft_id': draft.id, 'revision': draft.revision,
            'material_id': draft.material_id, 'source_sha256': draft.source_sha256,
            'artifact_ref': draft.artifact_ref, 'question_regions': deepcopy(draft.snapshot.get('question_regions', [])),
            'entries': combined_entries, 'sources': source_bindings}
    result['domains'] = domains
    result['source_provenance']['authoring_origins'] = {'tokens': tokens, 'identities': identities,
        'diagnostics': diagnostics}
    return result



def merge_question_analysis(current, analyzed):
    """Apply a Question-source projection without replacing Answer/Rubric state.

    Question analysis may intentionally refresh the question tree. The other
    authoring domains, their source bindings, and teacher operations remain the
    current revision's authoritative state. Candidates whose target no longer
    exists are kept for teacher recovery as unassigned candidates.
    """
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


def merge_answer_analysis(snapshot, draft, material_role='model_answer_source'):
    """Merge source-bound candidates into the current tree, without inference."""
    from .authoring_answers import authoring_questions
    aliases, questions = authoring_questions(snapshot)
    gradable = {q.id for q in questions if q.is_gradable}
    inverse = {identifier: key for key, identifier in aliases.items() if identifier in gradable}
    entries = deepcopy(draft.snapshot.get('entries', []))
    for entry in entries:
        if material_role == 'rubric_source':
            entry['answer_text'] = ''
        entry['authoring_question_key'] = inverse.get(entry.get('question_id'))
        entry['source_draft_id'] = draft.id
        entry['material_role'] = material_role
        if not entry['authoring_question_key']:
            entry.update(disposition='unassigned', mapping_state='needs_review')
    old = snapshot.get('domains', {}).get('answer') or {}
    sources = deepcopy(old.get('sources', {}))
    if old:
        sources[old['draft_id']] = {k: deepcopy(v) for k, v in old.items()
                                  if k not in {'entries', 'sources', 'analysis_result', 'analysis_results'}}
        sources[old['draft_id']].setdefault('material_role', old.get('material_role', 'model_answer_source'))
    retained = []
    incoming_by_id = {entry['id']: entry for entry in entries}
    for entry in old.get('entries', []):
        source_id = entry.get('source_draft_id', old.get('draft_id'))
        source = sources.get(source_id, {})
        # Reanalysis supersedes only this material; other sources remain intact.
        if source.get('material_id') != draft.material_id:
            retained.append({**deepcopy(entry), 'source_draft_id': source_id})
            continue
        if source.get('source_sha256') != draft.source_sha256:
            continue
        incoming = incoming_by_id.get(entry['id'])
        # Rubric edits live on source-bound candidate entries. Answer reanalysis
        # may replace those entries, so explicitly carry the independently owned
        # Rubric decisions forward when the native entry identity is stable.
        rubric_fields = ('rubric_edits', 'rubric_consolidated_groups', 'rubric_merge_history')
        if incoming is not None:
            for field in rubric_fields:
                if field in entry:
                    incoming[field] = deepcopy(entry[field])
        accepted_diagrams = any(r.get('state') == 'accepted' for r in entry.get('diagram_records', []))
        classification = entry.get('semantic_classification') or {}
        teacher_answer_work = bool(entry.get('teacher_correction')) or (
            classification.get('status') == 'teacher_reviewed' and any(
                segment.get('category') in {'model_answer', 'alternative_answer'}
                for segment in classification.get('segments', [])))
        teacher_rubric_work = bool(entry.get('rubric_edits')) or (
            classification.get('status') == 'teacher_reviewed' and any(
                segment.get('category') in {'rubric', 'uncertain'}
                for segment in classification.get('segments', [])))
        incoming_classification = (incoming or {}).get('semantic_classification') or {}
        if incoming is not None and teacher_answer_work and incoming_classification.get('status') == 'fallback':
            # A failed classifier response is not an answer update. Keep the
            # teacher-owned answer on the source-matched candidate even when
            # native extraction assigned it a new candidate ID.
            incoming['answer_text'] = entry.get('answer_text', '')
            incoming['answer_kind'] = entry.get('answer_kind', 'primary')
            if entry.get('teacher_correction'):
                incoming['teacher_correction'] = deepcopy(entry['teacher_correction'])
            if classification.get('status') == 'teacher_reviewed':
                incoming['semantic_classification'] = deepcopy(classification)
        if incoming is not None and accepted_diagrams:
            incoming['diagram_records'] = deepcopy(entry['diagram_records'])
        elif incoming is None and (accepted_diagrams or teacher_rubric_work or teacher_answer_work):
            # Native extraction creates fresh entry UUIDs. Retain teacher-owned
            # Answer/Rubric work on its original source identity; do not silently
            # lose it just because reanalysis returned new geometry candidates.
            preserved = {**deepcopy(entry), 'source_draft_id': source_id}
            if not teacher_answer_work:
                preserved.update(answer_text='', answer_kind='alternative')
            if not teacher_rubric_work and not teacher_answer_work:
                # Accepted diagrams outlive analysis only as verified image
                # assignments; unrelated old classifier output is superseded.
                preserved.update(rubric_edits=[], semantic_classification=None)
                for field in rubric_fields + ('manual_alternative_answers',):
                    preserved.pop(field, None)
            if not accepted_diagrams and not teacher_answer_work:
                preserved['diagram_records'] = []
                if teacher_rubric_work:
                    preserved['rubric_only_preserved'] = True
            retained.append(preserved)
    used_sources = {e['source_draft_id'] for e in retained}
    sources = {k: v for k, v in sources.items() if k in used_sources}
    if material_role == 'rubric_source':
        candidates = [(entry, segment) for entry in entries
            for segment in (entry.get('semantic_classification') or {}).get('segments', [])
            if segment.get('category') == 'rubric' or
            (segment.get('category') == 'uncertain' and
             (entry.get('semantic_classification') or {}).get('status') in
             {'classified', 'needs_teacher_review', 'teacher_reviewed'})]
        assigned = sum(bool(entry.get('authoring_question_key')) for entry, _ in candidates)
        candidate_count = len(candidates)
    else:
        assigned = sum(bool(e['authoring_question_key']) for e in entries)
        candidate_count = len(entries)
    fallback_count = sum(1 for entry in entries if
        (entry.get('semantic_classification') or {}).get('status') == 'fallback' or
        (entry.get('semantic_classification') or {}).get('retry_error'))
    result = {'status': 'no_candidates' if not candidate_count else
              'assigned' if assigned == candidate_count else 'partial' if assigned else 'needs_assignment',
              'assigned_count': assigned, 'unresolved_count': candidate_count-assigned,
              'fallback_count': fallback_count,
              'candidate_count': candidate_count}
    analysis_results = deepcopy(old.get('analysis_results', {}))
    if old.get('analysis_result') and old.get('material_role'):
        analysis_results.setdefault(old['material_role'], deepcopy(old['analysis_result']))
    analysis_results[material_role] = result
    snapshot.setdefault('domains', {})['answer'] = {
        'draft_id': draft.id, 'revision': draft.revision, 'material_id': draft.material_id,
        'source_sha256': draft.source_sha256, 'artifact_ref': draft.artifact_ref,
        'question_regions': deepcopy(draft.snapshot.get('question_regions', [])),
        'material_role': material_role,
        'entries': retained+entries, 'sources': sources, 'analysis_result': result,
        'analysis_results': analysis_results}
    for key in {e['authoring_question_key'] for e in retained+entries if e.get('authoring_question_key')}:
        current = [e for e in retained+entries if e.get('authoring_question_key') == key
                   and e.get('disposition', 'include') == 'include']
        answer_entries = [e for e in current if e.get('answer_text', '').strip() or
                          any(r.get('state') == 'accepted' for r in e.get('diagram_records', []))]
        primary = next((e for e in answer_entries if e.get('answer_kind', 'primary') == 'primary'), None)
        if answer_entries and material_role != 'rubric_source':
            snapshot['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                'alternatives': answer_alternatives(answer_entries),
                'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
        # A source can contain text that looks like a rubric, but only an
        # explicit Rubric-role analysis may update the Rubric projection.
        # Answer-source rubric-like segments remain available as candidates
        # for explicit teacher promotion in the workspace.
        if material_role == 'rubric_source' and any(has_rubric_state(e) for e in current):
            rubric_current = entries
            projected = [c for e in rubric_current if e.get('authoring_question_key') == key for c in rubric_projection(e)]
            # A fresh role analysis with only unresolved classifier segments is
            # not evidence that the teacher's existing criteria should be erased.
            if projected:
                snapshot['rubrics'][key] = projected
    return result
