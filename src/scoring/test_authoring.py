"""Whole-test draft foundation. Never publishes partial formal domain state.

Existing formal data and review provenance are copied, never rewritten. The
publication boundary stays closed until the source-domain and grading revision
adapters can atomically publish a complete, pinned confirmed revision.
"""
from copy import deepcopy
import json
import math
from uuid import uuid4

from sqlalchemy import select, update, func, or_

from .db.models import (Test, TestQuestion, TestMaterial, ModelAnswer, RubricVersion,
    TestQuestionAsset, StudentSubmission, GradingJob, GradingJobItem,
    TestAuthoringRevision, ConfirmedAuthoringRevision, TestArchive, DomainEvent, now)
from .pdf_native import canonical_hash


class AuthoringError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def projection(session, test, *, refresh=False):
    if refresh:
        session.refresh(test)
    questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test.id)
        .order_by(TestQuestion.sort_order, TestQuestion.id).execution_options(populate_existing=refresh)))
    answers = list(session.scalars(select(ModelAnswer).where(ModelAnswer.test_id == test.id,
        ModelAnswer.is_current.is_(True)).execution_options(populate_existing=refresh)))
    rubric = session.scalar(select(RubricVersion).where(RubricVersion.test_id == test.id,
        RubricVersion.status == 'approved').order_by(RubricVersion.version.desc()).execution_options(populate_existing=refresh))
    assets = list(session.scalars(select(TestQuestionAsset).join(TestQuestion)
        .where(TestQuestion.test_id == test.id)))
    nodes, answer_map, rubric_map = [], {}, {}
    for q in questions:
        text = q.question_text or ''
        if not text and q.content:
            text = '\n'.join(str(v.get('text') if v.get('type') == 'text' else v.get('transcription') or '')
                for v in q.content.get('items', []) if v.get('type') in {'text', 'formula'})
        nodes.append({'review_node_id': q.id, 'stable_key': q.id,
            'source_draft_stable_key': None, 'source_draft_node_id': None,
            'parent_key': q.parent_id, 'node_type': 'subquestion' if q.parent_id else 'major_question',
            'depth': 0, 'sort_order': q.sort_order, 'label': {'raw': q.display_label or q.question_number,
                'normalized': q.display_label or q.question_number}, 'body_text': text,
            'ordered_content': [{'type': 'text', 'order': 0, 'text': text}], 'included': True,
            'score_semantics': 'direct' if q.is_gradable else 'sum_children', 'score_points': q.max_points,
            'review_flags': [], 'formula_decisions': {}, 'figure_decisions': {}, 'warning_states': {}})
        answer = next((a for a in answers if a.question_id == q.id), None)
        answer_map[q.id] = {'primary': answer.answer_text or '' if answer else '', 'alternatives': [],
            'diagram_records': deepcopy((answer.provenance_json or {}).get('diagrams', [])) if answer else []}
        criteria = next((r.get('criteria', []) for r in (rubric.rubric_json.get('questions', []) if rubric else [])
            if r.get('question_id') == q.id), [])
        rubric_map[q.id] = deepcopy(criteria)
    return {'schema_version': 'test-authoring.v1', 'metadata': {'name': test.name,
        'description': test.description or '', 'total_points': test.total_points},
        'nodes': nodes, 'answers': answer_map, 'rubrics': rubric_map,
        # This is original evidence, separate from the unified editing projection.
        'source_provenance': {'questions': [{k: deepcopy(getattr(q, k)) for k in
            ('id', 'content', 'content_sha256', 'provenance', 'stable_question_key')} for q in questions],
            'model_answers': [{k: deepcopy(getattr(a, k)) for k in
                ('id', 'question_id', 'version', 'material_id', 'provenance_json')} for a in answers],
            'rubric': {'id': rubric.id, 'version': rubric.version,
                'generation_metadata': deepcopy(rubric.generation_metadata)} if rubric else None,
            'assets': [{k: deepcopy(getattr(a, k)) for k in ('id', 'question_id', 'sha256',
                'artifact_ref', 'provenance')} for a in assets]},
        'materials': [{'id': m.id, 'sha256': m.sha256, 'role': m.material_type} for m in
            session.scalars(select(TestMaterial).where(TestMaterial.test_id == test.id,
                TestMaterial.material_type != 'student_answer_source').order_by(TestMaterial.created_at, TestMaterial.id))]}


