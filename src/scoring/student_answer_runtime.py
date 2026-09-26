"""RuntimeManager-backed observation/reconstruction adapters.

The adapter exposes only the three H.3-A roles. It has no grading role and
never receives a ModelAnswer, Rubric, score, or grading policy.
"""

from contextlib import contextmanager
import json
from pathlib import Path

from .core import LocalClient, generation_payload, image_content, parse_response
from .vision_output import parse_output
from .pdf_native import sha256_file
from .coordinate import (COORDINATE_CONTRACT_VERSION, CoordinateSpace,
                         validate_bbox, legacy_1000_to_normalized)
import copy
import time
import pymupdf
import tempfile
import os

PROMPTS = {
    "identity": "Read only the handwritten student identity in the answer-sheet header. Read 学籍番号 and 名前; ignore 座席番号 completely. Do not use a filename or fixture label. Preserve leading zeroes and the original characters. Return JSON only with student_id, name, text, and uncertainties. If a field is unclear, leave it empty and explain the uncertainty.",
    "ricoh": "Observe this student's answer page only. Do not solve, judge, improve, or infer an intended answer. Distinguish handwritten student marks from printed question text, printed labels, headers, names, and student identifiers; report printed content only as evidence and never as student writing. Return ONE concise JSON object with text_blocks (text and bbox), formula_regions (region_id, page_id, bbox, visible transcription if any), reading_order, and warnings. All bbox coordinates MUST use the canonical normalized coordinate space: floating point values from 0.0 through 1.0, top-left origin, x-right/y-down, [x0,y0,x1,y1], relative to the entire supplied image. Include coordinate_space='normalized'. Enclose complete visible formulas. Do not include reasoning or extra prose.",
    "unimumer": "Transcribe only the visible formula in this crop. Do not solve, simplify, correct, or infer missing symbols. Preserve the student's notation.",
    "ornith_reconstruction": "Reconstruct only what the student wrote from the quoted evidence and original image. Printed question text, printed labels, headers, names, and student identifiers are not student writing and must not appear in answer_text or segments. Do not solve or judge correctness, do not use an expected answer, and preserve mistakes and uncertainty. If handwriting cannot be separated confidently, report uncertainty rather than copying printed text. Return JSON with question_id, answer_text, segments, uncertainties, and source_refs.",
}

BBOX_SCHEMA = {"type": "array", "minItems": 4, "maxItems": 4,
               "items": {"type": "number", "minimum": 0, "maximum": 1}}

RICOH_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "coordinate_space": {"const": "normalized"},
    "text_blocks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "properties": {"text": {"type": "string"}, "bbox": BBOX_SCHEMA},
        "required": ["text", "bbox"]}},
    "formula_regions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "properties": {"region_id": {"type": "string"}, "page_id": {"type": "string"},
                       "bbox": BBOX_SCHEMA,
                       "transcription": {"type": "string"}},
        "required": ["region_id", "page_id", "bbox"]}},
    "reading_order": {"type": "array", "items": {"type": "integer"}},
    "warnings": {"type": "array", "items": {"type": "string"}},
}, "required": ["coordinate_space", "text_blocks", "formula_regions", "reading_order", "warnings"]}


def normalize_ricoh_regions(raw, *, allow_explicit_1000=False):
    """Validate every region before publishing a normalized artifact or crop."""
    if not isinstance(raw, dict):
        raise ValueError("INVALID_RICOH_LAYOUT")
    space = raw.get("coordinate_space")
    if space != "normalized" and not (allow_explicit_1000 and space == "normalized_1000"):
        raise ValueError("INVALID_COORDINATE_SPACE")
    value = copy.deepcopy(raw)
    for key in ("text_blocks", "formula_regions", "visual_regions"):
        for region in value.get(key, []):
            declared = region.get("coordinate_space", space)
            if declared != space:
                raise ValueError("INVALID_COORDINATE_SPACE")
            try:
                box = validate_bbox(region.get("bbox"), space)
                # No magnitude-based inference and no tolerance outside canonical range.
                if min(box) < 0 or max(box) > (1 if space == "normalized" else 1000):
                    raise ValueError("range")
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("INVALID_RICOH_COORDINATES") from exc
            region["bbox"] = legacy_1000_to_normalized(box) if space == "normalized_1000" else box
            region["coordinate_space"] = "normalized"
            region["coordinate_version"] = COORDINATE_CONTRACT_VERSION
    value["coordinate_space"] = "normalized"
    value["coordinate_version"] = COORDINATE_CONTRACT_VERSION
    if space == "normalized_1000":
        value["source_coordinate_space"] = space
    return value

