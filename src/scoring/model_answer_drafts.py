"""Deterministic native-PDF model-answer segmentation for teacher review."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4


IMPORT_SCHEMA = "model-answer-review.v1"
FUZZY_MIN_LENGTH = 32
FUZZY_MIN_CONFIDENCE = 0.97


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

    # Database row order and PDF reading order do not describe the question tree.
    # Traverse every node (including structural parents) before filtering choices.
    children: dict[str | None, list[Any]] = {}
    for question in questions:
        parent = question.parent_id if question.parent_id in by_id else None
        children.setdefault(parent, []).append(question)
    ordered = []
    seen: set[str] = set()

    def walk(parent: str | None):
        for question in sorted(children.get(parent, []),
                               key=lambda item: (item.sort_order, item.question_number, item.id)):
            if question.id in seen:
                continue
            seen.add(question.id)
            ordered.append(question)
            walk(question.id)

    walk(None)
    for question in questions:
        if question.id not in seen:
            ordered.append(question)

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

    def body_for(question):
        body = getattr(question, "question_text", None)
        if body:
            return str(body).strip()
        content = getattr(question, "content", None)
        items = content.get("items", []) if isinstance(content, dict) else []
        def display_part(item):
            value = str(item.get("text") or item.get("transcription") or item.get("latex") or "").strip()
            if item.get("type") == "formula" and value and not value.startswith("$"):
                return f"${value}$"
            return value
        return "\n".join(
            display_part(item)
            for item in items if isinstance(item, dict) and item.get("type") in {"text", "formula"}
        ).strip()

    rank = {question.id: index for index, question in enumerate(ordered)}
    return [
        {"id": q.id, "label": label_for(q), "display_label": q.display_label or q.question_number,
         "parent_id": q.parent_id, "is_gradable": bool(q.is_gradable), "hierarchy_order": rank[q.id],
         "question_text": body_for(q), "max_points": getattr(q, "max_points", None)}
        for q in ordered
        if q.is_gradable
    ]


def _question_body_variants(question: Any) -> list[str]:
    """Return text for this question only, including its own ordered math content."""
    variants: list[str] = []
    body = str(getattr(question, "question_text", None) or "").strip()
    if body:
        variants.append(body)

    content = getattr(question, "content", None)
    items = content.get("items", []) if isinstance(content, dict) else []
    if isinstance(items, list):
        parts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "text":
                parts.append(str(item.get("text") or ""))
            elif kind == "formula":
                formula = str(item.get("transcription") or item.get("latex") or "").strip()
                if formula:
                    parts.append(formula)
        ordered_body = "".join(parts).strip()
        if ordered_body and ordered_body not in variants:
            variants.append(ordered_body)

    # Compare complete body/paragraphs first, then standalone sentences. Short
    # fragments are excluded later so a common phrase cannot erase an answer.
    for variant in list(variants):
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", variant) if part.strip()]
        variants.extend(part for part in paragraphs if part not in variants)
        for paragraph in paragraphs:
            sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])\s*", paragraph) if part.strip()]
            variants.extend(part for part in sentences if part not in variants)
    return list(dict.fromkeys(variants))


def _strip_leading_question_markers(text: str) -> tuple[str, int]:
    """Ignore leading question labels while retaining their source offset."""
    offset = len(text) - len(text.lstrip())
    marker = re.compile(
        r"^(?:(?:問題|問|question|q)\s*[0-9]+(?:[.-][0-9]+)*\s*[:：、.]?"
        r"|[（(]\s*[0-9a-z]+\s*[）)]\s*|[0-9]+[.)．、]\s*)",
        re.IGNORECASE,
    )
    while offset < len(text):
        match = marker.match(text[offset:])
        if not match:
            break
        offset += match.end()
        offset += len(text[offset:]) - len(text[offset:].lstrip())
    return text[offset:], offset


def _normalized_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    """Normalize comparison text and map normalized chars to source spans."""
    source, base_offset = _strip_leading_question_markers(text)
    normalized: list[str] = []
    source_starts: list[int] = []
    source_ends: list[int] = []
    index = 0
    while index < len(source):
        if any(source.startswith(delimiter, index) for delimiter in ("\\(", "\\)", "\\[", "\\]")):
            index += 2
            continue
        cluster_end = index + 1
        while cluster_end < len(source) and unicodedata.category(source[cluster_end]).startswith("M"):
            cluster_end += 1
        cluster = source[index:cluster_end]
        # Delimiters do not affect whether a question's mathematical wording
        # was repeated; keep the LaTeX command and operands themselves.
        folded = unicodedata.normalize("NFKC", cluster).casefold()
        for output_char in folded:
            if output_char.isspace() or output_char in {"$", "\u200b", "\ufeff"}:
                continue
            normalized.append(output_char)
            source_starts.append(base_offset + index)
            source_ends.append(base_offset + cluster_end)
        index = cluster_end
    return "".join(normalized), source_starts, source_ends


def normalize_question_text(value: str) -> str:
    """Public normalization helper used by matching tests and diagnostics."""
    return _normalized_with_offsets(value)[0]


def _safe_prefix_boundary(text: str, end: int, question_variant: str, matched_length: int) -> bool:
    if end >= len(text):
        return True
    next_char = text[end]
    if next_char.isspace():
        return True
    if matched_length < 12:
        return False
    stripped = question_variant.rstrip()
    if not stripped:
        return False
    terminal = stripped[-1]
    if terminal in "。！？!?；;：:」』）》】":
        # Avoid treating an ASCII period inside a number/identifier as a sentence boundary.
        if terminal == "." and next_char.isascii() and next_char.isalnum():
            return False
        return True
    return False


def remove_question_text(question: Any, answer_text: str) -> tuple[str, dict[str, Any]]:
    """Remove a confidently repeated leading question prompt from an answer.

    Exact normalized prefix matching is preferred. Fuzzy matching is limited to
    long prompts, a small edit window, and a high similarity threshold. The
    original answer is returned unchanged whenever matching is uncertain.
    """
    original = str(answer_text or "")
    base_metadata = {
        "status": "not_removed",
        "method": None,
        "confidence": None,
        "removed_prefix_length": 0,
        "question_id": getattr(question, "id", None),
    }
    candidates: list[tuple[str, str]] = []
    for variant in _question_body_variants(question):
        normalized, _, _ = _normalized_with_offsets(variant)
        if len(normalized) >= 12:
            candidates.append((variant, normalized))
    if not candidates or not original:
        return original, base_metadata

    answer_normalized, _, answer_ends = _normalized_with_offsets(original)
    if not answer_normalized:
        return original, base_metadata

    # Choose the longest exact leading match. This removes a full repeated
    # prompt when both a whole block and one of its sentences match.
    exact = [(variant, normalized) for variant, normalized in candidates
             if answer_normalized.startswith(normalized)]
    if exact:
        variant, normalized = max(exact, key=lambda item: len(item[1]))
        source_end = answer_ends[len(normalized) - 1]
        if _safe_prefix_boundary(original, source_end, variant, len(normalized)):
            while source_end < len(original) and original[source_end].isspace():
                source_end += 1
            metadata = {**base_metadata, "status": "removed", "method": "exact",
                        "confidence": 1.0, "removed_prefix_length": source_end}
            return original[source_end:].lstrip(), metadata

    # Only try approximate alignment for sufficiently long prompts. The
    # candidate window is tightly bounded to prevent large or speculative cuts.
    best: tuple[float, int, str] | None = None
    ambiguous_best = False
    for variant, normalized in candidates:
        length = len(normalized)
        if length < FUZZY_MIN_LENGTH or length > 500 or len(answer_normalized) < FUZZY_MIN_LENGTH:
            continue
        tolerance = max(1, min(8, int(length * 0.02)))
        for window_length in range(max(1, length - tolerance), min(len(answer_normalized), length + tolerance) + 1):
            ratio = SequenceMatcher(None, normalized, answer_normalized[:window_length], autojunk=False).ratio()
            if ratio < FUZZY_MIN_CONFIDENCE:
                continue
            end = answer_ends[window_length - 1]
            if not _safe_prefix_boundary(original, end, variant, length):
                continue
            candidate = (ratio, window_length, variant)
            if best is None:
                best = candidate
            elif ambiguous_best:
                continue
            elif abs(candidate[0] - best[0]) < 0.005 and candidate[1] != best[1]:
                # Equally plausible cuts with different lengths are ambiguous.
                ambiguous_best = True
            elif candidate[0] > best[0] + 0.005 or (
                abs(candidate[0] - best[0]) <= 0.005 and candidate[1] > best[1]
            ):
                best = candidate
    if best and not ambiguous_best and best[0] >= FUZZY_MIN_CONFIDENCE and best[1] > 0:
        confidence, matched_length, _ = best
        source_end = answer_ends[matched_length - 1]
        while source_end < len(original) and original[source_end].isspace():
            source_end += 1
        metadata = {**base_metadata, "status": "removed", "method": "fuzzy",
                    "confidence": round(confidence, 4), "removed_prefix_length": source_end}
        return original[source_end:].lstrip(), metadata

    return original, base_metadata


def _lines_from_ir(
    ir: dict[str, Any],
    allowed_element_ids_by_page: dict[int, set[str] | None] | None = None,
    *, preserve_whitespace: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
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
                element_ranges.append({"element_id": element.get("element_id"), "start": start,
                                       "end": offset, "separator_before": separator})
                previous = element
            raw_line = "".join(text_parts)
            line_text = raw_line if preserve_whitespace else raw_line.strip()
            if line_text:
                # Match the trimmed content to its offset within the original span concatenation.
                raw_line = "".join(text_parts)
                trim_left = 0 if preserve_whitespace else len(raw_line) - len(raw_line.lstrip())
                trim_right = len(raw_line) if preserve_whitespace else len(raw_line.rstrip())
                trimmed_ranges = []
                for item in element_ranges:
                    start = max(item["start"], trim_left)
                    end = min(item["end"], trim_right)
                    if start < end:
                        trimmed_ranges.append({**item, "start": start - trim_left,
                                               "end": end - trim_left})
                page_lines.append({"text": line_text, "element_ranges": trimmed_ranges,
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
            page_index = int(page.get("page_index", 0))
            allowed_ids = (allowed_element_ids_by_page or {}).get(page_index)
            selected_ranges = [item for item in line["element_ranges"]
                               if allowed_ids is None or item["element_id"] in allowed_ids]
            selected_parts = []
            selected_segments = []
            previous_range_index = None
            range_indexes = {id(item): range_index for range_index, item in enumerate(line["element_ranges"])}
            for item in selected_ranges:
                start, end = item["start"], item["end"]
                current_index = range_indexes[id(item)]
                piece = line["text"][start:end]
                if not piece:
                    continue
                separator = ""
                if selected_parts and previous_range_index is not None:
                    if current_index == previous_range_index + 1:
                        separator = item.get("separator_before") or ""
                    else:
                        # If omitted spans sat between selected spans, preserve
                        # only a separator that existed in the native line.
                        gap = line["text"][selected_segments[-1]["end"]:start]
                        if gap and gap.isspace():
                            separator = gap
                        elif selected_segments[-1]["text"][-1:].isascii() and selected_segments[-1]["text"][-1:].isalnum() \
                                and piece[:1].isascii() and piece[:1].isalnum():
                            separator = " "
                selected_parts.append(separator)
                selected_parts.append(piece)
                selected_segments.append({"start": start, "end": end, "text": piece,
                                          "element_id": item["element_id"],
                                          "separator_before": separator})
                previous_range_index = current_index
            visual_text = "".join(selected_parts).strip()
            # Span ids intentionally stay attached even when a heading is trimmed from the answer text.
            lines.append({"text": line["text"], "visual_text": visual_text,
                          "visual_segments": selected_segments,
                          "page_index": page_index, "start": line_start, "end": line_end,
                          "element_ids": element_ids})
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


def build_model_answer_entries(
    ir: dict[str, Any],
    questions: list[Any],
    *,
    allowed_element_ids_by_page: dict[int, set[str] | None] | None = None,
) -> list[dict[str, Any]]:
    """Segment only when a visible question marker uniquely matches the current tree.

    Ambiguous or unmatched marker text remains an unmapped draft for explicit teacher mapping.
    This parser is deterministic, uses no OCR fallback or model calls, and does not create Questions.
    """
    full_text, lines = _lines_from_ir(ir, allowed_element_ids_by_page)
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
        if allowed_element_ids_by_page is not None:
            pieces = []
            segments = []
            for segment in line.get("visual_segments", []):
                start, end = segment["start"], segment["end"]
                if end <= consumed:
                    continue
                start = max(start, consumed)
                piece = line["text"][start:end]
                if not piece:
                    continue
                if pieces:
                    pieces.append(segment.get("separator_before") or "")
                pieces.append(piece)
                segments.append({"page_index": line["page_index"],
                                 "text_start": line["start"] + start,
                                 "text_end": line["start"] + end,
                                 "element_ids": [segment["element_id"]]})
            text = "".join(pieces).strip()
        else:
            text = body.strip()
            segments = []
        if not text:
            return
        if current_target is None:
            return
        current_target["answer_text"] += ("\n" if current_target["answer_text"] else "") + text
        if allowed_element_ids_by_page is not None:
            current_target["source"]["segments"].extend(segments)
        else:
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
        if allowed_element_ids_by_page is None:
            text = full_text.strip()
            source_lines = lines
        else:
            text = "\n".join(line["visual_text"] for line in lines if line["visual_text"]).strip()
            source_lines = [line for line in lines if line["visual_text"]]
        if text:
            entries = [{"id": str(uuid4()), "question_id": None, "mapping_state": "needs_review",
                        "answer_text": text,
                        "source": {"material_id": ir.get("source", {}).get("material_id"),
                                   "source_sha256": ir.get("source", {}).get("sha256"),
                                   "segments": ([{"page_index": line["page_index"],
                                                  "text_start": line["start"] + segment["start"],
                                                  "text_end": line["start"] + segment["end"],
                                                  "element_ids": [segment["element_id"]]}
                                                 for line in source_lines
                                                 for segment in line.get("visual_segments", [])]
                                                if allowed_element_ids_by_page is not None else
                                                [{"page_index": line["page_index"],
                                                  "text_start": line["start"], "text_end": line["end"],
                                                  "element_ids": line["element_ids"]}
                                                 for line in lines])}}]

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

    question_by_id = {question.id: question for question in ordered_questions}
    for entry in combined:
        question = question_by_id.get(entry.get("question_id"))
        if question is None:
            continue
        cleaned, removal = remove_question_text(question, entry["answer_text"])
        entry["answer_text"] = cleaned
        entry["question_text_removal"] = removal

    # Keep a mapped entry whose entire extracted body duplicated its question.
    # The review UI can explain the empty result and the confirm endpoint already
    # rejects empty answers. Do not fall back to the unstripped PDF text here.
    return [entry for entry in combined
            if entry["answer_text"].strip() or entry.get("question_text_removal", {}).get("status") == "removed"]


def draft_view(draft, choices: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": draft.id, "test_id": draft.test_id, "material_id": draft.material_id,
            "source_sha256": draft.source_sha256, "state": draft.state, "revision": draft.revision,
            "entries": draft.snapshot.get("entries", []), "questions": choices,
            "page_count": draft.snapshot.get("page_count", 0),
            "parser": draft.snapshot.get("parser", {}),
            "extraction": draft.snapshot.get("extraction"),
            "pipeline": draft.snapshot.get("pipeline"),
            "created_at": draft.created_at.isoformat()}