def baseline_hash(snapshot):
    return canonical_hash({k: v for k, v in snapshot.items() if k != 'materials'})


def latest(session, test_id, *, include_backups=False):
    from sqlalchemy import case
    query = select(TestAuthoringRevision).where(TestAuthoringRevision.test_id == test_id)
    if include_backups:
        return session.scalar(query.order_by(TestAuthoringRevision.revision.desc()))
    return session.scalar(query.where(TestAuthoringRevision.state.in_(['draft', 'final_review', 'confirmed']))
        .order_by(case((TestAuthoringRevision.state.in_(['draft', 'final_review']), 0), else_=1),
                  TestAuthoringRevision.revision.desc()))


def create_draft(session, test, actor=None, *, source_roots=None, confirmed_revision_id=None):
    session.scalar(select(Test).where(Test.id == test.id).with_for_update().execution_options(populate_existing=True))
    if session.get(TestArchive, test.id):
        raise AuthoringError('TEST_ARCHIVED', 'このテストはアーカイブされています。')
    highest = latest(session, test.id, include_backups=True)
    prior = latest(session, test.id) or highest
    parent_id = confirmed_revision_id or test.active_confirmed_revision_id
    parent = session.get(ConfirmedAuthoringRevision, parent_id) if parent_id else None
    if parent_id and (not parent or parent.test_id != test.id):
        raise AuthoringError('AUTHORING_REVISION_NOT_FOUND', 'このテストの確定版を選択してください。')
    if prior and prior.state in {'draft', 'final_review'}:
        if confirmed_revision_id and prior.parent_confirmed_revision_id != parent_id:
            raise AuthoringError('AUTHORING_DRAFT_EXISTS', '編集可能な下書きがあります。現在の下書きを開いてください。')
        return prior
    if parent and canonical_hash(parent.snapshot) != parent.snapshot_sha256:
        raise AuthoringError('AUTHORING_CONFIRMED_INTEGRITY', '確定版の内容を確認できません。')
    baseline = projection(session, test)
    snapshot = deepcopy(parent.snapshot if parent else prior.snapshot if prior else baseline)
    if not prior and source_roots:
        from .authoring_sources import source_projection
        snapshot = source_projection(session, test, baseline, *source_roots)
    if not parent:
        from .authoring_sources import normalize_authoring_snapshot
        from .grading_definition import freeze_definition, capture_evidence
        snapshot = normalize_authoring_snapshot(snapshot)
        freeze_definition(snapshot, capture_evidence(session, snapshot, test.id))
    row = TestAuthoringRevision(id=str(uuid4()), test_id=test.id,
        revision=highest.revision+1 if highest else 1,
        edit_version=(session.scalar(select(func.max(TestAuthoringRevision.edit_version)).where(
            TestAuthoringRevision.test_id == test.id)) or 0)+1, state='draft',
        parent_confirmed_revision_id=parent.id if parent else None,
        snapshot=snapshot, snapshot_sha256=canonical_hash(snapshot),
        baseline_sha256=baseline_hash(baseline), created_by=actor)
    session.add(row)
    session.add(DomainEvent(entity_type='test', entity_id=test.id,
        event_type='authoring_draft_created', actor_user_id=actor, payload={'revision': row.revision}))
    session.flush()
    return row


