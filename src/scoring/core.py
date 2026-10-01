"""File contracts, local API access, and strict grading validation."""

import base64
import hashlib
import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .schemas import response_schema
from .runtime.network import runtime_opener, validate_endpoint

DEFAULT_GENERATION = {
    "temperature": 0,
    "seed": 42,
    "top_k": 40,
    "top_p": 0.95,
    "min_p": 0.05,
    "repeat_penalty": 1.0,
    "max_output_tokens": 4096,
}


def effective_generation(config, role=None):
    """Merge explicit generation settings while preserving legacy empty signatures."""
    settings = config.get("models", {}).get(role, {}) if role else {}
    values = {**config.get("generation", {}), **settings.get("generation", {})}
    if not values:
        return {}
    return {**DEFAULT_GENERATION, **values}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError(f"相対パスが必要: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"課題外の参照は禁止: {relative}")
    return path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        raise ValueError(f"不正なID: {value!r}")
    return value


def unique_ids(rows, key):
    ids = [identifier(row[key]) for row in rows]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"{key}が空または重複")
    return set(ids)


def validate_rubric(rubric):
    unique_ids(rubric["criteria"], "criterion_id")
    for criterion in rubric["criteria"]:
        scores = [level["score"] for level in criterion["levels"]]
        if (type(criterion["max_score"]) is not int or criterion["max_score"] <= 0
                or any(type(s) is not int or s < 0 for s in scores)
                or not scores or max(scores) != criterion["max_score"]
                or len(scores) != len(set(scores))):
            raise ValueError("不正な配点・許容点数")
    maximum = sum(c["max_score"] for c in rubric["criteria"])
    mode = rubric.get("aggregation", "sum")
    if mode not in {"sum", "cap", "unresolved"}:
        raise ValueError("未知の集計方式")
    if type(rubric["max_score"]) is not int or rubric["max_score"] <= 0:
        raise ValueError("不正な満点")
    if mode == "sum" and maximum != rubric["max_score"]:
        raise ValueError("観点合計と満点が一致しません")
    if mode == "cap" and maximum < rubric["max_score"]:
        raise ValueError("打ち切り点が観点合計を超えています")
    return mode


def load_assignment(root):
    root = Path(root).resolve()
    assignment = read_json(root / "assignment.json")
    identifier(assignment["assignment_id"])
    question_ids = unique_ids(assignment["questions"], "question_id")
    questions = []
    for entry in assignment["questions"]:
        q = dict(entry)
        q["text"] = safe_path(root, q["question"]).read_text(encoding="utf-8")
        q["rubric_data"] = read_json(safe_path(root, q["rubric"]))
        validate_rubric(q["rubric_data"])
        if q["rubric_data"]["question_id"] != q["question_id"]:
            raise ValueError("ルーブリックの設問ID不一致")
        q["reference_text"] = (safe_path(root, q["reference_answer"]).read_text(encoding="utf-8")
                               if q.get("reference_answer") else "")
        q["asset_paths"] = [safe_path(root, name) for name in q.get("assets", [])]
        if any(not p.is_file() for p in q["asset_paths"]):
            raise ValueError("問題図がありません")
        questions.append(q)
    submissions = []
    for relative in assignment["submissions"]:
        path = safe_path(root, relative)
        sub = read_json(path)
        identifier(sub["submission_id"])
        page_ids = unique_ids(sub["pages"], "page_id")
        if unique_ids(sub["answers"], "question_id") != question_ids:
            raise ValueError("答案の設問対応に過不足があります")
        for page in sub["pages"]:
            page["path"] = safe_path(path.parent, page["image"])
            if not page["path"].is_file() or page["path"].suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ValueError(f"PNG/JPEG答案がありません: {page['path']}")
        for answer in sub["answers"]:
            ids = answer["page_ids"]
            if not ids or len(ids) != len(set(ids)) or not set(ids) <= page_ids:
                raise ValueError("ページ参照が空・重複・不明")
        submissions.append(sub)
    unique_ids(submissions, "submission_id")
    return assignment, questions, submissions


