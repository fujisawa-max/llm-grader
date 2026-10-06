"""Pure validation and summaries for teacher-owned review snapshots."""
from copy import deepcopy
import math
import re

from .pdf_native import canonical_hash

SCHEMA = "question-import-review.v1"


class ReviewError(Exception):
    def __init__(self, code, status=409, *, node_key=None, field_key=None):
        self.code, self.status = code, status
        self.node_key, self.field_key = node_key, field_key
        super().__init__(code)


def regions(draft):
    return [{**r, "region_type": kind} for kind in ("formula", "figure")
            for r in draft.get(f"{kind}_regions", [])]


def initial_snapshot(draft_hash, draft, pin):
    nodes = []
    parent_keys = {node.get("parent_key") for node in draft["nodes"] if node.get("parent_key")}
    for n in draft["nodes"]:
        semantics = n["score"]["semantics"]
        points = n["score"]["points"]
        # New review workspaces default structural questions to the explicit
        # child-sum mode. Existing saved revisions are never rewritten here.
        if n["stable_key"] in parent_keys and semantics == "unset" and points is None:
            semantics = "sum_children"
        nodes.append({
            "review_node_id": n["stable_key"], "stable_key": n["stable_key"],
            "source_draft_stable_key": n["stable_key"], "source_draft_node_id": None,
            **{k: deepcopy(n[k]) for k in ("parent_key", "node_type", "depth", "sort_order",
                                          "label", "body_text", "ordered_content", "review_flags")},
            "included": True, "score_semantics": semantics,
            "score_points": points if semantics != "sum_children" else None,
            "effective_points_candidate": n["score"]["effective_points_candidate"],
            "formula_decisions": {}, "figure_decisions": {}, "warning_states": {},
        })
    return {"schema_version": SCHEMA, "source_draft_sha256": draft_hash, "vision_pin": pin,
            "nodes": nodes, "document_context": deepcopy(draft.get("document_context", {})),
            "review_flags": deepcopy(draft.get("review_flags", [])), "warning_states": {},
            "state": "editing", "reviewed": False, "editing_contract": 1}


def warning_catalog(draft, pin):
    warnings = []

    def add(scope, source, flags, owner=None):
        for flag in sorted(set(flags)):
            warnings.append({"id": f"{scope}:{source}:{flag}", "code": flag,
                             "scope": scope, "source_id": source, "owner": owner,
                             "blocking": True})

    add("draft", "document", draft.get("review_flags", []))
    for n in draft["nodes"]:
        add("node", n["stable_key"], n.get("review_flags", []), n["stable_key"])
    pinned = {p["region_id"]: p for p in pin.get("results", [])}
    for r in regions(draft):
        p = pinned.get(r["region_id"], {})
        flags = r.get("review_flags", []) + p.get("review_flags", [])
        add("region", r["region_id"], flags, r.get("assigned_question_key"))
    return warnings


def _text(value, limit=20000):
    # Teacher text is already a decoded Python ``str`` at this boundary.  Keep
    # every character verbatim; JSON encoding belongs to the transport/artifact
    # writer and must never be emulated with a manual backslash transform here.
    if not isinstance(value, str) or len(value) > limit:
        raise ReviewError("invalid_text_length", 422)


def _source_owner(node, by_key):
    """Stable reviewed origin, falling back to the legacy automatic ancestor."""
    seen = set()
    while node is not None and node["stable_key"] not in seen:
        seen.add(node["stable_key"])
        if node.get("source_review_owner") is not None:
            return node["source_review_owner"]
        if node.get("source_draft_stable_key") is not None:
            return node["source_draft_stable_key"]
        node = by_key.get(node.get("parent_key"))
    return None


def _content_evidence(item):
    return {key: value for key, value in item.items()
            if key not in {"type", "order", "text", "merged_source_segments", "source_slice"}}


def _contains_reviewed_formula(text, latex):
    # Markdown inline/display math differ only in presentation. Check the
    # reviewed transcription exactly, allowing delimiter-adjacent whitespace.
    return bool(latex and re.search(r"(?<!\\)\${1,2}\s*" + re.escape(latex) + r"\s*\${1,2}", text))


