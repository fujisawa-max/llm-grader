from types import SimpleNamespace
import unittest

from scoring.model_answer_drafts import (
    build_model_answer_entries,
    normalize_question_text,
    question_choices,
    remove_question_text,
)


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

    def test_repeated_question_prefix_is_removed_and_source_metadata_retained(self):
        question = self.questions[0]
        question.question_text = "機械学習における過学習とはどのような状態か説明しなさい。"
        entries = build_model_answer_entries(_ir([
            "Question 1",
            question.question_text,
            "訓練データに適合しすぎて、未知データへの性能が低下した状態。",
        ]), self.questions)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["question_id"], "q1")
        self.assertEqual(entries[0]["answer_text"], "訓練データに適合しすぎて、未知データへの性能が低下した状態。")
        self.assertEqual(entries[0]["question_text_removal"]["method"], "exact")
        self.assertGreaterEqual(len(entries[0]["source"]["segments"]), 2)
        self.assertEqual(entries[0]["source"]["material_id"], "material-1")

    def test_line_break_and_width_variation_is_removed(self):
        question = self.questions[0]
        question.question_text = "TP、FP、FN、TNを用いた計算式を示しなさい。"
        extracted = "TP、FP、FN、TNを用いた\n計算式を示しなさい。\nAccuracy = (TP + TN) / (TP + FP + FN + TN)"
        cleaned, metadata = remove_question_text(question, extracted)
        self.assertEqual(cleaned, "Accuracy = (TP + TN) / (TP + FP + FN + TN)")
        self.assertEqual(metadata["status"], "removed")
        self.assertEqual(normalize_question_text(" ＴＰ、ＦＰ\nＦＮ、ＴＮ "), "tp、fpfn、tn")
        self.assertEqual(normalize_question_text("か\u3099"), normalize_question_text("が"))

    def test_high_confidence_fuzzy_prefix_is_removed(self):
        question = self.questions[0]
        question.question_text = "決定木の過学習を防ぐために、訓練データの複雑さを適切に制御する方法を説明しなさい。"
        extracted = "決定木の過学習を防ぐために、訓練データの複雑さを適切に制御する方法を説明しなさぃ。\n枝刈りを行う。"
        cleaned, metadata = remove_question_text(question, extracted)
        self.assertEqual(cleaned, "枝刈りを行う。")
        self.assertEqual(metadata["method"], "fuzzy")
        self.assertGreaterEqual(metadata["confidence"], 0.97)

    def test_low_confidence_or_short_match_is_not_removed(self):
        question = self.questions[0]
        question.question_text = "説明せよ。"
        short_answer = "説明せよ。具体例を挙げて説明する。"
        cleaned, metadata = remove_question_text(question, short_answer)
        self.assertEqual(cleaned, short_answer)
        self.assertEqual(metadata["status"], "not_removed")

        question.question_text = "決定木の過学習を防ぐために、訓練データの複雑さを適切に制御する方法を説明しなさい。"
        low_confidence = "決定木とは何か、過学習した未知データで複雑さを調べる方法を説明しなさい。\n枝刈りを行う。"
        cleaned, metadata = remove_question_text(question, low_confidence)
        self.assertEqual(cleaned, low_confidence)
        self.assertEqual(metadata["status"], "not_removed")

    def test_nested_question_only_uses_its_own_body(self):
        self.questions[1].question_text = "親設問の導入文は子の本文から除去しない。"
        self.questions[2].question_text = "Accuracy（正解率）を計算しなさい。"
        entries = build_model_answer_entries(_ir([
            "Question 2", "（1）Accuracy（正解率）を計算しなさい。", "式に値を代入して求める。",
        ]), self.questions)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["question_id"], "q2a")
        self.assertEqual(entries[0]["answer_text"], "式に値を代入して求める。")

    def test_formula_in_question_content_participates_in_comparison(self):
        question = self.questions[0]
        question.question_text = ""
        question.content = {"items": [
            {"type": "text", "text": "次の式 "},
            {"type": "formula", "transcription": "x^2 + y^2 = 1"},
            {"type": "text", "text": " を考えなさい。"},
        ]}
        extracted = "次の式 x^2 + y^2 = 1 を考えなさい。\n半径1の円である。"
        cleaned, metadata = remove_question_text(question, extracted)
        self.assertEqual(cleaned, "半径1の円である。")
        self.assertEqual(metadata["status"], "removed")

    def test_question_only_result_remains_as_empty_mapped_entry(self):
        question = self.questions[0]
        question.question_text = "機械学習における過学習とはどのような状態か説明しなさい。"
        entries = build_model_answer_entries(_ir(["Question 1", question.question_text]), self.questions)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["answer_text"], "")
        self.assertEqual(entries[0]["question_text_removal"]["status"], "removed")


if __name__ == "__main__":
    unittest.main()
