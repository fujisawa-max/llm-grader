"""Source-grounded rubric grouping and reconstruction helpers."""

from __future__ import annotations

import hashlib
import re
from typing import Any


RUBRIC_GROUP_KINDS = frozenset({"rubric", "note", "question", "other", "uncertain"})
RUBRIC_GROUP_THRESHOLD = 0.82


class RubricGroupingError(ValueError):
    pass


def explicit_points(text: str) -> tuple[str, int | None, bool]:
    """Extract only explicit point marks; multiple marks are a conflict."""
    matches = list(re.finditer(
        r"[（(【]\s*(\d+)\s*点\s*[）)】]|(?<!\w)(\d+)\s*(?:点|points?)\s*[:：-]\s*|(\d+)\s*点",
        text, flags=re.IGNORECASE))
    values = [int(next(value for value in match.groups() if value is not None)) for match in matches]
    cleaned = text
    for match in reversed(matches):
        cleaned = cleaned[:match.start()] + cleaned[match.end():]
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"[ \t]*\n[ \t]*", "\n", cleaned).strip()
    return cleaned, values[0] if len(values) == 1 else None, len(values) > 1


def validate_rubric_groups(raw: Any, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != {"groups"} or not isinstance(raw["groups"], list):
        raise RubricGroupingError("malformed rubric grouping result")
    expected = {item["id"] for item in segments}
    seen: set[str] = set()
    groups = []
    for index, item in enumerate(raw["groups"], 1):
        if not isinstance(item, dict) or set(item) != {"group_id", "segment_ids", "kind", "confidence"}:
            raise RubricGroupingError("invalid rubric grouping fields")
        group_id, ids, kind, confidence = item["group_id"], item["segment_ids"], item["kind"], item["confidence"]
        if (not isinstance(group_id, str) or not group_id or not isinstance(ids, list) or not ids
                or kind not in RUBRIC_GROUP_KINDS or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            raise RubricGroupingError("invalid rubric group")
        if len(ids) != len(set(ids)) or any(segment_id not in expected or segment_id in seen for segment_id in ids):
            raise RubricGroupingError("unknown or duplicate rubric segment ID")
        seen.update(ids)
        groups.append({"group_id": group_id, "segment_ids": ids, "kind": kind,
                       "confidence": float(confidence), "source_order": index})
    if seen != expected:
        raise RubricGroupingError("rubric grouping omitted source segments")
    positions = {item["id"]: index for index, item in enumerate(segments)}
    for group in groups:
        group["segment_ids"] = sorted(group["segment_ids"], key=positions.__getitem__)
    return groups


def reconstruct_rubric_groups(segments: list[dict[str, Any]], groups: list[dict[str, Any]], *, method="llm_group"):
    """Construct candidate text from original spans, never from model prose."""
    by_id = {item["id"]: item for item in segments}
    result = []
    for group in groups:
        ordered = [by_id[segment_id] for segment_id in group["segment_ids"]]
        raw_text = "".join(str(item.get("source_text", item.get("text", ""))) for item in ordered)
        description, points, conflict = explicit_points(raw_text)
        original = [{key: item.get(key) for key in ("id", "page_index", "bbox", "start", "end", "source_text", "text")}
                    for item in ordered]
        stable = hashlib.sha256("\0".join(group["segment_ids"]).encode()).hexdigest()[:16]
        result.append({
            "id": f"rubric-{stable}", "group_id": group["group_id"],
            "segment_ids": group["segment_ids"], "kind": group["kind"],
            "description": description if group["kind"] == "rubric" else raw_text.strip(),
            "source_text": raw_text, "points": points or 0,
            "points_conflict": conflict, "confidence": group["confidence"],
            "needs_teacher_review": (group["confidence"] < RUBRIC_GROUP_THRESHOLD or conflict),
            "merge_type": method, "source_segments": original,
        })
    return result


def mechanical_rubric_groups(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservative geometry-aware fallback grouping for obvious wrapped lines."""
    premerged = mechanically_premerge_rubric_segments(segments)
    return [{"group_id": f"fallback-{item['id']}", "segment_ids": item.get("member_ids", [item["id"]]),
             "kind": "rubric", "confidence": 0.0, "source_order": index}
            for index, item in enumerate(premerged, 1)]


def mechanically_premerge_rubric_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join only same-page, nearby, aligned lines with clear continuation cues."""
    ordered = sorted(segments, key=lambda item: (item.get("page_index", 0), item.get("start", 0), item.get("id", "")))
    groups: list[list[dict[str, Any]]] = []
    for segment in ordered:
        previous = groups[-1][-1] if groups else None
        can_join = False
        if previous is not None and previous.get("page_index") == segment.get("page_index"):
            left, right = previous.get("bbox"), segment.get("bbox")
            if isinstance(left, list) and isinstance(right, list) and len(left) == len(right) == 4:
                height = max(1.0, left[3] - left[1], right[3] - right[1])
                vertical_gap = right[1] - left[3]
                aligned = abs(left[0] - right[0]) <= 24
                before = str(previous.get("source_text", previous.get("text", ""))).rstrip()
                after = str(segment.get("source_text", segment.get("text", ""))).lstrip()
                starts_new = bool(re.match(r"(?:[-・●▪]|[（(]?\d+[)）.．])\s*", after))
                unfinished = bool(before) and not re.search(r"[。.!?！？:：;；]$", before)
                can_join = aligned and -3 <= vertical_gap <= max(14, height * 0.8) and unfinished and not starts_new
        if can_join:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue
        ids = [item["id"] for item in group]
        stable = hashlib.sha256("\0".join(ids).encode()).hexdigest()[:16]
        result.append({"id": f"premerge-{stable}", "text": "".join(item.get("text", "") for item in group),
                       "source_text": "".join(item.get("source_text", item.get("text", "")) for item in group),
                       "member_ids": ids, "page_index": group[0].get("page_index"),
                       "bbox": [min(item["bbox"][0] for item in group if item.get("bbox")),
                                min(item["bbox"][1] for item in group if item.get("bbox")),
                                max(item["bbox"][2] for item in group if item.get("bbox")),
                                max(item["bbox"][3] for item in group if item.get("bbox"))]})
    return result
