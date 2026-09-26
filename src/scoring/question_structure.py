"""Deterministic, candidate-only interpretation of Document IR. No PDF access."""
from copy import deepcopy
import re
import unicodedata

from .pdf_native import canonical_hash

DRAFT_SCHEMA = "question-import-draft.v1"
PARSER_VERSION = "question-structure-v1.2.1"
DEFAULT_CONFIG = {
    "line_overlap": 0.45, "baseline_tolerance": 0.25,
    "major_pattern": r"^(?:問題\s*(\d+)|問\s*(\d+)|第\s*(\d+)\s*問)(?=\s|$)",
    "sub_pattern": r"^\s*\((\d+)\)",
    "inline_pattern": r"\(\d+\)",
    "score_pattern": r"\(\s*(各\s*)?(\d+(?:\.\d+)?)\s*点\s*\)",
    "formula_gap": 10.0, "formula_vertical_gap": 4.0,
    "figure_min_area_ratio": 0.01, "figure_min_side": 25.0,
    "figure_adjacency": 3.0, "column_gap": 90.0,
    "footer_ratio": 0.96,
    "ordered_content_version": "ordered-content-v1",
    "routing_evidence_version": "routing-evidence-v1",
}


def normalize(text):
    return unicodedata.normalize("NFKC", text)


def coordinate_contract(ir):
    """Return the explicit render contract while accepting older IR v1 data."""
    value = deepcopy(ir.get("coordinate_space") or {})
    value.setdefault("id", "pdf-point-unrotated-page")
    value.setdefault("unit", "PDF_point")
    value.setdefault("origin", "top_left")
    value.setdefault("axis", "x_right_y_down")
    value.setdefault("bbox_space", "mediabox_unrotated")
    value.setdefault("rotation", "page_rotation_degrees")
    value.setdefault("rotation_direction", "clockwise_for_rendered_view")
    value.setdefault("rendered_view", "cropbox_then_rotation")
    return value


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def gap(a, b, axis):
    return max(0, max(a[axis], b[axis]) - min(a[axis + 2], b[axis + 2]))


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def clusters(elements, connected):
    """Connected components with stable source-ID tie breaking."""
    pending = sorted(elements, key=lambda e: e["element_id"])
    result = []
    while pending:
        component = [pending.pop(0)]
        i = 0
        while i < len(component):
            rest = []
            for e in pending:
                if connected(component[i], e):
                    component.append(e)
                else:
                    rest.append(e)
            pending = rest
            i += 1
        result.append(component)
    return result


def _content_item(item_type, *, text=None, region_id=None, line=None, region=None,
                  source_element_ids=None):
    """Build a backend-neutral source anchor for review consumers."""
    source = line or region or {}
    ids = list(source_element_ids if source_element_ids is not None
               else source.get("source_element_ids", []))
    return {
        "type": item_type,
        "text": text,
        "region_id": region_id,
        "page_index": source.get("page_index"),
        "bbox": source.get("bbox"),
        "source_element_ids": ids,
        "geometric_order": source.get("geometric_order"),
        "native_orders": list(source.get("native_orders", [])),
        "coordinate_space_ref": "source_ir.coordinate_space",
    }


def _region_routing_evidence(group):
    """Aggregate native reasons without asserting mathematical semantics."""
    counts = {"math_font_span_count": 0, "math_text_span_count": 0,
              "math_like_span_count": 0, "superscript_geometry_count": 0,
              "subscript_geometry_count": 0}
    for element in group:
        signals = element.get("quality_signals", {})
        for key, value in signals.items():
            if key == "math_font_candidate" and value:
                counts["math_font_span_count"] += 1
            elif key == "math_text_candidate" and value:
                counts["math_text_span_count"] += 1
            elif key == "math_like_candidate" and value:
                counts["math_like_span_count"] += 1
            elif key == "superscript_candidate" and value:
                counts["superscript_geometry_count"] += 1
            elif key == "subscript_candidate" and value:
                counts["subscript_geometry_count"] += 1
    reasons = []
    if counts["math_font_span_count"]:
        reasons.append("math_font")
    if counts["math_text_span_count"]:
        reasons.append("math_text")
    if counts["superscript_geometry_count"]:
        reasons.append("superscript_geometry")
    if counts["subscript_geometry_count"]:
        reasons.append("subscript_geometry")
    if counts["math_like_span_count"]:
        reasons.append("math_like")
    if counts["math_font_span_count"] and (counts["math_text_span_count"] or len(group) > 1):
        strength = "strong"
    elif counts["math_text_span_count"] or len(group) > 1:
        strength = "supporting"
    else:
        strength = "weak"
    return {**counts, "source_span_count": len(group), "reasons": reasons,
            "strength": strength,
            "semantic_assertion": "none"}


