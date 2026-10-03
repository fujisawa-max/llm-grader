"""Read-only authoritative question context and derived grading readiness.

No model calls. A test's hierarchy, associations and assets are loaded in batches.
"""

import math
import os
from pathlib import Path

from sqlalchemy import select

from .adapters.artifacts import RunArtifactAdapter
from .db.models import ModelAnswer, RubricVersion, Test, TestQuestion, TestQuestionAsset
from .pdf_native import canonical_hash, sha256_file


class ContextError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def artifact_root(root=None):
    return Path(root or os.getenv("LLM_GRADER_QUESTION_IMPORT_ROOT", "artifacts/question-imports"))


def asset_path(asset, root):
    """Both extraction and artifact references must stay below the configured root."""
    try:
        store = RunArtifactAdapter(artifact_root(root))
        extraction = (asset.provenance or {}).get("extraction_id")
        if not isinstance(extraction, str) or not extraction:
            raise ContextError("ASSET_MISSING")
        base = store.path(extraction)
        path = RunArtifactAdapter(base).path(asset.artifact_ref)
        if not path.is_file():
            raise ContextError("ASSET_MISSING")
        if sha256_file(path) != asset.sha256:
            raise ContextError("ASSET_HASH_MISMATCH")
        return path
    except (OSError, ValueError) as exc:
        if isinstance(exc, ContextError):
            raise
        raise ContextError("ASSET_MISSING") from exc


class EffectiveQuestionContextBuilder:
    def __init__(self, questions, assets=(), *, root=None):
        self.questions = {q.id: q for q in questions}
        self.assets = {a.id: a for a in assets}
        self.root = artifact_root(root)
        self.verified_assets = {}

    def build(self, question_id):
        leaf = self.questions.get(question_id)
        if leaf is None:
            raise ContextError("QUESTION_NOT_FOUND")
        chain, seen, current = [], set(), leaf
        while current:
            if current.id in seen:
                raise ContextError("PARENT_CYCLE")
            if current.test_id != leaf.test_id:
                raise ContextError("CROSS_TEST_PARENT")
            seen.add(current.id)
            chain.append(current)
            if not current.parent_id:
                break
            current = self.questions.get(current.parent_id)
            if current is None:
                raise ContextError("PARENT_MISSING")
        chain.reverse()
        segments, assets, texts = [], [], []
        for q in chain:
            if q.content is not None:
                if not isinstance(q.content, dict) or not isinstance(q.content.get("items"), list):
                    raise ContextError("EFFECTIVE_CONTEXT_UNRESOLVABLE")
                if q.content_sha256 and canonical_hash(q.content) != q.content_sha256:
                    raise ContextError("CONTENT_HASH_MISMATCH")
                if q.content.get("schema_version") != "test-question-content.v1":
                    raise ContextError("UNSUPPORTED_CONTENT_SCHEMA")
                items = q.content["items"]
            else:
                if (q.provenance or {}).get("origin") == "review_import":
                    raise ContextError("EFFECTIVE_CONTEXT_UNRESOLVABLE")
                items = [{"type": "text", "text": q.question_text or ""}]
            resolved, text = [], []
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    raise ContextError("UNSUPPORTED_CONTENT_ITEM")
                kind = item.get("type")
                if kind in {"text", "formula"}:
                    field = "text" if kind == "text" else "transcription"
                    value = item.get(field)
                    if not isinstance(value, str) or (kind == "formula" and not value.strip()):
                        raise ContextError("EFFECTIVE_CONTEXT_UNRESOLVABLE")
                    resolved.append({"type": kind, field: value})
                    text.append(value)
                elif kind == "figure":
                    asset = self.assets.get(item.get("asset_id"))
                    if asset is None or asset.question_id != q.id:
                        raise ContextError("ASSET_MISSING")
                    if asset.id not in self.verified_assets:
                        asset_path(asset, self.root)
                        self.verified_assets[asset.id] = True
                    ref = {"asset_id": asset.id, "sha256": asset.sha256,
                           "mime_type": asset.mime_type, "source_question_id": q.id,
                           "item_index": index,
                           "url": f"/api/v1/tests/{leaf.test_id}/test-question-assets/{asset.id}"}
                    assets.append(ref)
                    resolved.append({"type": "figure", "asset_id": asset.id,
                                     "sha256": asset.sha256})
                    text.append("[図]")
                elif kind == "score_expression":
                    # Kept in its ordered slot, but not repeated in semantic question text.
                    resolved.append({"type": kind, "text": item.get("text", "")})
                else:
                    raise ContextError("UNSUPPORTED_CONTENT_ITEM")
            label = q.display_label or q.question_number
            body = "\n".join(text)
            texts.append(f"[{label}]\n{body}" if len(chain) > 1 else body)
            segments.append({"source_question_id": q.id, "stable_question_key": q.stable_question_key,
                             "display_label": label, "title": q.title,
                             "role": "self" if q.id == leaf.id else "ancestor", "items": resolved,
                             "content_sha256": q.content_sha256})
        result = {"schema_version": "effective-question-context.v1", "question_id": leaf.id,
                  "test_id": leaf.test_id, "ancestor_chain": [q.id for q in chain[:-1]],
                  "segments": segments, "effective_text": "\n\n".join(texts), "assets": assets,
                  "max_points": leaf.max_points, "is_gradable": leaf.is_gradable}
        result["context_sha256"] = canonical_hash(result)
        return result


