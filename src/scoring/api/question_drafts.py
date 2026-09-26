"""Candidate-only draft endpoints. No edit, confirm or TestQuestion mutation."""
from fastapi import APIRouter, Depends, HTTPException
from ..question_drafts import DraftError, QuestionDraftService


def router(db, root):
    routes = APIRouter(prefix="/api/v1")

    def invoke(session, method, identifier):
        try:
            return getattr(QuestionDraftService(session, root), method)(identifier)
        except DraftError as exc:
            raise HTTPException(exc.status, detail={"error": {"code": exc.code, "message": "問題構造Draftを取得・生成できません"}}) from exc

    @routes.post("/question-imports/{extraction_id}/draft", status_code=201)
    def generate(extraction_id: str, s=Depends(db)):
        return invoke(s, "generate", extraction_id)

    @routes.get("/question-imports/{extraction_id}/draft")
    def latest(extraction_id: str, s=Depends(db)):
        return invoke(s, "latest", extraction_id)

    @routes.get("/question-import-drafts/{draft_id}")
    def detail(draft_id: str, s=Depends(db)):
        return invoke(s, "get", draft_id)

    return routes
