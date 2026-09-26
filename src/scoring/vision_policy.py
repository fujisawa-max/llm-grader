"""Pure selective routing. No PDF renderer, model, database or runtime calls."""
from copy import deepcopy
import math
import re

from .coordinate import PageCoordinateSpace, expand_bbox, pdf_bbox_to_pixel, page_pixel_size, validate_bbox
from .pdf_native import canonical_hash

POLICY_VERSION = "native-selective-vision-v1"
OVERLAY_SCHEMA = "question-import-vision-overlay.v1"
DEFAULT_POLICY = {
    "formula_margin": 2.0, "figure_margin": 4.0,
    "formula_scale": 3.0, "figure_scale": 2.0,
    "max_width": 4096, "max_height": 4096, "max_pixels": 8_000_000,
    "max_formula_page_ratio": 0.25, "max_figure_page_ratio": 0.8,
    "vertical_tolerance": 0.2, "neighbor_clearance": 0.25,
    "coordinate_contract": "native-crop-local-render-v1",
}


def page_space(page):
    """Native text/image bboxes are unrotated and crop-local.

    H.2-A/B.1 erroneously labelled them mediabox_unrotated. Do not change
    historical evidence: normalize the viewport here, retaining physical
    cropbox/mediabox separately in the render manifest. No second rotation
    implementation is used: coordinate.py performs all rotation/scaling.
    """
    crop = page["cropbox"]
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    bounds = (0, 0, width, height)
    return PageCoordinateSpace(bounds, bounds, page["rotation"])


def region_pdf_bbox(region, page):
    """Explicit new region metadata; legacy Document IR regions are PDF points."""
    space = region.get("coordinate_space", "pdf_point")
    box = validate_bbox(region["bbox"], space)
    if space == "pdf_point":
        return box
    if space == "normalized":
        if region.get("reference_plane") != "source-page-crop-local-unrotated":
            raise ValueError("unknown_region_reference_plane")
        bounds = page_space(page).cropbox
        return [box[0] * bounds[2], box[1] * bounds[3], box[2] * bounds[2], box[3] * bounds[3]]
    raise ValueError("unsupported_region_coordinate_space")


def crop_geometry(page, box, kind, config):
    space = page_space(page)
    bounds = space.cropbox
    if (len(box) != 4 or not all(math.isfinite(v) for v in box)
            or box[2] <= box[0] or box[3] <= box[1]
            or box[2] <= 0 or box[3] <= 0 or box[0] >= bounds[2] or box[1] >= bounds[3]):
        raise ValueError("invalid_region_bbox")
    margin = config[f"{kind}_margin"]
    margins = [margin] * 4
    # Reduce margins that would extend into neighboring native prose. A
    # fraction bar already inside the source bbox is never trimmed.
    if kind == "formula":
        for e in page.get("elements", []):
            b = e.get("bbox")
            if (not b or e.get("type") != "text" or not (e.get("native_text") or "").strip()
                    or e.get("quality_signals", {}).get("math_like_candidate")):
                continue
            if min(box[3], b[3]) > max(box[1], b[1]):
                if b[2] <= box[0]:
                    margins[0] = min(margins[0], max(0, box[0]-b[2]-config["neighbor_clearance"]))
                if b[0] >= box[2]:
                    margins[2] = min(margins[2], max(0, b[0]-box[2]-config["neighbor_clearance"]))
            if min(box[2], b[2]) > max(box[0], b[0]):
                if b[3] <= box[1]:
                    margins[1] = min(margins[1], max(0, box[1]-b[3]-config["neighbor_clearance"]))
                if b[1] >= box[3]:
                    margins[3] = min(margins[3], max(0, b[1]-box[3]-config["neighbor_clearance"]))
    expanded = expand_bbox(box, margins, bounds=bounds)
    scale = config[f"{kind}_scale"]
    pixels = pdf_bbox_to_pixel(box, space, scale=scale, margin=margins)
    width, height = pixels.x1-pixels.x0, pixels.y1-pixels.y0
    ratio = (expanded[2]-expanded[0])*(expanded[3]-expanded[1])/(bounds[2]*bounds[3])
    if (width < 2 or height < 2 or width > config["max_width"] or height > config["max_height"]
            or width*height > config["max_pixels"] or ratio >= config[f"max_{kind}_page_ratio"]):
        raise ValueError("crop_limits_exceeded")
    return {"expanded_bbox": expanded, "source_bbox": list(box), "scale": scale,
            "dpi": scale*72, "pixel_bbox": pixels.as_dict()["bbox"], "width": width, "height": height,
            "clipped": pixels.clipped, "margins": margins, "margin_policy": "fixed-points-neighbor-limited-v1",
            "coordinate_space": config["coordinate_contract"], "page_rotation": page["rotation"],
            "cropbox": page["cropbox"], "mediabox": page["mediabox"],
            "rendered_page_size": list(page_pixel_size(space, scale=scale))}


