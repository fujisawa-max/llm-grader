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
    TestAuthoringRevision, TestArchive, DomainEvent, now)
from .pdf_native import canonical_hash


class AuthoringError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def projection(session, test):
    questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test.id)
        .order_by(TestQuestion.sort_order, TestQuestion.id)))
    answers = list(session.scalars(select(ModelAnswer).where(ModelAnswer.test_id == test.id,
        ModelAnswer.is_current.is_(True))))
    rubric = session.scalar(select(RubricVersion).where(RubricVersion.test_id == test.id,
        RubricVersion.status == 'approved').order_by(RubricVersion.version.desc()))
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


def latest(session, test_id):
    return session.scalar(select(TestAuthoringRevision).where(TestAuthoringRevision.test_id == test_id)
        .order_by(TestAuthoringRevision.revision.desc()))


def create_draft(session, test, actor=None, *, source_roots=None):
    session.scalar(select(Test).where(Test.id == test.id).with_for_update())
    if session.get(TestArchive, test.id):
        raise AuthoringError('TEST_ARCHIVED', 'このテストはアーカイブされています。')
    prior = latest(session, test.id)
    if prior and prior.state in {'draft', 'final_review'}:
        return prior
    baseline = projection(session, test)
    snapshot = deepcopy(prior.snapshot if prior else baseline)
    if not prior and source_roots:
        from .authoring_sources import source_projection
        snapshot = source_projection(session, test, baseline, *source_roots)
    row = TestAuthoringRevision(id=str(uuid4()), test_id=test.id,
        revision=prior.revision+1 if prior else 1, edit_version=1, state='draft',
        snapshot=snapshot, snapshot_sha256=canonical_hash(snapshot),
        baseline_sha256=baseline_hash(baseline), created_by=actor)
    session.add(row)
    session.add(DomainEvent(entity_type='test', entity_id=test.id,
        event_type='authoring_draft_created', actor_user_id=actor, payload={'revision': row.revision}))
    session.flush()
    return row


def validate_snapshot(value, previous):
    if (not isinstance(value, dict) or value.get('schema_version') != 'test-authoring.v1'
            or set(value) != set(previous) or len(json.dumps(value, ensure_ascii=False)) > 4_000_000):
        raise AuthoringError('AUTHORING_INVALID_SNAPSHOT', '下書きの形式が不正です。')
    # No client may manufacture/replace original evidence while editing text.
    if value['source_provenance'] != previous['source_provenance']:
        raise AuthoringError('AUTHORING_SOURCE_CHANGED', '元資料の出典情報は編集できません。')
    value['source_provenance'] = deepcopy(previous['source_provenance'])
    if 'domains' in previous:
        from .authoring_sources import validate_domains
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


def preflight(snapshot):
    issues = []
    def issue(key, section, message, field=None):
        issues.append({'question_key': key, 'section': section, 'message': message, **({'field': field} if field else {})})
    nodes = [n for n in snapshot['nodes'] if n.get('included', True)]
    if not nodes:
        issue(None, 'question', '設問がありません。')
    total = 0
    for n in nodes:
        key = n['stable_key']
        children = [c for c in nodes if c.get('parent_key') == key]
        if not n['body_text'].strip() and not n.get('diagram_records'):
            issue(key, 'question', '問題文を確認してください。')
        if not children:
            points = n.get('score_points')
            if not points or not math.isfinite(points):
                issue(key, 'question', '配点を確認してください。', 'score')
            else:
                total += points
            a = snapshot['answers'].get(key, {})
            accepted = any(r.get('state') == 'accepted' and r.get('trust_state') != 'hard_invalid'
                and (r.get('trust_state', 'trusted') == 'trusted' or r.get('teacher_confirmed'))
                for r in a.get('diagram_records', []) if isinstance(r, dict))
            if not str(a.get('primary', '')).strip() and not accepted:
                issue(key, 'answer', '模範解答本文または検証済みの図を確認してください。')
            criteria = snapshot['rubrics'].get(key, [])
            if any((c.get('points_conflict') and not c.get('points_confirmed')) or
                    c.get('grouping_confirmed') is False for c in criteria):
                issue(key, 'rubric', '採点基準の統合結果と配点を確認してください。')
            if not criteria or sum(c['points'] for c in criteria) != points:
                issue(key, 'rubric', '採点基準の配点合計を確認してください。')
        if n.get('review_flags') and not snapshot.get('domains', {}).get('question'):
            issue(key, 'question', '出典の未確認項目があります。')
    question = snapshot.get('domains', {}).get('question')
    if question:
        from .review_document import _formula_confirmation_resolved
        for n in nodes:
            for rid, decision in n.get('formula_decisions', {}).items():
                if not _formula_confirmation_resolved(decision):
                    issue(n['stable_key'], 'question', '元資料と数式を確認してください。')
            for rid, decision in n.get('figure_decisions', {}).items():
                if decision.get('decision', 'unreviewed') == 'unreviewed':
                    issue(n['stable_key'], 'question', '元資料の図を確認してください。')
        states = question['snapshot'].get('warning_states', {})
        for warning in question['document'].get('warnings', []):
            if warning.get('blocking') and states.get(warning['id'], {}).get('state', 'unreviewed') == 'unreviewed':
                owner = next((n['stable_key'] for n in nodes if n['stable_key'] == warning.get('owner') or
                    n.get('source_draft_stable_key') == warning.get('owner')), None)
                issue(owner, 'question', '元資料の確認事項を確認してください。')
    for diagnostic in snapshot['source_provenance'].get('authoring_origins', {}).get('diagnostics', []):
        issue(None, 'source', '保存済みレビューの元資料を確認できません。出典付きレビューを確認してください。')
    for entry in snapshot.get('domains', {}).get('answer', {}).get('entries', []):
        if entry.get('disposition') not in {'ignored', 'excluded'} and not entry.get('authoring_question_key'):
            issue(None, 'answer', '設問未割当の解答・採点基準候補があります。対応先を確認してください。')
    entries = snapshot.get('domains', {}).get('answer', {}).get('entries', [])
    for key in {e.get('authoring_question_key') for e in entries} - {None}:
        current = [e for e in entries if e.get('authoring_question_key') == key and
            e.get('disposition', 'include') == 'include']
        from .authoring_sources import has_rubric_state
        answer_candidates = [e for e in current if e.get('answer_text', '').strip() or
            e.get('diagram_records') or not has_rubric_state(e)]
        if sum(e.get('answer_kind', 'primary') == 'primary' for e in answer_candidates) > 1:
            issue(key, 'answer', '主な模範解答を1件にしてください。別解は別解として指定してください。')
    for entry in entries:
        classification = entry.get('semantic_classification') or {}
        if entry.get('disposition', 'include') == 'include' and classification.get('status') == 'needs_teacher_review':
            issue(entry.get('authoring_question_key'), 'answer', '解答候補の分類を確認してください。')
    if total != snapshot['metadata'].get('total_points'):
        issue(None, 'metadata', '設問の合計点とテストの合計点が一致していません。')
    # Fail closed rather than pretending a JSON copy is a grading snapshot.
    issue(None, 'publication', 'この画面からの試験内容確定は現在利用できません。')
    return {'issues': issues, 'total_points': total, 'can_confirm': False}


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
