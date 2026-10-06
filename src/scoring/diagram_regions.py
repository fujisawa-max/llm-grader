"""Source-backed diagram geometry and crops; no interpretation or inference.

Domain adapters must supply verified PDF/IR and exclusive reviewed ownership.
An optional grouping callback can only partition existing element IDs. It cannot
invent coordinates. This module deliberately has no database or model client.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
from uuid import uuid4

from .adapters.pdf_region import PyMuPdfRegionRenderer
from .pdf_native import canonical_hash, sha256_file
from .vision_policy import DEFAULT_POLICY, crop_geometry, page_space


MAX_ELEMENTS = 2048
MAX_REGIONS = 16
GAP = 4.0
POLICY = {**DEFAULT_POLICY, "figure_margin": 6.0, "max_figure_page_ratio": 0.55}


def _box(value, *, degenerate=False):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            or value[2] < value[0] or value[3] < value[1]
            or not degenerate and (value[2] == value[0] or value[3] == value[1])):
        raise ValueError("diagram_invalid_bbox")
    return list(value)


def union(elements):
    boxes = [_box(e["bbox"], degenerate=True) for e in elements]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _near(a, b):
    return all(max(0, max(a[k], b[k]) - min(a[k+2], b[k+2])) <= GAP for k in (0, 1))


def _contains(outer, inner):
    return all(outer[k] <= inner[k] and inner[k+2] <= outer[k+2] for k in (0, 1))


def visual_elements(page):
    """Read newer vector evidence without changing historical IR elements."""
    return [e for e in page.get("elements", []) if e.get("type") == "image"] + list(
        page.get("vector_elements", []))


def diagram_groups(page, *, allowed_ids, excluded_ids=(), grouping=None):
    """Conservative connected visual components inside verified ownership.

    Tiny components (fraction bars, underlines) are not figures. Text is attached
    only if already owned, short, and within the diagram envelope. Prose does
    not connect two components. Rectangular grids are marked ambiguous because
    geometry alone cannot distinguish a table from a visual diagram.
    """
    allowed, excluded = set(allowed_ids), set(excluded_ids)
    if allowed & excluded:
        raise ValueError("diagram_shared_source_unresolved")
    elements = visual_elements(page)
    if len(elements) > MAX_ELEMENTS:
        raise ValueError("diagram_element_limit")
    ids = [e["element_id"] for e in elements]
    if len(set(ids)) != len(ids):
        raise ValueError("diagram_duplicate_source_id")
    pending = sorted((deepcopy(e) for e in elements if e["element_id"] in allowed
                      and e.get("bbox")), key=lambda e: e["element_id"])
    for e in pending:
        _box(e["bbox"], degenerate=True)
    groups = []
    while pending:
        component = [pending.pop(0)]
        cursor = 0
        while cursor < len(component):
            rest = []
            for e in pending:
                if _near(e["bbox"], component[cursor]["bbox"]):
                    component.append(e)
                else:
                    rest.append(e)
            pending = rest
            cursor += 1
        box = union(component)
        if min(box[2]-box[0], box[3]-box[1]) < 25:
            continue
        # Reject components that touch visual evidence owned by a sibling.
        if any(e["element_id"] in excluded and e.get("bbox") and _near(box, e["bbox"])
               for e in elements):
            raise ValueError("diagram_source_boundary")
        horizontal = sum(e.get("native", {}).get("horizontal_lines", 0) for e in component)
        vertical = sum(e.get("native", {}).get("vertical_lines", 0) for e in component)
        ambiguous = horizontal >= 3 and vertical >= 3
        method, confidence = "geometry", None
        ricoh_result = None
        if ambiguous:
            if grouping is None:
                groups.append({"status": "unresolved", "reason_code": "diagram_geometry_ambiguous",
                               "bbox": box, "source_element_ids": [e["element_id"] for e in component],
                               "grouping_method": "geometry_ambiguous", "confidence": None, "ricoh_used": False})
                continue
            try:
                ricoh_result = grouping(deepcopy(component))
                selected = validate_grouping(ricoh_result, {e["element_id"] for e in component})
                if len(selected) != 1:
                    raise ValueError("diagram_grouping_ambiguous")
            except (ValueError, RuntimeError) as exc:
                groups.append({"status": "unresolved", "reason_code": str(exc), "bbox": box,
                    "source_element_ids": sorted(e['element_id'] for e in component),
                    "ricoh_used": True, "grouping_method": "geometry_ambiguous", "confidence": None})
                continue
            confidence = selected[0]["confidence"]
            component = [e for e in component if e["element_id"] in selected[0]["element_ids"]]
            box = union(component)
            method = "geometry_assisted"
        labels = [e for e in page.get("elements", []) if e.get("type") == "text"
                  and e["element_id"] in allowed and e.get("bbox")
                  and 0 < len((e.get("native_text") or "").strip()) <= 12
                  and _contains([box[0]-GAP, box[1]-GAP, box[2]+GAP, box[3]+GAP], e["bbox"])]
        component += labels
        groups.append({"status": "candidate", "bbox": union(component),
                       "source_element_ids": sorted(e["element_id"] for e in component),
                       "grouping_method": method, "confidence": confidence,
                       "ricoh_used": ambiguous, "grouping_result": ricoh_result})
    if len(groups) > MAX_REGIONS:
        raise ValueError("diagram_region_limit")
    return sorted(groups, key=lambda g: (g["bbox"][1], g["bbox"][0], g["source_element_ids"]))


def validate_grouping(value, known_ids):
    """No prose, unknown IDs, coordinates, repeated IDs or truncated JSON."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("diagram_grouping_invalid") from None
    if not isinstance(value, dict) or set(value) != {"groups"}:
        raise ValueError("diagram_grouping_invalid")
    groups = value["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_REGIONS:
        raise ValueError("diagram_grouping_invalid")
    seen = set()
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"element_ids", "confidence"}:
            raise ValueError("diagram_grouping_invalid")
        ids, confidence = group["element_ids"], group["confidence"]
        if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
                or len(set(ids)) != len(ids) or not set(ids) <= known_ids or seen & set(ids)
                or type(confidence) not in (float, int) or not math.isfinite(confidence)
                or not 0.9 <= confidence <= 1):
            raise ValueError("diagram_grouping_invalid")
        seen.update(ids)
    return deepcopy(groups)


