import tempfile
import unittest
from pathlib import Path

from scoring.cli import ocr_signature, reuse_ocr
from scoring.core import digest, write_json
from scoring.schemas import response_schema


class SchemaTests(unittest.TestCase):
    def test_locate_schema_declares_canonical_normalized_coordinates(self):
        schema = response_schema({"task": "locate", "page_id": "p1",
                                   "questions": [{"question_id": "q1"}]})
        self.assertEqual(schema["properties"]["coordinate_space"], {"const": "normalized"})
        bbox = schema["properties"]["regions"]["items"]["properties"]["bbox"]
        self.assertEqual(bbox["items"], {"type": "number", "minimum": 0, "maximum": 1})

    def test_reconstruction_requires_string_and_image_evidence(self):
        schema = response_schema({"question_id": "q1", "ocr": {"p1": {}}})
        self.assertEqual(schema["properties"]["transcript"]["type"], "string")
        self.assertEqual(schema["properties"]["evidence"]["minItems"], 1)
        self.assertEqual(schema["properties"]["question_id"], {"const": "q1"})

    def test_grading_limits_scores_to_the_rubric_and_null(self):
        schema = response_schema({"question_id": "q1", "ocr": {"p1": {}}, "rubric": {
            "criteria": [{"criterion_id": "c1", "max_score": 10,
                          "levels": [{"score": 0}, {"score": 5}, {"score": 10}]}]}})
        row = schema["properties"]["criteria"]["items"]["oneOf"][0]
        self.assertEqual(row["properties"]["score"]["enum"], [0, 5, 10, None])

    def test_ocr_reuse_rejects_changed_image_and_changed_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            image = base / "answer.png"
            image.write_bytes(b"image-one")
            source = base / "old/submissions/s1/ocr/ricoh"
            config = {"models": {"ocr": {"model_id": "ricoh"}}, "generation": {}}
            result = source / "p1.json"
            write_json(result, {"page_id": "p1", "text": "x=1", "uncertainties": []})
            write_json(source / "p1.status.json", {
                "state": "success", "result_sha256": digest(result), "signature": {
                    "model": config["models"]["ocr"], "generation": {}, "prompt": "ocr",
                    "materials": {"page_id": "p1"}, "images": [["p1", digest(image)]],
                },
            })
            page = {"page_id": "p1", "path": image}
            reuse_ocr(base / "old", base / "new", "s1", page, config, "ocr")
            self.assertTrue((base / "new/p1.json").exists())
            image.write_bytes(b"different-image")
            with self.assertRaises(ValueError):
                reuse_ocr(base / "old", base / "other", "s1", page, config, "ocr")
            image.write_bytes(b"image-one")
            result.write_text('{}')
            with self.assertRaises(ValueError):
                reuse_ocr(base / "old", base / "other", "s1", page, config, "ocr")


class MathReuseTests(unittest.TestCase):
    def test_math_reuse_requires_matching_engine_parser_and_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            image = base / "answer.png"
            image.write_bytes(b"formula")
            page = {"page_id": "p1", "path": image}
            config = {"models": {"math_ocr": {"model_id": "unimumer",
                       "generation": {"max_output_tokens": 500}}}, "generation": {"temperature": 0}}
            source = base / "old/submissions/s1/ocr/unimumer"
            result = source / "p1.json"
            write_json(result, {"page_id": "p1", "text": "x=1", "latex": ["x=1"],
                                "source": "reasoning_content", "uncertainties": []})
            signature = ocr_signature("unimumer", page, config, "math prompt")
            status = {"state": "success", "result_sha256": digest(result), "signature": signature}
            write_json(source / "p1.status.json", status)
            reuse_ocr(base / "old", base / "new", "s1", page, config, "math prompt", "unimumer")
            self.assertTrue((base / "new/p1.json").exists())
            signature["parser_sha256"] = "outdated-parser"
            write_json(source / "p1.status.json", status)
            with self.assertRaises(ValueError):
                reuse_ocr(base / "old", base / "other", "s1", page, config, "math prompt", "unimumer")
            status["signature"] = ocr_signature("unimumer", page, config, "math prompt")
            write_json(source / "p1.status.json", status)
            config["models"]["math_ocr"]["generation"]["max_output_tokens"] = 1000
            with self.assertRaises(ValueError):
                reuse_ocr(base / "old", base / "other", "s1", page, config, "math prompt", "unimumer")