def validate_snapshot(value, previous):
    # Older drafts stored Rubric edits inside Answer candidate entries.  Read
    # both sides through the same deterministic adapter before CAS validation
    # so the first save upgrades the JSON shape without losing teacher work.
    from .authoring_sources import normalize_authoring_snapshot
    submitted_rubrics = deepcopy(value.get('rubrics', {})) if isinstance(value, dict) else {}
    submitted_rubric_domain = deepcopy(value.get('domains', {}).get('rubric')) if isinstance(value, dict) else None
    saved_recovery_ids = {candidate.get('id') for candidate in previous.get('domains', {}).get(
        'recovery', {}).get('rubric_candidates', [])}
    previous = normalize_authoring_snapshot(previous)
    legacy_points_only = {
        criterion['id']: criterion['points']
        for entry in previous.get('domains', {}).get('rubric', {}).get('entries', [])
        if isinstance(entry, dict)
        for criterion in entry.get('criteria', [])
        if isinstance(criterion, dict) and isinstance(criterion.get('id'), str)
        and not criterion.get('levels')
    }
    # Legacy recovery rows are derived on read. Seed them from the saved
    # automatic evidence before adapting a teacher's new routing decision;
    # otherwise that edit changes their immutable status/target provenance.
    value = deepcopy(value)
    if isinstance(value, dict):
        recovery = value.setdefault('domains', {}).setdefault('recovery', {})
        candidates = recovery.setdefault('rubric_candidates', [])
        if isinstance(candidates, list):
            submitted_ids = {candidate.get('id') for candidate in candidates if isinstance(candidate, dict)}
            candidates.extend(deepcopy(candidate) for candidate in previous['domains']['recovery']['rubric_candidates']
                              if candidate['id'] not in saved_recovery_ids | submitted_ids)
    value = normalize_authoring_snapshot(value)
    # The executable projection/evidence is server-owned, never client policy.
    saved_definition = previous.get('domains', {}).get('grading_definition')
    if saved_definition is not None:
        value['domains']['grading_definition'] = deepcopy(saved_definition)
    else:
        value['domains'].pop('grading_definition', None)
    # Older clients edited the flattened `rubrics` map. Translate such a
    # write into RubricDraft when the role-specific domain itself is unchanged.
    # This preserves the API's legacy round-trip while keeping the separated
    # domain authoritative after validation.
    if (isinstance(submitted_rubrics, dict) and submitted_rubrics != previous.get('rubrics')
            and submitted_rubric_domain in (None, previous.get('domains', {}).get('rubric'))):
        value['rubrics'] = submitted_rubrics
        rubric = value['domains']['rubric']
        question_keys = set(value.get('rubrics', {})) | set(previous.get('rubrics', {}))
        for key in question_keys:
            submitted = value.get('rubrics', {}).get(key, [])
            old_projection = previous.get('rubrics', {}).get(key, [])
            if submitted == old_projection:
                continue
            incoming = {criterion.get('id'): criterion for criterion in submitted if isinstance(criterion, dict)}
            known = set()
            for entry in rubric.get('entries', []):
                if entry.get('authoring_question_key') != key:
                    continue
                current = []
                for criterion in entry.get('criteria', []):
                    identifier = criterion.get('id')
                    known.add(identifier)
                    replacement = incoming.get(identifier)
                    if replacement is None:
                        current.append({**criterion, 'excluded': True})
                        continue
                    # Legacy projection writes can edit teacher-facing fields,
                    # but may not rewrite criterion provenance or stable IDs.
                    allowed = {field: replacement[field] for field in
                        ('description', 'points', 'excluded', 'points_confirmed', 'grouping_confirmed', 'levels')
                        if field in replacement}
                    current.append({**criterion, **allowed})
                entry['criteria'] = current
            additions = [deepcopy(criterion) for identifier, criterion in incoming.items() if identifier not in known]
            if additions:
                manual = next((entry for entry in rubric.get('entries', [])
                               if entry.get('authoring_question_key') == key
                               and entry.get('material_role') == 'teacher_manual'), None)
                if manual is None:
                    identity = (value.get('source_provenance', {}).get('authoring_origins', {})
                                .get('identities', {}).get(key, {}).get('formal_question_id') or key)
                    manual = {'id': f'teacher-rubric-{uuid4()}', 'authoring_question_key': key,
                        'question_id': identity, 'material_role': 'teacher_manual', 'source_draft_id': None,
                        'material_id': None, 'source_sha256': None,
                        'source': {'kind': 'teacher_manual', 'material_id': None,
                            'source_sha256': None, 'segments': []}, 'criteria': [], 'operation_history': []}
                    rubric.setdefault('entries', []).append(manual)
                manual['criteria'].extend(additions)
    if (not isinstance(value, dict) or value.get('schema_version') != 'test-authoring.v1'
            or set(value) - {'question_text_buffers'} != set(previous) - {'question_text_buffers'} or len(json.dumps(value, ensure_ascii=False)) > 4_000_000):
        raise AuthoringError('AUTHORING_INVALID_SNAPSHOT', '下書きの形式が不正です。')
    # No client may manufacture/replace original evidence while editing text.
    if value['source_provenance'] != previous['source_provenance']:
        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '元資料の出典情報は編集できません。')
    value['source_provenance'] = deepcopy(previous['source_provenance'])
    if 'domains' in previous:
        from .authoring_sources import validate_domains
        # On the Web authoring path, executable score levels are canonical.
        # Keep `points` only as a compatibility projection for older domain
        # adapters; malformed/incomplete score rows are left for validation.
        rubric_domain = value.get('domains', {}).get('rubric', {})
        for entry in rubric_domain.get('entries', []) if isinstance(rubric_domain, dict) else []:
            for criterion in entry.get('criteria', []) if isinstance(entry, dict) else []:
                levels = criterion.get('levels') if isinstance(criterion, dict) else None
                if isinstance(levels, list) and not levels and criterion.get('id') in legacy_points_only:
                    # Keep editable legacy points-only drafts stable until the
                    # teacher explicitly opens/prepares their Rubric editor.
                    criterion['points'] = legacy_points_only[criterion['id']]
                elif isinstance(levels, list) and all(
                    isinstance(level, dict)
                    and (level.get('score') is None or (
                        type(level.get('score')) in (int, float)
                        and math.isfinite(level['score'])
                        and level['score'] >= 0
                    ))
                    for level in levels
                ):
                    criterion['points'] = max(
                        (level['score'] for level in levels if level.get('score') is not None),
                        default=0,
                    )
        validate_domains(value, previous)
    if (not isinstance(value['metadata'], dict) or not isinstance(value['metadata'].get('name'), str)
            or not value['metadata']['name'].strip() or len(value['metadata']['name']) > 200
            or type(value['metadata'].get('total_points')) not in (int, float)
            or not math.isfinite(value['metadata']['total_points']) or value['metadata']['total_points'] < 0):
        raise AuthoringError('AUTHORING_INVALID_METADATA', 'テスト名を確認してください。')
    nodes = value.get('nodes')
    if not isinstance(nodes, list) or len(nodes) > 1000:
        raise AuthoringError('AUTHORING_INVALID_HIERARCHY', '設問の構造を確認してください。')
    keys = [n.get('stable_key') for n in nodes if isinstance(n, dict)]
    if len(keys) != len(nodes) or any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(keys):
        raise AuthoringError('AUTHORING_INVALID_HIERARCHY', '設問IDが重複しています。')
    buffers = value.get('question_text_buffers', {})
    if (not isinstance(buffers, dict) or not set(buffers) <= set(keys) or
            any(not isinstance(v, str) or len(v) > 20000 for v in buffers.values())):
        raise AuthoringError('AUTHORING_INVALID_TEXT', '問題文の編集内容を確認してください。')
    by_key = {n['stable_key']: n for n in nodes}
    for node in nodes:
        if (not isinstance(node.get('label'), dict) or not isinstance(node['label'].get('raw'), str)
                or (node.get('parent_key') is not None and not isinstance(node['parent_key'], str))
                or not isinstance(node.get('ordered_content'), list)
                or not all(isinstance(v, dict) and isinstance(v.get('type'), str) for v in node['ordered_content'])
                or type(node.get('included')) is not bool or type(node.get('sort_order')) is not int
                or node.get('score_semantics') not in {'direct', 'sum_children', 'each_child', 'unset', 'ambiguous'}
                or not all(isinstance(node.get(k), dict) for k in
                    ('formula_decisions', 'figure_decisions', 'warning_states'))):
            raise AuthoringError('AUTHORING_INVALID_HIERARCHY', '設問の形式を確認してください。')
        current, seen = node, set()
        while current:
            key = current['stable_key']
            if key in seen:
                raise AuthoringError('AUTHORING_INVALID_HIERARCHY', '設問の階層が循環しています。')
            seen.add(key)
            parent = current.get('parent_key')
            if parent and parent not in by_key:
                raise AuthoringError('AUTHORING_INVALID_HIERARCHY', '親設問が見つかりません。')
            current = by_key.get(parent)
        points = node.get('score_points')
        if points is not None and (type(points) not in (int, float) or not math.isfinite(points) or points < 0):
            raise AuthoringError('AUTHORING_INVALID_POINTS', '配点を確認してください。')
        if not isinstance(node.get('body_text'), str) or len(node['body_text']) > 20000:
            raise AuthoringError('AUTHORING_INVALID_TEXT', '問題文の長さを確認してください。')
    if not isinstance(value.get('materials'), list):
        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '資料の対応を確認してください。')
    for name in ('answers', 'rubrics'):
        if not isinstance(value[name], dict) or not set(value[name]) <= set(keys):
            raise AuthoringError('AUTHORING_INVALID_TARGET', '解答・採点基準の対応先を確認してください。')
    for answer in value['answers'].values():
        if (not isinstance(answer, dict) or not isinstance(answer.get('primary'), str)
                or len(answer['primary']) > 100000 or not isinstance(answer.get('alternatives'), list)
                or not all(isinstance(a, str) and len(a) <= 100000 for a in answer['alternatives'])
                or not isinstance(answer.get('diagram_records'), list)):
            raise AuthoringError('AUTHORING_INVALID_TEXT', '模範解答本文を確認してください。')
    if not value.get('domains', {}).get('answer'):
        for key, answer in value['answers'].items():
            if answer['diagram_records'] != previous.get('answers', {}).get(key, {}).get('diagram_records', []):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', '図の変更には出典付きレビューを使用してください。')
    for criteria in value['rubrics'].values():
        if not isinstance(criteria, list) or len(criteria) > 500:
            raise AuthoringError('AUTHORING_INVALID_RUBRIC', '採点基準を確認してください。')
        for c in criteria:
            if (not isinstance(c, dict) or not isinstance(c.get('description'), str)
                    or type(c.get('points')) not in (int, float) or not math.isfinite(c['points']) or c['points'] < 0):
                raise AuthoringError('AUTHORING_INVALID_RUBRIC', '採点基準の内容と配点を確認してください。')
    from .authoring_text_review import restore_question_corrections
    restore_question_corrections(value, previous)
    return deepcopy(value)


