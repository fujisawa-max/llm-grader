import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from scoring.model_answer_drafts import build_model_answer_entries
from scoring.model_answer_visual import compare_model_answer_pages, select_question_text_material
from scoring.pdf_native import PyMuPdfNativeExtractor


class ModelAnswerVisualDifferenceTests(unittest.TestCase):
    def test_visual_comparison_requires_a_unique_question_sheet(self):
        first = SimpleNamespace(material_type="question_sheet", id="q1")
        second = SimpleNamespace(material_type="question_sheet", id="q2")
        answer = SimpleNamespace(material_type="model_answer_source", id="answer")
        self.assertIsNone(select_question_text_material([answer]))
        self.assertIs(select_question_text_material([first, answer]), first)
        self.assertIsNone(select_question_text_material([first, second]))

    def make_pdf(self, path: Path, *, answer: str | None = None, shift: float = 0, font_size: float = 12):
        document = pymupdf.open()
        page = document.new_page(width=420, height=600)
        page.insert_text((30 + shift, 50 + shift), "Question 1", fontsize=font_size)
        page.insert_text((30 + shift, 86 + shift), "Describe the purpose of regularization.", fontsize=font_size)
        if answer:
            page.insert_text((30, 300), answer, fontsize=12)
        document.save(path)
        document.close()

    def extract_ir(self, path: Path, output_dir: Path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return PyMuPdfNativeExtractor(max_pages=10).extract(
            path, source_sha256=digest, material_id="answer-material",
            output_dir=output_dir,
        ).as_dict()

    def question(self):
        return SimpleNamespace(
            id="q1", display_label="問題1", question_number="1", stable_question_key="q1",
            parent_id=None, sort_order=1, is_gradable=True,
            question_text="Describe the purpose of regularization.", content=None,
        )

    def test_added_area_selects_native_answer_text_and_excludes_repeated_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem_pdf = root / "problem.pdf"
            answer_pdf = root / "answer.pdf"
            self.make_pdf(problem_pdf)
            self.make_pdf(answer_pdf, answer="It controls model complexity to reduce overfitting.")
            ir = self.extract_ir(answer_pdf, root / "ir")

            comparison = compare_model_answer_pages(problem_pdf, answer_pdf, ir)
            self.assertEqual(comparison["status"], "used", comparison)
            self.assertGreater(comparison["selected_span_count"], 0)
            region = comparison["regions"][0]
            x0, y0, x1, y1 = region["pdf_bbox"]
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x1, 420)
            self.assertLessEqual(y1, 600)
            allowed = {
                int(page_index): set(element_ids) if element_ids is not None else None
                for page_index, element_ids in comparison["allowed_element_ids_by_page"].items()
            }
            entries = build_model_answer_entries(ir, [self.question()],
                                                 allowed_element_ids_by_page=allowed)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["question_id"], "q1")
            self.assertEqual(entries[0]["answer_text"],
                             "It controls model complexity to reduce overfitting.")
            self.assertTrue(entries[0]["source"]["segments"])
            selected_ids = {element_id for segment in entries[0]["source"]["segments"]
                            for element_id in segment["element_ids"]}
            original_by_id = {item["element_id"]: item
                              for item in ir["pages"][0]["elements"] if item.get("element_id")}
            self.assertTrue(all("It controls" in original_by_id[item]["native_text"]
                                for item in selected_ids))

    def test_small_added_answer_and_minor_page_shift_do_not_trigger_whole_page_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem_pdf = root / "problem.pdf"
            answer_pdf = root / "answer.pdf"
            self.make_pdf(problem_pdf)
            self.make_pdf(answer_pdf, answer="x=1", shift=1.5)
            ir = self.extract_ir(answer_pdf, root / "ir")

            comparison = compare_model_answer_pages(problem_pdf, answer_pdf, ir)
            self.assertEqual(comparison["status"], "used", comparison)
            self.assertLess(comparison["page_diagnostics"][0]["difference_ratio"], 0.1)
            allowed = {
                int(page_index): set(element_ids) if element_ids is not None else None
                for page_index, element_ids in comparison["allowed_element_ids_by_page"].items()
            }
            entries = build_model_answer_entries(ir, [self.question()],
                                                 allowed_element_ids_by_page=allowed)
            self.assertEqual(entries[0]["answer_text"], "x=1")

    def test_page_geometry_or_page_count_mismatch_uses_existing_native_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem_pdf = root / "problem.pdf"
            answer_pdf = root / "answer.pdf"
            self.make_pdf(problem_pdf)
            document = pymupdf.open()
            page = document.new_page(width=500, height=600)
            page.insert_text((30, 50), "Question 1", fontsize=12)
            page.insert_text((30, 86), "Describe the purpose of regularization.", fontsize=12)
            page.insert_text((30, 300), "A short answer.", fontsize=12)
            document.new_page(width=500, height=600)
            document.save(answer_pdf)
            document.close()
            ir = self.extract_ir(answer_pdf, root / "ir")

            comparison = compare_model_answer_pages(problem_pdf, answer_pdf, ir)
            self.assertEqual(comparison["status"], "fallback")
            self.assertEqual(comparison["reason"], "page_count_mismatch")
            self.assertEqual(comparison["allowed_element_ids_by_page"], {})

            single_page_pdf = root / "geometry-mismatch.pdf"
            single_page = pymupdf.open()
            page = single_page.new_page(width=500, height=600)
            page.insert_text((30, 50), "Question 1", fontsize=12)
            page.insert_text((30, 86), "Describe the purpose of regularization.", fontsize=12)
            page.insert_text((30, 300), "A short answer.", fontsize=12)
            single_page.save(single_page_pdf)
            single_page.close()
            single_ir = self.extract_ir(single_page_pdf, root / "single-ir")
            geometry = compare_model_answer_pages(problem_pdf, single_page_pdf, single_ir)
            self.assertEqual(geometry["status"], "fallback")
            self.assertEqual(geometry["page_diagnostics"][0]["reason"], "page_geometry_mismatch")

    def test_small_rendering_variation_without_added_answer_is_not_treated_as_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problem_pdf = root / "problem.pdf"
            answer_pdf = root / "answer.pdf"
            self.make_pdf(problem_pdf)
            self.make_pdf(answer_pdf, shift=1.5, font_size=12.2)
            ir = self.extract_ir(answer_pdf, root / "ir")

            comparison = compare_model_answer_pages(problem_pdf, answer_pdf, ir)
            self.assertEqual(comparison["status"], "fallback", comparison)


if __name__ == "__main__":
    unittest.main()
