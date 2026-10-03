import unittest
from unittest.mock import patch
import json

from scoring.model_answer_classification import ModelAnswerSemanticClassifier
from scoring.rubric_consolidation import (
    RubricGroupingError,
    explicit_points,
    mechanically_premerge_rubric_segments,
    reconstruct_rubric_groups,
    validate_rubric_groups,
)


class RubricConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"id": "s1", "start": 0, "end": 12, "text": "criterion is", "source_text": "criterion is",
             "page_index": 0, "bbox": [10, 10, 100, 20]},
            {"id": "s2", "start": 12, "end": 30, "text": " correctly explained.", "source_text": " correctly explained.",
             "page_index": 0, "bbox": [10, 21, 110, 31]},
            {"id": "s3", "start": 30, "end": 40, "text": "(10点)", "source_text": "(10点)",
             "page_index": 0, "bbox": [10, 32, 40, 42]},
        ]

    def test_explicit_point_extraction_does_not_infer_and_detects_conflict(self):
        self.assertEqual(explicit_points("5 points: criterion")[0:2], ("criterion", 5))
        self.assertEqual(explicit_points("criterion (10点)")[0:2], ("criterion", 10))
        self.assertEqual(explicit_points("criterion")[0:2], ("criterion", None))
        cleaned, points, conflict = explicit_points("first (5点) second (10点)")
        self.assertTrue(conflict)
        self.assertIsNone(points)
        self.assertEqual(cleaned, "first second")

    def test_mechanical_premerge_only_joins_nearby_unfinished_wrapped_line(self):
        result = mechanically_premerge_rubric_segments(self.segments[:2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["member_ids"], ["s1", "s2"])
        self.assertEqual(result[0]["source_text"], "criterion is correctly explained.")

    def test_mechanical_premerge_keeps_sentence_and_question_boundaries(self):
        ended = [dict(self.segments[0], source_text="criterion ends.") , self.segments[1]]
        far = [self.segments[0], dict(self.segments[1], bbox=[250, 21, 350, 31])]
        other_page = [self.segments[0], dict(self.segments[1], page_index=1)]
        for pair in (ended, far, other_page):
            self.assertEqual(len(mechanically_premerge_rubric_segments(pair)), 2)

    def test_group_validation_rejects_duplicate_unknown_missing_and_invalid_kind(self):
        cases = [
            {"groups": [{"group_id": "a", "segment_ids": ["s1", "s1"], "kind": "rubric", "confidence": .9}]},
            {"groups": [{"group_id": "a", "segment_ids": ["fake"], "kind": "rubric", "confidence": .9}]},
            {"groups": [{"group_id": "a", "segment_ids": ["s1"], "kind": "rubric", "confidence": .9}]},
            {"groups": [{"group_id": "a", "segment_ids": ["s1", "s2", "s3"], "kind": "answer", "confidence": .9}]},
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(RubricGroupingError):
                validate_rubric_groups(raw, self.segments)

    def test_deterministic_reconstruction_uses_original_segments_in_reading_order(self):
        groups = validate_rubric_groups({"groups": [{"group_id": "g", "segment_ids": ["s3", "s1", "s2"],
            "kind": "rubric", "confidence": .95}]}, self.segments)
        candidate = reconstruct_rubric_groups(self.segments, groups)[0]
        self.assertEqual(candidate["segment_ids"], ["s1", "s2", "s3"])
        self.assertEqual(candidate["source_text"], "criterion is correctly explained.(10点)")
        self.assertEqual(candidate["description"], "criterion is correctly explained.")
        self.assertEqual(candidate["points"], 10)
        self.assertEqual(candidate["merge_type"], "llm_group")
        self.assertEqual([item["id"] for item in candidate["source_segments"]], ["s1", "s2", "s3"])

    def test_multiple_point_annotations_require_teacher_confirmation(self):
        segments = [dict(self.segments[0], source_text="criterion (5点) "),
                    dict(self.segments[1], id="s2", source_text="evidence (10点)")]
        groups = [{"group_id": "g", "segment_ids": ["s1", "s2"], "kind": "rubric", "confidence": .99}]
        candidate = reconstruct_rubric_groups(segments, groups)[0]
        self.assertTrue(candidate["points_conflict"])
        self.assertTrue(candidate["needs_teacher_review"])
        self.assertEqual(candidate["points"], 0)

    def test_classifier_grouping_returns_only_validated_source_ids(self):
        class Manager:
            calls = 0

            def ensure_running(self, profile_id):
                self.calls += 1
                return {"endpoint": "http://runtime/v1", "profile": {"model_id": "model",
                    "generation": {}, "request_timeout_seconds": 10, "runtime_type": "managed"}}

        class Client:
            generation = {"temperature": 0, "seed": 1, "top_k": 1, "top_p": 1,
                          "min_p": 0, "repeat_penalty": 1, "max_output_tokens": 100}
            timeout = 10

            def __init__(self, *_args):
                pass

            def request(self, _url, request):
                payload = json.loads(request["messages"][1]["content"])
                ids = [segment["id"] for segment in payload["source_segments"]]
                result = {"groups": [{"group_id": "one-criterion", "segment_ids": ids,
                                       "kind": "rubric", "confidence": 0.96}]}
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

        manager = Manager()
        with patch("scoring.model_answer_classification.LocalClient", Client):
            groups = ModelAnswerSemanticClassifier(manager).group_rubric_segments(segments=self.segments)
        self.assertEqual(groups[0]["segment_ids"], ["s1", "s2", "s3"])
        self.assertEqual(groups[0]["confidence"], 0.96)
        self.assertEqual(manager.calls, 1)


if __name__ == "__main__":
    unittest.main()
