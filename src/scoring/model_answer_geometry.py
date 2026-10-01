"""Spatial assignment of immutable native PDF lines to the existing question tree.

No assignment is inherited from the last text match. Each line is independently
checked against heading regions. Missing/competing evidence remains unassigned.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from typing import Any
from uuid import uuid4

from .model_answer_drafts import (
    _lines_from_ir, _marker, _normalized_label, _question_tokens, normalize_question_text, remove_question_text,
)

PIPELINE_VERSION = "geometry-semantic.v1"


def native_segments(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep original line text, point coordinates and native span references."""
    _, lines = _lines_from_ir(ir, preserve_whitespace=True)
    pages = {int(p["page_index"]): p for p in ir.get("pages", [])}
    elements = {e["element_id"]: e for p in pages.values() for e in p.get("elements", [])}
    result = []
    for order, line in enumerate(lines):
        boxes = [elements[e].get("bbox") for e in line["element_ids"] if e in elements]
        boxes = [b for b in boxes if b and len(b) == 4]
        box = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None)
        text = line["text"]
        identity = f'{ir.get("source", {}).get("sha256")}:{line["page_index"]}:{line["element_ids"]}:{text}'
        page = pages[line["page_index"]]
        width, height = page.get("width", 0), page.get("height", 0)
        center = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] if box else None
        result.append({
            "id": "pdf-" + sha256(identity.encode()).hexdigest()[:24],
            "original_text": text, "text": text, "text_sha256": sha256(text.encode()).hexdigest(),
            "page_index": line["page_index"], "bbox": box, "center": center,
            "relative_position": [center[0] / width, center[1] / height] if center and width and height else None,
            "reading_order": order, "text_start": line["start"], "text_end": line["end"],
            "element_ids": line["element_ids"],
            "source_spans": [{"element_id": e, "text": elements[e].get("native_text"),
                              "bbox": elements[e].get("bbox")}
                             for e in line["element_ids"] if e in elements],
        })
    return result


def _heading_anchors(segments, questions):
    children = defaultdict(list)
    by_id = {q.id: q for q in questions}
    for q in questions:
        children[q.parent_id].append(q)

    def unique(token, siblings):
        hits = [q for q in siblings if _normalized_label(token) in _question_tokens(q)]
        return hits[0] if len(hits) == 1 else None

    anchors = []
    current_parent = None
    for segment in segments:
        marker = _marker(segment["original_text"])
        if not marker or not segment["bbox"]:
            continue
        kind, number, _, _ = marker
        question = None
        if kind in {"root", "path"}:
            pieces = number.replace("-", ".").split(".")
            question = unique(pieces[0], children[None])
            for piece in pieces[1:]:
                question = unique(piece, children[question.id]) if question else None
            current_parent = question.id if question else None
        elif kind in {"child", "numbered"}:
            # Search the active ancestor chain, never another root's children.
            parent = by_id.get(current_parent)
            while parent and not question:
                question = unique(number, children[parent.id])
                parent = by_id.get(parent.parent_id)
            if question:
                current_parent = question.id
        if question:
            anchors.append({"question_id": question.id, "page_index": segment["page_index"],
                            "bbox": segment["bbox"], "heading": segment["original_text"],
                            "origin": "native_heading"})
    return anchors


def _depth(question_id, by_id):
    seen = set()
    while question_id in by_id and question_id not in seen:
        seen.add(question_id)
        question_id = by_id[question_id].parent_id
    return len(seen)


