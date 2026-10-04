from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..latex_normalization import LatexNormalizer


class NormalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    context_type: Literal["model_answer", "rubric", "question", "sample_answer", "generic"] = "generic"
    context_label: str = Field(default="", max_length=500)


def router(classifier):
    routes = APIRouter(prefix="/api/v1/text-tools")

    @routes.post("/latex-normalize")
    def normalize(body: NormalizeRequest):
        if classifier is None or not hasattr(classifier, "manager"):
            raise HTTPException(503, {"error": {"code": "NORMALIZER_UNAVAILABLE", "message": "LaTeX変換を利用できません。元の本文は保持されています。"}})
        try:
            return LatexNormalizer(classifier.manager, classifier.profile_id).normalize(body.text, body.context_type, body.context_label)
        except (ValueError, RuntimeError, TimeoutError, OSError, KeyError, TypeError) as exc:
            raise HTTPException(503, {"error": {"code": "NORMALIZATION_FAILED", "message": "LaTeX変換案を作成できませんでした。再試行してください。"}}) from exc

    return routes