COMPACT_RICOH_SCHEMA = {"type": "object", "additionalProperties": False,
    "properties": {"regions": {"type": "array", "maxItems": 32, "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"question_ref": {"type": "string"},
                       "type": {"type": "string", "enum": ["text", "formula", "visual"]},
                       "bbox": BBOX_SCHEMA, "text": {"type": "string", "maxLength": 240}},
        "required": ["question_ref", "type", "bbox", "text"]}}},
    "required": ["regions"]}

ANSWER_REGION_SCHEMA = {"type": "object", "additionalProperties": False,
    "properties": {"question_ref": {"type": "string"},
        "answer_regions": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"type": {"type": "string", "enum": ["text", "formula", "visual"]},
                           "bbox": BBOX_SCHEMA, "text": {"type": "string", "maxLength": 120}},
            "required": ["type", "bbox", "text"]}},
        "no_answer_detected": {"type": "boolean"}},
    "required": ["question_ref", "answer_regions", "no_answer_detected"]}
ANSWER_PAGE_SCHEMA = {"type": "object", "additionalProperties": False,
                      "properties": {"questions": {"type": "array", "maxItems": 32,
                          "items": ANSWER_REGION_SCHEMA}}, "required": ["questions"]}

# Scoped answer retries use the same bounded coordinate contract as the page
# pass.  The grammar is deliberately small: it prevents an out-of-range
# coordinate from becoming evidence while leaving transcription to the
# vision model.  Page-relative conversion is recorded separately by the
# caller and never inferred from numeric magnitude.
ANSWER_PAGE_GRAMMAR = r'''
root ::= "{" ws "\"questions\":" ws "[" ws (question ("," ws question){0,31})? "]" ws "}"
question ::= "{" ws "\"question_ref\":" ws ref "," ws "\"answer_regions\":" ws "[" ws (answer ("," ws answer){0,7})? "]" ws "," ws "\"no_answer_detected\":" ws bool "}" ws
answer ::= "{" ws "\"type\":" ws kind "," ws "\"bbox\":" ws "[" unit "," ws unit "," ws unit "," ws unit "]" ws "," ws "\"text\":" ws text "}" ws
kind ::= "\"text\"" | "\"formula\"" | "\"visual\""
bool ::= "true" | "false"
unit ::= ("0." [0-9]{1,6} | "1.0") ws
ref ::= "\"" char{1,80} "\""
text ::= "\"" char{0,120} "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
ws ::= " "?
'''


def _bbox_overlap(a, b):
    if not a or not b:
        return 0.0
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    return intersection / area if area else 0.0

# llama.cpp's schema converter does not constrain fractional number ranges.
# This grammar enforces [0,1] lexically and has no trailing-content production.
COMPACT_RICOH_GRAMMAR = r'''
root ::= "{" ws "\"regions\":" ws "[" ws (region ("," ws region){0,31})? "]" ws "}"
region ::= "{" ws "\"question_ref\":" ws ref "," ws "\"type\":" ws kind "," ws "\"bbox\":" ws "[" unit "," ws unit "," ws unit "," ws unit "]" "," ws "\"text\":" ws text "}" ws
kind ::= "\"text\"" | "\"formula\"" | "\"visual\""
unit ::= ("0." [0-9]{1,6} | "1.0") ws
ref ::= "\"" char{1,40} "\""
text ::= "\"" char{0,240} "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
ws ::= " "?
'''

