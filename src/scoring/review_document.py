"""Pure validation and summaries for teacher-owned review snapshots."""
from copy import deepcopy
import math
import re

from .pdf_native import canonical_hash

SCHEMA = "question-import-review.v1"


class ReviewError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def regions(draft):
    return [{**r, "region_type": kind} for kind in ("formula", "figure")
            for r in draft.get(f"{kind}_regions", [])]


def initial_snapshot(draft_hash, draft, pin):
    nodes = []
    for n in draft["nodes"]:
        nodes.append({
            "review_node_id": n["stable_key"], "stable_key": n["stable_key"],
            "source_draft_stable_key": n["stable_key"], "source_draft_node_id": None,
            **{k: deepcopy(n[k]) for k in ("parent_key", "node_type", "depth", "sort_order",
                                          "label", "body_text", "ordered_content", "review_flags")},
            "included": True, "score_semantics": n["score"]["semantics"],
            "score_points": n["score"]["points"],
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
                          "figure_decisions", "warning_states"}
        if set(n) - allowed_fields:
            raise ReviewError("unknown_node_fields", 422)
        required_fields = allowed_fields - {"effective_points_candidate", "depth"}
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
            raise ReviewError("invalid_parent", 422)
        if type(order) is not int or not 0 <= order <= 10000:
            raise ReviewError("invalid_order", 422)
        if (parent, order) in orders:
            raise ReviewError("duplicate_order", 422)
        orders.add((parent, order))
        if not isinstance(n.get("node_type"), str) or n["node_type"] not in {"major_question", "subquestion"}:
            raise ReviewError("invalid_node_type", 422)
        if (parent is None) != (n["node_type"] == "major_question"):
            raise ReviewError("parent_type_mismatch", 422)
        label = n.get("label")
        if not isinstance(label, dict) or set(label) != {"raw", "normalized"}:
            raise ReviewError("invalid_label", 422)
        for text in label.values():
            _text(text, 200)
        if n["included"] and not (label["raw"].strip() or label["normalized"].strip()):
            raise ReviewError("label_required", 422)
        _text(n.get("body_text", ""))
        semantics, points = n.get("score_semantics"), n.get("score_points")
        if not isinstance(semantics, str) or semantics not in {"direct", "each_child", "unset", "ambiguous"}:
            raise ReviewError("invalid_score_semantics", 422)
        if points is not None and (type(points) not in (int, float) or
                                   not math.isfinite(points) or points < 0 or points > 1e9):
            raise ReviewError("invalid_score", 422)
        if (semantics == "unset" and points is not None or
                semantics in {"direct", "each_child"} and points is None):
            raise ReviewError("score_type_mismatch", 422)
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
            original = baseline["ordered_content"]
        else:
            if n.get("source_draft_node_id") is not None or n.get("review_flags", []):
                raise ReviewError("invalid_teacher_node_source", 422)
            original = None
        items = n.get("ordered_content")
        if not isinstance(items, list) or len(items) > 2000:
            raise ReviewError("invalid_ordered_content", 422)
        if original is not None and len(items) != len(original):
            raise ReviewError("source_anchor_changed", 422)
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ReviewError("invalid_ordered_content", 422)
            if original is not None:
                old = original[i]
                ignored = {"text"} if old["type"] == "text" else set()
                if {k: v for k, v in item.items() if k not in ignored} != {
                        k: v for k, v in old.items() if k not in ignored}:
                    raise ReviewError("source_anchor_changed", 422)
            elif item.get("type") != "text" or set(item) - {"type", "order", "text"}:
                raise ReviewError("invalid_teacher_content", 422)
            if item.get("type") == "text":
                _text(item.get("text"))
        # Preserve the historical body field until ordered text is actually edited.
        prior = previous.get(key, {})
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
                raise ReviewError("cycle", 422)
            if parent not in by_key or n["included"] and not by_key[parent]["included"]:
                raise ReviewError("orphan_node", 422)
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
    pinned = {p["region_id"]: p for p in pin.get("results", [])}
    for n in nodes:
        for kind, allowed in (("formula", {"unreviewed", "use_native", "use_vision", "teacher_edit"}),
                              ("figure", {"unreviewed", "accepted_as_evidence", "needs_correction"})):
            decisions = n.get(f"{kind}_decisions", {})
            if not isinstance(decisions, dict):
                raise ReviewError("invalid_decision", 422)
            owned = {r["region_id"]: r for r in draft.get(f"{kind}_regions", [])
                     if r.get("assigned_question_key") == n.get("source_draft_stable_key")}
            for rid, d in decisions.items():
                if rid not in owned or not isinstance(d, dict) or set(d) - {
                        "decision", "teacher_transcription", "note", "evidence_identity"}:
                    raise ReviewError("invalid_region_decision", 422)
                decision = d.get("decision")
                if not isinstance(decision, str) or decision not in allowed:
                    raise ReviewError("invalid_decision", 422)
                _text(d.get("note", ""), 2000)
                _text(d.get("teacher_transcription", ""))
                native = owned[rid].get("text_fragments", [])
                vision = pinned.get(rid, {})
                if decision == "use_native" and not any(x.get("native_text", "").strip() for x in native):
                    raise ReviewError("native_evidence_missing", 422)
                if decision == "use_vision" and not vision.get("has_candidate"):
                    raise ReviewError("vision_evidence_missing", 422)
                if decision == "teacher_edit" and not d.get("teacher_transcription", "").strip():
                    raise ReviewError("teacher_transcription_required", 422)
                identity = {"native_sha256": canonical_hash(owned[rid]),
                            "vision_result_id": vision.get("result_id"),
                            "normalized_sha256": vision.get("normalized_sha256"),
                            "raw_sha256": vision.get("raw_sha256"),
                            "crop_sha256": vision.get("crop_sha256")}
                if d.get("evidence_identity") not in (None, identity):
                    raise ReviewError("decision_evidence_mismatch", 422)
                d["evidence_identity"] = identity
            if mark and n["included"]:
                for rid in owned:
                    if decisions.get(rid, {}).get("decision", "unreviewed") == "unreviewed":
                        raise ReviewError(f"{kind}_review_required", 422)
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
            scores.append(n["score_points"])
        elif n["score_semantics"] == "each_child" and children:
            scores.append(n["score_points"] * len(children))
        elif not children or n["score_semantics"] == "ambiguous":
            unresolved += 1
    result = {"included_questions": len(included), "excluded_questions": len(snap["nodes"]) - len(included),
              "score_unresolved": unresolved, "total_points_candidate": None if unresolved else sum(scores)}
    for kind in ("formula", "figure"):
        decisions = [n.get(f"{kind}_decisions", {}).get(r["region_id"], {}).get("decision", "unreviewed")
                     for n in included for r in draft.get(f"{kind}_regions", [])
                     if r.get("assigned_question_key") == n.get("source_draft_stable_key")]
        result[f"{kind}_unreviewed"] = decisions.count("unreviewed")
        result[f"{kind}_reviewed"] = len(decisions) - decisions.count("unreviewed")
    result["unresolved_warnings"] = sum(
        snap.get("warning_states", {}).get(w["id"], {}).get("state", "unreviewed") == "unreviewed"
        for w in warning_catalog(draft, pin) if w["owner"] is None or w["owner"] in by_key)
    return result