class LayoutProjector:
    def __init__(self, config):
        self.config = config

    def project(self, ir):
        lines, unassigned = [], []
        for page in sorted(ir["pages"], key=lambda p: p["page_index"]):
            groups = []
            for e in sorted(page["elements"], key=lambda e: (
                    -float(e.get("native", {}).get("font_size") or 0),
                    (e.get("bbox") or [0, 0, 0, 0])[1],
                    (e.get("bbox") or [0, 0, 0, 0])[0], e["element_id"])):
                if e["type"] != "text" or not (e.get("normalized_text") or "").strip():
                    continue
                if not e.get("bbox"):
                    unassigned.append({"page_index": page["page_index"], "element_id": e["element_id"],
                                       "review_flags": ["unassigned_content"]})
                    continue
                b = e["bbox"]
                candidates = []
                for i, group in enumerate(groups):
                    anchor = group[0]["bbox"]
                    overlap = min(b[3], anchor[3]) - max(b[1], anchor[1])
                    height = max(1, min(b[3]-b[1], anchor[3]-anchor[1]))
                    size = float(e.get("native", {}).get("font_size") or height)
                    if overlap / height >= self.config["line_overlap"] or abs(b[3]-anchor[3]) <= size*self.config["baseline_tolerance"]:
                        candidates.append((abs((b[1]+b[3])-(anchor[1]+anchor[3])), i))
                if candidates:
                    groups[min(candidates)[1]].append(e)
                else:
                    groups.append([e])
            groups.sort(key=lambda g: (union([e["bbox"] for e in g])[1], union([e["bbox"] for e in g])[0]))
            for group in groups:
                group.sort(key=lambda e: (e["bbox"][0], e["bbox"][1], e["element_id"]))
                flags = []
                if any(gap(a["bbox"], b["bbox"], 0) > self.config["column_gap"] for a, b in zip(group, group[1:])):
                    flags.append("ambiguous_geometric_order")
                lines.append({"line_id": f"line-{len(lines):05d}", "page_index": page["page_index"],
                              "geometric_order": len(lines), "bbox": union([e["bbox"] for e in group]),
                              "text": " ".join(e["normalized_text"] for e in group),
                              "source_element_ids": [e["element_id"] for e in group],
                              "native_orders": [e.get("reading_order") for e in group],
                              "fragments": [{"element_id": e["element_id"], "bbox": e["bbox"],
                                             "native_order": e.get("reading_order"), "text": e["native_text"],
                                             "font": e.get("native", {}).get("font"),
                                             "math_evidence": e.get("quality_signals", {})} for e in group],
                              "review_flags": flags})
        return {"schema_version": "question-layout-projection.v1",
                "coordinate_space": coordinate_contract(ir),
                "lines": lines, "unassigned_content": unassigned}