def _formula_confirmation_resolved(decision):
    """Resolve the teacher confirmation independently from where a formula lives.

    Older revisions used the source decision as their confirmation signal. Keep
    reading those revisions that way, while an explicit status on newer
    revisions takes precedence (notably for a merged but still unreviewed formula).
    """
    if not isinstance(decision, dict):
        return False
    if decision.get("decision") == "excluded":
        return True
    status = decision.get("confirmation_status")
    if status is not None:
        return status == "confirmed"
    return decision.get("decision", "unreviewed") != "unreviewed"


def _validate_content_provenance(nodes, source, by_key):
    # source_slice indexes the immutable OCR text in the original draft, not
    # the teacher-edited Markdown string currently shown in the textarea.
    groups = {key: [] for key in source}
    for node in nodes:
        owner = _source_owner(node, by_key)
        if owner is None:
            for item in node["ordered_content"]:
                if item.get("type") != "text" or set(item) - {"type", "order", "text"}:
                    raise ReviewError("invalid_teacher_content", 422)
        else:
            groups[owner].append(node)
    for owner, members in groups.items():
        original = source[owner]["ordered_content"]
        anchors = [{key: value for key, value in item.items() if key != "order"}
                   for item in original if item.get("type") != "text"]
        present = []
        refs = []
        formula_segments = []
        decisions = {}
        figure_decisions = set()
        for node in members:
            for rid, decision in node.get("formula_decisions", {}).items():
                if rid in decisions:
                    raise ReviewError("duplicate_region_decision", 422)
                decisions[rid] = decision
            for rid in node.get("figure_decisions", {}):
                if rid in figure_decisions:
                    raise ReviewError("duplicate_region_decision", 422)
                figure_decisions.add(rid)
            for item in node["ordered_content"]:
                if item.get("type") != "text":
                    anchor = {key: value for key, value in item.items() if key != "order"}
                    try:
                        anchors.remove(anchor)
                    except ValueError:
                        raise ReviewError("source_anchor_changed", 422, node_key=node["stable_key"], field_key="source_mapping") from None
                    present.append(anchor)
                    continue
                evidence = _content_evidence(item)
                if evidence or "source_slice" in item:
                    refs.append((evidence, item.get("source_slice"), node["stable_key"]))
                segments = item.get("merged_source_segments", [])
                if not isinstance(segments, list) or len(segments) > 2000:
                    raise ReviewError("source_anchor_changed", 422, node_key=node["stable_key"], field_key="source_mapping")
                for segment in segments:
                    if not isinstance(segment, dict) or not segment:
                        raise ReviewError("source_anchor_changed", 422, node_key=node["stable_key"], field_key="source_mapping")
                    if segment.get("type") == "formula_region":
                        formula_segments.append((segment, item["text"], node["stable_key"]))
                    else:
                        refs.append((_content_evidence(segment), segment.get("source_slice"), node["stable_key"]))
        original_text = [item for item in original if item.get("type") == "text"]
        used = [[] for _ in original_text]
        for evidence, source_slice, target_node in refs:
            matches = [index for index, item in enumerate(original_text)
                       if _content_evidence(item) == evidence]
            if len(matches) != 1 or not evidence:
                raise ReviewError("source_anchor_changed", 422, node_key=target_node, field_key="source_mapping")
            index = matches[0]
            if source_slice is None:
                if used[index]:
                    raise ReviewError("source_anchor_changed", 422, node_key=target_node, field_key="source_mapping")
                used[index].append(None)
            else:
                if (not isinstance(source_slice, list) or len(source_slice) != 3 or
                        any(type(value) is not int for value in source_slice)):
                    raise ReviewError("invalid_source_slice", 422, node_key=target_node, field_key="source_mapping")
                start, end, total = source_slice
                if not 0 <= start < end <= total == len(original_text[index]["text"]) or any(
                        old is None or old[2] != total or max(start, old[0]) < min(end, old[1])
                        for old in used[index]):
                    raise ReviewError("invalid_source_slice", 422, node_key=target_node, field_key="source_mapping")
                used[index].append(source_slice)
        for anchor in original:
            if anchor.get("type") != "formula_region":
                continue
            evidence = {key: value for key, value in anchor.items() if key != "order"}
            decision = decisions.get(anchor["region_id"], {})
            state = decision.get("decision") if isinstance(decision, dict) else None
            if evidence in present:
                if state in {"excluded", "merged_into_text"}:
                    raise ReviewError("formula_content_decision_mismatch", 422)
            elif state == "merged_into_text":
                matches = [text for segment, text, _ in formula_segments if segment == evidence]
                latex = decision.get("teacher_transcription", "").strip()
                if len(matches) != 1:
                    target_node = next((node_key for segment, _, node_key in formula_segments if segment == evidence), owner)
                    raise ReviewError("source_anchor_changed", 422, node_key=target_node, field_key="source_mapping")
                if not latex or not _contains_reviewed_formula(matches[0], latex):
                    raise ReviewError("merged_formula_text_missing", 422)
            elif state != "excluded":
                raise ReviewError("formula_content_decision_mismatch", 422)
        if any(anchor.get("type") != "formula_region" for anchor in anchors):
            raise ReviewError("source_anchor_changed", 422, node_key=owner, field_key="source_mapping")
        for segment, _, target_node in formula_segments:
            if not any({key: value for key, value in item.items() if key != "order"} == segment
                       and item.get("type") == "formula_region" for item in original):
                raise ReviewError("source_anchor_changed", 422, node_key=target_node, field_key="source_mapping")