def save_draft(session, test, value, expected, actor=None):
    row = latest(session, test.id)
    if not row or row.state not in {'draft', 'final_review'}:
        raise AuthoringError('AUTHORING_NOT_EDITABLE', '編集可能な下書きを開いてください。')
    snapshot = validate_snapshot(value, row.snapshot)
    material_ids = [m.get('id') for m in snapshot['materials'] if isinstance(m, dict)]
    if (len(material_ids) != len(snapshot['materials'])
            or any(not isinstance(v, str) or not v for v in material_ids)
            or len(set(material_ids)) != len(material_ids)):
        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '資料の対応を確認してください。')
    for m in snapshot['materials']:
        material = session.get(TestMaterial, m['id'])
        if not material or material.test_id != test.id or material.sha256 != m.get('sha256') or material.material_type != m.get('role'):
            raise AuthoringError('AUTHORING_SOURCE_CHANGED', '資料の出典が変わっています。')
    validate_material_replacements(snapshot)
    from .authoring_text_review import confirm_manual_text_edits
    confirm_manual_text_edits(snapshot, row.snapshot, expected+1)
    from .grading_definition import freeze_definition, capture_evidence, snapshot_evidence
    evidence = snapshot.get('domains', {}).get('grading_definition', {}).get('evidence')
    if evidence is None:
        evidence = snapshot_evidence(snapshot, test.id) if row.parent_confirmed_revision_id else capture_evidence(session, snapshot, test.id)
    freeze_definition(snapshot, evidence)
    result = session.execute(update(TestAuthoringRevision).where(TestAuthoringRevision.id == row.id,
        TestAuthoringRevision.edit_version == expected, TestAuthoringRevision.state.in_(['draft', 'final_review']))
        .values(snapshot=snapshot, snapshot_sha256=canonical_hash(snapshot), edit_version=expected+1,
            state='draft', updated_at=now()))
    if result.rowcount != 1:
        raise AuthoringError('AUTHORING_SAVE_CONFLICT', '別の保存が行われました。再読み込みして確認してください。')
    session.add(DomainEvent(entity_type='test', entity_id=test.id,
        event_type='authoring_draft_saved', actor_user_id=actor, payload={'edit_version': expected+1}))
    session.flush()
    session.refresh(row)
    return row


