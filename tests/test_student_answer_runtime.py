import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scoring.student_answer_runtime import RuntimeStudentAnswerStages
from scoring.core import DEFAULT_GENERATION
import pymupdf


class Manager:
    def __init__(self, runtime_type="managed"):
        self.runtime_type = runtime_type
        self.events = []

    def status(self, runtime_id):
        self.events.append(("status", runtime_id))
        return {"profile": {"runtime_type": self.runtime_type}, "pid": None}

    def ensure_running(self, runtime_id):
        self.events.append(("ensure", runtime_id))
        return {"endpoint": "http://runtime.example/v1"}

    def stop(self, runtime_id):
        self.events.append(("stop", runtime_id))


class Client:
    def __init__(self, *args, **kwargs):
        self.base = "http://runtime.example/v1"
        self.generation = DEFAULT_GENERATION

    def request(self, *args):
        return {"choices": [{"finish_reason": "stop", "message": {"content": '{"coordinate_space":"normalized"}'}}]}


class RuntimeStudentAnswerTests(unittest.TestCase):
    def test_duplicate_compact_regions_are_preserved_and_require_review(self):
        region = {"question_ref": "1", "type": "text", "bbox": [0.1, 0.2, 0.4, 0.5], "text": "x"}
        stages = RuntimeStudentAnswerStages(Manager(), {})
        with patch.object(stages, "_structured_request", return_value={"regions": [dict(region), dict(region)]}):
            _, normalized = stages.ricoh_page_compact(Path("unused.png"))
        self.assertEqual(len(normalized["regions"]), 1)
        self.assertFalse(normalized["review_required"])
        self.assertEqual(normalized["regions"][0]["duplicate_count"], 2)
        self.assertEqual(normalized["warnings"], [])

    def test_different_same_question_regions_require_review(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        a = {"question_ref": "1", "type": "text", "bbox": [0.1, 0.2, 0.4, 0.5], "text": "x"}
        b = {"question_ref": "1", "type": "text", "bbox": [0.1, 0.2, 0.4, 0.6], "text": "x"}
        with patch.object(stages, "_structured_request", return_value={"regions": [a, b]}):
            _, normalized = stages.ricoh_page_compact(Path("unused.png"))
        self.assertEqual(len(normalized["regions"]), 2)
        self.assertTrue(normalized["review_required"])
        self.assertEqual(normalized["warnings"], ["DUPLICATE_RICOH_REGION"])

    def test_compact_rejects_truncation_before_json_decode(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        with patch("scoring.student_answer_runtime.image_content", return_value={}), patch(
                "scoring.student_answer_runtime.LocalClient", Client), patch.object(
                Client, "request", return_value={"choices": [{"finish_reason": "length",
                "message": {"content": '{"regions": []}'}}]}):
            with self.assertRaisesRegex(ValueError, "length"):
                stages.ricoh_page_compact(Path("unused.png"))

    def test_compact_validates_schema_and_bbox_without_repairs(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        for value in ({}, {"regions": [{"question_ref": "1", "type": "visual",
                       "bbox": [0, 0, 1, 1], "text": "description"}]},
                      {"regions": [{"question_ref": "1", "type": "text",
                       "bbox": [100, 200, 300, 400], "text": "text"}]}):
            with self.subTest(value=value), patch.object(stages, "_structured_request", return_value=value):
                with self.assertRaises(ValueError):
                    stages.ricoh_page_compact(Path("unused.png"))

    def test_scoped_retry_transforms_crop_relative_bbox_explicitly(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        anchors = [{"question_ref": "q1", "bbox": [0.1, 0.2, 0.4, 0.3],
                    "search_bbox": [0.2, 0.3, 0.8, 0.7], "canvas_bboxes": []}]
        page_pass = {"questions": [{"question_ref": "q1", "answer_regions": [],
                                     "no_answer_detected": True}]}
        scoped = {"questions": [{"question_ref": "q1", "answer_regions": [{
            "type": "formula", "bbox": [0.1, 0.2, 0.4, 0.5], "text": "x"}],
            "no_answer_detected": False}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(
                stages, "_structured_request", side_effect=[page_pass, scoped]):
            page = Path(directory) / "page.png"
            pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False).save(page)
            _, normalized = stages.ricoh_page_answers(page, anchors)
        region = normalized["questions"][0]["answer_regions"][0]
        for actual, expected in zip(region["bbox"], [0.26, 0.38, 0.44, 0.5]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(region["source_coordinate_space"], "normalized_crop")
        self.assertEqual(region["coordinate_transform"]["crop_bbox"], anchors[0]["search_bbox"])

    def test_scoped_retry_does_not_infer_normalized_1000(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        anchors = [{"question_ref": "q1", "bbox": [0.1, 0.2, 0.4, 0.3],
                    "search_bbox": [0.2, 0.3, 0.8, 0.7], "canvas_bboxes": []}]
        invalid = {"questions": [{"question_ref": "q1", "answer_regions": [{
            "type": "formula", "bbox": [100, 200, 300, 500], "text": "x"}],
            "no_answer_detected": False}]}
        with tempfile.TemporaryDirectory() as directory, patch.object(
                stages, "_structured_request", side_effect=[
                    {"questions": [{"question_ref": "q1", "answer_regions": [],
                                     "no_answer_detected": True}]}, invalid]):
            page = Path(directory) / "page.png"
            pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False).save(page)
            _, normalized = stages.ricoh_page_answers(page, anchors)
        self.assertEqual(normalized["questions"][0]["answer_regions"], [])
        self.assertTrue(normalized["questions"][0]["no_answer_detected"])

    def test_ricoh_request_disables_thinking_and_keeps_schema(self):
        stages = RuntimeStudentAnswerStages(Manager(), {})
        with patch("scoring.student_answer_runtime.image_content", return_value={}), patch(
                "scoring.student_answer_runtime.LocalClient", Client), patch.object(
                Client, "request", return_value={"choices": [{"finish_reason": "stop",
                "message": {"content": '{"regions": []}'}}]}) as request:
            stages.ricoh_page_compact(Path("unused.png"))
        payload = request.call_args.args[1]
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertIn("unit ::=", payload["grammar"])
        self.assertNotIn("response_format", payload)

    def test_owned_runtime_stops_and_role_is_reconstruction_only(self):
        manager = Manager()
        with tempfile.TemporaryDirectory() as directory, patch(
                "scoring.student_answer_runtime.LocalClient", Client):
            page = Path(directory) / "page.png"
            document = pymupdf.open()
            document.new_page(width=100, height=100).get_pixmap().save(page)
            document.close()
            stages = RuntimeStudentAnswerStages(manager, {"models": {"ocr": {}, "math_ocr": {}, "grader": {}}})
            stages.ricoh(page, "q1")
        self.assertIn(("ensure", "ocr"), manager.events)
        self.assertIn(("stop", "ocr"), manager.events)
        self.assertNotIn("grading", str(manager.events))

    def test_truncated_valid_json_is_rejected_and_owned_runtime_released(self):
        manager = Manager()
        with patch("scoring.student_answer_runtime.image_content", return_value={}), patch("scoring.student_answer_runtime.LocalClient", Client), patch.object(
                Client, "request", return_value={"choices": [{"finish_reason": "length",
                "message": {"content": "{}"}}]}):
            with self.assertRaisesRegex(ValueError, "length"):
                RuntimeStudentAnswerStages(manager, {}).ricoh(Path("unused.png"), "q1")
        self.assertIn(("stop", "ocr"), manager.events)

    def test_borrowed_runtime_is_not_stopped(self):
        manager = Manager(runtime_type="external")
        with tempfile.TemporaryDirectory() as directory, patch(
                "scoring.student_answer_runtime.LocalClient", Client):
            page = Path(directory) / "page.png"
            document = pymupdf.open()
            document.new_page(width=100, height=100).get_pixmap().save(page)
            document.close()
            RuntimeStudentAnswerStages(manager, {"models": {"ocr": {}}}).ricoh(page, "q1")
        self.assertNotIn(("stop", "ocr"), manager.events)

    def test_ricoh_normalized_view_requires_explicit_canonical_space(self):
        manager = Manager()
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "page.png"
            document = pymupdf.open()
            document.new_page(width=100, height=200).get_pixmap().save(page)
            document.close()
            stages = RuntimeStudentAnswerStages(manager, {})
            with patch.object(stages, "_structured_request", return_value={
                    "coordinate_space": "normalized", "text_blocks": [],
                    "formula_regions": [{"region_id": "f", "page_id": "page",
                                         "bbox": [0.1, 0.2, 0.5, 0.6]}],
                    "reading_order": [], "warnings": []}):
                _, result = stages.ricoh(page, "q1")
            self.assertEqual(result["coordinate_space"], "normalized")
            self.assertEqual(result["formula_regions"][0]["coordinate_space"], "normalized")
            self.assertEqual(result["formula_regions"][0]["bbox"], [0.1, 0.2, 0.5, 0.6])

            with patch.object(stages, "_structured_request", return_value={
                    "coordinate_space": "normalized_1000", "text_blocks": [],
                    "formula_regions": [], "reading_order": [], "warnings": []}):
                with self.assertRaisesRegex(ValueError, "INVALID_COORDINATE_SPACE"):
                    stages.ricoh(page, "q1")


if __name__ == "__main__":
    unittest.main()
