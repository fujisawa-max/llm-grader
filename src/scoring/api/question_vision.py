"""Selective question vision API. Native drafts remain immutable baselines."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ..question_vision import VisionFallbackService, VisionError


class VisionExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execute: bool = False
    region_ids: list[str] | None = None


class VisionResume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_ids: list[str] | None = None


def router(db, root, *, inference=None, policy=None):
    routes = APIRouter(prefix="/api/v1")

    def invoke(session, action, *args, **kwargs):
        try:
            return getattr(VisionFallbackService(session, root, inference=inference, policy=policy), action)(*args, **kwargs)
        except VisionError as exc:
            raise HTTPException(exc.status, detail={"error": {"code": exc.code,
                                "message": "問題の視覚情報を処理できません。状態と設定を確認してください。"}}) from exc

    @routes.post("/question-import-drafts/{draft_id}/vision-plan")
    def plan(draft_id: str, s=Depends(db)):
        return invoke(s, "plan", draft_id)

    @routes.post("/question-import-drafts/{draft_id}/vision-runs", status_code=201)
    def create(draft_id: str, body: VisionExecution, s=Depends(db)):
        run = invoke(s, "create", draft_id)
        return invoke(s, "execute", run["id"], region_ids=body.region_ids) if body.execute else run

    @routes.post("/question-import-vision-runs/{run_id}/resume")
    def resume(run_id: str, body: VisionResume, s=Depends(db)):
        return invoke(s, "execute", run_id, region_ids=body.region_ids)

    @routes.get("/question-import-vision-runs/{run_id}")
    def status(run_id: str, s=Depends(db)):
        return invoke(s, "get", run_id)

    @routes.get("/question-import-vision-runs/{run_id}/results")
    def results(run_id: str, s=Depends(db)):
        return {"run_id": run_id, "results": invoke(s, "results", run_id)}

    return routes
