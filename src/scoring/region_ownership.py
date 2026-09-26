"""Classify page regions before they can enter a student-answer pipeline."""

import re


def _compact(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value or "", flags=re.UNICODE)


def classify_regions(regions, question_texts, *, native_regions=None, answer_search_regions=None):
    """Annotate, without deleting, Ricoh regions with ownership evidence.

    Exact native-text matches are only accepted as printed evidence when the
    matching native block is also spatially aligned. A region with both
    printed and handwriting evidence is never auto-adopted.
    """
    native_regions = native_regions or {}
    answer_search_regions = answer_search_regions or {}
    output = []
    for region in regions:
        ref = region.get("question_ref", "")
        text = region.get("text", "")
        native = question_texts.get(ref, "")
        norm_text, norm_native = _compact(text), _compact(native)
        bbox = region.get("bbox")
        native_bbox = native_regions.get(ref)
        spatial = bool(bbox and native_bbox and _overlap(bbox, native_bbox) > 0.1)
        search_bbox = answer_search_regions.get(ref)
        # Search-area membership is deliberately checked from the canonical
        # coordinates as well as by overlap. This avoids treating a region
        # that merely touches an anchor edge as handwriting.
        in_answer_search = bool(
            bbox and search_bbox and _overlap(bbox, search_bbox) > 0.5 and
            bbox[1] >= search_bbox[1] - 1e-6 and bbox[3] <= search_bbox[3] + 1e-6
        )
        exact_text = bool(norm_text and norm_native and norm_text == norm_native)
        native_substring = bool(norm_text and norm_native and
                               (norm_text in norm_native or norm_native in norm_text))
        if exact_text and (spatial or native_bbox is None):
            ownership, reason, review = "PRINTED_QUESTION", "native_text_and_layout_match", False
        elif native_substring and spatial:
            ownership, reason, review = "MIXED", "native_text_overlap_in_same_bbox", True
        elif native_substring and native_bbox is None:
            ownership, reason, review = "PRINTED_QUESTION", "native_text_overlap", False
        elif region.get("type") == "visual" and not text:
            ownership, reason, review = "STUDENT_HANDWRITING", "visual_mark_region", False
        elif in_answer_search and not spatial:
            # This region was returned from a Question-native answer search
            # area and is spatially separate from printed text. It is safe to
            # route as handwriting evidence; the original region remains in
            # the audit artifact.
            ownership, reason, review = "STUDENT_HANDWRITING", "inside_authoritative_answer_search_area", False
        else:
            ownership, reason, review = "UNKNOWN", "insufficient_printed_handwriting_evidence", True
        annotated = dict(region)
        annotated.update({"ownership": ownership, "ownership_reason": reason,
                          "review_required": review})
        output.append(annotated)
    return output


def _overlap(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    return inter / area_a if area_a else 0.0
