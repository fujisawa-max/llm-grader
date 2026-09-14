import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scoring.cli import checkpoint, validate_ocr, validate_reconstruction
from scoring.core import (
    LocalClient, load_assignment, parse_response, safe_path, validate_grade,
    validate_rubric,
)

ROOT = Path(__file__).resolve().parents[1]


def rubric():
    return {"question_id": "q1", "max_score": 5, "criteria": [
        {"criterion_id": "c1", "max_score": 5,
         "levels": [{"score": 0, "condition": "誤答"}, {"score": 5, "condition": "正答"}]}]}


def grade():
    return {"question_id": "q1", "criteria": [
        {"criterion_id": "c1", "max_score": 5, "score": 5, "reason": "正しい",
         "evidence": [{"page_id": "p1", "quote": "x=4"}]}],
        "needs_review": False, "review_reasons": []}


class GradingTests(unittest.TestCase):
    def test_total_is_computed_and_model_total_ignored(self):
        value = grade()
        value["score"] = 100
        self.assertEqual(validate_grade(value, rubric(), {"p1"})["score"], 5)

    def test_unreadable_is_null_not_zero(self):
        value = grade()
        value["criteria"][0]["score"] = None
        result = validate_grade(value, rubric(), {"p1"})
        self.assertIsNone(result["score"])
        self.assertTrue(result["needs_review"])

    def test_invalid_scores_ids_and_evidence_are_rejected(self):
        for key, invalid in [("score", -1), ("score", 10), ("score", True),
                             ("max_score", 10), ("criterion_id", "unknown"),
                             ("evidence", []), ("evidence", [{"page_id": "p2", "quote": "x"}])]:
            with self.subTest(key=key, invalid=invalid):
                value = grade()
                value["criteria"][0][key] = invalid
                with self.assertRaises(ValueError):
                    validate_grade(value, rubric(), {"p1"})

    def test_missing_or_duplicate_criteria_are_rejected(self):
        for rows in [[], grade()["criteria"] * 2]:
            value = grade()
            value["criteria"] = rows
            with self.assertRaises(ValueError):
                validate_grade(value, rubric(), {"p1"})

    def test_mismatched_rubric_total_is_rejected(self):
        r = rubric()
        r["max_score"] = 10
        with self.assertRaises(ValueError):
            validate_rubric(r)

    def test_unresolved_rubric_has_no_total(self):
        r = rubric()
        r["aggregation"] = "unresolved"
        self.assertIsNone(validate_grade(grade(), r, {"p1"})["score"])

    def test_corrected_graph_has_four_five_point_criteria(self):
        r = json.loads((ROOT / "examples/basic-math-small-exam1/questions/q02_2/rubric.json").read_text())
        self.assertEqual(validate_rubric(r), "sum")
        self.assertEqual(len(r["criteria"]), 4)
        self.assertEqual(sum(c["max_score"] for c in r["criteria"]), 20)


class InputTests(unittest.TestCase):
    def test_path_escape_and_symlink_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            (root / "outside").symlink_to(Path(directory), target_is_directory=True)
            for relative in ["../outside", "/tmp/example", "outside/test"]:
                with self.assertRaises(ValueError):
                    safe_path(root, relative)

    def test_missing_image_is_not_a_blank_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "q.md").write_text("question")
            (root / "rubric.json").write_text(json.dumps(rubric()))
            (root / "assignment.json").write_text(json.dumps({
                "assignment_id": "test", "questions": [{"question_id": "q1", "question": "q.md",
                    "rubric": "rubric.json", "reference_answer": None}], "submissions": ["s.json"]}))
            (root / "s.json").write_text(json.dumps({"submission_id": "s1", "pages": [
                {"page_id": "p1", "image": "missing.png"}],
                "answers": [{"question_id": "q1", "page_ids": ["p1"]}]}))
            with self.assertRaises(ValueError):
                load_assignment(root)

    def test_empty_ocr_requires_review(self):
        value = validate_ocr({"page_id": "p1", "text": "", "uncertainties": []}, "p1")
        self.assertTrue(value["uncertainties"])

    def test_reconstruction_uncertainty_cannot_clear_review(self):
        value = {"question_id": "q1", "transcript": "?", "needs_review": False,
                 "uncertainties": [{"page_id": "p1", "reason": "不明"}], "changes": [],
                 "evidence": [{"page_id": "p1", "quote": "?"}]}
        self.assertTrue(validate_reconstruction(value, "q1", {"p1"})["needs_review"])

    def test_truncated_generation_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_response({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})

    def test_remote_server_is_rejected(self):
        with self.assertRaises(ValueError):
            LocalClient({"models": {"ocr": {"base_url": "https://example.com/v1"}}}, "ocr")

    def test_text_only_server_is_rejected(self):
        config = {"models": {"grader": {"base_url": "http://127.0.0.1:8080/v1",
                                        "model_id": "ornith", "label": "Ornith"}}}
        client = LocalClient(config, "grader")
        with patch.object(client, "request", side_effect=[{"data": [{"id": "ornith"}]},
                                                         {"modalities": {"vision": False}}]):
            with self.assertRaisesRegex(ValueError, "画像入力"):
                client.preflight()


class CheckpointTests(unittest.TestCase):
    def test_success_is_reused_but_changed_input_is_rejected(self):
        class Client:
            settings = {"model_id": "test"}
            generation = {}
            calls = 0

            def chat(self, *args):
                self.calls += 1
                return {"choices": [{"finish_reason": "stop", "message": {"content": '{"text":"x"}'}}]}

        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            args = (client, Path(directory), "ocr", "prompt", {"page": 1}, [], lambda v: v)
            checkpoint(*args)
            checkpoint(*args)
            self.assertEqual(client.calls, 1)
            changed = list(args)
            changed[4] = {"page": 2}
            with self.assertRaises(ValueError):
                checkpoint(*changed)

    def test_failed_request_is_saved_and_can_be_resumed(self):
        class Client:
            settings = {}
            generation = {}
            calls = 0

            def chat(self, *args):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("test timeout")
                return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            client = Client()
            args = (client, folder, "ocr", "prompt", {}, [], lambda v: v)
            with self.assertRaises(TimeoutError):
                checkpoint(*args)
            self.assertEqual(json.loads((folder / "ocr.status.json").read_text())["state"], "failed")
            checkpoint(*args)
            self.assertEqual(json.loads((folder / "ocr.status.json").read_text())["state"], "success")


if __name__ == "__main__":
    unittest.main()
