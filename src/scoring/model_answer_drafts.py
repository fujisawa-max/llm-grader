"""Deterministic native-PDF model-answer segmentation for teacher review."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any
from uuid import uuid4


IMPORT_SCHEMA = "model-answer-review.v1"


def _normalized_label(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    value = re.sub(r"^(?:問題|問|question|q)\s*", "", value)
    value = re.sub(r"^[（(]|[）)]$", "", value)
    return re.sub(r"[\s.．、:：()（）]", "", value)


def _question_tokens(question) -> set[str]:
    values = {question.display_label, question.question_number}
    key = getattr(question, "stable_question_key", None)
    if key:
        suffix = re.search(r"(?:^|-)q([0-9]+(?:[.-][0-9]+)*)$", key, re.IGNORECASE)
        if suffix:
            values.add(suffix.group(1))
    tokens = set()
    for value in values:
        normalized = _normalized_label(value)
        if normalized:
            tokens.add(normalized)
        # A display label such as "問題2（1）" may contain a complete path.
        for number in re.findall(r"[0-9a-z]+(?:[.-][0-9a-z]+)*", unicodedata.normalize("NFKC", str(value or "")).lower()):
            tokens.add(number.replace(".", "").replace("-", ""))
            tokens.add(re.split(r"[.-]", number)[-1])
    return tokens


def question_choices(questions: list[Any]) -> list[dict[str, Any]]:
    by_id = {q.id: q for q in questions}

    def label_for(question, seen=None):
        seen = set(seen or ())
        if question.id in seen:
            return question.display_label or question.question_number
        seen.add(question.id)
        current = question.display_label or question.question_number
        parent = by_id.get(question.parent_id) if question.parent_id else None
        if parent:
            return f"{label_for(parent, seen)} > {current}"
        return current

    return [
        {"id": q.id, "label": label_for(q), "display_label": q.display_label or q.question_number,
         "parent_id": q.parent_id, "is_gradable": bool(q.is_gradable)}
        for q in sorted(questions, key=lambda item: (item.sort_order, item.question_number, item.id))
        if q.is_gradable
    ]


def _lines_from_ir(ir: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Build page text with Unicode offsets and links back to native IR spans."""
    all_text: list[str] = []
    lines: list[dict[str, Any]] = []
    for page in ir.get("pages", []):
        groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for element in page.get("elements", []):
            if element.get("type") != "text" or not element.get("native_text"):
                continue
            native = element.get("native") or {}
            groups[(int(native.get("block_index", 0)), int(native.get("line_index", 0)))].append(element)
        page_lines = []
        for group in groups.values():
            group.sort(key=lambda item: int(item.get("reading_order") or 0))
            text_parts: list[str] = []
            element_ranges = []
            offset = 0
            previous = None
            for element in group:
                value = str(element.get("native_text") or "")
                if not value:
                    continue
                separator = ""
                if previous is not None:
                    left = previous.get("bbox") or [0, 0, 0, 0]
                    right = element.get("bbox") or [0, 0, 0, 0]
                    left_char = text_parts[-1][-1:] if text_parts and text_parts[-1] else ""
                    right_char = value[:1]
                    if left_char.isascii() and right_char.isascii() and left_char.isalnum() and right_char.isalnum() and right[0] - left[2] > 1.5:
                        separator = " "
                if separator:
                    text_parts.append(separator)
                    offset += len(separator)
                start = offset
                text_parts.append(value)
                offset += len(value)
                element_ranges.append({"element_id": element.get("element_id"), "start": start, "end": offset})
                previous = element
            line_text = "".join(text_parts).strip()
            if line_text:
                # Match the trimmed content to its offset within the original span concatenation.
                raw_line = "".join(text_parts)
                trim_left = len(raw_line) - len(raw_line.lstrip())
                trim_right = len(raw_line.rstrip())
                page_lines.append({"text": line_text, "trim_left": trim_left, "trim_right": trim_right,
                                   "element_ranges": element_ranges,
                                   "reading_order": min(int(item.get("reading_order") or 0) for item in group)})
        # Group insertion follows the extractor's native order; sorting by the
        # first span makes that invariant explicit and avoids reconstructing it
        # from block/line identifiers.
        page_lines.sort(key=lambda line: line["reading_order"])
        page_text_parts = []
        page_offset = 0
        for index, line in enumerate(page_lines):
            if index:
                page_text_parts.append("\n")
                page_offset += 1
            line_start = page_offset
            page_text_parts.append(line["text"])
            line_end = line_start + len(line["text"])
            element_ids = [item["element_id"] for item in line["element_ranges"]]
            # Span ids intentionally stay attached even when a heading is trimmed from the answer text.
            lines.append({"text": line["text"], "page_index": int(page.get("page_index", 0)),
                          "start": line_start, "end": line_end, "element_ids": element_ids})
            page_offset = line_end
        page_text = "".join(page_text_parts)
        all_text.append(page_text)
    return "\n\f\n".join(all_text), lines