def preflight(snapshot, *, question_warnings=None):
    from .grading_definition import compile_definition
    issues = compile_definition(snapshot)[1]
    def issue(key, section, message, field=None, code=None, entry_id=None, criterion_id=None, **target):
        if code == 'question_body' and any(item.get('code') == code and item.get('question_key') == key for item in issues):
            return
        issues.append({'question_key': key, 'section': section, 'message': message, **({'field': field} if field else {}), **({'code': code} if code else {}),
            **({'entry_id': entry_id} if entry_id else {}), **({'criterion_id': criterion_id} if criterion_id else {}), **target})
    nodes = [n for n in snapshot['nodes'] if n.get('included', True)]
    if not nodes:
        issue(None, 'question', '設問がありません。')
    total = 0
    for n in nodes:
        key = n['stable_key']
        children = [c for c in nodes if c.get('parent_key') == key]
        if not n['body_text'].strip() and not n.get('diagram_records'):
            issue(key, 'question', '問題文を確認してください。', 'content', 'question_body')
        if not children:
            points = n.get('score_points')
            if not points or not math.isfinite(points):
                issue(key, 'question', '配点を確認してください。', 'score', 'question_score')
            else:
                total += points
            a = snapshot['answers'].get(key, {})
            accepted = any(r.get('state') == 'accepted' and r.get('trust_state') != 'hard_invalid'
                and (r.get('trust_state', 'trusted') == 'trusted' or r.get('teacher_confirmed'))
                for r in a.get('diagram_records', []) if isinstance(r, dict))
            if not str(a.get('primary', '')).strip() and not accepted:
                issue(key, 'answer', '模範解答本文または検証済みの図を確認してください。', code='answer_missing')
            criteria = snapshot['rubrics'].get(key, [])
            if any((c.get('points_conflict') and not c.get('points_confirmed')) or
                    c.get('grouping_confirmed') is False for c in criteria):
                pending = next(c for c in criteria if (c.get('points_conflict') and not c.get('points_confirmed')) or c.get('grouping_confirmed') is False)
                issue(key, 'rubric', '採点基準の統合結果と得点段階を確認してください。', code='rubric_review', criterion_id=pending.get('id'))
            rubric_total = sum(max((level.get('score') for level in c.get('levels', [])
                if isinstance(level, dict) and type(level.get('score')) in (int, float)
                and math.isfinite(level['score']) and level['score'] >= 0), default=0)
                for c in criteria)
            if not criteria or rubric_total != points:
                issue(key, 'rubric', '得点段階の最高点合計を設問の配点に合わせてください。', 'levels', 'rubric_points')
        if n.get('review_flags') and not snapshot.get('domains', {}).get('question'):
            issue(key, 'question', '出典の未確認項目があります。')
    question = snapshot.get('domains', {}).get('question')
    catalog = []
    if question:
        from .review_document import _formula_confirmation_resolved
        from .authoring_question_issues import question_source_target, warning_question_key
        for n in nodes:
            for rid, decision in n.get('formula_decisions', {}).items():
                if not _formula_confirmation_resolved(decision):
                    issue(n['stable_key'], 'question', '出典確認: 数式の確認が未完了です。', 'formula', 'question_formula_review', **question_source_target(question, kind='formula_review', region_id=rid, materials=snapshot.get('materials', [])))
            for rid, decision in n.get('figure_decisions', {}).items():
                if decision.get('decision', 'unreviewed') == 'unreviewed':
                    issue(n['stable_key'], 'question', '出典確認: 図の確認が未完了です。', 'figure', 'question_figure_review', **question_source_target(question, kind='figure_review', region_id=rid, materials=snapshot.get('materials', [])))
        states = question['snapshot'].get('warning_states', {})
        seen_warnings = set()
        from .source_warning_requirements import warning_requirements
        catalog = warning_requirements(question_warnings if question_warnings is not None else question['document'].get('warnings', []), question, nodes)
        for warning in catalog:
            if warning['id'] in seen_warnings:
                continue
            seen_warnings.add(warning['id'])
            if warning.get('blocking') and warning.get('actionable', True) and states.get(warning['id'], {}).get('state', 'unreviewed') == 'unreviewed':
                target = question_source_target(question, kind='source_warning', warning=warning, materials=snapshot.get('materials', []))
                owner = warning_question_key(nodes, warning, question)
                from .source_warning_requirements import SPATIAL_WARNING, SPATIAL_LABEL
                message = SPATIAL_LABEL if warning['code'] == SPATIAL_WARNING else f"出典確認: {target['source_review_label']}が未確認です。"
                issue(owner, 'question', message, 'source_warning', 'question_source_warning', **target)
    for warning in source_warnings(snapshot):
        issue(warning['question_key'], 'question', '編集した本文と元資料の対応を確認してください。', 'content', warning['code'], correction_type='text_source_review')
    for diagnostic in snapshot['source_provenance'].get('authoring_origins', {}).get('diagnostics', []):
        issue(None, 'source', '保存済みレビューの元資料を確認できません。出典付きレビューを確認してください。')
    for entry in snapshot.get('domains', {}).get('answer', {}).get('entries', []):
        if entry.get('disposition') not in {'ignored', 'excluded'} and not entry.get('authoring_question_key'):
            issue(None, 'answer', '設問未割当の模範解答候補があります。対応先を確認してください。', 'mapping', 'answer_unassigned', entry_id=entry['id'])
    entries = snapshot.get('domains', {}).get('answer', {}).get('entries', [])
    for key in {e.get('authoring_question_key') for e in entries} - {None}:
        current = [e for e in entries if e.get('authoring_question_key') == key and
            e.get('disposition', 'include') == 'include']
        answer_candidates = [e for e in current if e.get('answer_text', '').strip() or e.get('diagram_records')]
        if sum(e.get('answer_kind', 'primary') == 'primary' for e in answer_candidates) > 1:
            issue(key, 'answer', '主な模範解答を1件にしてください。別解は別解として指定してください。')
    for entry in entries:
        classification = entry.get('semantic_classification') or {}
        if entry.get('disposition', 'include') == 'include' and classification.get('status') == 'needs_teacher_review':
            issue(entry.get('authoring_question_key'), 'answer', '解答候補の分類を確認してください。', 'classification', 'answer_classification', entry_id=entry['id'])
    for entry in snapshot.get('domains', {}).get('rubric', {}).get('entries', []):
        if entry.get('disposition') not in {'ignored', 'excluded'} and not entry.get('authoring_question_key'):
            issue(None, 'rubric', '設問未割当の採点基準候補があります。対応先を確認してください。', 'mapping', 'rubric_unassigned', entry_id=entry['id'])
    for candidate in snapshot.get('domains', {}).get('recovery', {}).get('rubric_candidates', []):
        if not candidate.get('dismissed') and candidate.get('origin_role') == 'rubric_source':
            issue(candidate.get('question_key'), 'rubric', '未割当の採点基準候補を確認してください。', 'recovery', 'rubric_recovery', entry_id=candidate['id'])
    if total != snapshot['metadata'].get('total_points'):
        issue(None, 'metadata', '設問の合計点とテストの合計点が一致していません。', 'total', 'test_total')
    from .authoring_issue_guidance import issue_guidance
    issues = [issue_guidance(snapshot, item, total) for item in issues]
    return {'issues': issues, 'question_warning_catalog': catalog, 'notifications': [], 'total_points': total,
        'question_count': len(nodes), 'gradable_question_count': sum(1 for n in nodes if not any(
            c.get('included', True) and c.get('parent_key') == n['stable_key'] for c in nodes)),
        'can_confirm': not issues}