def question_regions(ir, questions, *, question_ir=None):
    """Heading → next sibling boundary, clipped recursively to parent regions.

    Matching problem-PDF geometry is preferred. Native answer headings are the
    fallback; incompatible page geometry is never silently scaled.
    """
    pages = {int(p["page_index"]): p for p in ir.get("pages", [])}
    answer_anchors = _heading_anchors(native_segments(ir), questions)
    anchors = answer_anchors
    if question_ir:
        problem_pages = {int(p["page_index"]): p for p in question_ir.get("pages", [])}
        compatible = {i for i, p in pages.items() if i in problem_pages
                      and abs(p.get("width", 0) - problem_pages[i].get("width", 0)) < 2
                      and abs(p.get("height", 0) - problem_pages[i].get("height", 0)) < 2
                      and p.get("rotation", 0) == problem_pages[i].get("rotation", 0)}
        problem_anchors = [{**a, "origin": "question_pdf_heading"}
                           for a in _heading_anchors(native_segments(question_ir), questions)
                           if a["page_index"] in compatible]
        covered = {(a["question_id"], a["page_index"]) for a in problem_anchors}
        anchors = problem_anchors + [a for a in answer_anchors
                                     if (a["question_id"], a["page_index"]) not in covered]
        # Review content may retain source element references even after text edits.
        # Only resolve exact IDs against the same question PDF; never text-guess offsets.
        problem_elements = {e["element_id"]: (i, e) for i, p in problem_pages.items()
                            for e in p.get("elements", [])}
        for q in questions:
            if any(a["question_id"] == q.id for a in anchors):
                continue
            refs = set()

            def collect(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in {"source_element_ids", "element_ids"} and isinstance(item, list):
                            refs.update(x for x in item if isinstance(x, str))
                        elif key in {"source_element_id", "element_id"} and isinstance(item, str):
                            refs.add(item)
                        else:
                            collect(item)
                elif isinstance(value, list):
                    for item in value:
                        collect(item)
            collect(getattr(q, "content", None))
            hits = [(i, e) for key, (i, e) in problem_elements.items()
                    if key in refs and i in compatible and e.get("bbox")]
            if hits:
                i, e = min(hits, key=lambda hit: (hit[0], hit[1]["bbox"][1], hit[1]["bbox"][0]))
                anchors.append({"question_id": q.id, "page_index": i, "bbox": e["bbox"],
                                "heading": q.display_label, "origin": "question_source_element"})
    by_id = {q.id: q for q in questions}
    barriers = [s for s in native_segments(question_ir or ir)
                if s["bbox"] and (marker := _marker(s["original_text"])) and marker[0] == "root"
                and not any(a["page_index"] == s["page_index"] and a["bbox"] == s["bbox"] for a in anchors)]
    regions = []
    for anchor in sorted(anchors, key=lambda a: _depth(a["question_id"], by_id)):
        q = by_id[anchor["question_id"]]
        box, page = anchor["bbox"], pages[anchor["page_index"]]
        # Horizontal lanes separate headings in clearly distinct columns.
        siblings = [a for a in anchors if a is not anchor
                    and by_id[a["question_id"]].parent_id == q.parent_id
                    and a["page_index"] == anchor["page_index"]]
        right_columns = [a["bbox"][0] for a in siblings if a["bbox"][0] > box[2] + 20]
        lane_right = min(right_columns) if right_columns else page.get("width", 0)
        lane_left = box[0] - 20
        next_headings = [a for a in siblings if a["bbox"][1] > box[1] + 1
                         and abs(a["bbox"][0] - box[0]) < 40]
        bottom = min((a["bbox"][1] for a in next_headings), default=page.get("height", 0))
        unknown_boundaries = [s["bbox"][1] for s in barriers
                              if s["page_index"] == anchor["page_index"]
                              and s["bbox"][1] > box[1] and abs(s["bbox"][0] - box[0]) < 40]
        bottom = min([bottom, *unknown_boundaries])
        parent_regions = [r for r in regions if r["question_id"] == q.parent_id
                          and r["page_index"] == anchor["page_index"]
                          and r["top"] <= box[1] < r["bottom"]]
        if q.parent_id:
            if len(parent_regions) != 1:
                continue
            parent = parent_regions[0]
            bottom = min(bottom, parent["bottom"])
            lane_left, lane_right = max(lane_left, parent["left"]), min(lane_right, parent["right"])
        regions.append({**anchor, "top": box[1], "bottom": bottom,
                        "left": lane_left, "right": lane_right,
                        "parent_id": q.parent_id, "depth": _depth(q.id, by_id),
                        "evidence": "見出しから次の同階層見出し（または親領域・ページ末尾）まで"})
    return regions


def map_segments(ir, questions, *, question_ir=None, allowed_element_ids_by_page=None):
    segments = native_segments(ir)
    regions = question_regions(ir, questions, question_ir=question_ir)
    by_id = {q.id: q for q in questions}
    for segment in segments:
        box = segment["bbox"]
        hits = [r for r in regions if box and r["page_index"] == segment["page_index"]
                and r["top"] <= segment["center"][1] < r["bottom"]
                and box[2] > r["left"] and box[0] < r["right"]]
        if hits:
            deepest = max(r["depth"] for r in hits)
            hits = [r for r in hits if r["depth"] == deepest]
        region = hits[0] if len(hits) == 1 else None
        # An open previous page alone is insufficient proof of continuation.
        # Explicit repeated headings/source anchors create the next page region.
        status = "automatic" if region else "ambiguous" if hits else "unassigned"
        question = by_id.get(region["question_id"]) if region else None
        normalized = normalize_question_text(segment["original_text"])
        body = normalize_question_text(getattr(question, "question_text", None) or "")
        segment["question_text_match"] = bool(question and len(normalized) >= 12 and normalized in body)
        allowed = (allowed_element_ids_by_page or {}).get(segment["page_index"])
        segment["visual_difference"] = {
            "available": allowed is not None,
            "added": any(e in allowed for e in segment["element_ids"]) if allowed is not None else None,
        }
        segment["geometry"] = {
            "question_id": question.id if question else None,
            "assignment_status": status if not question or question.is_gradable else "parent_only",
            "confidence": 0.95 if region else 0.0,
            "evidence": region["evidence"] if region else "所属領域を一意に特定できません",
            "region": region, "parent_id": question.parent_id if question else None,
        }
    return segments, regions


def build_geometry_entries(ir, questions, *, question_ir=None, allowed_element_ids_by_page=None):
    segments, regions = map_segments(ir, questions, question_ir=question_ir,
                                     allowed_element_ids_by_page=allowed_element_ids_by_page)
    by_id = {q.id: q for q in questions}
    grouped = {}
    for segment in segments:
        geometry = segment["geometry"]
        qid = geometry["question_id"]
        target = qid if qid in by_id and by_id[qid].is_gradable else None
        # Preserve separate unmapped regions; never attach to the last mapped question.
        key = target or (qid, segment["page_index"], geometry["assignment_status"])
        grouped.setdefault(key, []).append(segment)
    entries = []
    for values in grouped.values():
        qid = values[0]["geometry"]["question_id"]
        question = by_id.get(qid)
        target = qid if question and question.is_gradable else None
        text = "\n".join(s["original_text"] for s in values)
        # Mechanical fallback uses the same geometry assignment but keeps 8a/8b.
        selected = [s for s in values if s["visual_difference"]["added"] is not False]
        fallback = "\n".join(s["original_text"] for s in selected)
        if question:
            fallback, removal = remove_question_text(question, fallback)
        else:
            removal = {"status": "not_removed"}
        # Label stripping belongs only to fallback; classifier sees the untouched source.
        marker = _marker(fallback.split("\n", 1)[0]) if fallback else None
        if marker and target:
            first, *rest = fallback.split("\n")
            fallback = "\n".join([marker[2], *rest]).strip()
        # A non-gradable parent heading with no answer is context, not a saved answer.
        if not target and qid and all(_marker(s["original_text"]) for s in values):
            continue
        entries.append({"id": str(uuid4()), "question_id": target,
                        "mapping_state": "automatic" if target else "needs_review",
                        "answer_text": fallback, "candidate_text": text,
                        "question_text_removal": removal,
                        "geometry": values[0]["geometry"],
                        "source": {**ir.get("source", {}), "source_sha256": ir.get("source", {}).get("sha256"),
                                   "segments": values}})
    return entries, regions