def validate_grade(result, rubric, page_ids):
    if result.get("question_id") != rubric["question_id"]:
        raise ValueError("採点結果の設問ID不一致")
    criteria = {c["criterion_id"]: c for c in rubric["criteria"]}
    if unique_ids(result["criteria"], "criterion_id") != set(criteria):
        raise ValueError("採点観点が欠落・重複・不明")
    if type(result.get("needs_review")) is not bool:
        raise ValueError("needs_reviewは真偽値が必要")
    reasons = result.get("review_reasons")
    if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
        raise ValueError("review_reasonsは文字列配列が必要")
    for row in result["criteria"]:
        definition = criteria[row["criterion_id"]]
        score = row["score"]
        allowed = [level["score"] for level in definition["levels"]]
        if score is not None and (type(score) is not int or score not in allowed):
            raise ValueError("許容されない点数")
        if type(row.get("max_score")) is not int or row["max_score"] != definition["max_score"]:
            raise ValueError("モデルが満点を変更しました")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("採点理由がありません")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("採点根拠がありません")
        for item in evidence:
            if item.get("page_id") not in page_ids or not (
                isinstance(item.get("quote"), str) and item["quote"].strip()
                or isinstance(item.get("visual_observation"), str) and item["visual_observation"].strip()
            ):
                raise ValueError("不正な根拠・ページ参照")
    scores = [row["score"] for row in result["criteria"]]
    mode = validate_rubric(rubric)
    raw = None if None in scores else sum(scores)
    result["raw_score"] = raw
    result["score"] = (None if raw is None or mode == "unresolved"
                       else min(raw, rubric["max_score"]) if mode == "cap" else raw)
    if result["score"] is None:
        result["needs_review"] = True
        result["review_reasons"].append("採点不能または配点未確定")
    if result["review_reasons"]:
        result["needs_review"] = True
    return result


def image_content(path):
    mime = mimetypes.guess_type(str(path))[0]
    if mime not in {"image/png", "image/jpeg"}:
        raise ValueError("PNG/JPEGのみ対応")
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


class LocalClient:
    def __init__(self, config, role, endpoint_override=None):
        self.settings = config["models"][role]
        self.base = (endpoint_override or self.settings["base_url"]).rstrip("/")
        self.origin = validate_endpoint(self.base, config.get("trusted_runtime_hosts", ()))
        self.role = role
        self.timeout = self.settings.get("request_timeout_seconds", config.get("request_timeout_seconds", 300))
        self.generation = {**DEFAULT_GENERATION, **config.get("generation", {}),
                           **self.settings.get("generation", {})}
        self.opener = runtime_opener()

    def request(self, url, payload=None):
        target = urllib.parse.urlparse(url)
        if (target.scheme != self.origin.scheme or target.netloc != self.origin.netloc
                or target.query or target.fragment
                or not (target.path.startswith("/v1/") or target.path in {"/props", "/health"})):
            raise ValueError("runtime request must stay on the configured endpoint")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8')[:1500]}") from exc

    def preflight(self):
        models = self.request(self.base + "/models")
        if self.settings["model_id"] not in {m["id"] for m in models["data"]}:
            raise ValueError(f"モデルID不一致: {self.settings['model_id']}")
        props = self.request(self.base.removesuffix("/v1") + "/props")
        expected = self.settings.get("expected_ftype")
        if expected and props.get("model_ftype") != expected:
            raise ValueError(f"量子化が不一致: expected={expected}, actual={props.get('model_ftype')}")
        if not props.get("modalities", {}).get("vision"):
            raise ValueError(f"画像入力が無効です: {self.settings['label']}。mmproj付きで起動してください")
        return {"models": models, "props": props}

    def chat(self, prompt, materials, images):
        if self.role == "math_ocr":
            # Uni-MuMER is a formula transcriber, not a JSON assistant. Match
            # eval_handwrite.py's plain user request (including reasoning fallback).
            content = [{"type": "text", "text": prompt}]
            content.extend(image_content(path) for _, path in images)
            return self.request(self.base + "/chat/completions", {
                "model": self.settings["model_id"],
                "messages": [{"role": "user", "content": content}],
                **generation_payload(self.generation),
                "stream": False,
            })
        content = [{"type": "text", "text": json.dumps(materials, ensure_ascii=False)}]
        for label, path in images:
            content.extend([{"type": "text", "text": label}, image_content(path)])
        payload = {
            "model": self.settings["model_id"],
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": content}],
            **generation_payload(self.generation),
            "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "scoring_response", "strict": True, "schema": response_schema(materials),
            }},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        return self.request(self.base + "/chat/completions", payload)


def generation_payload(generation):
    """Return explicit llama.cpp sampling fields for every completion request."""
    return {"temperature": generation["temperature"], "seed": generation["seed"],
            "top_k": generation["top_k"], "top_p": generation["top_p"],
            "min_p": generation["min_p"], "repeat_penalty": generation["repeat_penalty"],
            "max_tokens": generation["max_output_tokens"]}


def parse_response(raw, *, allow_reasoning=False):
    choice = raw["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError(f"生成が正常終了していません: {choice.get('finish_reason')}")
    message = choice["message"]
    text = (message.get("content") or "").strip()
    if not text and allow_reasoning:
        text = (message.get("reasoning_content") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("JSON objectが必要")
    return result
