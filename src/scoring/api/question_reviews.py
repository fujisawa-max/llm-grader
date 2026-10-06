from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import select
from ..db.models import QuestionImportConfirmation, TestQuestionAsset
from ..question_reviews import QuestionReviewService, ReviewError
from ..question_import import QuestionImportPlanner, QuestionImportConfirmationService
from ..question_corrections import QuestionCorrectionService


class ReviewSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=1, strict=True)
    snapshot: dict
    changed_nodes: list[str] = []


class MarkReviewed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=1, strict=True)


class DiagramRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    expected_revision: int = Field(ge=1, strict=True)


class DiagramCropRequest(DiagramRequest):
    final_bbox: list[float] = Field(min_length=4, max_length=4)


class QuestionMathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    expected_revision: int = Field(ge=1, strict=True)
    expected_source: dict


class ImportConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    expected_revision_sha256: str = Field(min_length=64, max_length=64)
    import_plan_sha256: str = Field(min_length=64, max_length=64)
    mode: Literal["append"]


class CorrectionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_region_id: str = Field(min_length=1, max_length=128)
    expected_old_transcription: str = Field(max_length=20000)
    new_transcription: str = Field(max_length=20000)


class DisplayLabelCorrectionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_display_label"]
    expected_old_value: str = Field(max_length=200)
    new_value: str = Field(min_length=1, max_length=200)


class TitleCorrectionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_title"]
    expected_old_value: str = Field(max_length=200)
    new_value: str = Field(min_length=1, max_length=200)


class MaxPointsCorrectionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_max_points"]
    expected_old_value: float | None = None
    new_value: float = Field(gt=0)


class TextSegmentCorrectionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_text_segment"]
    item_index: int = Field(ge=0, strict=True)
    expected_old_text: str = Field(max_length=20000)
    new_text: str = Field(min_length=1, max_length=20000)


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_sha256: str = Field(min_length=64, max_length=64)
    operations: list[CorrectionOperation | DisplayLabelCorrectionOperation | TitleCorrectionOperation | MaxPointsCorrectionOperation | TextSegmentCorrectionOperation] = Field(min_length=1, max_length=100)
    reason_code: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=2000)
    plan_sha256: str | None = Field(default=None, min_length=64, max_length=64)


