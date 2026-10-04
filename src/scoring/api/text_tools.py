from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import logging

from ..latex_normalization import LatexNormalizer, LatexNormalizationError

logger = logging.getLogger(__name__)


class NormalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    context_type: Literal["model_answer", "rubric", "question", "sample_answer", "generic"] = "generic"
    context_label: str = Field(default="", max_length=500)


def router(classifier):
    routes = APIRouter(prefix="/api/v1/text-tools")

    @routes.post("/latex-normalize")
    def normalize(body: NormalizeRequest):
        logger.info("latex API request context=%s chars=%d", body.context_type, len(body.text))
        if classifier is None or not hasattr(classifier, "manager"):
            raise HTTPException(503, {"error": {"code": "latex_runtime_unavailable", "message": "LaTeX変換を利用できません。元の本文は保持されています。"}})
        try:
            return LatexNormalizer(classifier.manager, classifier.profile_id).normalize(body.text, body.context_type, body.context_label)
        except LatexNormalizationError as exc:
            messages = {
                "latex_runtime_unavailable": "LLMのprofileまたは接続設定を利用できません。",
                "latex_runtime_start_failed": "LLMを起動できませんでした。",
                "latex_runtime_start_timeout": "LLMの起動に時間がかかりすぎています。",
                "latex_inference_timeout": "LaTeX変換に時間がかかりすぎています。",
                "latex_inference_failed": "LLMから変換結果を取得できませんでした。",
                "latex_invalid_response": "LLMから有効な変換結果を取得できませんでした。",
            }
            logger.warning("latex API failed code=%s stage=%s", exc.code, exc.stage)
            raise HTTPException(504 if "timeout" in exc.code else 503, {"error": {
                "code": exc.code, "message": messages[exc.code], "details": {"stage": exc.stage}}}) from exc
        except (ValueError, RuntimeError, TimeoutError, OSError, KeyError, TypeError) as exc:
            raise HTTPException(503, {"error": {"code": "NORMALIZATION_FAILED", "message": "LaTeX変換案を作成できませんでした。再試行してください。"}}) from exc

    return routes