def validate_snapshot(snapshot, current, draft, pin, *, mark=False):
    """Validate teacher data without accepting source/provenance changes from clients."""
    if not isinstance(snapshot, dict):
        raise ReviewError("invalid_snapshot", 422)
    if len(str(snapshot)) > 2_000_000:
        raise ReviewError("snapshot_too_large", 422)
    snap = deepcopy(snapshot)
    editable = {"nodes", "state", "reviewed", "warning_states", "editing_contract"}
    if {k: v for k, v in snap.items() if k not in editable} != {
            k: v for k, v in current.items() if k not in editable}:
        raise ReviewError("immutable_evidence_changed", 422)
    if not isinstance(snap.get("state"), str) or snap["state"] not in {"editing", "reviewed"}:
        raise ReviewError("invalid_review_state", 422)
    if snap.get("reviewed") != (snap["state"] == "reviewed"):
        raise ReviewError("invalid_review_state", 422)
    if snap["state"] == "reviewed" and not mark:
        raise ReviewError("use_mark_reviewed", 422)
    nodes = snap.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 1000:
        raise ReviewError("invalid_nodes", 422)
    source = {n["stable_key"]: n for n in draft["nodes"]}
    previous = {n["stable_key"]: n for n in current["nodes"]}
    by_key, identities, sources, orders = {}, set(), set(), set()
    for n in nodes:
        if not isinstance(n, dict):
            raise ReviewError("invalid_node", 422)
        allowed_fields = {"review_node_id", "stable_key", "source_draft_stable_key", "source_draft_node_id",
                          "parent_key", "node_type", "depth", "sort_order", "label", "body_text",
                          "ordered_content", "included", "score_semantics", "score_points",
                          "effective_points_candidate", "review_flags", "formula_decisions",
                          "figure_decisions", "warning_states", "source_mapping_decision", "math_ocr_edits", "source_review_owner", "diagram_records"}
        if set(n) - allowed_fields:
            raise ReviewError("unknown_node_fields", 422)
        required_fields = allowed_fields - {"effective_points_candidate", "depth", "source_mapping_decision", "math_ocr_edits", "source_review_owner", "diagram_records"}
        if not required_fields.issubset(n):
            raise ReviewError("missing_node_fields", 422)
        key, identity = n.get("stable_key"), n.get("review_node_id")
        if not isinstance(key, str) or not re.fullmatch(r"[\w.-]{1,128}", key):
            raise ReviewError("invalid_node_key", 422)
        if not isinstance(identity, str) or not re.fullmatch(r"[\w.-]{1,128}", identity):
            raise ReviewError("invalid_node_identity", 422)
        if key in by_key or identity in identities:
            raise ReviewError("duplicate_node", 422)
        by_key[key] = n
        identities.add(identity)
        if type(n.get("included")) is not bool:
            raise ReviewError("invalid_included", 422)
        parent, order = n.get("parent_key"), n.get("sort_order")
        if parent is not None and not isinstance(parent, str):
            raise ReviewError("invalid_parent", 422, node_key=key, field_key="parent")
        if type(order) is not int or not 0 <= order <= 10000:
            raise ReviewError("invalid_order", 422)
        if (parent, order) in orders:
            raise ReviewError("duplicate_order", 422)
        orders.add((parent, order))
        if not isinstance(n.get("node_type"), str) or n["node_type"] not in {"major_question", "subquestion"}:
            raise ReviewError("invalid_node_type", 422)
        if (parent is None) != (n["node_type"] == "major_question"):
            raise ReviewError("parent_type_mismatch", 422, node_key=key, field_key="parent")
        label = n.get("label")
        if not isinstance(label, dict) or set(label) != {"raw", "normalized"}:
            raise ReviewError("invalid_label", 422)
        for text in label.values():
            try:
                _text(text, 200)
            except ReviewError as exc:
                raise ReviewError(exc.code, exc.status, node_key=key, field_key="label") from exc
        if n["included"] and not (label["raw"].strip() or label["normalized"].strip()):
            raise ReviewError("label_required", 422, node_key=key, field_key="label")
        _text(n.get("body_text", ""))
        semantics, points = n.get("score_semantics"), n.get("score_points")
        if not isinstance(semantics, str) or semantics not in {"direct", "sum_children", "each_child", "unset", "ambiguous"}:
            raise ReviewError("invalid_score_semantics", 422, node_key=key, field_key="score")
        if points is not None and (type(points) not in (int, float) or
                                   not math.isfinite(points) or points < 0 or points > 1e9):
            raise ReviewError("invalid_score", 422, node_key=key, field_key="score")
        if (semantics in {"unset", "sum_children"} and points is not None or
                semantics in {"direct", "each_child"} and points is None):
            raise ReviewError("score_type_mismatch", 422, node_key=key, field_key="score")
        src = n.get("source_draft_stable_key")
        if src is not None and not isinstance(src, str):
            raise ReviewError("invalid_source_node", 422)
        if key in previous:
            for field in ("review_node_id", "source_draft_stable_key", "source_draft_node_id"):
                if n.get(field) != previous[key].get(field):
                    raise ReviewError("source_identity_changed", 422)
        if src is not None:
            if src not in source or src in sources or key != src or key not in previous:
                raise ReviewError("invalid_source_node", 422)
            sources.add(src)
            baseline = source[src]
            if n.get("review_flags") != baseline["review_flags"]:
                raise ReviewError("source_warning_changed", 422)
        else:
            if n.get("source_draft_node_id") is not None or n.get("review_flags", []):
                raise ReviewError("invalid_teacher_node_source", 422)
        items = n.get("ordered_content")
        if not isinstance(items, list) or len(items) > 2000:
            raise ReviewError("invalid_ordered_content", 422)
        if any(not isinstance(item, dict) for item in items):
            raise ReviewError("invalid_ordered_content", 422)
        prior = previous.get(key, {})
        for i, item in enumerate(items):
            if type(item.get("order")) is not int or (items != prior.get("ordered_content") and item["order"] != i):
                raise ReviewError("invalid_ordered_content", 422, node_key=key, field_key=f"text:{i}" if item.get("type") == "text" else "node")
            if item.get("type") == "text":
                try:
                    _text(item.get("text"))
                except ReviewError as exc:
                    raise ReviewError(exc.code, exc.status, node_key=key, field_key=f"text:{i}") from exc
        # Preserve the historical body field until ordered text is actually edited.
        if items != prior.get("ordered_content"):
            n["body_text"] = "\n".join(i["text"] for i in items if i.get("type") == "text")
        elif key in previous and n["body_text"] != prior["body_text"]:
            raise ReviewError("edit_ordered_text", 422)
        if n.get("warning_states", {}) != prior.get("warning_states", {}):
            raise ReviewError("use_document_warning_states", 422)
    if sources != set(source):
        raise ReviewError("automatic_node_removed", 422)
    for key, n in by_key.items():
        seen, parent = {key}, n.get("parent_key")
        depth = 0
        while parent is not None:
            if parent in seen:
                raise ReviewError("cycle", 422, node_key=key, field_key="parent")
            if parent not in by_key or n["included"] and not by_key[parent]["included"]:
                raise ReviewError("orphan_node", 422, node_key=key, field_key="parent")
            seen.add(parent)
            depth += 1
            parent = by_key[parent].get("parent_key")
        n["depth"] = depth
        if mark and n["included"]:
            has_content = any(i.get("type") != "text" or i.get("text", "").strip()
                              for i in n["ordered_content"])
            has_children = any(c["included"] and c.get("parent_key") == key for c in nodes)
            if not has_content and not has_children:
                raise ReviewError("node_content_required", 422)
            if n["score_semantics"] == "each_child" and not has_children:
                raise ReviewError("each_child_requires_children", 422)
            if n["score_semantics"] == "sum_children" and not has_children:
                raise ReviewError("sum_children_requires_children", 422, node_key=key, field_key="score")
        # The server binds a teacher node to its validated source origin once.
        # Reparenting changes hierarchy, not the immutable PDF ownership chain.
        if n.get("source_draft_stable_key") is None:
            prior = previous.get(key)
            expected_owner = _source_owner(prior, previous) if prior else _source_owner(
                {k: v for k, v in n.items() if k != "source_review_owner"}, by_key)
            if n.get("source_review_owner") not in (None, expected_owner):
                raise ReviewError("source_identity_changed", 422)
            if expected_owner is not None:
                n["source_review_owner"] = expected_owner
        elif n.get("source_review_owner") is not None:
            raise ReviewError("source_identity_changed", 422)
        mapping_decision = n.get("source_mapping_decision")
        if mapping_decision is not None:
            if (not isinstance(mapping_decision, str) or mapping_decision not in
                    {"automatic", "teacher_manual_mapping", "teacher_unmapped_override"}
                    or n.get("source_draft_stable_key") is not None
                    or n.get("node_type") != "subquestion" or n.get("parent_key") is None
                    or _source_owner(n, by_key) is None):
                raise ReviewError("invalid_source_mapping_decision", 422, node_key=key, field_key="source_mapping")
            has_text_mapping = False
            for item in n["ordered_content"]:
                if item.get("type") != "text":
                    continue
                if _content_evidence(item) or "source_slice" in item:
                    has_text_mapping = True
                segments = item.get("merged_source_segments", [])
                if not isinstance(segments, list):
                    raise ReviewError("invalid_source_mapping_decision", 422, node_key=key, field_key="source_mapping")
                for segment in segments:
                    if not isinstance(segment, dict):
                        raise ReviewError("invalid_source_mapping_decision", 422, node_key=key, field_key="source_mapping")
                    if segment.get("type") != "formula_region" and (
                            _content_evidence(segment) or "source_slice" in segment):
                        has_text_mapping = True
            if mapping_decision == "teacher_unmapped_override":
                if has_text_mapping or any(
                        item.get("type") == "text" and any(
                            segment.get("type") != "formula_region"
                            for segment in item.get("merged_source_segments", []) if isinstance(segment, dict))
                        for item in n["ordered_content"]):
                    raise ReviewError("invalid_unmapped_source_decision", 422, node_key=key, field_key="source_mapping")
            elif not has_text_mapping and not any(
                    item.get("type") == "formula_region" or any(
                        segment.get("type") == "formula_region" for segment in item.get("merged_source_segments", []))
                    for item in n["ordered_content"]):
                raise ReviewError("missing_source_mapping_decision", 422, node_key=key, field_key="source_mapping")
    _validate_content_provenance(nodes, source, by_key)
    from .question_math_source import validate_math_edits
    for n in nodes:
        if 'math_ocr_edits' in n:
            validate_math_edits(n['math_ocr_edits'], n, draft, nodes)
    pinned = {p["region_id"]: p for p in pin.get("results", [])}
    for n in nodes:
        for kind, allowed in (("formula", {"unreviewed", "use_native", "use_vision", "teacher_edit",
                                           "excluded", "merged_into_text"}),
                              ("figure", {"unreviewed", "accepted_as_evidence", "needs_correction", "excluded"})):
            decisions = n.get(f"{kind}_decisions", {})
            if not isinstance(decisions, dict):
                raise ReviewError("invalid_decision", 422)
            owner = _source_owner(n, by_key)
            owned = {r["region_id"]: r for r in draft.get(f"{kind}_regions", [])
                     if r.get("assigned_question_key") == owner}
            for rid, d in decisions.items():
                allowed_decision_fields = {"decision", "teacher_transcription", "note", "evidence_identity"}
                if kind == "formula":
                    allowed_decision_fields |= {"confirmation_status", "confirmation_method"}
                if rid not in owned or not isinstance(d, dict) or set(d) - allowed_decision_fields:
                    raise ReviewError("invalid_region_decision", 422)
                decision = d.get("decision")
                if not isinstance(decision, str) or decision not in allowed:
                    raise ReviewError("invalid_decision", 422)
                if kind == "formula":
                    confirmation_status = d.get("confirmation_status")
                    confirmation_method = d.get("confirmation_method")
                    if confirmation_status is not None and confirmation_status not in {"unreviewed", "confirmed"}:
                        raise ReviewError("invalid_formula_confirmation", 422,
                                          node_key=n["stable_key"], field_key=f"formula:{rid}")
                    if confirmation_method is not None and confirmation_method not in {"individual", "bulk"}:
                        raise ReviewError("invalid_formula_confirmation", 422,
                                          node_key=n["stable_key"], field_key=f"formula:{rid}")
                    if confirmation_method is not None and confirmation_status != "confirmed":
                        raise ReviewError("invalid_formula_confirmation", 422,
                                          node_key=n["stable_key"], field_key=f"formula:{rid}")
                _text(d.get("note", ""), 2000)
                _text(d.get("teacher_transcription", ""))
                native = owned[rid].get("text_fragments", [])
                vision = pinned.get(rid, {})
                if decision == "use_native" and not any(x.get("native_text", "").strip() for x in native):
                    raise ReviewError("native_evidence_missing", 422)
                if decision == "use_vision" and not vision.get("has_candidate"):
                    raise ReviewError("vision_evidence_missing", 422)
                if decision == "teacher_edit" and not d.get("teacher_transcription", "").strip():
                    raise ReviewError("teacher_transcription_required", 422, node_key=n["stable_key"], field_key=f"formula:{rid}")
                if decision == "merged_into_text":
                    formula_source = d.get("teacher_transcription", "").strip()
                    if not formula_source or not any(
                            item.get("type") == "text" and _contains_reviewed_formula(item.get("text", ""), formula_source)
                            for item in n["ordered_content"]):
                        raise ReviewError("merged_formula_text_missing", 422)
                identity = {"native_sha256": canonical_hash(owned[rid]),
                            "vision_result_id": vision.get("result_id"),
                            "normalized_sha256": vision.get("normalized_sha256"),
                            "raw_sha256": vision.get("raw_sha256"),
                            "crop_sha256": vision.get("crop_sha256")}
                if d.get("evidence_identity") not in (None, identity):
                    raise ReviewError("decision_evidence_mismatch", 422)
                d["evidence_identity"] = identity
    if mark:
        for kind in ("formula", "figure"):
            for region in draft.get(f"{kind}_regions", []):
                owner = region.get("assigned_question_key")
                if owner not in by_key or not by_key[owner]["included"]:
                    continue
                decisions = [n.get(f"{kind}_decisions", {}).get(region["region_id"], {})
                             for n in nodes if _source_owner(n, by_key) == owner]
                if kind == "formula":
                    if not any(_formula_confirmation_resolved(d) for d in decisions):
                        raise ReviewError("formula_review_required", 422, node_key=owner,
                                          field_key=f"formula:{region['region_id']}")
                elif not any(d.get("decision", "unreviewed") != "unreviewed" for d in decisions):
                    raise ReviewError(f"{kind}_review_required", 422, node_key=owner,
                                      field_key=f"figure:{region['region_id']}")
    catalog = {w["id"]: w for w in warning_catalog(draft, pin)}
    resolutions = snap.get("warning_states", {})
    if not isinstance(resolutions, dict):
        raise ReviewError("invalid_warning_states", 422)
    for wid, resolution in resolutions.items():
        if wid not in catalog or not isinstance(resolution, dict) or set(resolution) - {"state", "note"}:
            raise ReviewError("unknown_warning", 422)
        if not isinstance(resolution.get("state"), str) or resolution["state"] not in {"unreviewed", "acknowledged", "resolved"}:
            raise ReviewError("invalid_warning_state", 422)
        _text(resolution.get("note", ""), 2000)
    if mark:
        for wid, warning in catalog.items():
            owner = warning["owner"]
            active = owner is None or by_key.get(owner, {}).get("included", True)
            if active and resolutions.get(wid, {}).get("state", "unreviewed") == "unreviewed":
                raise ReviewError("warning_acknowledgement_required", 422)
    snap["editing_contract"] = 1
    return snap