class DiagramRegionExtractor:
    """Reuse the existing coordinate-aware region renderer and artifact policy."""
    def __init__(self, source, ir, store):
        self.source, self.ir, self.store = Path(source), ir, store
        if sha256_file(self.source) != ir["source"]["sha256"]:
            raise ValueError("diagram_source_integrity_error")

    def candidates(self, *, domain, target_key, ownership, exclusions=None, grouping=None):
        if domain not in {"question", "model_answer"}:
            raise ValueError("diagram_invalid_domain")
        result = []
        self.discovery_args = dict(domain=domain, target_key=target_key, ownership=ownership, exclusions=exclusions)
        for page in self.ir["pages"]:
            index = page["page_index"]
            by_id = {e["element_id"]: e for e in page.get("elements", []) + visual_elements(page)}
            for group in diagram_groups(page, allowed_ids=ownership.get(index, []),
                                        excluded_ids=(exclusions or {}).get(index, []), grouping=grouping):
                identity = {"domain": domain, "target_key": target_key,
                            "source_sha256": self.ir["source"]["sha256"], "page_index": index,
                            "source_element_ids": group["source_element_ids"], "bbox": group["bbox"]}
                result.append({**group, **identity, "id": "diagram-" + canonical_hash(identity)[:24],
                               "material_id": self.ir["source"].get("material_id"),
                               "source_ir_sha256": canonical_hash(self.ir),
                               "source_elements": [{"id": identifier,
                                   "type": by_id[identifier]["type"],
                                   "bbox": deepcopy(by_id[identifier]["bbox"]),
                                   "reading_order": by_id[identifier].get("reading_order"),
                                   "original_text": by_id[identifier].get("native_text")}
                                   for identifier in group["source_element_ids"]],
                               "automatic_bbox": group["bbox"], "teacher_adjusted": False})
        if len(result) > MAX_REGIONS:
            raise ValueError("diagram_region_limit")
        return result

    def crop(self, candidate, *, final_bbox=None):
        """Only server-derived candidates. Manual bounds do not change ownership.

        Callers must check competing Question boundaries before allowing manual
        expansion. This low-level method verifies page bounds and size limits.
        """
        page = next((p for p in self.ir["pages"] if p["page_index"] == candidate["page_index"]), None)
        if (page is None or candidate["source_sha256"] != self.ir["source"]["sha256"]
                or sha256_file(self.source) != candidate["source_sha256"]):
            raise ValueError("diagram_source_integrity_error")
        box = _box(final_bbox if final_bbox is not None else candidate["automatic_bbox"])
        bounds = page_space(page).cropbox
        if not _contains(bounds, box):
            raise ValueError("diagram_crop_outside_page")
        geometry = crop_geometry(page, box, "figure", POLICY)
        expanded = geometry['expanded_bbox']
        if hasattr(self, 'allowed_bounds'):
            if not any(_contains(b, expanded) for b in self.allowed_bounds.get(page['page_index'], [])):
                raise ValueError('diagram_source_boundary')
            if any(all(min(expanded[k+2], b[k+2]) > max(expanded[k], b[k]) for k in (0, 1))
                   for b in getattr(self, 'blocked_bounds', {}).get(page['page_index'], [])):
                raise ValueError('diagram_source_boundary')
        key = canonical_hash({"source": candidate["source_sha256"], "page": page["page_index"],
                              "crop": geometry})
        ref = f"diagrams/{key}.png"
        output = self.store.path(ref)
        metadata = self.store.path(f"diagrams/{key}.json")
        if metadata.exists():
            render = json.loads(metadata.read_text())
            if (render["sha256"] != sha256_file(output)
                    or render["source_pdf_sha256"] != candidate["source_sha256"]
                    or render["page_index"] != page["page_index"]
                    or any(render.get(k) != v for k, v in geometry.items())):
                raise ValueError("diagram_artifact_integrity_error")
        else:
            temp = output.with_name(f".{uuid4()}.png")
            render = PyMuPdfRegionRenderer().render(self.source, page,
                {"page_index": page["page_index"], "region_id": candidate["id"],
                 "region_type": "figure", "crop": geometry}, POLICY, temp)
            temp.replace(output)
            self.store.write(f"diagrams/{key}.json", render)
        return {**candidate, "final_bbox": box, "crop_bbox": geometry["expanded_bbox"],
                "teacher_adjusted": box != candidate["automatic_bbox"],
                "crop_width": render["width"], "crop_height": render["height"],
                "crop_sha256": render["sha256"], "artifact_ref": ref}