def archive_impact(session, test):
    def count(model, criterion):
        return session.scalar(select(func.count()).select_from(model).where(criterion)) or 0
    value = {'test_id': test.id, 'name': test.name,
        'questions': count(TestQuestion, TestQuestion.test_id == test.id),
        'model_answers': count(ModelAnswer, ModelAnswer.test_id == test.id),
        'rubrics': count(RubricVersion, RubricVersion.test_id == test.id),
        'submissions': count(StudentSubmission, StudentSubmission.test_id == test.id),
        'grading_jobs': count(GradingJob, GradingJob.test_id == test.id),
        'results': session.scalar(select(func.count()).select_from(GradingJobItem).join(GradingJob)
            .where(GradingJob.test_id == test.id, or_(GradingJobItem.normalized_result_hash.is_not(None),
                GradingJobItem.score.is_not(None)))) or 0}
    return {**value, 'impact_sha256': canonical_hash(value)}


def replacement_problems(snapshot):
    """Replacement preserves old evidence but requires rebinding to the new source."""
    references = {m['id']: m for m in snapshot.get('materials', [])}
    superseded = [references[m['replaces_material_id']]
        for m in references.values() if m.get('replaces_material_id') in references]
    domains = snapshot.get('domains', {})
    result = []
    for name, context in domains.items():
        sha = (context.get('document', {}).get('source_pdf_sha256') if name == 'question'
               else context.get('source_sha256'))
        affected = (any(m.get('role') == 'question_sheet' and m.get('sha256') == sha for m in superseded)
                    if name == 'question' else any(m['id'] in {context.get('material_id'),
                        *(source.get('material_id') for source in context.get('sources', {}).values())}
                        for m in superseded))
        if sha and affected:
            result.append({'domain': name, 'code': 'authoring_material_replaced'})
    return result