def router(db, root, classifier=None):
    r = APIRouter(prefix="/api/v1")

    def diagrams_service(s, review_id, node_key, revision=None):
        from ..diagram_review import question_diagram_review
        service = QuestionReviewService(s, root)
        rev = service._review(review_id).current_revision if revision is None else revision
        return question_diagram_review(service, review_id, node_key, rev), service, rev

    def diagram_error(exc):
        code = exc.code if isinstance(exc, ReviewError) else str(exc)
        status = exc.status if isinstance(exc, ReviewError) else (409 if 'stale' in code or 'revision' in code else 422)
        if 'not_found' in code:
            status = 404
        raise HTTPException(status, detail={'error': {'code': code}}) from exc

    def diagram_response(review, records, review_id, node_key):
        for record in records:
            if record.get('crop_sha256'):
                review.preview(record)
                record['preview_url'] = (f'/api/v1/question-import-reviews/{review_id}/nodes/{node_key}/diagrams/'
                    f'{record["id"]}/crop?crop_sha={record["crop_sha256"]}')
        return {'diagrams': records}

    @r.get('/question-import-reviews/{review_id}/nodes/{node_key}/diagrams')
    @r.post('/question-import-reviews/{review_id}/nodes/{node_key}/diagrams')
    def diagrams(review_id: str, node_key: str, request: Request, body: DiagramRequest | None = None, s=Depends(db)):
        try:
            review, service, revision = diagrams_service(s, review_id, node_key, body.expected_revision if body else None)
            if request.method == 'POST' and body:
                review.discover(getattr(classifier, 'manager', None))
            data = service.get(review_id)
            node = next(n for n in data['snapshot']['nodes'] if n['stable_key'] == node_key)
            return diagram_response(review, review.records(node.get('diagram_records', []), revision=revision), review_id, node_key)
        except (ValueError, ReviewError) as exc:
            diagram_error(exc)

    @r.post('/question-import-reviews/{review_id}/nodes/{node_key}/diagrams/{candidate_id}/crop-preview')
    def diagram_preview(review_id: str, node_key: str, candidate_id: str, body: DiagramCropRequest, s=Depends(db)):
        try:
            review, _, revision = diagrams_service(s, review_id, node_key, body.expected_revision)
            record = review.record(candidate_id, final_bbox=body.final_bbox, revision=revision)
            return diagram_response(review, [record], review_id, node_key)['diagrams'][0]
        except (ValueError, ReviewError) as exc:
            diagram_error(exc)

    @r.get('/question-import-reviews/{review_id}/nodes/{node_key}/diagrams/{candidate_id}/crop')
    def diagram_crop(review_id: str, node_key: str, candidate_id: str, crop_sha: str | None = None, s=Depends(db)):
        try:
            review, _, _ = diagrams_service(s, review_id, node_key)
            return FileResponse(review.preview_path(candidate_id, crop_sha), media_type='image/png')
        except (ValueError, ReviewError) as exc:
            diagram_error(exc)

    @r.post("/question-import-reviews/{review_id}/nodes/{node_key}/math-ocr")
    @r.post("/question-import-reviews/{review_id}/nodes/{node_key}/items/{item_index}/math-ocr")
    def math_ocr(review_id: str, node_key: str, body: QuestionMathRequest,
                 item_index: int | None = None, s=Depends(db)):
        import json
        import logging
        from ..question_math_source import question_math_source, compact_provenance
        from ..source_math_ocr import SourceMathOCR, MathOCRError
        if (item_index is not None and item_index < 0) or len(json.dumps(body.expected_source)) > 200000:
            raise HTTPException(422, detail={"error": {"code": "math_question_source_missing"}})
        try:
            path, segments, source, exclusions = question_math_source(QuestionReviewService(s, root), review_id,
                node_key, item_index, body.expected_revision, body.expected_source)
            if classifier is None or classifier.manager is None:
                raise MathOCRError('math_runtime_unavailable')
            logging.getLogger(__name__).info('question math OCR requested review=%s node=%s item=%s segments=%s',
                review_id, node_key, item_index, len(segments))
            result = SourceMathOCR(classifier.manager, excluded_source_regions=exclusions).propose(
                path, segments, body.text, alignment_mode='source_fragment')
            result['source'] = source
            if result['status'] in {'safe', 'ambiguous'}:
                result['apply_provenance'] = compact_provenance(result)
            return result
        except ReviewError as exc:
            raise HTTPException(exc.status, detail={"error": {"code": exc.code}}) from exc
        except MathOCRError as exc:
            raise HTTPException(504 if 'timeout' in exc.code else 503, detail={"error": {"code": exc.code}}) from exc
        except ValueError as exc:
            raise HTTPException(422, detail={"error": {"code": str(exc)}}) from exc
        except Exception as exc:
            logging.getLogger(__name__).warning('question math OCR failure review=%s node=%s type=%s',
                review_id, node_key, type(exc).__name__)
            raise HTTPException(503, detail={"error": {"code": "math_runtime_unavailable"}}) from exc

    def call(s, method, *args, **kw):
        try:
            return getattr(QuestionReviewService(s, root), method)(*args, **kw)
        except ReviewError as e:
            internal_codes = {"invalid_source_slice", "source_anchor_changed", "source_identity_changed",
                              "immutable_evidence_changed", "invalid_teacher_content"}
            details = {"node_key": e.node_key, "field_key": e.field_key}
            if e.status == 422:
                category = "internal_consistency" if e.code in internal_codes else "user_validation"
                details.update({"category": category,
                                "recoverable": category != "internal_consistency",
                                "recovery_action": "reload_latest" if category == "internal_consistency" else None})
            raise HTTPException(
                e.status, detail={"error": {"code": e.code, "message": "レビューを処理できません",
                                           "details": details}}
            ) from e

    @r.post("/question-import-reviews/{review_id}/import-plan")
    def import_plan(review_id: str, s=Depends(db)):
        try:
            return QuestionImportPlanner(s, root).plan(review_id)
        except ReviewError as e:
            raise HTTPException(
                e.status, detail={"error": {"code": e.code, "message": "import plan unavailable"}}
            )

    @r.post("/question-import-reviews/{review_id}/confirm")
    def confirm(review_id: str, body: ImportConfirm, s=Depends(db)):
        try:
            return QuestionImportConfirmationService(s, root).confirm(
                review_id,
                body.expected_revision,
                body.expected_revision_sha256,
                body.import_plan_sha256,
                body.mode,
            )
        except ReviewError as e:
            s.rollback()
            raise HTTPException(
                e.status,
                detail={"error": {"code": e.code, "message": "import could not be confirmed"}},
            )

    @r.get("/question-import-confirmations/{confirmation_id}")
    def confirmation(confirmation_id: str, s=Depends(db)):
        try:
            return QuestionImportConfirmationService(s, root).get_confirmation(confirmation_id)
        except ReviewError as e:
            raise HTTPException(
                e.status, detail={"error": {"code": e.code, "message": "confirmation not found"}}
            )

    @r.get("/question-import-reviews/{review_id}/confirmation")
    def existing_confirmation(review_id: str, s=Depends(db)):
        call(s, "get", review_id)
        row = s.scalar(
            select(QuestionImportConfirmation).where(
                QuestionImportConfirmation.review_id == review_id
            )
        )
        if not row:
            return None
        return confirmation(row.id, s)

    @r.get("/test-question-assets/{asset_id}")
    def asset_file(asset_id: str, s=Depends(db)):
        asset = s.get(TestQuestionAsset, asset_id)
        if not asset:
            raise HTTPException(404, "asset_not_found")
        try:
            service = QuestionImportConfirmationService(s, root)
            service.get_confirmation(asset.provenance["confirmation_id"])
            from ..adapters.artifacts import RunArtifactAdapter
            from pathlib import Path

            store = RunArtifactAdapter(Path(root) / asset.provenance["extraction_id"])
            path = QuestionReviewService._artifact(store, asset.artifact_ref, asset.sha256)
            return FileResponse(path, media_type=asset.mime_type)
        except ReviewError as e:
            raise HTTPException(e.status, e.code) from e

    @r.get("/tests/{test_id}/question-import-reviews")
    def list_reviews(test_id: str, s=Depends(db)):
        return call(s, "list_for_test", test_id)

    @r.post("/question-import-drafts/{draft_id}/reviews", status_code=201)
    def create(draft_id, s=Depends(db)):
        return call(s, "create", draft_id)

    @r.get("/question-import-reviews/{review_id}")
    def get(review_id, s=Depends(db)):
        return call(s, "get", review_id)

    @r.post("/question-import-reviews/{review_id}/revisions")
    def save(review_id, body: ReviewSave, s=Depends(db)):
        return call(s, "save", review_id, body.model_dump())

    @r.get("/question-import-reviews/{review_id}/revisions")
    def revisions(review_id, s=Depends(db)):
        return {"revisions": call(s, "revisions", review_id)}

    @r.get("/question-import-reviews/{review_id}/revisions/{revision}")
    def revision(review_id: str, revision: int, s=Depends(db)):
        return call(s, "get", review_id, revision)

    @r.get("/question-import-reviews/{review_id}/pages/{page_index}/metadata")
    def page_metadata(review_id: str, page_index: int, revision: int | None = Query(default=None, ge=1), s=Depends(db)):
        return call(s, "preview", review_id, page_index, revision)[1]

    @r.get("/question-import-reviews/{review_id}/pages/{page_index}/preview")
    def page_preview(review_id: str, page_index: int, s=Depends(db)):
        path, metadata = call(s, "preview", review_id, page_index)
        return FileResponse(path, media_type="image/png", headers={"ETag": metadata["sha256"]})

    @r.get("/question-import-reviews/{review_id}/regions/{region_id}/evidence")
    def evidence(review_id: str, region_id: str, s=Depends(db)):
        return call(s, "region_evidence", review_id, region_id)

    @r.get("/question-import-reviews/{review_id}/regions/{region_id}/crop")
    def crop(review_id: str, region_id: str, s=Depends(db)):
        return FileResponse(call(s, "region_crop", review_id, region_id), media_type="image/png")

    @r.get("/question-import-reviews/{review_id}/regions/{region_id}/vision-raw")
    def raw(review_id: str, region_id: str, s=Depends(db)):
        return call(s, "region_raw", review_id, region_id)

    @r.post("/question-import-reviews/{review_id}/mark-reviewed")
    def reviewed(review_id, body: MarkReviewed, s=Depends(db)):
        return call(s, "mark_reviewed", review_id, body.base_revision)

    @r.post("/test-questions/{question_id}/correction-plan")
    def correction_plan(question_id: str, body: CorrectionRequest, s=Depends(db)):
        try:
            return QuestionCorrectionService(s, root).plan(
                question_id,
                expected_content_sha256=body.expected_content_sha256,
                operations=[x.model_dump() for x in body.operations],
                reason_code=body.reason_code,
                note=body.note,
            )
        except ReviewError as e:
            raise HTTPException(e.status, detail={"error": {"code": e.code, "message": "correction plan unavailable"}}) from e

    @r.post("/test-questions/{question_id}/corrections")
    def correction_apply(question_id: str, body: CorrectionRequest, s=Depends(db)):
        if not body.plan_sha256:
            raise HTTPException(422, detail={"error": {"code": "correction_plan_required", "message": "correction plan is required"}})
        try:
            return QuestionCorrectionService(s, root).apply(
                question_id,
                expected_content_sha256=body.expected_content_sha256,
                operations=[x.model_dump() for x in body.operations],
                reason_code=body.reason_code,
                plan_sha256=body.plan_sha256,
                note=body.note,
            )
        except ReviewError as e:
            s.rollback()
            raise HTTPException(e.status, detail={"error": {"code": e.code, "message": "correction could not be applied"}}) from e

    @r.get("/test-questions/{question_id}/corrections")
    def correction_history(question_id: str, s=Depends(db)):
        try:
            return {"corrections": QuestionCorrectionService(s, root).history(question_id)}
        except ReviewError as e:
            raise HTTPException(e.status, detail={"error": {"code": e.code, "message": "correction history unavailable"}}) from e

    return r
