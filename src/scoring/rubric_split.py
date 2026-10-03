"""Validated range-only rubric split proposals; no model prose is accepted."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from .rubric_consolidation import explicit_points

POINT_PATTERN = re.compile(r"(?:[（(【]\s*)?\d+\s*(?:点|points?)(?:\s*[）)】])?", re.IGNORECASE)
REASONS = {"independent_criteria", "repeated_point_markers", "separate_evaluation_targets", "semantic_boundary", "uncertain", "single_criterion"}


def validate_split(raw: Any, candidate_id: str, text: str) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"candidate_id", "split", "confidence", "reason", "parts"}:
        raise ValueError("invalid split fields")
    confidence = raw["confidence"]
    if (raw["candidate_id"] != candidate_id or type(raw["split"]) is not bool
            or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0 <= confidence <= 1 or raw["reason"] not in REASONS
            or not isinstance(raw["parts"], list)):
        raise ValueError("invalid split proposal")
    parts = raw["parts"]
    if not raw["split"]:
        if parts:
            raise ValueError("unsplit proposal must have no ranges")
        return raw
    if not 2 <= len(parts) <= 20:
        raise ValueError("split needs two or more parts")
    cursor = 0
    for part in parts:
        if (not isinstance(part, dict) or set(part) != {"start", "end"}
                or type(part["start"]) is not int or type(part["end"]) is not int
                or part["start"] != cursor or not part["start"] < part["end"] <= len(text)
                or not text[part["start"]:part["end"]].strip()):
            raise ValueError("overlap, gap, empty or out-of-range split")
        cursor = part["end"]
    if cursor != len(text):
        raise ValueError("split omitted source text")
    return raw


def reconstruct_split(raw: dict, candidate_id: str, text: str) -> dict:
    validated = validate_split(raw, candidate_id, text)
    markers = list(POINT_PATTERN.finditer(text))
    # A sole total cannot safely be allocated to a selected part.
    ambiguous = len(markers) == 1 or any(
        part["start"] < mark.start() < part["end"] < mark.end()
        or mark.start() < part["start"] < mark.end()
        for part in raw["parts"] for mark in markers)
    parts = []
    for part in validated["parts"]:
        source = text[part["start"]:part["end"]]
        description, points, conflict = explicit_points(source)
        parts.append({**part, "source_text": source, "description": description,
                      "points": 0 if ambiguous else points or 0,
                      "points_conflict": ambiguous or conflict or points is None})
    return {**validated, "parts": parts,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