def validate_material_replacements(snapshot):
    references = {m['id']: m for m in snapshot.get('materials', [])}
    for item in references.values():
        old_id = item.get('replaces_material_id')
        if old_id is None:
            continue
        old = references.get(old_id) if isinstance(old_id, str) else None
        if (not old or old_id == item['id'] or old.get('role') != item.get('role')
                or old.get('sha256') == item.get('sha256')):
            raise AuthoringError('AUTHORING_INVALID_REPLACEMENT', '差し替え元と新しい資料の対応を確認してください。')
        visited = {item['id']}
        while old:
            if old['id'] in visited:
                raise AuthoringError('AUTHORING_INVALID_REPLACEMENT', '資料の差し替え関係を確認してください。')
            visited.add(old['id'])
            old = references.get(old.get('replaces_material_id'))


def source_text(node, snapshot):
    regions = {r['region_id']: r for r in snapshot.get('domains', {}).get('question', {}).get('document', {}).get('regions', [])}
    text = ''
    for item in node['ordered_content']:
        if item['type'] == 'text':
            value = item.get('text', '')
        elif item['type'] == 'formula_region':
            rid = item['region_id']
            value = node.get('formula_decisions', {}).get(rid, {}).get('teacher_transcription')
            if value is None:
                value = '\n'.join((f.get('native_text') or '') for f in regions.get(rid, {}).get('text_fragments', []))
        else:
            continue
        if text and not text.endswith('\n'):
            text += '\n'
        text += value
    return text