class QuestionStructureParser:
    def __init__(self, config=None):
        self.config = deepcopy(DEFAULT_CONFIG)
        if config:
            unknown = set(config) - set(self.config)
            if unknown:
                raise ValueError("unknown structure configuration")
            self.config.update(config)
        self.config_hash = canonical_hash({"version": PARSER_VERSION, "config": self.config})

    @staticmethod
    def _ordered_content(nodes, layout, regions):
        """Return deterministic visual content anchors for each draft node.

        This is a projection only: formula and figure items reference their
        region evidence and are never linearized into semantic text.
        """
        by_key = {node["stable_key"]: node for node in nodes}
        items = {key: [] for key in by_key}
        owner = {}
        line_by_element = {
            element_id: line for line in layout["lines"]
            for element_id in line["source_element_ids"]
        }
        for node in nodes:
            for source in node["source_regions"]:
                for element_id in source["source_element_ids"]:
                    owner[element_id] = node["stable_key"]

        # Text fragments retain their native source IDs.  Math fragments are
        # represented by the formula-region item below, avoiding duplication.
        for line in layout["lines"]:
            owners = {owner[eid] for eid in line["source_element_ids"] if eid in owner}
            if len(owners) != 1:
                continue
            key = next(iter(owners))
            for fragment in line["fragments"]:
                evidence = fragment.get("math_evidence", {})
                if evidence.get("math_like_candidate"):
                    continue
                items[key].append({
                    **_content_item("text", text=fragment.get("text"),
                                   source_element_ids=[fragment["element_id"]], line=line),
                    "_sort": (line["page_index"], line["geometric_order"],
                              fragment["bbox"][0], fragment["bbox"][1], 0, fragment["element_id"]),
                })

        for kind in ("formula_regions", "figure_regions"):
            item_type = "formula_region" if kind == "formula_regions" else "figure_region"
            for region in regions[kind]:
                key = region.get("assigned_question_key")
                if key not in items:
                    continue
                box = region["bbox"]
                source_lines = [line_by_element[element_id] for element_id in region["source_element_ids"]
                                if element_id in line_by_element]
                native_orders = sorted({order for line in source_lines for order in line["native_orders"]
                                        if order is not None})
                geometric_orders = [line["geometric_order"] for line in source_lines]
                anchor = _content_item(item_type, region_id=region["region_id"], region=region)
                anchor["native_orders"] = native_orders
                anchor["geometric_order"] = min(geometric_orders) if geometric_orders else None
                geometric_order = anchor["geometric_order"]
                items[key].append({
                    **anchor,
                    "_sort": (region["page_index"], geometric_order if geometric_order is not None else 10**9,
                              box[0], box[1], 1, region["region_id"]),
                })

        for node in nodes:
            key = node["stable_key"]
            for evidence in node["score"]["evidence"]:
                box = evidence["bbox"]
                source_lines = [line_by_element[element_id] for element_id in evidence.get("source_element_ids", [])
                                if element_id in line_by_element]
                geometric_order = min((line["geometric_order"] for line in source_lines), default=None)
                native_orders = sorted({order for line in source_lines for order in line["native_orders"]
                                        if order is not None})
                anchor = _content_item("score_expression", text=evidence.get("raw_expression"),
                                       source_element_ids=evidence.get("source_element_ids", []),
                                       region=evidence)
                anchor["text"] = evidence.get("normalized_expression")
                anchor["raw_text"] = evidence.get("raw_expression")
                anchor["geometric_order"] = geometric_order
                anchor["native_orders"] = native_orders
                items[key].append({
                    **anchor,
                    "_sort": (evidence["page_index"], geometric_order if geometric_order is not None else 10**9,
                              box[2], box[1], 2,
                              evidence.get("normalized_expression", "")),
                })

        for key, content in items.items():
            content.sort(key=lambda item: item["_sort"])
            for order, item in enumerate(content):
                item.pop("_sort", None)
                item["order"] = order
            by_key[key]["ordered_content"] = content

    def build(self, ir):
        if ir.get("schema_version") != "question-document-ir.v1":
            raise ValueError("unsupported Document IR schema")
        layout = LayoutProjector(self.config).project(ir)
        major_re = re.compile(self.config["major_pattern"])
        sub_re = re.compile(self.config["sub_pattern"])
        inline_re = re.compile(self.config["inline_pattern"])
        score_re = re.compile(self.config["score_pattern"])
        nodes, context, anchors = [], [], []
        unassigned_scores = []
        current = parent = None
        flags = set()
        seen_labels = set()
        owner = {}
        page_by_id = {p["page_index"]: p for p in ir["pages"]}
        # Figure-contained labels belong to visual evidence, not body prose.
        figure_seeds = {}
        for page in ir["pages"]:
            figure_seeds[page["page_index"]] = [e for e in page["elements"] if e["type"] == "image" and e.get("bbox")
                and area(e["bbox"]) >= page["width"]*page["height"]*self.config["figure_min_area_ratio"]
                and min(e["bbox"][2]-e["bbox"][0], e["bbox"][3]-e["bbox"][1]) >= self.config["figure_min_side"]]
        for line in layout["lines"]:
            text = normalize(line["text"])
            major = major_re.match(text)
            sub = sub_re.match(text)
            inline = list(inline_re.finditer(text))
            page = page_by_id[line["page_index"]]
            footer = line["bbox"][1] > page["height"] * self.config["footer_ratio"]
            inside_figure = any(b[0] <= line["bbox"][0] and b[1] <= line["bbox"][1] and b[2] >= line["bbox"][2] and b[3] >= line["bbox"][3]
                                for b in (e["bbox"] for e in figure_seeds[line["page_index"]]))
            if footer or inside_figure:
                context.append({**line, "role": "figure_annotation" if inside_figure else "footer_candidate"})
                continue
            # A line with several inline labels or no content after a label is
            # insufficient to establish an independent child.
            standalone = bool(sub and len(inline) == 1 and text[sub.end():].strip())
            if major or (standalone and parent):
                label = major.group(0) if major else sub.group(0)
                key = f"q{sum(n['depth'] == 0 for n in nodes)+1}" if major else f"{parent['stable_key']}.{sum(n['parent_key'] == parent['stable_key'] for n in nodes)+1}"
                node_flags = list(line["review_flags"])
                identity = (None if major else parent["stable_key"], label.strip())
                if identity in seen_labels:
                    node_flags.append("duplicate_question_label")
                    if parent and not major:
                        parent["review_flags"].append("ambiguous_parent_assignment")
                seen_labels.add(identity)
                current = {"stable_key": key, "parent_key": None if major else parent["stable_key"],
                           "node_type": "major_question" if major else "subquestion", "depth": 0 if major else 1,
                           "sort_order": len(nodes), "label": {"raw": line["text"][:len(label)], "normalized": label.strip()},
                           "body_text": "", "source_regions": [], "score": {"semantics": "unset", "points": None, "evidence": [],
                           "effective_points_candidate": None, "aggregate_points_candidate": None},
                           "formula_regions": [], "figure_regions": [], "review_flags": node_flags}
                nodes.append(current)
                if major:
                    parent = current
                anchors.append((line["page_index"], line["bbox"][1], current))
            if inline and current and (major or not standalone):
                current["review_flags"].append("inline_subquestion_label")
            if not current:
                context.append({**line, "role": "document_preamble"})
                for match in score_re.finditer(text):
                    unassigned_scores.append({"raw_expression": line["text"], "normalized_expression": match.group(0),
                        "page_index": line["page_index"], "bbox": line["bbox"],
                        "source_element_ids": line["source_element_ids"], "question_key": None})
                    flags.add("unassigned_score_expression")
                continue
            current["source_regions"].append({k: line[k] for k in ("page_index", "bbox", "geometric_order", "source_element_ids", "native_orders")})
            current["review_flags"].extend(line["review_flags"])
            prose = [f["text"] for f in line["fragments"] if not f["math_evidence"].get("math_like_candidate")]
            current["body_text"] += ("\n" if current["body_text"] else "") + " ".join(prose)
            for eid in line["source_element_ids"]:
                owner[eid] = current["stable_key"]
            for match in score_re.finditer(text):
                current["score"]["evidence"].append({"raw_expression": line["text"], "normalized_expression": match.group(0),
                    "numeric_points": float(match.group(2)), "semantics": "each_child" if match.group(1) else "direct",
                    "page_index": line["page_index"], "bbox": line["bbox"], "source_element_ids": line["source_element_ids"],
                    "question_key": current["stable_key"], "bbox_precision": "source_line"})
        by_key = {n["stable_key"]: n for n in nodes}
        for n in nodes:
            score = n["score"]
            evidence = score["evidence"]
            children = [c for c in nodes if c["parent_key"] == n["stable_key"]]
            n["leaf_candidate"] = not children
            if len(evidence) == 1:
                score.update(semantics=evidence[0]["semantics"], points=evidence[0]["numeric_points"])
            elif evidence:
                score["semantics"] = "ambiguous"
                n["review_flags"].append("score_scope_ambiguous")
            if score["semantics"] == "direct":
                if children:
                    n["review_flags"].append("direct_score_with_children")
                else:
                    score["effective_points_candidate"] = score["points"]
            if score["semantics"] == "each_child":
                unsafe = {"inline_subquestion_label", "ambiguous_parent_assignment", "duplicate_question_label", "ambiguous_geometric_order"}
                safe = bool(children) and not unsafe.intersection(n["review_flags"]) and all(
                    not unsafe.intersection(c["review_flags"]) and not c["score"]["evidence"] for c in children)
                if safe:
                    for child in children:
                        child["score"]["effective_points_candidate"] = score["points"]
                        child["score"]["derived_from"] = n["stable_key"]
                    score["aggregate_points_candidate"] = score["points"] * len(children)
                else:
                    score["semantics"] = "ambiguous"
                    n["review_flags"].append("each_child_without_clear_children")
        regions = {"formula_regions": [], "figure_regions": []}
        for page in ir["pages"]:
            if page.get("vector_summary", {}).get("count", 0):
                flags.add("unresolved_vector_evidence")
            math = [e for e in page["elements"] if e["type"] == "text" and e.get("bbox") and (e.get("normalized_text") or "").strip()
                    and (e.get("quality_signals", {}).get("math_like_candidate") or "math_like_candidate" in e.get("review_flags", []))]
            math_groups = clusters(math, lambda a, b: gap(a["bbox"], b["bbox"], 0) <= self.config["formula_gap"] and gap(a["bbox"], b["bbox"], 1) <= self.config["formula_vertical_gap"])
            images = [e for e in page["elements"] if e["type"] == "image" and e.get("bbox")]
            image_groups = clusters(images, lambda a, b: gap(a["bbox"], b["bbox"], 0) <= self.config["figure_adjacency"] and gap(a["bbox"], b["bbox"], 1) <= self.config["figure_adjacency"])
            seeds = {e["element_id"] for e in figure_seeds[page["page_index"]]}
            image_groups = [g for g in image_groups if any(e["element_id"] in seeds for e in g)]
            for kind, groups in (("formula", math_groups), ("figure", image_groups)):
                groups.sort(key=lambda g: (union([e["bbox"] for e in g])[1], union([e["bbox"] for e in g])[0]))
                for group in groups:
                    box = union([e["bbox"] for e in group])
                    owners = {owner[e["element_id"]] for e in group if e["element_id"] in owner}
                    assigned = next(iter(owners)) if len(owners) == 1 else None
                    if not owners:
                        preceding = [(p, y, n) for p, y, n in anchors if (p, y) <= (page["page_index"], box[1])]
                        following = [(p, y) for p, y, n in anchors if (p, y) > (page["page_index"], box[1])]
                        if preceding and not any(p == page["page_index"] and y < box[3] for p, y in following):
                            assigned = preceding[-1][2]["stable_key"]
                    region_flags = [] if assigned else [f"unassigned_{kind}_region"]
                    region = {"region_id": f"{kind}-{len(regions[kind+'_regions'])+1:04d}", "page_index": page["page_index"], "bbox": box,
                              "coordinate_space_ref": "source_ir.coordinate_space",
                              "source_element_ids": [e["element_id"] for e in group], "assigned_question_key": assigned,
                              "review_flags": region_flags}
                    if kind == "formula":
                        region.update(text_fragments=[{"element_id": e["element_id"], "native_text": e["native_text"], "bbox": e["bbox"],
                                                     "native_order": e.get("reading_order")} for e in group],
                                      fonts=sorted({str(e.get("native", {}).get("font")) for e in group}),
                                      math_evidence_reasons=sorted({k for e in group for k, v in e.get("quality_signals", {}).items() if v is True and k.endswith("candidate")}),
                                      routing_evidence=_region_routing_evidence(group))
                    else:
                        region["image_evidence"] = [{k: e.get(k) for k in ("element_id", "bbox", "sha256", "artifact_ref", "native")} for e in group]
                    regions[kind+"_regions"].append(region)
                    if assigned:
                        by_key[assigned][kind+"_regions"].append(region["region_id"])
                    flags.update(region_flags)
        for n in nodes:
            n["review_flags"] = sorted(set(n["review_flags"]))
            n["review_required"] = bool(n["review_flags"])
            flags.update(n["review_flags"])
        self._ordered_content(nodes, layout, regions)
        if layout["unassigned_content"]:
            flags.add("unassigned_content")
        if not nodes:
            flags.add("no_question_candidates")
        leaves = [n for n in nodes if n["leaf_candidate"]]
        total = sum(n["score"]["effective_points_candidate"] for n in leaves) if leaves and all(n["score"]["effective_points_candidate"] is not None for n in leaves) else None
        draft = {"schema_version": DRAFT_SCHEMA, "parser": {"name": "native-question-structure", "version": PARSER_VERSION,
                 "config": deepcopy(self.config), "config_hash": self.config_hash}, "source_ir_sha256": canonical_hash(ir),
                 "coordinate_space": coordinate_contract(ir),
                 "nodes": nodes, "document_context": context, **regions, "total_points_candidate": total,
                 "unassigned_score_expressions": unassigned_scores,
                 "unassigned_content": layout["unassigned_content"], "review_flags": sorted(flags), "review_required": bool(flags)}
        return layout, draft
