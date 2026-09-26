import unittest

from scoring.region_ownership import classify_regions


class RegionOwnershipTests(unittest.TestCase):
    def test_native_text_is_printed_and_not_student_answer(self):
        region = {"question_ref": "Q1", "type": "text", "bbox": [0.1, 0.2, 0.4, 0.3], "text": "Question text"}
        result = classify_regions([region], {"Q1": "Question text"})[0]
        self.assertEqual(result["ownership"], "PRINTED_QUESTION")
        self.assertFalse(result["review_required"])

    def test_same_bbox_mixed_text_requires_review(self):
        region = {"question_ref": "Q1", "type": "text", "bbox": [0.1, 0.2, 0.4, 0.3], "text": "Question text answer"}
        result = classify_regions([region], {"Q1": "Question text"},
                                  native_regions={"Q1": [0.1, 0.2, 0.4, 0.3]})[0]
        self.assertEqual(result["ownership"], "MIXED")
        self.assertTrue(result["review_required"])

    def test_region_inside_authoritative_answer_search_is_handwriting(self):
        region = {"question_ref": "Q1", "type": "text",
                  "bbox": [0.1, 0.31, 0.8, 0.5], "text": "student writing"}
        result = classify_regions(
            [region], {"Q1": "Question text"},
            native_regions={"Q1": [0.1, 0.2, 0.4, 0.3]},
            answer_search_regions={"Q1": [0.0, 0.3, 1.0, 0.6]},
        )[0]
        self.assertEqual(result["ownership"], "STUDENT_HANDWRITING")
        self.assertFalse(result["review_required"])

    def test_region_crossing_next_anchor_is_not_auto_adopted(self):
        region = {"question_ref": "Q1", "type": "text",
                  "bbox": [0.1, 0.31, 0.8, 0.7], "text": "student writing"}
        result = classify_regions(
            [region], {"Q1": "Question text"},
            native_regions={"Q1": [0.1, 0.2, 0.4, 0.3]},
            answer_search_regions={"Q1": [0.0, 0.3, 1.0, 0.6]},
        )[0]
        self.assertEqual(result["ownership"], "UNKNOWN")
        self.assertTrue(result["review_required"])


if __name__ == "__main__":
    unittest.main()