MESSAGES = {
    "MISSING_MAX_POINTS": "配点が未設定です。0点として扱いません。",
    "INVALID_MAX_POINTS": "現在の採点エンジンは正の整数配点を必要とします。",
    "MISSING_MODEL_ANSWER": "この問題の模範解答は未登録です。採点基準とは別に登録してください。",
    "EMPTY_MODEL_ANSWER": "模範解答の本文が空です。",
    "MISSING_RUBRIC": "この問題の採点基準は未登録または未承認です。模範解答の登録状態とは別です。",
    "INVALID_RUBRIC": "採点基準の観点・配点が不正です。",
    "RUBRIC_SCORE_MISMATCH": "採点基準と問題の配点が一致しません。",
    "GRADER_ASSET_UNSUPPORTED": "選択した採点adapterは問題図を扱えません。",
}


def reason(code):
    return {"code": code, "message": MESSAGES.get(code, code), "severity": "blocker"}


class GradingReadinessService:
    # LocalClient.chat + cli grading pass question asset_paths as images. No inference here.
    def __init__(self, session, *, root=None, supports_assets=True):
        self.s, self.root, self.supports_assets = session, root, supports_assets

    def evaluate(self, test_id):
        from .domain import validate_rubric

        test = self.s.get(Test, test_id)
        if test is None:
            raise ContextError("TEST_NOT_FOUND")
        qs = list(self.s.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)
                                .order_by(TestQuestion.sort_order, TestQuestion.id)))
        assets = list(self.s.scalars(select(TestQuestionAsset).join(TestQuestion)
                                    .where(TestQuestion.test_id == test_id)))
        answers = list(self.s.scalars(select(ModelAnswer).where(
            ModelAnswer.test_id == test_id, ModelAnswer.is_current.is_(True))
            .order_by(ModelAnswer.version.desc(), ModelAnswer.id)))
        rubric = self.s.scalar(select(RubricVersion).where(
            RubricVersion.test_id == test_id, RubricVersion.status == "approved")
            .order_by(RubricVersion.version.desc()))
        data = rubric.rubric_json if rubric and isinstance(rubric.rubric_json, dict) else {}
        rubric_items = data.get("questions", [])
        if not isinstance(rubric_items, list):
            rubric_items = []
        rubric_valid = True
        try:
            if rubric:
                validate_rubric(rubric.rubric_json, test)
        except (ValueError, TypeError, KeyError, AttributeError):
            rubric_valid = False
        builder = EffectiveQuestionContextBuilder(qs, assets, root=self.root)
        rows = []
        for q in qs:
            row = {"question_id": q.id, "parent_id": q.parent_id,
                   "stable_question_key": q.stable_question_key,
                   "content_sha256": q.content_sha256,
                   "display_label": q.display_label or q.question_number,
                   "max_points": q.max_points, "is_gradable": q.is_gradable,
                   "state": "NOT_GRADABLE", "blockers": [], "warnings": [],
                   "score_ready": False, "model_answer_ready": False,
                   "rubric_ready": False, "asset_ready": False, "context_ready": False,
                   "context_sha256": None}
            matching_answers = [a for a in answers if a.question_id == q.id]
            answer = matching_answers[0] if matching_answers else None
            entries = [v for v in rubric_items if isinstance(v, dict) and v.get("question_id") == q.id]
            if not q.is_gradable:
                if answer or entries:
                    row["warnings"].append({"code": "STRUCTURAL_ASSOCIATION_IGNORED",
                                            "message": "既存の関連付けは採点に使用しません。"})
                rows.append(row)
                continue
            codes = []
            if q.max_points is None:
                codes.append("MISSING_MAX_POINTS")
            elif not math.isfinite(q.max_points) or q.max_points <= 0 or q.max_points != int(q.max_points):
                codes.append("INVALID_MAX_POINTS")
            else:
                row["score_ready"] = True
            if len(matching_answers) > 1:
                codes.append("AMBIGUOUS_MODEL_ANSWER")
            elif answer is None:
                codes.append("MISSING_MODEL_ANSWER")
            elif not (answer.answer_text or "").strip():
                codes.append("EMPTY_MODEL_ANSWER")
            else:
                row["model_answer_ready"] = True
                row["model_answer"] = {"id": answer.id, "version": answer.version,
                                       "sha256": canonical_hash(answer.answer_text)}
            if not entries:
                codes.append("MISSING_RUBRIC")
            elif not rubric_valid or len(entries) != 1 or not entries[0].get("criteria"):
                codes.append("INVALID_RUBRIC")
            elif entries[0].get("max_points") != q.max_points:
                codes.append("RUBRIC_SCORE_MISMATCH")
            else:
                row["rubric_ready"] = True
                row["rubric"] = {"id": rubric.id, "version": rubric.version,
                                 "sha256": canonical_hash(entries[0])}
            try:
                context = builder.build(q.id)
                row["context_sha256"] = context["context_sha256"]
                row["context_ready"] = row["asset_ready"] = True
                row["asset_count"] = len(context["assets"])
                if context["assets"] and not self.supports_assets:
                    codes.append("GRADER_ASSET_UNSUPPORTED")
            except ContextError as exc:
                codes.append(exc.code)
            row["blockers"] = [reason(code) for code in codes]
            row["state"] = "BLOCKED" if codes else "READY"
            rows.append(row)
        gradable = [r for r in rows if r["is_gradable"]]
        return {"test_id": test_id, "total_questions": len(rows),
                "structural_count": len(rows) - len(gradable), "gradable_count": len(gradable),
                "ready_gradable_count": sum(r["state"] == "READY" for r in gradable),
                "blocked_gradable_count": sum(r["state"] == "BLOCKED" for r in gradable),
                **{f"{k}_count": sum(r[k] for r in gradable) for k in
                   ("score_ready", "model_answer_ready", "rubric_ready", "asset_ready")},
                "can_start_grading": bool(gradable) and all(r["state"] == "READY" for r in gradable),
                "blockers": [] if gradable else [reason("NO_GRADABLE_QUESTIONS")],
                "grader_supports_assets": self.supports_assets, "questions": rows}

    def context(self, question_id):
        q = self.s.get(TestQuestion, question_id)
        if q is None:
            raise ContextError("QUESTION_NOT_FOUND")
        qs = self.s.scalars(select(TestQuestion).where(TestQuestion.test_id == q.test_id)).all()
        assets = self.s.scalars(select(TestQuestionAsset).join(TestQuestion)
                                .where(TestQuestion.test_id == q.test_id)).all()
        return EffectiveQuestionContextBuilder(qs, assets, root=self.root).build(question_id)
