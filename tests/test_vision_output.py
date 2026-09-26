import json
import unittest

from scoring.pdf_native import canonical_hash
from scoring.vision_output import parse_output


def raw(text, field="content", **extra):
    return {"choices": [{"message": {field: text}, **extra}]}


class FormulaOutputTests(unittest.TestCase):
    def test_content_and_whitespace_are_preserved(self):
        v = parse_output(raw("  2 x ^ { 3 } - 2 1 x + 6 9  "), "math_ocr", [])
        self.assertEqual(v["transcription_normalized"], "2 x ^ { 3 } - 2 1 x + 6 9")
        self.assertEqual(v["source_field"], "choices[0].message.content")

    def test_reasoning_fallback(self):
        for field in ("reasoning_content", "reasoning"):
            v = parse_output(raw("x^3", field), "math_ocr", ["x^3"])
            self.assertEqual(v["transcription_normalized"], "x^3")
            self.assertIn("reasoning_output_requires_review", v["review_flags"])

    def test_content_preferred_and_blank_falls_back(self):
        r = raw("x=1")
        r["choices"][0]["message"]["reasoning_content"] = "x=2"
        self.assertEqual(parse_output(r, "math_ocr", [])["transcription_normalized"], "x=1")
        r["choices"][0]["message"]["content"] = "  "
        self.assertEqual(parse_output(r, "math_ocr", [])["transcription_normalized"], "x=2")

    def test_exact_duplicates_only(self):
        v = parse_output(raw("x^3\n```latex\nx^3\n```\nx ^ 3\nx^2"), "math_ocr", [])
        self.assertEqual(v["transcription_normalized"], "x^3\nx ^ 3\nx^2")
        self.assertTrue(v["duplicate_removed"])

    def test_matrix_repeated_rows_not_removed(self):
        s = "\\begin{matrix}\n1 & 0 \\\\\n1 & 0 \\\\\n\\end{matrix}"
        v = parse_output(raw(s), "math_ocr", [])
        self.assertEqual(v["transcription_normalized"], s)
        self.assertFalse(v["duplicate_removed"])

    def test_prose_excluded_with_offsets(self):
        s = "The visible expression:\nx^3\n説明です"
        v = parse_output(raw(s), "math_ocr", [])
        self.assertEqual(v["transcription_normalized"], "x^3")
        for part in v["source_fragments"]:
            self.assertEqual(s[part["start"]:part["end"]], part["text"])
        self.assertIn("non_formula_text_excluded", v["review_flags"])

    def test_empty_and_truncated(self):
        for r in ({}, {"choices": []}, raw("")):
            self.assertIn("vision_output_empty", parse_output(r, "math_ocr", [])["review_flags"])
        self.assertIn("vision_output_truncated", parse_output(raw("x", finish_reason="length"), "math_ocr", [])["review_flags"])

    def test_no_answer_candidate(self):
        v = parse_output(raw("解くと\nx=2"), "math_ocr", [])
        self.assertEqual(v["transcription_normalized"], "")
        self.assertIn("model_answering_detected", v["review_flags"])


class FigureOutputTests(unittest.TestCase):
    def test_json_fences_and_prose(self):
        obj = {"visible_text": ["-2π"], "labels": ["3"], "visual_elements": ["curve"], "spatial_relations": []}
        s = json.dumps(obj)
        for text in (s, "```json\n"+s+"\n```", "```\n"+s+"\n```", "Observation:\n"+s+"\nDone."):
            v = parse_output(raw(text), "ocr", [])
            self.assertTrue(v["structured"])
            self.assertEqual(v["output"], obj)

    def test_malformed_and_plain_fallback(self):
        for text in ('{"visible_text":["π"] "labels":[]}', "横軸にπと書いてある", '__import__("os").system("false")'):
            v = parse_output(raw(text), "ocr", [])
            self.assertFalse(v["structured"])
            self.assertEqual(v["output"]["unparsed_text"], text)
            self.assertIn("vision_output_parse_failed", v["review_flags"])

    def test_echoed_template_does_not_hide_real_prose(self):
        text = 'JSON: {"visible_text":[],"labels":[],"visual_elements":[],"spatial_relations":[]}。\nvisible_textは["π","3"]です。'
        v = parse_output(raw(text, "reasoning_content"), "ocr", [])
        self.assertFalse(v["structured"])
        self.assertEqual(v["output"]["visible_text"], ["π", "3"])
        self.assertIn("json_template_ignored", v["review_flags"])
        self.assertNotIn("visual_elements", v["output"])

    def test_conflicting_json_not_arbitrated(self):
        objects = [{"visible_text": [s], "visual_elements": [], "spatial_relations": []} for s in ("1", "2")]
        v = parse_output(raw("\n".join(map(json.dumps, objects))), "ocr", [])
        self.assertFalse(v["structured"])
        self.assertIn("ambiguous_json_candidates", v["review_flags"])

    def test_answering_not_adopted(self):
        obj = {"visible_text": ["3"], "visual_elements": ["the answer is y=cos(x)"], "spatial_relations": []}
        v = parse_output(raw(json.dumps(obj)), "ocr", [])
        self.assertFalse(v["structured"])
        self.assertNotIn("visual_elements", v["output"])
        self.assertIn("model_answering_detected", v["review_flags"])

    def test_empty(self):
        self.assertIn("vision_output_empty", parse_output(raw(""), "ocr", [])["review_flags"])

    def test_determinism_and_hash_convention(self):
        for role in ("math_ocr", "ocr"):
            a = parse_output(raw("x^3\nx^3"), role, ["x"], region_id="r", source_raw_sha256="a"*64)
            self.assertEqual(a, parse_output(raw("x^3\nx^3"), role, ["x"], region_id="r", source_raw_sha256="a"*64))
            digest = a.pop("normalized_sha256")
            self.assertEqual(digest, canonical_hash(a))
