from types import SimpleNamespace
import unittest

from scoring.model_answer_drafts import build_model_answer_entries, question_choices


def _ir(lines):
    elements = []
    for line_index, text in enumerate(lines):
        elements.append({
            "element_id": f"page-0001-span-0000-{line_index:04d}-0000",
            "type": "text",
            "native_text": text,
            "reading_order": line_index,
            "native": {"block_index": 0, "line_index": line_index, "span_index": 0},
            "bbox": [10, line_index * 16, 220, line_index * 16 + 12],
        })
    return {"source": {"material_id": "material-1", "sha256": "a" * 64,
                       "page_count": 1},
            "pages": [{"page_index": 0, "elements": elements}]}


class ModelAnswerDraftTests(unittest.TestCase):
    def setUp(self):
        self.questions = [
            SimpleNamespace(id="q1", display_label="問題1", question_number="1", stable_question_key="q1",
                            parent_id=None, sort_order=1, is_gradable=True),
            SimpleNamespace(id="q2", display_label="問題2", question_number="2", stable_question_key="q2",
                            parent_id=None, sort_order=2, is_gradable=False),
            SimpleNamespace(id="q2a", display_label="(1)", question_number="2.1", stable_question_key="q2.1",
                            parent_id="q2", sort_order=1, is_gradable=True),
            SimpleNamespace(id="q2b", display_label="(2)", question_number="2.2", stable_question_key="q2.2",
                            parent_id="q2", sort_order=2, is_gradable=True),
        ]

    def test_explicit_root_and_nested_markers_map_to_existing_question_tree(self):
        entries = build_model_answer_entries(_ir([
            "Question 1", "Answer one", "Question 2", "（1）First subanswer", "(2) Second subanswer",
        ]), self.questions)
        self.assertEqual([(entry["question_id"], entry["answer_text"]) for entry in entries], [
            ("q1", "Answer one"), ("q2a", "First subanswer"), ("q2b", "Second subanswer"),
        ])
        self.assertTrue(all(entry["mapping_state"] == "automatic" for entry in entries))
        self.assertEqual(entries[1]["source"]["material_id"], "material-1")
        self.assertTrue(entries[1]["source"]["segments"][0]["element_ids"])

    def test_unmatched_or_ambiguous_marker_stays_unmapped(self):
        questions = self.questions + [SimpleNamespace(
            id="other-1", display_label="(1)", question_number="3.1", stable_question_key="q3.1",
            parent_id="q3", sort_order=1, is_gradable=True)]
        entries = build_model_answer_entries(_ir(["Question 3", "1. Unique?", "Free text"]), questions)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["question_id"])
        self.assertEqual(entries[0]["mapping_state"], "needs_review")

    def test_question_choices_are_hierarchical_and_gradable_only(self):
        choices = question_choices(self.questions)
        self.assertEqual([item["id"] for item in choices], ["q1", "q2a", "q2b"])
        self.assertEqual(choices[1]["label"], "問題2 > (1)")


if __name__ == "__main__":
    unittest.main()
