"""Fast contract tests for editable teacher text and immutable PDF evidence."""
from copy import deepcopy
import unittest

from scoring.review_document import (
    ReviewError, initial_snapshot, review_summary, validate_snapshot, warning_catalog,
)


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

    def test_formula_delete_records_exclusion_without_removing_source_region(self):
        changed = deepcopy(self.current)
        node = changed["nodes"][0]
        node["ordered_content"] = [
            {**item, "order": index} for index, item in enumerate(
                item for item in node["ordered_content"] if item.get("region_id") != "f1")]
        node["formula_decisions"]["f1"] = {"decision": "excluded"}
        result = validate_snapshot(changed, self.current, self.draft, self.pin)
        self.assertEqual(result["nodes"][0]["formula_decisions"]["f1"]["decision"], "excluded")
        self.assertEqual(self.draft["formula_regions"][0]["region_id"], "f1")
        self.assertEqual(review_summary(result, self.draft, self.pin)["formula_unreviewed"], 0)
        reviewed = deepcopy(result)
        reviewed["state"], reviewed["reviewed"] = "reviewed", True
        validate_snapshot(reviewed, result, self.draft, self.pin, mark=True)
        forged = deepcopy(changed)
        forged["nodes"][0]["formula_decisions"]["f1"] = {"decision": "use_native"}
        with self.assertRaisesRegex(ReviewError, "formula_content_decision_mismatch"):
            validate_snapshot(forged, self.current, self.draft, self.pin)

    def test_formula_merge_requires_original_anchor_and_inline_text(self):
        changed = deepcopy(self.current)
        node = changed["nodes"][0]
        first, formula, last = node["ordered_content"]
        anchor = {key: value for key, value in formula.items() if key != "order"}
        node["ordered_content"] = [
            {**first, "text": r"元の問題文$\frac{1}{3}$",
             "merged_source_segments": [anchor]},
            {**last, "order": 1},
        ]
        node["formula_decisions"]["f1"] = {
            "decision": "merged_into_text", "teacher_transcription": r"\frac{1}{3}"}
        result = validate_snapshot(changed, self.current, self.draft, self.pin)
        self.assertEqual(result["nodes"][0]["ordered_content"][0]["merged_source_segments"], [anchor])
        self.assertEqual(review_summary(result, self.draft, self.pin)["formula_unreviewed"], 0)
        reviewed = deepcopy(result)
        reviewed["state"], reviewed["reviewed"] = "reviewed", True
        validate_snapshot(reviewed, result, self.draft, self.pin, mark=True)
        forged = deepcopy(changed)
        forged["nodes"][0]["ordered_content"][0]["merged_source_segments"][0]["region_id"] = "fake"
        with self.assertRaisesRegex(ReviewError, "source_anchor_changed"):
            validate_snapshot(forged, self.current, self.draft, self.pin)
        missing_text = deepcopy(changed)
        missing_text["nodes"][0]["ordered_content"][0]["text"] = "元の問題文"
        with self.assertRaisesRegex(ReviewError, "merged_formula_text_missing"):
            validate_snapshot(missing_text, self.current, self.draft, self.pin)

    def test_formula_warning_remains_traceable_after_exclusion(self):
        self.draft["formula_regions"][0]["review_flags"] = ["formula_low_confidence"]
        before = warning_catalog(self.draft, self.pin)
        changed = deepcopy(self.current)
        node = changed["nodes"][0]
        node["ordered_content"] = [
            {**item, "order": index} for index, item in enumerate(
                item for item in node["ordered_content"] if item.get("region_id") != "f1")]
        node["formula_decisions"]["f1"] = {"decision": "excluded"}
        result = validate_snapshot(changed, self.current, self.draft, self.pin)
        self.assertEqual(warning_catalog(self.draft, self.pin), before)
        self.assertEqual(review_summary(result, self.draft, self.pin)["unresolved_warnings"], 1)
        changed = deepcopy(self.current)
        changed["nodes"][0]["ordered_content"].append({
            "type": "text", "order": 3, "text": "偽造", "page_index": 999})
        with self.assertRaisesRegex(ReviewError, "source_anchor_changed"):
            validate_snapshot(changed, self.current, self.draft, self.pin)

    def test_major_split_reassigns_evidence_without_assigning_points(self):
        source_text = "導入\n1. 境界\n2. 領域\n3. 点"
        self.draft["nodes"][0]["ordered_content"][0]["text"] = source_text
        current = initial_snapshot("draft-hash", self.draft, self.pin)
        changed = deepcopy(current)
        parent = changed["nodes"][0]
        original = parent["ordered_content"][0]
        formula = parent["ordered_content"][1]
        lines = source_text.splitlines(keepends=True)
        start = 0
        pieces = []
        for line in lines:
            end = start + len(line)
            pieces.append({**original, "text": line, "source_slice": [start, end, len(source_text)]})
            start = end
        parent["ordered_content"] = [{**pieces[0], "order": 0}, {**parent["ordered_content"][2], "order": 1}]
        parent["score_semantics"], parent["score_points"] = "unset", None
        for index in range(3):
            key = f"teacher-child-{index}"
            content = [{**pieces[index + 1], "order": 0}]
            if index == 1:
                content.append({**formula, "order": 1})
            changed["nodes"].append({
                "review_node_id": key, "stable_key": key, "source_draft_stable_key": None,
                "source_draft_node_id": None, "parent_key": "q1", "node_type": "subquestion",
                "depth": 1, "sort_order": index, "label": {"raw": f"({index+1})", "normalized": f"({index+1})"},
                "body_text": "", "ordered_content": content, "included": True,
                "score_semantics": "unset", "score_points": None, "review_flags": [],
                "formula_decisions": {}, "figure_decisions": {}, "warning_states": {},
            })
        result = validate_snapshot(changed, current, self.draft, self.pin)
        self.assertEqual([n["parent_key"] for n in result["nodes"][1:]], ["q1"] * 3)
        self.assertEqual(result["nodes"][2]["ordered_content"][1]["region_id"], "f1")
        self.assertEqual([n["score_points"] for n in result["nodes"]], [None] * 4)
        self.assertEqual(result["nodes"][2]["ordered_content"][0]["source_element_ids"], ["span-1"])
        forged = deepcopy(changed)
        forged["nodes"][2]["ordered_content"][0]["source_slice"] = [0, 5, len(source_text)]
        with self.assertRaisesRegex(ReviewError, "invalid_source_slice") as context:
            validate_snapshot(forged, current, self.draft, self.pin)
        self.assertEqual(context.exception.node_key, "teacher-child-1")
        self.assertEqual(context.exception.field_key, "source_mapping")

    def test_partial_split_keeps_ambiguous_text_in_parent_without_fabricated_mapping(self):
        draft = deepcopy(self.draft)
        source_text = "導入\n1. 元の境界\n2. 領域を示す\n3. 点のクラスを答える"
        evidence = {"type": "text", "order": 0, "text": source_text, "page_index": 0,
                    "bbox": [60.0, 55.0, 285.0, 73.0], "source_element_ids": ["span-1"]}
        draft["nodes"][0]["ordered_content"] = [evidence]
        draft["formula_regions"] = []
        current = initial_snapshot("draft-hash", draft, self.pin)
        changed = deepcopy(current)
        parent = changed["nodes"][0]
        parent["ordered_content"] = [
            {"type": "text", "order": 0, "text": "導入\n", "source_slice": [0, 3, len(source_text)],
             **{key: value for key, value in evidence.items() if key not in {"type", "order", "text"}}},
            {"type": "text", "order": 1, "text": "新しく書き直した境界"},
        ]
        parent["score_semantics"], parent["score_points"] = "unset", None

        def add_child(key, label, start, end, text):
            changed["nodes"].append({
                "review_node_id": key, "stable_key": key, "source_draft_stable_key": None,
                "source_draft_node_id": None, "parent_key": "q1", "node_type": "subquestion",
                "depth": 1, "sort_order": len(changed["nodes"]) - 1,
                "label": {"raw": label, "normalized": label}, "body_text": text,
                "ordered_content": [{
                    "type": "text", "order": 0, "text": text,
                    "source_slice": [start, end, len(source_text)],
                    **{field: value for field, value in evidence.items() if field not in {"type", "order", "text"}},
                }],
                "included": True, "score_semantics": "unset", "score_points": None,
                "review_flags": [], "formula_decisions": {}, "figure_decisions": {}, "warning_states": {},
            })

        second = "2. 領域を示す"
        third = "3. 点のクラスを答える"
        add_child("teacher-child-2", "(2)", source_text.index(second), source_text.index(second) + len(second), "領域を示す")
        add_child("teacher-child-3", "(3)", source_text.index(third), source_text.index(third) + len(third), "点のクラスを答える")

        result = validate_snapshot(changed, current, draft, self.pin)
        self.assertEqual([node["parent_key"] for node in result["nodes"][1:]], ["q1", "q1"])
        self.assertEqual(result["nodes"][0]["ordered_content"][1]["text"], "新しく書き直した境界")
        self.assertNotIn("source_slice", result["nodes"][0]["ordered_content"][1])
        self.assertEqual([node["ordered_content"][0]["source_slice"] for node in result["nodes"][1:]], [
            [source_text.index(second), source_text.index(second) + len(second), len(source_text)],
            [source_text.index(third), source_text.index(third) + len(third), len(source_text)],
        ])

    def test_save_validation_identifies_node_and_field(self):
        invalid = deepcopy(self.current)
        invalid["nodes"][0]["score_points"] = None
        with self.assertRaises(ReviewError) as context:
            validate_snapshot(invalid, self.current, self.draft, self.pin)
        self.assertEqual(context.exception.code, "score_type_mismatch")
        self.assertEqual(context.exception.node_key, "q1")
        self.assertEqual(context.exception.field_key, "score")
