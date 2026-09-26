from fastapi import APIRouter, Depends, HTTPException
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


def router(db, root):
    r = APIRouter(prefix="/api/v1")

    def call(s, method, *args, **kw):
        try:
            return getattr(QuestionReviewService(s, root), method)(*args, **kw)
        except ReviewError as e:
            raise HTTPException(
                e.status, detail={"error": {"code": e.code, "message": "レビューを処理できません"}}
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
    def page_metadata(review_id: str, page_index: int, s=Depends(db)):
        return call(s, "preview", review_id, page_index)[1]

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