def source_warnings(snapshot):
    warnings = [{'question_key': n['stable_key'], 'code': 'authoring_text_source_unresolved',
             'message': '元資料との対応に確認が必要です。編集内容は保存されています。'}
            for n in snapshot['nodes'] if n['stable_key'] in snapshot.get('question_text_buffers', {}) and
            snapshot['question_text_buffers'][n['stable_key']] != source_text(n, snapshot)]
    if snapshot['source_provenance'].get('authoring_origins', {}).get('pending_question_review'):
        warnings.append({'question_key': None, 'code': 'authoring_question_review_changed',
            'message': '旧問題レビューが更新されています。保存済みの設問本文・分割・階層を保持しています。'})
    return warnings


def material_analysis_readiness(snapshot, material=None, *, editable=True, dirty=False, busy=False):
    if not editable:
        return {'state': 'readonly', 'reason': '修正版を作成すると編集できます。'}
    if busy:
        return {'state': 'busy', 'reason': '処理中です。完了までお待ちください。'}
    if not material:
        return {'state': 'missing_material', 'reason': '資料を選択してください。'}
    if material['role'] not in {'question_sheet', 'model_answer_source', 'rubric_source'}:
        return {'state': 'unsupported', 'reason': 'この資料は解析対象ではありません。'}
    if dirty:
        return {'state': 'unsaved_changes', 'reason': '変更を保存してから解析してください。'}
    if any(m.get('replaces_material_id') == material['id'] for m in snapshot['materials']):
        return {'state': 'stale_source', 'reason': '差し替え済みの資料です。新しい資料を選択してください。'}
    analyzed = any(m['id'] == material['id'] and m['sha256'] == material['sha256']
                   for m in snapshot['source_provenance'].get('analysis_materials', []))
    domains = snapshot.get('domains', {})
    if material['role'] == 'question_sheet':
        analyzed = analyzed or domains.get('question', {}).get('document', {}).get('source_pdf_sha256') == material['sha256']
    elif material['role'] == 'model_answer_source':
        answer = domains.get('answer') or {}
        analyzed = analyzed or any(source.get('material_id') == material['id'] and
            source.get('source_sha256') == material['sha256']
            for source in [answer, *answer.get('sources', {}).values()])
    else:
        rubric = domains.get('rubric') or {}
        analyzed = analyzed or any(source.get('material_id') == material['id'] and
            source.get('source_sha256') == material['sha256']
            for source in [rubric, *rubric.get('sources', {}).values()])
    return {'state': 'ready', 'reason': '', 'analyzed': analyzed}
