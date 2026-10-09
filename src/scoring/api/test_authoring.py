"""Domain-authorized whole-test drafts and reversible Test management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func, case

from ..review_document import ReviewError
from ..db.models import (Test, CourseOffering, Course,
    TestArchive, GradingJob, DomainEvent, TestMaterial)
from ..test_authoring import (AuthoringError, projection, latest, create_draft,
    save_draft, preflight, archive_impact, baseline_hash)


class ManualDiagramCrop(BaseModel):
    expected_revision: int = Field(ge=1)
    page_index: int = Field(ge=0)
    bbox: list[float] = Field(min_length=4, max_length=4)


class SaveAuthoring(BaseModel):
    expected_edit_version: int = Field(ge=1)
    snapshot: dict
    continue_after_external_change: bool = False


class SourceImport(BaseModel):
    expected_edit_version: int = Field(ge=1)
    preserve_previous: bool = False
    analysis_material_id: str | None = None


class AnalyzeSource(SourceImport):
    material_id: str


class RubricSplitTool(BaseModel):
    expected_revision: int = Field(ge=1)
    candidate_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=20000)
    offset: int | None = Field(default=None, ge=1)
    question_key: str | None = Field(default=None, max_length=128)


class ConsolidationCriterion(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=20000)
    points: float = Field(ge=0, allow_inf_nan=False)


class ConsolidationTool(BaseModel):
    expected_revision: int = Field(ge=1)
    criteria: list[ConsolidationCriterion] | None = Field(default=None, max_length=500)


class ArchiveRequest(BaseModel):
    test_name: str
    impact_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def router(db, question_root=None, answer_root=None, classifier=None, answer_create=None):
    r = APIRouter(prefix='/api/v1')

    def owned(test_id, s, allow_archived=False):
        test = s.get(Test, test_id)
        if not test:
            raise HTTPException(404, 'TEST_NOT_FOUND')
        offering = s.get(CourseOffering, test.course_offering_id)
        course = s.get(Course, offering.course_id)
        actor = s.info.get('auth_user')
        if not actor or (actor.role != 'admin' and course.owner_user_id != actor.id):
            raise HTTPException(403, 'COURSE_ACCESS_DENIED')
        if not allow_archived and s.get(TestArchive, test_id):
            raise HTTPException(410, 'TEST_ARCHIVED')
        return test

    def validate_materials(snapshot, session, test_id):
        for reference in snapshot.get('materials', []):
            material = session.get(TestMaterial, reference['id']) if isinstance(reference, dict) and isinstance(reference.get('id'), str) else None
            if (not material or material.test_id != test_id or reference.get('sha256') != material.sha256
                    or reference.get('role') != material.material_type):
                raise AuthoringError('AUTHORING_SOURCE_CHANGED', 'この試験の資料と出典情報を確認してください。')

        from ..test_authoring import validate_material_replacements
        validate_material_replacements(snapshot)

    def view(row):
        from ..test_authoring import source_warnings, material_analysis_readiness
        from ..authoring_sources import normalize_authoring_snapshot
        from ..pdf_native import canonical_hash
        snapshot = normalize_authoring_snapshot(row.snapshot)
        return {**{k: getattr(row, k) for k in ('id', 'test_id', 'revision', 'edit_version', 'state',
            'baseline_sha256')}, 'snapshot_sha256': canonical_hash(snapshot), 'snapshot': snapshot,
            'source_warnings': source_warnings(snapshot),
            'analysis_readiness': {m['id']: material_analysis_readiness(snapshot, m,
                editable=row.state in {'draft', 'final_review'}) for m in snapshot['materials']}}


    def error(exc, s):
        s.rollback()
        raise HTTPException(409, {'error': {'code': exc.code, 'message': str(exc)}}) from exc

    def source_problems(row, session):
        if not row:
            return []
        from ..test_authoring import replacement_problems
        problems = replacement_problems(row.snapshot)
        from ..authoring_sources import normalize_authoring_snapshot
        domains = normalize_authoring_snapshot(row.snapshot).get('domains', {})
        from ..source_registration import deleted_material_ids
        deleted = deleted_material_ids(session, row.test_id)
        answer = domains.get('answer') or {}
        referenced = {answer.get('material_id')}
        referenced.discard(None)
        if referenced & deleted:
            root_role = answer.get('material_role', 'model_answer_source')
            problems.append({'domain': 'rubric' if root_role == 'rubric_source' else 'answer',
                'code': 'source_binding_deleted'})
        for source in answer.get('sources', {}).values():
            if source.get('material_id') in deleted:
                role = source.get('material_role')
                problems.append({'domain': 'rubric' if role == 'rubric_source' else 'answer',
                    'code': 'source_binding_deleted'})
        question = domains.get('question') or {}
        question_material = question.get('document', {}).get('material_id')
        if question_material in deleted:
            problems.append({'domain': 'question', 'code': 'question_source_binding_deleted'})
        if domains.get('question'):
            try:
                from ..authoring_question import AuthoringQuestionReview
                service = AuthoringQuestionReview(session, question_root, row)
                service.get(service.bound['document']['id'])
            except (ReviewError, ValueError, OSError, KeyError) as exc:
                problems.append({'domain': 'question', 'code': getattr(exc, 'code', 'question_source_stale')})
        if domains.get('answer'):
            try:
                from ..authoring_answers import AuthoringAnswers
                AuthoringAnswers(session, answer_root, row)
            except (ReviewError, ValueError, OSError, KeyError) as exc:
                problems.append({'domain': 'answer', 'code': str(exc) if isinstance(exc, ValueError) else 'model_answer_source_stale'})
        return problems

    @r.get('/tests/{test_id}/authoring/status')
    def authoring_status(test_id: str, s=Depends(db)):
        owned(test_id, s)
        row = latest(s, test_id)
        return {'state': row.state if row else None, 'revision_id': row.id if row else None, 'edit_version': row.edit_version if row else None}

    @r.get('/tests/{test_id}/authoring')
    def get_authoring(test_id: str, s=Depends(db)):
        test = owned(test_id, s)
        row = latest(s, test_id)
        if not row and latest(s, test_id, include_backups=True):
            raise HTTPException(409, 'AUTHORING_RESUME_UNAVAILABLE')
        from ..authoring_sources import source_tokens
        tokens = source_tokens(s, test_id)
        bound = (row.snapshot.get('source_provenance', {}).get('authoring_origins') or {}).get('tokens') if row else tokens
        return {'revision': view(row) if row else None, 'legacy': projection(s, test),
            'external_source_change': bound != tokens, 'source_tokens': tokens, 'source_problems': source_problems(row, s),
            'publication_available': False}

    @r.post('/tests/{test_id}/authoring/revisions')
    def begin(test_id: str, s=Depends(db)):
        from sqlalchemy.exc import IntegrityError
        test = owned(test_id, s)
        try:
            row = create_draft(s, test, s.info['auth_user'].id,
                source_roots=(question_root, answer_root) if question_root and answer_root else None)
            s.commit()
            return view(row)
        except AuthoringError as exc:
            error(exc, s)
        except IntegrityError:
            # SQLite lacks SELECT FOR UPDATE; the existing unique revision key
            # resolves simultaneous first opens without a duplicate active draft.
            s.rollback()
            row = latest(s, test_id)
            if row and row.state in {'draft', 'final_review'}:
                return view(row)
            raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')

    @r.put('/tests/{test_id}/authoring')
    def save(test_id: str, v: SaveAuthoring, s=Depends(db)):
        test = owned(test_id, s)
        try:
            from ..authoring_sources import source_tokens
            current = latest(s, test_id)
            if not current or current.state not in {'draft', 'final_review'}:
                raise AuthoringError('AUTHORING_NOT_EDITABLE', '編集可能な保存版を開いてください。')
            if current.edit_version != v.expected_edit_version:
                raise AuthoringError('AUTHORING_SAVE_CONFLICT', '別の保存が行われました。再読み込みして確認してください。')
            origin = (current.snapshot.get('source_provenance', {}).get('authoring_origins') or {}) if current else {}
            if origin and origin.get('tokens') != source_tokens(s, test_id) and not v.continue_after_external_change:
                raise AuthoringError('AUTHORING_EXTERNAL_REVIEW_CHANGED', '外部の保存済みレビューが更新されています。現在の下書きを継続するか、最新レビューを取り込んでください。')
            from ..test_authoring import validate_snapshot
            validate_materials(v.snapshot, s, test_id)
            if current:
                v.snapshot = validate_snapshot(v.snapshot, current.snapshot)
            if v.snapshot.get('domains', {}).get('question'):
                from ..authoring_question import AuthoringQuestionReview
                from ..review_document import ReviewError
                try:
                    v.snapshot['nodes'] = AuthoringQuestionReview(s, question_root, current,
                        v.snapshot).validate_working(current.snapshot)
                except (ReviewError, ValueError) as exc:
                    raise AuthoringError(getattr(exc, 'code', str(exc)), '保存できませんでした。設問構造または出典情報が無効です。編集内容は画面に保持されています。') from exc
            if v.snapshot.get('domains', {}).get('answer'):
                from ..authoring_answers import AuthoringAnswers
                try:
                    AuthoringAnswers(s, answer_root, current, v.snapshot).validate()
                except (ValueError, KeyError, TypeError) as exc:
                    import logging
                    logging.getLogger(__name__).warning('Authoring answer validation rejected: %s', exc, exc_info=True)
                    raise AuthoringError('AUTHORING_ANSWER_SOURCE_INVALID', '保存できませんでした。解答・図・採点基準の出典情報が無効です。編集内容は画面に保持されています。') from exc
            row = save_draft(s, test, v.snapshot, v.expected_edit_version, s.info['auth_user'].id)
            if origin and v.continue_after_external_change:
                from copy import deepcopy
                from ..pdf_native import canonical_hash
                tokens = source_tokens(s, test_id)
                acknowledged = deepcopy(row.snapshot)
                saved_origin = acknowledged['source_provenance']['authoring_origins']
                if saved_origin.get('tokens') != tokens:
                    saved_origin['kept_authoring_after_external_change'] = tokens
                    saved_origin['tokens'] = tokens
                    row.snapshot = acknowledged
                    row.snapshot_sha256 = canonical_hash(acknowledged)
            s.commit()
            return view(row)
        except AuthoringError as exc:
            error(exc, s)

    def mark_analysis(snapshot, previous, material):
        from copy import deepcopy
        refs = deepcopy(previous.get('source_provenance', {}).get('analysis_materials', []))
        ref = {'id': material.id, 'sha256': material.sha256}
        if ref not in refs:
            refs.append(ref)
        snapshot['source_provenance']['analysis_materials'] = refs

    def apply_analysis_snapshot(session, row, snapshot, expected, preserve, baseline=None):
        from sqlalchemy import update
        from ..db.models import TestAuthoringRevision, now
        from ..pdf_native import canonical_hash
        previous_refs = {m['id']: m for m in row.snapshot.get('materials', [])}
        for ref in snapshot.get('materials', []):
            old = previous_refs.get(ref['id'], {})
            if old.get('replaces_material_id'):
                ref['replaces_material_id'] = old['replaces_material_id']
        previous_analyses = row.snapshot.get('source_provenance', {}).get('analysis_materials')
        if previous_analyses and 'analysis_materials' not in snapshot['source_provenance']:
            from copy import deepcopy
            snapshot['source_provenance']['analysis_materials'] = deepcopy(previous_analyses)
        values = {'state': 'analysis_backup'} if preserve else {
            'snapshot': snapshot, 'snapshot_sha256': canonical_hash(snapshot),
            'baseline_sha256': baseline or row.baseline_sha256,
            'edit_version': expected+1, 'updated_at': now()}
        result = session.execute(update(TestAuthoringRevision).where(
            TestAuthoringRevision.id == row.id, TestAuthoringRevision.edit_version == expected,
            TestAuthoringRevision.state == 'draft').values(**values))
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
        if preserve:
            previous_id = row.id
            row = TestAuthoringRevision(test_id=row.test_id, revision=latest(session, row.test_id, include_backups=True).revision+1,
                edit_version=expected+1, state='draft', snapshot=snapshot,
                snapshot_sha256=canonical_hash(snapshot), baseline_sha256=baseline or row.baseline_sha256,
                created_by=session.info['auth_user'].id)
            session.add(row)
            session.flush()
            session.add(DomainEvent(entity_type='test', entity_id=row.test_id,
                actor_user_id=session.info['auth_user'].id, event_type='authoring_analysis_revision_created',
                payload={'previous_revision_id': previous_id, 'revision_id': row.id}))
        return row

    @r.post('/tests/{test_id}/authoring/source-import')
    def import_sources(test_id: str, v: SourceImport, s=Depends(db)):
        from ..authoring_sources import source_projection
        from ..db.models import ModelAnswerImportDraft, TestMaterial
        test = owned(test_id, s)
        row = latest(s, test_id)
        if not row or row.state != 'draft' or row.edit_version != v.expected_edit_version:
            raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
        baseline = projection(s, test)
        snapshot = source_projection(s, test, baseline, question_root, answer_root)
        if not v.analysis_material_id:
            from copy import deepcopy
            from ..authoring_sources import source_tokens, merge_answer_analysis
            snapshot = deepcopy(row.snapshot)
            origin = snapshot['source_provenance'].setdefault('authoring_origins', {})
            tokens = source_tokens(s, test_id)
            old_tokens = origin.get('tokens', {})
            # Saved legacy review import is domain-scoped. A changed Question
            # review cannot restore the old hierarchy/text over teacher edits.
            for role_name in ('model_answer_source', 'rubric_source'):
                token_name = 'answer' if role_name == 'model_answer_source' else 'rubric'
                if old_tokens.get(token_name) != tokens.get(token_name):
                    from ..source_registration import deleted_material_ids
                    draft = s.scalar(select(ModelAnswerImportDraft).join(TestMaterial,
                        TestMaterial.id == ModelAnswerImportDraft.material_id).where(
                        ModelAnswerImportDraft.test_id == test_id,
                        TestMaterial.material_type == role_name,
                        ~TestMaterial.id.in_(deleted_material_ids(s, test_id) or {''})).order_by(
                        ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.id.desc()))
                    if draft:
                        if role_name == 'model_answer_source':
                            merge_answer_analysis(snapshot, draft)
                        else:
                            from ..authoring_sources import merge_rubric_analysis
                            merge_rubric_analysis(snapshot, draft)
            if old_tokens.get('question') != tokens['question']:
                origin['pending_question_review'] = tokens['question']
            origin['tokens'] = tokens
        if v.analysis_material_id:
            material = s.get(TestMaterial, v.analysis_material_id)
            from ..source_registration import deleted_material_ids
            if material and material.id in deleted_material_ids(s, test_id):
                raise HTTPException(409, 'MATERIAL_BINDING_DELETED')
            sha = snapshot.get('domains', {}).get('question', {}).get('document', {}).get('source_pdf_sha256')
            if not material or material.test_id != test_id or material.material_type != 'question_sheet' or material.sha256 != sha:
                raise HTTPException(409, 'AUTHORING_ANALYSIS_SOURCE_CHANGED')
            from ..authoring_sources import merge_question_analysis
            snapshot = merge_question_analysis(row.snapshot, snapshot)
            mark_analysis(snapshot, row.snapshot, material)
        row = apply_analysis_snapshot(s, row, snapshot, v.expected_edit_version,
            (v.preserve_previous or not v.analysis_material_id), baseline_hash(baseline))
        s.add(DomainEvent(entity_type='test', entity_id=test.id, actor_user_id=s.info['auth_user'].id,
            event_type='authoring_sources_imported', payload={'edit_version': v.expected_edit_version+1}))
        s.commit()
        s.refresh(row)
        return view(row)

    @r.post('/tests/{test_id}/authoring/analyze-answer')
    def analyze_answer(test_id: str, v: AnalyzeSource, s=Depends(db)):
        from copy import deepcopy
        from ..authoring_answers import authoring_questions
        from ..authoring_sources import source_tokens
        from .model_answer_imports import ImportCreate
        owned(test_id, s)
        row = latest(s, test_id)
        if not row or row.state != 'draft' or row.edit_version != v.expected_edit_version:
            raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
        if not answer_create:
            raise HTTPException(503, 'AUTHORING_ANALYSIS_UNAVAILABLE')
        snapshot = deepcopy(row.snapshot)
        from ..test_authoring import material_analysis_readiness
        selected_material = s.get(TestMaterial, v.material_id)
        if not selected_material or selected_material.test_id != test_id:
            raise HTTPException(404, 'MATERIAL_NOT_FOUND')
        from ..source_registration import deleted_material_ids
        if selected_material.id in deleted_material_ids(s, test_id):
            raise HTTPException(409, 'MATERIAL_BINDING_DELETED')
        ref = next((m for m in snapshot['materials'] if m['id'] == v.material_id), None)
        if ref is None:
            ref = {'id': selected_material.id, 'sha256': selected_material.sha256, 'role': selected_material.material_type}
            snapshot['materials'].append(ref)
        if ref['sha256'] != selected_material.sha256 or ref['role'] != selected_material.material_type:
            raise HTTPException(409, 'AUTHORING_ANALYSIS_SOURCE_CHANGED')
        readiness = material_analysis_readiness(snapshot, ref)
        if readiness['state'] != 'ready':
            raise HTTPException(409, {'error': {'code': 'AUTHORING_ANALYSIS_NOT_READY', 'message': readiness['reason']}})
        aliases, questions = authoring_questions(snapshot)
        draft = answer_create(test_id, ImportCreate(material_id=v.material_id), s,
            questions_override=questions, commit=False)
        mark_analysis(snapshot, row.snapshot, s.get(TestMaterial, draft.material_id))
        if selected_material.material_type == 'model_answer_source':
            from ..authoring_sources import merge_answer_analysis
            merge_answer_analysis(snapshot, draft)
        elif selected_material.material_type == 'rubric_source':
            from ..authoring_sources import merge_rubric_analysis
            merge_rubric_analysis(snapshot, draft)
        else:
            raise HTTPException(422, 'AUTHORING_ANALYSIS_ROLE_UNSUPPORTED')
        origin = snapshot['source_provenance'].setdefault('authoring_origins', {})
        tokens = deepcopy(origin.get('tokens') or source_tokens(s, test_id))
        token_name = 'rubric' if selected_material.material_type == 'rubric_source' else 'answer'
        tokens[token_name] = source_tokens(s, test_id)[token_name]
        origin['tokens'] = tokens
        row = apply_analysis_snapshot(s, row, snapshot, v.expected_edit_version, v.preserve_previous)
        s.commit()
        s.refresh(row)
        return view(row)

    def question_context(test_id, s, revision=None):
        from ..authoring_question import AuthoringQuestionReview
        from ..review_document import ReviewError
        owned(test_id, s)
        row = latest(s, test_id)
        if not row or (revision is not None and revision != row.edit_version):
            raise ReviewError('revision_conflict', 409)
        from ..test_authoring import replacement_problems
        if any(p['domain'] == 'question' for p in replacement_problems(row.snapshot)):
            raise ReviewError('authoring_material_replaced', 409)
        service = AuthoringQuestionReview(s, question_root, row)
        return service, row, service.bound['document']['id']

    from .question_reviews import QuestionMathRequest, DiagramRequest, DiagramCropRequest
    from fastapi import Request
    from fastapi.responses import FileResponse

    def question_error(exc):
        raise HTTPException(getattr(exc, 'status', 422),
            {'error': {'code': getattr(exc, 'code', str(exc))}}) from exc

    @r.post('/tests/{test_id}/authoring/nodes/{node_key}/split-suggest')
    def question_split(test_id: str, node_key: str, body: RubricSplitTool, s=Depends(db)):
        from ..rubric_split import reconstruct_split
        owned(test_id, s)
        row = latest(s, test_id)
        if not row or row.edit_version != body.expected_revision or row.state != 'draft':
            raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
        node = next((n for n in row.snapshot['nodes'] if n['stable_key'] == node_key), None)
        if not node or body.candidate_id != node_key:
            raise HTTPException(404, 'AUTHORING_TARGET_MISSING')
        if not callable(getattr(classifier, 'suggest_review_split', None)):
            raise HTTPException(503, 'QUESTION_SPLIT_UNAVAILABLE')
        try:
            result = classifier.suggest_review_split(candidate_id=node_key, text=body.text,
                question_label=node['label']['raw'], segment_ids=[], context_type='question')
            contract = {k: result[k] for k in ('candidate_id', 'split', 'confidence', 'reason')}
            contract['parts'] = [{k: p[k] for k in ('start', 'end')} for p in result['parts']]
            return reconstruct_split(contract, node_key, body.text)
        except Exception as exc:
            raise HTTPException(503, 'QUESTION_SPLIT_UNAVAILABLE') from exc

    @r.post('/tests/{test_id}/authoring/nodes/{node_key}/math-ocr')
    def question_math(test_id: str, node_key: str, body: QuestionMathRequest, s=Depends(db)):
        from ..question_math_source import question_math_source, compact_provenance
        from ..source_math_ocr import SourceMathOCR, MathOCRError
        from ..review_document import ReviewError
        try:
            service, _, rid = question_context(test_id, s, body.expected_revision)
            path, segments, source, exclusions = question_math_source(service, rid, node_key,
                None, body.expected_revision, body.expected_source)
            if not getattr(classifier, 'manager', None):
                raise MathOCRError('math_runtime_unavailable')
            result = SourceMathOCR(classifier.manager, excluded_source_regions=exclusions).propose(
                path, segments, body.text, alignment_mode='source_fragment')
            result['source'] = source
            if result['status'] in {'safe', 'ambiguous'}:
                result['apply_provenance'] = compact_provenance(result)
            return result
        except MathOCRError as exc:
            raise HTTPException(504 if 'timeout' in exc.code else 503,
                {'error': {'code': exc.code}}) from exc
        except (ReviewError, ValueError) as exc:
            question_error(exc)

    def diagram_context(test_id, node_key, s, revision=None):
        from ..diagram_review import question_diagram_review
        service, row, rid = question_context(test_id, s, revision)
        return question_diagram_review(service, rid, node_key, row.edit_version), row

    def diagram_view(engine, records, test_id, node_key):
        for record in records:
            if record.get('crop_sha256'):
                engine.preview(record)
                record['preview_url'] = (f'/api/v1/tests/{test_id}/authoring/nodes/{node_key}/diagrams/'
                    f'{record["id"]}/crop?crop_sha={record["crop_sha256"]}')
        return {'diagrams': records}

    @r.get('/tests/{test_id}/authoring/nodes/{node_key}/diagrams')
    @r.post('/tests/{test_id}/authoring/nodes/{node_key}/diagrams')
    def question_diagrams(test_id: str, node_key: str, request: Request,
        body: DiagramRequest | None = None, s=Depends(db)):
        from ..review_document import ReviewError
        try:
            engine, row = diagram_context(test_id, node_key, s, body.expected_revision if body else None)
            if request.method == 'POST' and body:
                engine.discover(getattr(classifier, 'manager', None))
            node = next(n for n in row.snapshot['nodes'] if n['stable_key'] == node_key)
            return diagram_view(engine, engine.records(node.get('diagram_records', []), revision=row.edit_version), test_id, node_key)
        except (ReviewError, ValueError) as exc:
            question_error(exc)

    @r.post('/tests/{test_id}/authoring/nodes/{node_key}/diagrams/{candidate_id}/crop-preview')
    def question_crop_preview(test_id: str, node_key: str, candidate_id: str,
        body: DiagramCropRequest, s=Depends(db)):
        from ..review_document import ReviewError
        try:
            engine, _ = diagram_context(test_id, node_key, s, body.expected_revision)
            record = engine.record(candidate_id, final_bbox=body.final_bbox, revision=body.expected_revision)
            return diagram_view(engine, [record], test_id, node_key)['diagrams'][0]
        except (ReviewError, ValueError) as exc:
            question_error(exc)

    @r.get('/tests/{test_id}/authoring/nodes/{node_key}/diagrams/{candidate_id}/crop')
    def question_crop(test_id: str, node_key: str, candidate_id: str, crop_sha: str | None = None, s=Depends(db)):
        from ..review_document import ReviewError
        try:
            engine, _ = diagram_context(test_id, node_key, s)
            return FileResponse(engine.preview_path(candidate_id, crop_sha), media_type='image/png')
        except (ReviewError, ValueError) as exc:
            question_error(exc)

    def answer_context(test_id, entry_id, s, revision=None, question_id=None):
        from ..authoring_answers import AuthoringAnswers
        owned(test_id, s)
        row = latest(s, test_id)
        if not row or (revision is not None and row.edit_version != revision):
            raise HTTPException(409, {'error': {'code': 'revision_conflict'}})
        if entry_id.startswith('formal-entry:'):
            from types import SimpleNamespace
            key = entry_id.removeprefix('formal-entry:')
            if not any(n['stable_key'] == key for n in row.snapshot['nodes']):
                raise HTTPException(404, 'AUTHORING_TARGET_MISSING')
            criteria = row.snapshot['rubrics'].get(key, [])
            entry = {'id': entry_id, 'authoring_question_key': key, 'rubric_edits': criteria,
                'semantic_classification': {'segments': [
                    {'id': c['id'], 'text': c['description'], 'source_text': c['description'],
                     'category': 'rubric', 'confidence': 1} for c in criteria if not c.get('excluded')]}}
            return SimpleNamespace(snapshot=row.snapshot), entry, row
        # Resolve replacement state after binding the requested candidate to
        # its own source draft. The combined Answer/Rubric domain may contain
        # several materials; replacing one must not disable another role's
        # candidates or diagram reuse.
        context = AuthoringAnswers(s, answer_root, row)
        try:
            entry = context.entry(entry_id, question_id)
        except ValueError as exc:
            if str(exc) == 'authoring_material_replaced':
                raise HTTPException(409, {'error': {'code': 'authoring_material_replaced'}}) from exc
            raise
        return context, entry, row

    def answer_diagram_view(engine, records, test_id, entry_id, question_id, reuse=False):
        from urllib.parse import urlencode
        for record in records:
            if record.get('crop_sha256'):
                engine.preview(record)
                params = {'crop_sha': record['crop_sha256'], 'scope': record.get('scope', 'exact')}
                if question_id:
                    params['question_id'] = question_id
                if record.get('reuse_ref'):
                    params['reuse_ref'] = record['reuse_ref']
                record['preview_url'] = (f'/api/v1/tests/{test_id}/authoring/entries/{entry_id}/diagrams/'
                    f'{record["id"]}/crop?{urlencode(params)}')
        if reuse:
            return {'diagrams': [], 'reusable_diagrams': records}
        if records and all(record.get('scope') == 'manual' for record in records):
            return {'diagrams': records, 'fallback': None}
        return {'diagrams': records, 'fallback': engine.fallback(), 'diagnostics': engine.diagnostics()}

    from typing import Literal

    @r.get('/tests/{test_id}/authoring/entries/{entry_id}/diagrams')
    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/diagrams')
    def answer_diagrams(test_id: str, entry_id: str, request: Request,
        body: DiagramRequest | None = None, question_id: str | None = None,
        scope: Literal['exact', 'parent', 'pdf', 'reuse', 'manual'] | None = None,
        reuse_diagnostics: bool = False, s=Depends(db)):
        try:
            context, entry, row = answer_context(test_id, entry_id, s, body.expected_revision if body else None, question_id)
            if not hasattr(context, 'diagrams'):
                raise ValueError('authoring_answer_source_missing')
            engine = context.diagrams(entry)
            if scope == 'reuse':
                if request.method != 'GET':
                    raise ValueError('diagram_invalid_scope')
                decisions = [] if reuse_diagnostics else None
                records = engine.reuse().available(row.edit_version, diagnostics=decisions)
                view = answer_diagram_view(engine, records, test_id, entry_id, question_id, True)
                if reuse_diagnostics:
                    for other in context.entries:
                        if other.get('source_draft_id') != context.bound['draft_id']:
                            decisions.append({'entry_id': other['id'], 'question_id': other.get('question_id'),
                                'diagram_id': None, 'outcome': 'excluded', 'reason': 'source_draft_mismatch'})
                    view['reuse_diagnostics'] = {'revision_id': row.id, 'edit_version': row.edit_version,
                        'source_draft_id': context.bound['draft_id'], 'material_id': context.bound['material_id'],
                        'source_sha256': context.bound['source_sha256'], 'source_artifact': context.bound['artifact_ref'],
                        'target_question_id': engine.assigned, 'target_root': engine.reuse().root(engine.assigned),
                        'saved_entry_count': len(context.entries),
                        'saved_diagram_count': sum(len(e.get('diagram_records', [])) for e in context.entries),
                        'saved_accepted_diagram_count': sum(r.get('state') == 'accepted'
                            for e in context.entries for r in e.get('diagram_records', [])),
                        'compatible_source_entry_count': len(engine.reuse_context['entries']),
                        'candidate_count': len(records), 'decisions': decisions}
                return view
            if request.method == 'POST' and body:
                engine.discover(getattr(classifier, 'manager', None), scope or 'exact')
            return answer_diagram_view(engine, engine.records(entry.get('diagram_records', []),
                revision=row.edit_version, scope=scope or ('exact' if request.method == 'POST' else None)), test_id, entry_id, question_id)
        except ValueError as exc:
            question_error(exc)

    @r.get('/tests/{test_id}/authoring/entries/{entry_id}/manual-crop')
    def manual_crop_source(test_id: str, entry_id: str, question_id: str, s=Depends(db)):
        try:
            context, entry, _ = answer_context(test_id, entry_id, s, question_id=question_id)
            if (not hasattr(context, 'bound') or context.bound.get('material_role', 'model_answer_source') != 'model_answer_source'
                    or s.get(TestMaterial, context.bound['material_id']).material_type != 'model_answer_source'):
                raise ValueError('authoring_answer_source_missing')
            engine = context.diagrams(entry)
            from ..vision_policy import page_space
            material = s.get(TestMaterial, context.bound['material_id'])
            return {'material_id': material.id, 'filename': material.original_filename,
                'source_sha256': context.bound['source_sha256'],
                'pages': [{'page_index': p['page_index'], 'width': page_space(p).cropbox[2],
                    'height': page_space(p).cropbox[3], 'rotation': p['rotation']} for p in engine.ir['pages']]}
        except ValueError as exc:
            question_error(exc)

    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/manual-crop')
    def manual_crop(test_id: str, entry_id: str, body: ManualDiagramCrop, question_id: str, s=Depends(db)):
        try:
            context, entry, row = answer_context(test_id, entry_id, s, body.expected_revision, question_id)
            if (not hasattr(context, 'bound') or context.bound.get('material_role', 'model_answer_source') != 'model_answer_source'
                    or s.get(TestMaterial, context.bound['material_id']).material_type != 'model_answer_source'):
                raise ValueError('authoring_answer_source_missing')
            engine = context.diagrams(entry)
            record = engine.manual_review().create(body.page_index, body.bbox)
            record['revision'] = row.edit_version
            return answer_diagram_view(engine, [record], test_id, entry_id, question_id)['diagrams'][0]
        except ValueError as exc:
            question_error(exc)

    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/diagrams/{candidate_id}/crop-preview')
    def answer_crop_preview(test_id: str, entry_id: str, candidate_id: str, body: DiagramCropRequest,
        question_id: str | None = None, scope: Literal['exact', 'parent', 'pdf', 'reuse', 'manual'] = 'exact',
        reuse_ref: str | None = None, s=Depends(db)):
        try:
            context, entry, row = answer_context(test_id, entry_id, s, body.expected_revision, question_id)
            if not hasattr(context, 'diagrams'):
                raise ValueError('authoring_answer_source_missing')
            engine = context.diagrams(entry)
            record = engine.record(candidate_id, final_bbox=body.final_bbox, revision=row.edit_version, scope=scope, reuse_ref=reuse_ref)
            return answer_diagram_view(engine, [record], test_id, entry_id, question_id)['diagrams'][0]
        except ValueError as exc:
            question_error(exc)

    @r.get('/tests/{test_id}/authoring/entries/{entry_id}/diagrams/{candidate_id}/crop')
    def answer_crop(test_id: str, entry_id: str, candidate_id: str, crop_sha: str | None = None,
        question_id: str | None = None, scope: Literal['exact', 'parent', 'pdf', 'reuse', 'manual'] = 'exact',
        reuse_ref: str | None = None, s=Depends(db)):
        try:
            context, entry, _ = answer_context(test_id, entry_id, s, question_id=question_id)
            if not hasattr(context, 'diagrams'):
                raise ValueError('authoring_answer_source_missing')
            engine = context.diagrams(entry)
            return FileResponse(engine.preview_path(candidate_id, crop_sha, scope=scope, reuse_ref=reuse_ref), media_type='image/png')
        except ValueError as exc:
            question_error(exc)

    from .model_answer_imports import MathOCRRequest

    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/math-ocr')
    def answer_math(test_id: str, entry_id: str, body: MathOCRRequest, s=Depends(db)):
        from ..source_math_ocr import SourceMathOCR, MathOCRError
        try:
            context, entry, row = answer_context(test_id, entry_id, s, body.expected_revision)
            if not hasattr(context, 'pdf'):
                raise ValueError('authoring_answer_source_missing')
            if not getattr(classifier, 'manager', None):
                raise MathOCRError('math_runtime_unavailable')
            result = SourceMathOCR(classifier.manager).propose(context.pdf,
                entry.get('source', {}).get('segments', []), body.text)
            result['source'] = {'draft_id': context.bound['draft_id'], 'entry_id': entry_id,
                'material_id': context.bound['material_id'], 'source_sha256': context.bound['source_sha256'], 'revision': row.edit_version}
            return result
        except MathOCRError as exc:
            raise HTTPException(504 if 'timeout' in exc.code else 503, {'error': {'code': exc.code}}) from exc
        except ValueError as exc:
            question_error(exc)

    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/rubric-split')
    def rubric_split(test_id: str, entry_id: str, body: RubricSplitTool, s=Depends(db)):
        from ..rubric_split import reconstruct_split
        from ..authoring_sources import normalize_authoring_snapshot
        try:
            # Splitting teacher text does not depend on PDF/diagram validity.
            # Keep authorization/CAS and target identity, without requiring an
            # unchanged Answer material for an independent Rubric operation.
            owned(test_id, s)
            row = latest(s, test_id)
            if not row or row.edit_version != body.expected_revision or row.state != 'draft':
                raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
            normalized = normalize_authoring_snapshot(row.snapshot)
            entry = next((e for e in normalized.get('domains', {}).get('rubric', {}).get('entries', [])
                          if e['id'] == entry_id), None)
            key = entry.get('authoring_question_key') if entry else body.question_key
            if entry_id.startswith('formal-entry:'):
                key = entry_id.removeprefix('formal-entry:')
            elif entry is None:
                from uuid import UUID
                if not entry_id.startswith(('teacher-entry-', 'teacher-rubric-')):
                    raise ValueError('authoring_answer_candidate_missing')
                UUID(entry_id.removeprefix('teacher-entry-').removeprefix('teacher-rubric-'))
            node = next((n for n in row.snapshot['nodes'] if n['stable_key'] == key), None)
            if not node and (entry is None or key is not None):
                raise HTTPException(404, 'AUTHORING_TARGET_MISSING')
            if body.offset is not None:
                contract = {'candidate_id': body.candidate_id, 'split': True, 'confidence': 1,
                    'reason': 'semantic_boundary', 'parts': [{'start': 0, 'end': body.offset},
                        {'start': body.offset, 'end': len(body.text)}]}
            else:
                if not callable(getattr(classifier, 'suggest_rubric_split', None)):
                    raise HTTPException(503, {'error': {'code': 'RUBRIC_SPLIT_UNAVAILABLE',
                        'message': 'AIによる分割案を利用できません。カーソル位置で分割するか、時間をおいて再試行してください。'}})
                result = classifier.suggest_rubric_split(candidate_id=body.candidate_id, text=body.text,
                    question_label=node['label']['raw'] if node else '', segment_ids=[])
                contract = {k: result[k] for k in ('candidate_id', 'split', 'confidence', 'reason')}
                contract['parts'] = [{k: p[k] for k in ('start', 'end')} for p in result['parts']]
            return reconstruct_split(contract, body.candidate_id, body.text)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422 if isinstance(exc, (ValueError, KeyError)) else 503,
                {'error': {'code': 'RUBRIC_SPLIT_FAILED',
                    'message': '分割案を作成できませんでした。本文と分割位置を確認し、再試行してください。'}}) from exc

    @r.post('/tests/{test_id}/authoring/entries/{entry_id}/rubric-consolidate')
    def rubric_consolidate(test_id: str, entry_id: str, body: ConsolidationTool, s=Depends(db)):
        from ..rubric_consolidation import consolidate_rubrics
        import time
        try:
            owned(test_id, s)
            row = latest(s, test_id)
            if not row or row.edit_version != body.expected_revision or row.state != 'draft':
                raise HTTPException(409, {'error': {'code': 'revision_conflict'}})
            from ..authoring_sources import normalize_authoring_snapshot
            normalized = normalize_authoring_snapshot(row.snapshot)
            entry = next((candidate for candidate in normalized.get('domains', {}).get('rubric', {}).get('entries', [])
                          if candidate.get('id') == entry_id), None)
            classification = (entry or {}).get('semantic_classification') or {}
            if body.criteria is not None:
                if len({c.id for c in body.criteria}) != len(body.criteria):
                    raise ValueError('rubric_duplicate_candidate')
                classification = {'segments': [{'id': c.id, 'text': f'{c.description} ({c.points:g}点)',
                    'source_text': f'{c.description} ({c.points:g}点)', 'category': 'rubric', 'confidence': 1}
                    for c in body.criteria]}
            groups, method = consolidate_rubrics(classification, classifier, time.monotonic()+120)
            return {'groups': groups, 'method': method}
        except ValueError as exc:
            question_error(exc)

    @r.get('/tests/{test_id}/authoring/review')
    @r.post('/tests/{test_id}/authoring/review')
    def review(test_id: str, body: SaveAuthoring | None = None, s=Depends(db)):
        test = owned(test_id, s)
        row = latest(s, test_id)
        snapshot = row.snapshot if row else projection(s, test)
        if body:
            if not row or row.edit_version != body.expected_edit_version:
                raise HTTPException(409, 'AUTHORING_SAVE_CONFLICT')
            from ..test_authoring import validate_snapshot
            try:
                validate_materials(body.snapshot, s, test_id)
                snapshot = validate_snapshot(body.snapshot, row.snapshot)
                if snapshot.get('domains', {}).get('answer'):
                    from ..authoring_answers import AuthoringAnswers
                    AuthoringAnswers(s, answer_root, row, snapshot).validate()
            except (AuthoringError, ValueError) as exc:
                raise HTTPException(422, {'error': {'code': getattr(exc, 'code', 'AUTHORING_SOURCE_INVALID'),
                    'message': '編集内容と出典の対応を確認してください。変更は保存されていません。'}}) from exc
        result = preflight(snapshot)
        for problem in source_problems(row, s):
            result['issues'].append({'question_key': None, 'section': 'source', 'message': '元PDFとの対応が無効になっています。資料と保存済みレビューを確認してください。', 'code': problem['code']})
        if row and row.baseline_sha256 != baseline_hash(projection(s, test)):
            result['issues'].append({'question_key': None, 'section': 'source',
                'message': '元の正式内容が変更されています。出典付きレビューを確認してください。'})
        return result

    @r.post('/tests/{test_id}/authoring/confirm')
    def confirm(test_id: str, s=Depends(db)):
        owned(test_id, s)
        # Publishing requires atomic domain adapters + submission/job revision
        # pins. Never silently freeze only a JSON draft or individual sections.
        raise HTTPException(409, {'error': {'code': 'AUTHORING_PUBLICATION_NOT_READY',
            'message': 'この画面からの試験内容確定は現在利用できません。'}})

    @r.get('/tests/{test_id}/archive-impact')
    def impact(test_id: str, s=Depends(db)):
        return archive_impact(s, owned(test_id, s))

    @r.post('/tests/{test_id}/archive')
    def archive(test_id: str, v: ArchiveRequest, s=Depends(db)):
        test = owned(test_id, s)
        s.scalar(select(Test).where(Test.id == test_id).with_for_update())
        impact = archive_impact(s, test)
        if v.test_name != test.name or v.impact_sha256 != impact['impact_sha256']:
            raise HTTPException(409, 'ARCHIVE_CONFIRMATION_CHANGED')
        if s.scalar(select(GradingJob.id).where(GradingJob.test_id == test_id,
                GradingJob.state.in_(['queued', 'running', 'paused']))):
            raise HTTPException(409, 'ACTIVE_GRADING_JOB')
        s.add(TestArchive(test_id=test.id, archived_by=s.info['auth_user'].id,
            previous_status=test.status, impact=impact))
        s.add(DomainEvent(entity_type='test', entity_id=test.id,
            event_type='test_archived', actor_user_id=s.info['auth_user'].id, payload=impact))
        s.commit()
        return {'archived': True, 'test_id': test.id}

    @r.post('/tests/{test_id}/restore')
    def restore(test_id: str, s=Depends(db)):
        owned(test_id, s, allow_archived=True)
        s.execute(delete(TestArchive).where(TestArchive.test_id == test_id))
        s.add(DomainEvent(entity_type='test', entity_id=test_id,
            event_type='test_restored', actor_user_id=s.info['auth_user'].id))
        s.commit()
        return {'restored': True, 'test_id': test_id}

    @r.get('/courses/{course_id}/recent-tests')
    def recent(course_id: str, s=Depends(db)):
        course = s.get(Course, course_id)
        actor = s.info.get('auth_user')
        if not course:
            raise HTTPException(404, 'COURSE_NOT_FOUND')
        if not actor or (actor.role != 'admin' and actor.id != course.owner_user_id):
            raise HTTPException(403, 'COURSE_ACCESS_DENIED')
        from ..db.models import TestAuthoringRevision
        edits = select(TestAuthoringRevision.test_id,
            func.max(TestAuthoringRevision.updated_at).label('last_saved')).group_by(TestAuthoringRevision.test_id).subquery()
        current_state = select(TestAuthoringRevision.state).where(TestAuthoringRevision.test_id == Test.id).order_by(
            TestAuthoringRevision.revision.desc()).limit(1).correlate(Test).scalar_subquery()
        last_changed = case((edits.c.last_saved > Test.updated_at, edits.c.last_saved), else_=Test.updated_at)
        values = s.scalars(select(Test).join(CourseOffering).outerjoin(edits, edits.c.test_id == Test.id).where(CourseOffering.course_id == course_id,
            ~Test.id.in_(select(TestArchive.test_id))).order_by(
                case((current_state.in_(['draft', 'final_review']), 0), else_=1),
                last_changed.desc(), Test.id).limit(1))
        result = []
        for test in values:
            row = latest(s, test.id)
            result.append({'id': test.id, 'name': test.name,
                'authoring_state': row.state if row else 'legacy', 'status': test.status})
        return {'tests': result}
    return r