def _marker(line: str):
    """Return (kind, normalized number, body, consumed source chars)."""
    full = unicodedata.normalize("NFKC", line)

    def source_prefix_length(normalized_body: str) -> int:
        """Translate a normalized match offset back to Python source characters."""
        normalized_body = normalized_body.lstrip()
        if not normalized_body:
            return len(line)
        for index in range(len(line) + 1):
            if unicodedata.normalize("NFKC", line[index:]).lstrip() == normalized_body:
                return index
        # Marker grammars are intentionally conservative; this fallback is
        # only reached for unusual compatibility characters.
        return max(0, len(line) - len(normalized_body))

    explicit = re.match(r"^\s*(?:問題|問|question|q)\s*([0-9]+(?:[.-][0-9]+)*)\s*(?:[：:]\s*|[、.]\s*|\s+|$)(.*)$", full, re.IGNORECASE)
    if explicit:
        body = explicit.group(2)
        return "root", explicit.group(1), body, source_prefix_length(body)
    nested = re.match(r"^\s*([0-9]+(?:[.-][0-9]+)+)\s*(?:[).．、:：]?\s*)(.*)$", full)
    if nested:
        body = nested.group(2)
        return "path", nested.group(1), body, source_prefix_length(body)
    child = re.match(r"^\s*[（(]\s*([0-9a-z]+)\s*[）)]\s*(?:[：:]\s*)?(.*)$", full, re.IGNORECASE)
    if child:
        body = child.group(2)
        return "child", child.group(1).lower(), body, source_prefix_length(body)
    numbered = re.match(r"^\s*([0-9]+)[.)．、]\s*(.*)$", full)
    if numbered:
        body = numbered.group(2)
        return "numbered", numbered.group(1), body, source_prefix_length(body)
    return None


def build_model_answer_entries(ir: dict[str, Any], questions: list[Any]) -> list[dict[str, Any]]:
    """Segment only when a visible question marker uniquely matches the current tree.

    Ambiguous or unmatched marker text remains an unmapped draft for explicit teacher mapping.
    This parser is deterministic, uses no OCR fallback or model calls, and does not create Questions.
    """
    full_text, lines = _lines_from_ir(ir)
    ordered_questions = sorted(questions, key=lambda q: (q.sort_order, q.question_number, q.id))
    children: dict[str | None, list[Any]] = defaultdict(list)
    for question in ordered_questions:
        children[question.parent_id].append(question)

    def match_siblings(marker: str, siblings: list[Any]):
        token = _normalized_label(marker)
        hits = [q for q in siblings if token in _question_tokens(q)]
        return hits[0] if len(hits) == 1 else None

    def match_path(path: str):
        pieces = [piece for piece in re.split(r"[.-]", path) if piece]
        if not pieces:
            return None
        current = match_siblings(pieces[0], children[None])
        if current is None:
            return None
        for piece in pieces[1:]:
            current = match_siblings(piece, children[current.id])
            if current is None:
                return None
        return current

    parts: list[dict[str, Any]] = []
    current_parent: str | None = None
    current_target: dict[str, Any] | None = None

    def begin(question, body, line, consumed):
        nonlocal current_target
        target = question if question and question.is_gradable else None
        current_target = {
            "id": str(uuid4()),
            "question_id": target.id if target else None,
            "mapping_state": "automatic" if target else "needs_review",
            "answer_text": "",
            "source": {"material_id": ir.get("source", {}).get("material_id"),
                       "source_sha256": ir.get("source", {}).get("sha256"), "segments": []},
        }
        parts.append(current_target)
        append(body, line, consumed)

    def append(body, line, consumed=0):
        text = body.strip()
        if not text:
            return
        if current_target is None:
            return
        current_target["answer_text"] += ("\n" if current_target["answer_text"] else "") + text
        start = min(line["end"], line["start"] + consumed)
        while start < line["end"] and line["text"][start - line["start"]].isspace():
            start += 1
        if start < line["end"]:
            current_target["source"]["segments"].append({
                "page_index": line["page_index"], "text_start": start, "text_end": line["end"],
                "element_ids": line["element_ids"],
            })

    for line in lines:
        marker = _marker(line["text"])
        if not marker:
            append(line["text"], line)
            continue
        kind, number, body, consumed = marker
        question = None
        if kind == "root":
            question = match_path(number)
            if question:
                current_parent = question.id
                begin(question, body, line, consumed)
                continue
        elif kind in {"child", "numbered"} and current_parent:
            question = match_siblings(number, children[current_parent])
            if question:
                begin(question, body, line, consumed)
                continue
        elif kind == "path":
            question = match_path(number)
            if question:
                current_parent = question.parent_id
                begin(question, body, line, consumed)
                continue
        # Preserve unmatched marker text as an explicitly unmapped candidate rather than guessing.
        current_parent = None if kind == "root" else current_parent
        if (kind in {"child", "numbered", "path"} and current_target is not None
                and current_target.get("mapping_state") == "needs_review"):
            append(line["text"], line, 0)
            continue
        begin(None, line["text"], line, 0)

    # If the PDF has no recognizable question markers, keep the entire native text editable.
    entries = [part for part in parts if part["answer_text"].strip()]
    if not entries:
        text = full_text.strip()
        if text:
            entries = [{"id": str(uuid4()), "question_id": None, "mapping_state": "needs_review",
                        "answer_text": text,
                        "source": {"material_id": ir.get("source", {}).get("material_id"),
                                   "source_sha256": ir.get("source", {}).get("sha256"),
                                   "segments": [{"page_index": line["page_index"],
                                                 "text_start": line["start"], "text_end": line["end"],
                                                 "element_ids": line["element_ids"]}
                                                for line in lines]}}]

    # Combine repeated labelled fragments for the same question without losing their citations.
    combined: list[dict[str, Any]] = []
    known: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry.get("question_id")
        if key and key in known:
            known[key]["answer_text"] += "\n" + entry["answer_text"]
            known[key]["source"]["segments"].extend(entry["source"]["segments"])
        else:
            combined.append(entry)
            if key:
                known[key] = entry
    return combined


def draft_view(draft, choices: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": draft.id, "test_id": draft.test_id, "material_id": draft.material_id,
            "source_sha256": draft.source_sha256, "state": draft.state, "revision": draft.revision,
            "entries": draft.snapshot.get("entries", []), "questions": choices,
            "page_count": draft.snapshot.get("page_count", 0),
            "parser": draft.snapshot.get("parser", {}), "created_at": draft.created_at.isoformat()}