class VisionRoutingPolicy:
    def __init__(self, config=None):
        self.config = {**DEFAULT_POLICY, **(config or {})}
        if set(self.config) != set(DEFAULT_POLICY):
            raise ValueError("unknown_vision_policy_setting")
        for key, value in self.config.items():
            if isinstance(DEFAULT_POLICY[key], (int, float)):
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                    raise ValueError("invalid_vision_policy_setting")
        if self.config["coordinate_contract"] != DEFAULT_POLICY["coordinate_contract"]:
            raise ValueError("unsupported_coordinate_contract")
        self.config_hash = canonical_hash({"version": POLICY_VERSION, "config": self.config})

    def build(self, draft, ir):
        pages = {p["page_index"]: p for p in ir["pages"]}
        routes = []
        for kind in ("formula", "figure"):
            for region in draft[f"{kind}_regions"]:
                rid = region["region_id"]
                if not re.fullmatch(r"(?:formula|figure)-\d+", rid):
                    raise ValueError("invalid_region_id")
                anchors = [{"question_key": n["stable_key"], "order": a["order"]}
                           for n in draft["nodes"] for a in n.get("ordered_content", [])
                           if a.get("region_id") == rid and a["type"] == f"{kind}_region"]
                page = pages[region["page_index"]]
                elements = {e["element_id"]: e for e in page["elements"]}
                spans = [elements[eid] for eid in region["source_element_ids"]]
                decision, role, reasons = "AMBIGUOUS", None, ["missing_or_ambiguous_anchor"]
                if len(anchors) == 1 and anchors[0]["question_key"] == region["assigned_question_key"]:
                    if kind == "figure":
                        decision, role, reasons = "VISION_REQUIRED", "ocr", ["visual_information_not_in_native_text"]
                    else:
                        evidence = region.get("routing_evidence", {})
                        heights = [s["bbox"][3]-s["bbox"][1] for s in spans]
                        centers = [(s["bbox"][3]+s["bbox"][1])/2 for s in spans]
                        vertical = len(spans) > 1 and max(centers)-min(centers) > min(heights)*self.config["vertical_tolerance"]
                        damaged = any("�" in (s.get("native_text") or "") for s in spans)
                        if damaged or (len(spans) > 1 and (vertical or evidence.get("math_font_span_count", 0) > 1)):
                            decision, role = "VISION_RECOMMENDED", "math_ocr"
                            reasons = ["fragmented_math_evidence"]
                            if vertical:
                                reasons.append("multiple_vertical_positions")
                            if damaged:
                                reasons.append("replacement_character")
                        else:
                            decision, reasons = "NATIVE_SUFFICIENT", ["continuous_native_text_no_vertical_complexity"]
                geometry = crop_geometry(page, region_pdf_bbox(region, page), kind, self.config)
                routes.append({"region_id": rid, "region_type": kind, "page_index": region["page_index"],
                               "assigned_question_key": region["assigned_question_key"], "anchors": anchors,
                               "decision": decision, "model_role": role, "reasons": reasons,
                               "source_element_ids": region["source_element_ids"], "crop": geometry,
                               "routing_evidence": deepcopy(region.get("routing_evidence", {})),
                               "native_fragments": [s.get("native_text") for s in spans if s.get("type") == "text"]})
        return {"schema_version": "question-import-vision-plan.v1", "policy_version": POLICY_VERSION,
                "config": deepcopy(self.config), "config_hash": self.config_hash,
                "source_draft_sha256": canonical_hash(draft), "source_ir_sha256": canonical_hash(ir),
                "source_pdf_sha256": ir["source"]["sha256"], "routes": routes,
                "vision_request_count": sum(r["model_role"] is not None for r in routes)}