RECONSTRUCTION_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "question_id": {"type": "string"}, "answer_text": {"type": "string"},
    "segments": {"type": "array", "items": {"type": "object"}},
    "uncertainties": {"type": "array", "items": {"type": "object"}},
    "source_refs": {"type": "array", "items": {"type": "string"}},
}, "required": ["question_id", "answer_text", "segments", "uncertainties", "source_refs"]}


class RuntimeStudentAnswerStages:
    def __init__(self, manager, config, *, runtime_ids=None, image_resolver=None, audit=None):
        self.image_resolver = image_resolver
        self.audit = audit or (lambda event: None)
        self.last_raw = None
        self.manager = manager
        self.config = config
        self.runtime_ids = {"ricoh": "ocr", "unimumer": "math_ocr", "ornith_reconstruction": "ornith_reconstruction"}
        self.runtime_ids.update(runtime_ids or {})

    @contextmanager
    def _runtime(self, role):
        runtime_id = self.runtime_ids[role]
        before = self.manager.status(runtime_id)
        owned = before.get("profile", {}).get("runtime_type") == "managed" and before.get("pid") is None
        try:
            ready = self.manager.ensure_running(runtime_id)
            endpoint = ready.get("endpoint") or ready.get("profile", {}).get("endpoint")
            if not endpoint:
                raise RuntimeError("runtime endpoint unavailable")
            if ready.get("ok") is False:
                raise RuntimeError("MODEL_RUNTIME_UNHEALTHY")
            self.active_profile = ready.get("profile", {})
            self.audit({"event": "runtime", "role": role, "owned": owned, "endpoint": endpoint, "profile": self.active_profile})
            yield endpoint
        finally:
            if owned:
                self.manager.stop(runtime_id)

    def _request(self, role, text, materials=None, images=()):
        settings = self.config.get("models", {}).get(self.runtime_ids[role],
                                                       self.config.get("models", {}).get(role, {}))
        with self._runtime(role) as endpoint:
            client_role = "math_ocr" if role == "unimumer" else role
            client = LocalClient({"models": {client_role: {**settings, "base_url": endpoint,
                "model_id": settings.get("model_id", role)}}, "generation": self.config.get("generation", {})}, client_role)
            started = time.monotonic()
            self.audit({"event": "call", "role": role})
            raw = client.chat(text, materials or {}, [(str(index), Path(image)) for index, image in enumerate(images)])
            self.audit({"event": "response", "role": role, "raw": raw, "seconds": time.monotonic()-started})
            return raw

    def ricoh(self, page_path, question_id):
        raw = self._structured_request("ricoh", PROMPTS["ricoh"], RICOH_SCHEMA,
                                       {"page_id": page_path.stem, "question_id": question_id}, [page_path])
        normalized = normalize_ricoh_regions(raw)
        pix = pymupdf.Pixmap(str(page_path))
        if raw.get("coordinate_space", CoordinateSpace.NORMALIZED.value) != CoordinateSpace.NORMALIZED.value:
            raise ValueError("INVALID_COORDINATE_SPACE")
        normalized["coordinate_space"] = CoordinateSpace.NORMALIZED.value
        normalized["coordinate_version"] = COORDINATE_CONTRACT_VERSION
        normalized["coordinate_contract"] = {"space": CoordinateSpace.NORMALIZED.value,
                                              "format": "xyxy", "origin": "top_left",
                                              "reference": "supplied_image",
                                              "width": pix.width, "height": pix.height}
        for block in normalized.get("text_blocks", []):
            validate_bbox(block.get("bbox"), CoordinateSpace.NORMALIZED)
            block["coordinate_space"] = CoordinateSpace.NORMALIZED.value
        for region in normalized.get("formula_regions", []):
            region["region_id"] = f"answer-{page_path.stem}-formula-{region.get('region_id', 'unknown')}"
            box = region.get("bbox")
            try:
                region["bbox"] = validate_bbox(box, CoordinateSpace.NORMALIZED)
            except ValueError as exc:
                raise ValueError("INVALID_FORMULA_COORDINATES") from exc
            region["coordinate_space"] = CoordinateSpace.NORMALIZED.value
            region["coordinate_version"] = COORDINATE_CONTRACT_VERSION
            region["question_id"] = question_id
            region["page_id"] = page_path.stem
        normalized["question_id"] = question_id
        return self.last_raw, normalized

    def ricoh_identity(self, page_path):
        """Extract header identity as a separate, non-answer observation."""
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "page_id": {"const": page_path.stem}, "student_id": {"type": "string"},
            "name": {"type": "string"}, "text": {"type": "string"},
            "uncertainties": {"type": "array", "items": {"type": "object"}},
        }, "required": ["page_id", "student_id", "name", "text", "uncertainties"]}
        raw = self._structured_request("ricoh", PROMPTS["identity"], schema,
                                       {"page_id": page_path.stem, "identity_bbox": {
                                           "header_bbox": [0.56, 0.02, 0.92, 0.17],
                                           "student_number_bbox": [0.68, 0.075, 0.92, 0.12],
                                           "student_name_bbox": [0.68, 0.115, 0.92, 0.17]}},
                                       [page_path])
        if raw.get("page_id") != page_path.stem:
            raise ValueError("IDENTITY_PAGE_MISMATCH")
        return self.last_raw, {"student_number": raw.get("student_id", ""),
                               "student_name": raw.get("name", ""),
                               "raw_text": raw.get("text", ""),
                               "uncertainties": raw.get("uncertainties", []),
                               "source_bbox": {"header_bbox": [0.56, 0.02, 0.92, 0.17],
                                               "student_number_bbox": [0.68, 0.075, 0.92, 0.12],
                                               "student_name_bbox": [0.68, 0.115, 0.92, 0.17]}}

    def ricoh_page_compact(self, page_path):
        """Run one compact page extraction reusable by all questions on page."""
        prompt = ("Locate separate handwritten answer regions for EACH subquestion on this page. "
                  "Do not merge the whole page into one region. Exclude printed questions and personal headers. "
                  "Use the nearby printed question/subquestion label as question_ref. "
                  "type is text/formula/visual. bbox is [left,top,right,bottom] in fractional page coordinates. "
                  "Halfway across the page is 0.5, a quarter down is 0.25, NOT 500 or 250. "
                  "left < right and top < bottom; every coordinate is between 0.0 and 1.0. "
                  "text is only a short visible handwriting excerpt (at most 60 characters), not full transcription. "
                  "For visual regions text is empty. Preserve mistakes. No reasoning or commentary. JSON only.")
        raw = self._structured_request("ricoh", prompt, COMPACT_RICOH_SCHEMA,
                                       {"page_id": page_path.stem}, [page_path],
                                       grammar=COMPACT_RICOH_GRAMMAR)
        if set(raw) != {"regions"} or not isinstance(raw["regions"], list) or len(raw["regions"]) > 32:
            raise ValueError("INVALID_RICOH_COMPACT_SCHEMA")
        exact = {}
        question_shapes = {}
        warnings = []
        for region in raw["regions"]:
            if (not isinstance(region, dict) or set(region) != {"question_ref", "type", "bbox", "text"}
                    or not isinstance(region["question_ref"], str)
                    or region["type"] not in {"text", "formula", "visual"}
                    or not isinstance(region["text"], str) or len(region["text"]) > 240
                    or (region["type"] == "visual" and region["text"] != "")):
                raise ValueError("INVALID_RICOH_COMPACT_SCHEMA")
            region["bbox"] = validate_bbox(region["bbox"], CoordinateSpace.NORMALIZED)
            region["coordinate_space"] = CoordinateSpace.NORMALIZED.value
            identity = (region["question_ref"], region["type"], tuple(region["bbox"]), region["text"])
            if identity in exact:
                exact[identity]["duplicate_count"] = exact[identity].get("duplicate_count", 1) + 1
                continue
            shape = region["question_ref"]
            if shape in question_shapes and "DUPLICATE_RICOH_REGION" not in warnings:
                warnings.append("DUPLICATE_RICOH_REGION")
            question_shapes.setdefault(shape, region)
            exact[identity] = region
        regions = list(exact.values())
        return self.last_raw, {"coordinate_space": "normalized", "regions": regions,
                               "warnings": warnings, "review_required": bool(warnings)}

    def ricoh_page_answers(self, page_path, anchors):
        """Find handwriting inside authoritative printed-question anchors."""
        prompt = ("Inspect the supplied image visually and detect ONLY the student's dark handwritten ink "
                  "inside each supplied answer search_bbox. The page visibly contains handwriting; find it. "
                  "Do not return printed question text, labels, or blank lines. "
                  "The printed anchor bbox itself is not an answer region. Search from its bottom to the next anchor's top "
                  "and any answer area to its right according to the supplied search_bbox. Return every anchor exactly once. "
                  "Use only fractional [0,1] page bboxes, with left<right and top<bottom. "
                  "If no handwriting is visible, answer_regions=[] and no_answer_detected=true. "
                  "Use answer bboxes around the handwriting strokes, never the printed anchor bbox. "
                  "Do not infer or correct answers. JSON only.")
        # Keep the page detector payload small.  Native element boxes and
        # review hashes are provenance, not model input; sending them here
        # needlessly consumes the vision model context window.
        model_anchors = [{"question_ref": a["question_ref"],
                          "bbox": a["bbox"],
                          "search_bbox": a["search_bbox"],
                          "canvas_bboxes": a.get("canvas_bboxes", [])}
                         for a in anchors]
        page_materials = {"page_id": page_path.stem, "question_anchors": model_anchors}
        initial_error = None
        initial = None
        try:
            initial = self._structured_request("ricoh", prompt, ANSWER_PAGE_SCHEMA,
                                               page_materials, [page_path])
        except (ValueError, TypeError) as exc:
            # finish_reason=length and contract-invalid coordinates are audit
            # failures, never usable answer evidence.  A single scoped retry
            # per missing/invalid anchor is the bounded recovery path.
            initial_error = str(exc)
            self.audit({"event": "page_answer_retry", "reason": initial_error,
                        "page_id": page_path.stem})
        by_ref = {a["question_ref"]: {"question_ref": a["question_ref"],
                  "answer_regions": [], "no_answer_detected": True} for a in model_anchors}
        retry_refs = set(by_ref)
        if initial is not None:
            for item in initial.get("questions", []):
                ref = item.get("question_ref")
                if ref not in by_ref:
                    continue
                try:
                    for region in item.get("answer_regions", []):
                        region["bbox"] = validate_bbox(region.get("bbox"), CoordinateSpace.NORMALIZED)
                    by_ref[ref] = {"question_ref": ref,
                                   "answer_regions": list(item.get("answer_regions", [])),
                                   "no_answer_detected": bool(item.get("no_answer_detected"))}
                    if by_ref[ref]["answer_regions"]:
                        retry_refs.discard(ref)
                except (ValueError, TypeError):
                    retry_refs.add(ref)
        # A compact page pass can legitimately miss dense/faint handwriting;
        # retry only its authoritative answer crop.  Crop-relative bboxes are
        # transformed explicitly and retain both coordinate spaces.
        focused_prompt = ("Inspect only this cropped answer area. Detect every visible student handwriting mark, "
                          "including handwritten formulas and drawings. Never return printed question text. "
                          "Coordinates are normalized to this crop. Return JSON only.")
        scoped_audit = []
        if retry_refs:
            image_doc = pymupdf.open(str(page_path))
            try:
                page = image_doc[0]
                width, height = page.rect.width, page.rect.height
                for anchor in model_anchors:
                    ref = anchor["question_ref"]
                    if ref not in retry_refs:
                        continue
                    box = list(anchor["search_bbox"])
                    crop_box = (int(box[0] * width), int(box[1] * height),
                                max(int(box[2] * width), int(box[0] * width) + 1),
                                max(int(box[3] * height), int(box[1] * height) + 1))
                    fd, crop_name = tempfile.mkstemp(prefix="ricoh-answer-", suffix=".png")
                    os.close(fd)
                    crop_path = Path(crop_name)
                    try:
                        page.get_pixmap(clip=pymupdf.Rect(*crop_box), alpha=False).save(str(crop_path))
                        local = {"question_ref": ref, "answer_regions": [],
                                 "search_bbox": [0.0, 0.0, 1.0, 1.0],
                                 "coordinate_space": "normalized_crop"}
                        try:
                            retry = self._structured_request("ricoh", focused_prompt, ANSWER_PAGE_SCHEMA,
                                {"page_id": page_path.stem, "question_anchors": [local],
                                 "coordinate_space": "normalized_crop"}, [crop_path],
                                grammar=ANSWER_PAGE_GRAMMAR)
                        except (ValueError, TypeError) as exc:
                            scoped_audit.append({"question_ref": ref, "error": str(exc)})
                            continue
                        local_items = retry.get("questions", [])
                        local_regions = list(local_items[0].get("answer_regions", [])) if local_items else []
                        converted = []
                        try:
                            for region in local_regions:
                                b = validate_bbox(region.get("bbox"), CoordinateSpace.NORMALIZED)
                                page_box = [box[0] + b[0] * (box[2]-box[0]),
                                            box[1] + b[1] * (box[3]-box[1]),
                                            box[0] + b[2] * (box[2]-box[0]),
                                            box[1] + b[3] * (box[3]-box[1])]
                                page_box = validate_bbox(page_box, CoordinateSpace.NORMALIZED)
                                converted.append({**region, "bbox": page_box,
                                                  "coordinate_space": "normalized",
                                                  "source_coordinate_space": "normalized_crop",
                                                  "coordinate_transform": {"from": "normalized_crop",
                                                      "to": "normalized", "crop_bbox": box}})
                        except (ValueError, TypeError) as exc:
                            scoped_audit.append({"question_ref": ref, "error": str(exc),
                                                 "coordinate_space": "normalized_crop"})
                            continue
                        by_ref[ref] = {"question_ref": ref, "answer_regions": converted,
                                       "no_answer_detected": not converted}
                        scoped_audit.append({"question_ref": ref, "coordinate_space": "normalized_crop",
                                             "regions": converted})
                    finally:
                        crop_path.unlink(missing_ok=True)
            finally:
                image_doc.close()
        raw = {"page_pass": initial, "initial_error": initial_error,
               "scoped_retries": scoped_audit}
        seen = set()
        result = []
        allowed = {a["question_ref"] for a in anchors}
        anchor_by_ref = {a["question_ref"]: a for a in anchors}
        for item in by_ref.values():
            if item["question_ref"] not in allowed:
                raise ValueError("INVALID_ANSWER_REGION_OWNERSHIP")
            regions = []
            excluded_printed = []
            anchor = anchor_by_ref[item["question_ref"]]
            for region in item["answer_regions"]:
                if region["type"] == "visual" and region["text"]:
                    raise ValueError("INVALID_VISUAL_ANSWER_TEXT")
                region["bbox"] = validate_bbox(region["bbox"], CoordinateSpace.NORMALIZED)
                # A model occasionally echoes the supplied printed anchor.
                # Preserve that raw evidence for audit, but never expose it as
                # a Student Answer region. Only spatial overlap with the
                # authoritative native anchor triggers this exclusion; an
                # answer that repeats words below the prompt remains valid.
                if _bbox_overlap(region["bbox"], anchor.get("bbox")) > 0.2:
                    excluded = dict(region)
                    excluded.update({"ownership": "PRINTED_QUESTION",
                                     "ownership_reason": "overlaps_authoritative_question_anchor",
                                     "review_required": False})
                    excluded_printed.append(excluded)
                    continue
                key = (item["question_ref"], region["type"], tuple(region["bbox"]), region["text"])
                if key in seen:
                    continue
                seen.add(key)
                regions.append(region)
            result.append({"question_ref": item["question_ref"], "answer_regions": regions,
                           "excluded_printed_regions": excluded_printed,
                           "no_answer_detected": bool(not regions)})
        if {x["question_ref"] for x in result} != allowed:
            raise ValueError("MISSING_ANSWER_REGION_QUESTION")
        # Persist the page pass plus every bounded scoped retry as audit
        # provenance.  Only ``result`` below is eligible evidence.
        return raw, {"coordinate_space": "normalized", "questions": result}

    def ricoh_regions(self, page_path, targets):
        """Scoped full-page evidence; one coordinate-contract correction retry at most.

        Raw invalid replies may be retained by the audit sink, but never returned
        as normalized evidence. The caller may persist/crop only the valid return.
        """
        ids = [t["question_id"] for t in targets]
        props = {"region_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"},
                 "question_id": {"type": "string", "enum": ids}, "bbox": BBOX_SCHEMA}
        region = {"type": "object", "additionalProperties": False,
                  "properties": props, "required": list(props)}
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "coordinate_space": {"const": "normalized"},
            "formula_regions": {"type": "array", "maxItems": 6, "items": region},
            "visual_regions": {"type": "array", "maxItems": 6, "items": region},
            "warnings": {"type": "array", "items": {"type": "string"}}},
            "required": ["coordinate_space", "formula_regions", "visual_regions", "warnings"]}
        prompt = ("Locate ONLY the supplied target student answers on the full page. "
                  "Ignore printed questions and personal headers. Do not solve or correct handwriting. "
                  "Return formula_regions for handwritten calculations and visual_regions for drawing answers. "
                  "Graph regions must contain the complete axes, student curve, annotations and surrounding canvas, "
                  "but not neighboring problems. All bbox values MUST be fractions between 0.0 and 1.0 inclusive "
                  "relative to the full image, [left,top,right,bottom]. For example halfway down is 0.5, NOT 500. "
                  "Never use 0-1000 or pixel coordinates. Return concise JSON only, not transcriptions.")
        for attempt in range(2):
            raw = self._structured_request("ricoh", prompt, schema, {"targets": targets}, [page_path])
            try:
                value = normalize_ricoh_regions(raw)
            except ValueError as exc:
                self.audit({"event": "contract_rejected", "role": "ricoh", "attempt": attempt,
                            "error": str(exc)})
                if attempt or str(exc) not in {"INVALID_RICOH_COORDINATES", "INVALID_COORDINATE_SPACE"}:
                    raise
                prompt += " CONTRACT CORRECTION: Your previous bbox violated [0,1]. Reobserve the image and return fractional coordinates only."
                continue
            seen = set()
            for kind in ("formula_regions", "visual_regions"):
                for r in value.get(kind, []):
                    from .core import identifier
                    identifier(r["region_id"])
                    if r["question_id"] not in ids or r["region_id"] in seen:
                        raise ValueError("INVALID_RICOH_REGION_OWNERSHIP")
                    seen.add(r["region_id"])
                    r["page_id"] = f"submission-source-{sha256_file(page_path)[:16]}"
            return self.last_raw, value

    def unimumer(self, crop_path, region):
        raw = self._request("unimumer", PROMPTS["unimumer"], {"region_id": region["region_id"]}, [crop_path])
        parsed = parse_output(raw, "math_ocr", native=[])
        transcription = parsed.get("transcription_normalized") or parsed.get("output", {}).get("recognized_expression", "")
        return raw, {"region_id": region["region_id"], "transcription": transcription,
                     "parser": parsed.get("parser_name"), "parser_warnings": parsed.get("parser_warnings", [])}

    def ornith_reconstruction(self, payload):
        if self.image_resolver is None:
            raise ValueError("RECONSTRUCTION_IMAGE_RESOLVER_REQUIRED")
        images = self.image_resolver(payload)
        if not images:
            raise ValueError("RECONSTRUCTION_IMAGE_MISSING")
        for reference, path in images:
            pages = {p["page_id"]: p for p in payload["source_answer"].get(
                'evidence_images', payload['source_answer']['pages'])}
            if reference not in pages or sha256_file(Path(path)) != pages[reference]["sha256"]:
                raise ValueError("RECONSTRUCTION_IMAGE_IDENTITY_MISMATCH")
        compact = compact_reconstruction_input(payload)
        return self._structured_request("ornith_reconstruction", PROMPTS["ornith_reconstruction"],
                                        RECONSTRUCTION_SCHEMA, compact, images)

    def _structured_request(self, role, prompt, schema, materials, images, *, grammar=None):
        settings = self.config.get("models", {}).get(self.runtime_ids[role],
                                                       self.config.get("models", {}).get(role, {}))
        with self._runtime(role) as endpoint:
            client_role = role
            client = LocalClient({"models": {client_role: {"base_url": endpoint,
                "model_id": settings.get("model_id", role),
                "generation": settings.get("generation", {}),
                "request_timeout_seconds": settings.get("request_timeout_seconds", 300)},
                }, "generation": self.config.get("generation", {})}, client_role)
            content = [{"type": "text", "text": json.dumps(materials, ensure_ascii=False)}]
            for index, item in enumerate(images):
                label, path = item if isinstance(item, tuple) else (str(index), item)
                content.extend([{"type": "text", "text": label}, image_content(path)])
            payload = {"model": settings.get("model_id", role),
                       "messages": [{"role": "system", "content": prompt},
                                    {"role": "user", "content": content}],
                       **generation_payload(client.generation), "stream": False,
                       "response_format": {"type": "json_schema", "json_schema":
                                           {"name": f"{role}_response", "strict": True, "schema": schema}},
                       "chat_template_kwargs": {"enable_thinking": False}}
            if role == "ricoh":
                payload["reasoning_effort"] = "none"
            if grammar is not None:
                payload.pop("response_format")
                payload["grammar"] = grammar
            if role == "ornith_reconstruction":
                props = client.request(endpoint.removesuffix("/v1") + "/props")
                if not props.get("modalities", {}).get("vision", False):
                    raise ValueError("RECONSTRUCTION_MODEL_IMAGE_UNSUPPORTED")
                self.audit({"event": "capability", "role": role, "props": props})
            self.audit({"event": "request", "role": role, "payload": payload})
            started = time.monotonic()
            self.audit({"event": "call", "role": role})
            response = client.request(client.base + "/chat/completions", payload)
            self.last_raw = response
            self.audit({"event": "response", "role": role, "raw": response, "seconds": time.monotonic()-started})
            return parse_response(response, allow_reasoning=False)


def compact_reconstruction_input(payload):
    """Allow-list model evidence; full raw responses remain in audit artifacts."""
    q = payload["question"]
    return {
        "question_id": q["question_id"],
        "question_text": q["context"]["effective_text"],
        "source_refs": [p["page_id"] for p in payload["source_answer"]["pages"]],
        "text_evidence": [{"page_id": p["page_id"],
            "blocks": p["normalized"].get("text_blocks", []),
            "warnings": p["normalized"].get("warnings", [])}
            for p in payload.get("ricoh_evidence", [])],
        "formula_evidence": [{"region_id": f["region_id"], "page_id": f["page_id"],
            "bbox": f["bbox"], "coordinate_space": f.get("coordinate_space", CoordinateSpace.NORMALIZED.value),
            "transcription": f["normalized"].get("transcription", ""),
            "warnings": f.get("warnings", [])}
            for f in payload.get("formula_evidence", [])],
    }
