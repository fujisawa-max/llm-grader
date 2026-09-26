"""A deterministic end-to-end test, with no real answers or model server."""

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from scoring.cli import run_exam
from scoring.core import read_json, write_json


class PipelineTests(unittest.TestCase):
    def test_image_reaches_all_stages_and_reference_only_reaches_grading(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            assignment = base / "assignment"
            assignment.mkdir()
            (assignment / "question.md").write_text("TEST_QUESTION")
            (assignment / "reference.md").write_text("SECRET_REFERENCE")
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
            pix.clear_with(255)
            pix.save(assignment / "answer.png")
            original_image = (assignment / "answer.png").read_bytes()
            write_json(assignment / "rubric.json", {
                "question_id": "q1", "max_score": 5, "criteria": [{"criterion_id": "c1",
                "max_score": 5, "levels": [{"score": 0}, {"score": 5}]}]})
            write_json(assignment / "assignment.json", {"assignment_id": "test", "questions": [{
                "question_id": "q1", "question": "question.md", "rubric": "rubric.json",
                "reference_answer": "reference.md"}], "submissions": ["submission.json"]})
            write_json(assignment / "submission.json", {"submission_id": "s1", "pages": [
                {"page_id": "p1", "image": "answer.png"}], "answers": [
                {"question_id": "q1", "page_ids": ["p1"]}]})
            write_json(base / "expected.json", {"expected_scores": {"s1": 98765}})
            write_json(base / "config.json", {"execution_mode": "resident_serial",
                "models": {r: {"model_id": r} for r in ("ocr", "math_ocr", "grader")}})
            calls = []
            responses = [
                {"page_id": "p1", "text": "x=4", "uncertainties": []},
                {"page_id": "p1", "coordinate_space": "normalized", "needs_review": False,
                 "questions": [{"question_id": "q1", "status": "located", "reason": "数式あり"}],
                 "regions": [{"region_id": "r1", "question_id": "q1", "kind": "math",
                              "bbox": [0.1, 0.1, 0.4, 0.4], "description": "解答の式"}]},
                "MATH_RESPONSE",
                {"question_id": "q1", "transcript": "x=4", "needs_review": False,
                 "uncertainties": [], "changes": [], "evidence": [{"page_id": "p1", "quote": "x=4"}]},
                {"question_id": "q1", "needs_review": False, "review_reasons": [],
                 "criteria": [{"criterion_id": "c1", "score": 5, "max_score": 5,
                               "reason": "correct", "evidence": [{"page_id": "p1", "quote": "x=4"}]}]},
            ]

            class FakeClient:
                def __init__(self, config, role):
                    self.settings = config["models"][role]
                    self.generation = {}

                def preflight(self):
                    return {"test": True}

                def chat(self, prompt, materials, images):
                    calls.append((prompt, materials, images))
                    value = responses[len(calls) - 1]
                    message = ({"content": "", "reasoning_content": r"PRIVATE_PROSE \[x=4\]"}
                               if value == "MATH_RESPONSE" else {"content": json.dumps(value)})
                    return {"choices": [{"finish_reason": "stop", "message": message}]}

            args = argparse.Namespace(config=str(base / "config.json"), assignment=str(assignment),
                                      run=str(base / "run"), stage="all", submission=None)
            with patch("scoring.cli.LocalClient", FakeClient), patch("scoring.cli.fcntl.flock"):
                # Inference is mocked; do not contend with a real local pilot run.
                args.stage = "ocr"
                args.ocr_engine = "ricoh"
                run_exam(args)
                self.assertEqual(len(calls), 2)
                args.ocr_engine = "unimumer"
                run_exam(args)
                self.assertEqual(len(calls), 3)
                args.stage = "grade"
                args.ocr_engine = "both"
                run_exam(args)
                args.stage = "all"
                run_exam(args)
                args.stage = "grade"
                # Missing one OCR must stop grading instead of silently falling back.
                (base / "run/submissions/s1/ocr/unimumer/regions/p1/r1/transcription.status.json").unlink()
                with self.assertRaises(OSError):
                    run_exam(args)
            self.assertEqual(len(calls), 5, "successful checkpoints should avoid repeated inference")
            for index, (_, materials, images) in enumerate(calls):
                if index == 2:
                    self.assertNotEqual(images[0][1].read_bytes(), original_image)
                    self.assertEqual(materials["region"]["question_id"], "q1")
                    self.assertIn("bbox_pixels", materials["crop"])
                else:
                    self.assertEqual(images[0][1].read_bytes(), original_image)
                self.assertNotIn("98765", json.dumps(materials))
            for _, materials, _ in calls[:4]:
                self.assertNotIn("SECRET_REFERENCE", json.dumps(materials))
                self.assertNotIn("rubric", materials)
            for _, materials, _ in calls[3:]:
                self.assertEqual(set(materials["ocr"]["p1"]), {"ricoh", "unimumer"})
                self.assertEqual(materials["ocr"]["p1"]["unimumer"]["latex"], ["x=4"])
                self.assertNotIn("PRIVATE_PROSE", json.dumps(materials))
            self.assertEqual(calls[4][1]["reference_answer"], "SECRET_REFERENCE")
            self.assertEqual(read_json(base / "run/totals.json")["provisional_scores"], {"s1": 5})
            self.assertFalse((base / "run/inputs/assignment/expected.json").exists())


if __name__ == "__main__":
    unittest.main()
