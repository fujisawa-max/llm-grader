import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scoring.cli import checkpoint
from scoring.core import LocalClient, parse_response, read_json
from scoring.math_ocr import extract_latex_fragments, parse_math_response


def response(content="", reasoning="", finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {
        "content": content, "reasoning_content": reasoning}}]}


class MathExtractionTests(unittest.TestCase):
    def test_content_has_priority(self):
        value = parse_math_response(response(r"x=\frac{1}{2}", "x=999"), "p1")
        self.assertEqual(value["latex"], [r"x=\frac{1}{2}"])
        self.assertEqual(value["source"], "content")

    def test_reasoning_extracts_all_forms_in_order_without_prose(self):
        text = ("Let me read the image.\n```latex\nx=1\n```\n"
                r"Next $$y=2$$ then \[z=3\] and \(a=4\), $b=5$." "\n"
                "LaTeX: c=6\nThis is the final answer.")
        value = parse_math_response(response(None, text), "p1")
        self.assertEqual(value["latex"], ["x=1", "y=2", "z=3", "a=4", "b=5", "c=6"])
        self.assertEqual(value["source"], "reasoning_content")
        self.assertNotIn("Let me", value["text"])
        self.assertTrue(value["uncertainties"])

    def test_bare_latex_repeated_halves_match_eval_handwrite_behavior(self):
        latex = "f = x ^ { 2 } - y ^ { 2 } - 1"
        value = parse_math_response(response(" ", latex + "\n" + latex), "p1")
        self.assertEqual(value["latex"], [latex])
        self.assertTrue(value["duplicate_half_removed"])

    def test_distinct_candidates_and_repeated_content_are_preserved(self):
        self.assertEqual(parse_math_response(response("x=1\nx=1"), "p1")["latex"], ["x=1", "x=1"])
        value = parse_math_response(response("", r"Maybe $x=1$, or $x=7$."), "p1")
        self.assertEqual(value["latex"], ["x=1", "x=7"])

    def test_aligned_environment_and_nested_braces_are_preserved(self):
        text = r"\begin{aligned} x&=\frac{1}{\sqrt{2}}\\ y&=3 \end{aligned}"
        self.assertEqual(extract_latex_fragments(text), [text])

    def test_fenced_delimiters_do_not_duplicate_formula(self):
        self.assertEqual(extract_latex_fragments("```tex\n$$x=1$$\n```"), ["x=1"])

    def test_explanation_or_code_is_not_accepted_as_latex(self):
        for text in ["No expression is visible.", "画像には式がありません。",
                     "```python\nprint(123)\n```", r"\text{This is only prose}"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_math_response(response("", text), "p1")

    def test_nonempty_nonmath_content_does_not_fall_back(self):
        with self.assertRaises(ValueError):
            parse_math_response(response("No answer", "$x=1$"), "p1")

    def test_empty_and_unbalanced_output_fail(self):
        for raw in [response(), response(r"\frac{1}{2")]:
            with self.assertRaises(ValueError):
                parse_math_response(raw, "p1")

    def test_truncated_math_is_saved_with_review_flag(self):
        value = parse_math_response(response("", "$x=1$", "length"), "p1")
        self.assertTrue(value["truncated"])
        self.assertEqual(value["uncertainties"][-1]["location"], "generation")

    def test_ricoh_can_read_reasoning_json_but_grader_cannot(self):
        raw = response(None, '```json\n{"page_id":"p1","text":"x=1","uncertainties":[]}\n```')
        self.assertEqual(parse_response(raw, allow_reasoning=True)["text"], "x=1")
        with self.assertRaises(ValueError):
            parse_response(raw)


class MathRequestTests(unittest.TestCase):
    def test_unimumer_uses_plain_user_request_and_role_generation(self):
        config = {"models": {"math_ocr": {"base_url": "http://127.0.0.1:8082/v1",
                    "model_id": "unimumer-q4", "generation": {"max_output_tokens": 1000}}},
                  "generation": {"temperature": 0, "max_output_tokens": 4096}}
        client = LocalClient(config, "math_ocr")
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "p.png"
            image.write_bytes(b"test")
            with patch.object(client, "request", return_value={}) as request:
                client.chat("transcribe", {"page_id": "p1"}, [("p1", image)])
            url, payload = request.call_args.args
        self.assertEqual(url, "http://127.0.0.1:8082/v1/chat/completions")
        self.assertEqual(payload["max_tokens"], 1000)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("chat_template_kwargs", payload)
        self.assertEqual([m["role"] for m in payload["messages"]], ["user"])
        self.assertEqual(payload["messages"][0]["content"][1]["type"], "image_url")


class MathCheckpointTests(unittest.TestCase):
    def test_truncation_preserves_raw_response_but_not_successful_ocr(self):
        class Client:
            settings = {}
            generation = {}

            def chat(self, *args):
                return response("", "$x=1$", "length")

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            checkpoint(Client(), folder, "p1", "math", {"page_id": "p1"}, [], lambda v: v,
                       parser=lambda raw: parse_math_response(raw, "p1"), parser_signature="test")
            self.assertEqual(read_json(folder / "p1.status.json")["state"], "success")
            self.assertEqual(len(list(folder.glob("*.raw.json"))), 1)
            self.assertTrue(read_json(folder / "p1.json")["truncated"])