def review_summary(snap, draft, pin):
    included = [n for n in snap["nodes"] if n["included"]]
    by_key = {n["stable_key"]: n for n in included}
    all_by_key = {n["stable_key"]: n for n in snap["nodes"]}
    scores = []
    unresolved = 0
    for n in included:
        children = [c for c in included if c["parent_key"] == n["stable_key"]]
        parent = by_key.get(n["parent_key"])
        while parent:
            if parent["score_semantics"] == "direct" and n["score_semantics"] != "unset":
                unresolved += 1  # Parent/child direct points may overlap; do not infer a total.
                break
            parent = by_key.get(parent["parent_key"])
        inherited = by_key.get(n["parent_key"], {}).get("score_semantics") == "each_child"
        if inherited:
            if n["score_semantics"] != "unset":
                unresolved += 1
            continue
        if n["score_semantics"] == "direct":
            if children:
                unresolved += 1
            else:
                scores.append(n["score_points"])
        elif n["score_semantics"] == "sum_children":
            # Child points are already counted at the grading leaves. The
            # structural parent contributes no additional points.
            if not children:
                unresolved += 1
        elif n["score_semantics"] == "each_child" and children:
            # Backward compatibility: the legacy mode assigns this same
            # stored amount to every direct child and skips those children.
            if any(any(grandchild["parent_key"] == child["stable_key"] for grandchild in included)
                   for child in children):
                unresolved += 1
            else:
                scores.append(n["score_points"] * len(children))
        elif n["score_semantics"] == "unset" and children:
            unresolved += 1  # Unset does not mean “use the child scores”.
        elif not children or n["score_semantics"] == "ambiguous":
            unresolved += 1
    result = {"included_questions": len(included), "excluded_questions": len(snap["nodes"]) - len(included),
              "score_unresolved": unresolved, "total_points_candidate": None if unresolved else sum(scores)}
    for kind in ("formula", "figure"):
        decisions = []
        for region in draft.get(f"{kind}_regions", []):
            if region.get("assigned_question_key") not in by_key:
                continue
            values = [n.get(f"{kind}_decisions", {}).get(region["region_id"], {}).get("decision")
                      for n in included if _source_owner(n, all_by_key)
                      == region.get("assigned_question_key")]
            if kind == "formula":
                formula_decisions = [n.get("formula_decisions", {}).get(region["region_id"])
                                     for n in included if _source_owner(n, all_by_key)
                                     == region.get("assigned_question_key")]
                decisions.append("reviewed" if any(_formula_confirmation_resolved(value)
                                                     for value in formula_decisions) else "unreviewed")
            else:
                decisions.append(next((value for value in values if value), "unreviewed"))
        result[f"{kind}_unreviewed"] = decisions.count("unreviewed")
        result[f"{kind}_reviewed"] = len(decisions) - decisions.count("unreviewed")
    result["unresolved_warnings"] = sum(
        snap.get("warning_states", {}).get(w["id"], {}).get("state", "unreviewed") == "unreviewed"
        for w in warning_catalog(draft, pin) if w["owner"] is None or w["owner"] in by_key)
    return result
