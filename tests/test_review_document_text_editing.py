"""Fast contract tests for editable teacher text and immutable PDF evidence."""
from copy import deepcopy
import unittest

from scoring.review_document import ReviewError, initial_snapshot, validate_snapshot


class ReviewTextEditingTests(unittest.TestCase):
    def setUp(self):
        self.draft = {"nodes": [{
            "stable_key": "q1", "parent_key": None, "node_type": "major_question", "depth": 0,
            "sort_order": 0, "label": {"raw": "問題1", "normalized": "問題1"},
            "body_text": "元の問題文", "ordered_content": [
                {"type": "text", "order": 0, "text": "元の問題文", "page_index": 0,
                 "bbox": [60.0, 55.0, 285.0, 73.0], "source_element_ids": ["span-1"]},
                {"type": "formula_region", "order": 1, "region_id": "f1"},
                {"type": "text", "order": 2, "text": "続き"}],
            "review_flags": [], "score": {"semantics": "direct", "points": 10,
                                          "effective_points_candidate": 10},
        }], "formula_regions": [{"region_id": "f1", "assigned_question_key": "q1",
                                "text_fragments": []}], "figure_regions": [], "review_flags": []}
        self.pin = {"run_id": None, "results": []}
        self.current = initial_snapshot("draft-hash", self.draft, self.pin)

    def test_text_insert_reorder_and_delete_keep_formula_anchor(self):
        changed = deepcopy(self.current)
        items = changed["nodes"][0]["ordered_content"]
        items.insert(1, {"type": "text", "order": 0, "text": "追加"})
        # A browser JSON round trip serializes integral float coordinates as integers.
        items[0]["bbox"] = [60, 55, 285, 73]
        for index, item in enumerate(items):
            item["order"] = index
        result = validate_snapshot(changed, self.current, self.draft, self.pin)
        self.assertEqual([item["type"] for item in result["nodes"][0]["ordered_content"]],
                         ["text", "text", "formula_region", "text"])
        removed = deepcopy(result)
        removed["nodes"][0]["ordered_content"] = [
            item for item in removed["nodes"][0]["ordered_content"] if item.get("text") != "元の問題文"]
        for index, item in enumerate(removed["nodes"][0]["ordered_content"]):
            item["order"] = index
        result = validate_snapshot(removed, result, self.draft, self.pin)
        self.assertEqual(result["nodes"][0]["body_text"], "追加\n続き")

    def test_pdf_formula_anchor_and_text_provenance_cannot_be_forged(self):
        changed = deepcopy(self.current)
        changed["nodes"][0]["ordered_content"][1]["region_id"] = "other"
        with self.assertRaisesRegex(ReviewError, "source_anchor_changed"):
            validate_snapshot(changed, self.current, self.draft, self.pin)

    def test_formula_reorder_and_text_merge_preserve_both_sources(self):
        second = {"type": "text", "order": 1, "text": "後半", "page_index": 0,
                  "bbox": [60, 75, 285, 95], "source_element_ids": ["span-2"]}
        self.draft["nodes"][0]["ordered_content"].insert(1, second)
        for index, item in enumerate(self.draft["nodes"][0]["ordered_content"]):
            item["order"] = index
        current = initial_snapshot("draft-hash", self.draft, self.pin)
        changed = deepcopy(current)
        items = changed["nodes"][0]["ordered_content"]
        # Move the formula past the trailing text, then merge two adjacent
        # PDF-backed text spans without discarding the second span's evidence.
        items[2], items[3] = items[3], items[2]
        source = {k: v for k, v in items[1].items() if k not in {"type", "order", "text"}}
        items[0]["text"] += items[1]["text"]
        items[0]["merged_source_segments"] = [source]
        del items[1]
        for index, item in enumerate(items):
            item["order"] = index
        result = validate_snapshot(changed, current, self.draft, self.pin)
        merged = result["nodes"][0]["ordered_content"][0]
        self.assertEqual(merged["source_element_ids"], ["span-1"])
        self.assertEqual(merged["merged_source_segments"][0]["source_element_ids"], ["span-2"])
        self.assertEqual([item["type"] for item in result["nodes"][0]["ordered_content"]],
                         ["text", "text", "formula_region"])
        forged = deepcopy(result)
        forged["nodes"][0]["ordered_content"][0]["merged_source_segments"][0]["source_element_ids"] = ["fake"]
        with self.assertRaisesRegex(ReviewError, "source_anchor_changed"):
            validate_snapshot(forged, result, self.draft, self.pin)
        changed = deepcopy(self.current)
        changed["nodes"][0]["ordered_content"].append({
            "type": "text", "order": 3, "text": "偽造", "page_index": 999})
        with self.assertRaisesRegex(ReviewError, "source_anchor_changed"):
            validate_snapshot(changed, self.current, self.draft, self.pin)
