import copy
import tempfile
import unittest
from pathlib import Path

import pymupdf

from scoring.regions import crop_image, for_question, process_regions, validate_layout


def layout():
    return {"page_id": "p1", "needs_review": False,
            "questions": [{"question_id": "q1", "status": "located", "reason": "式あり"}],
            "regions": [{"region_id": "r1", "question_id": "q1", "kind": "math",
                         "bbox": [100, 200, 500, 400], "description": "計算"}]}


class LayoutTests(unittest.TestCase):
    def test_invalid_coordinates_and_large_regions_are_rejected(self):
        for box in [[-1, 0, 20, 20], [0, 0, 1001, 20], [0, 50, 20, 10],
                    [0, 0, 0, 20], [True, 0, 20, 20], [0.5, 0, 20, 20], [0, 0, 1000, 1000]]:
            value = layout()
            value["regions"][0]["bbox"] = box
            with self.subTest(box=box), self.assertRaises(ValueError):
                validate_layout(value, "p1", ["q1"])

    def test_question_coverage_and_region_ids_are_validated(self):
        for change in ("missing", "unknown", "duplicate", "blank"):
            value = layout()
            if change == "missing":
                value["questions"] = []
            elif change == "unknown":
                value["regions"][0]["question_id"] = "q2"
            elif change == "duplicate":
                value["regions"] *= 2
            else:
                value["questions"][0]["status"] = "blank"
            if change == "blank":
                self.assertEqual(validate_layout(value, "p1", ["q1"])["questions"][0]["status"], "unreadable")
            else:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_layout(value, "p1", ["q1"])

    def test_unreadable_is_distinct_from_blank(self):
        value = layout()
        value["regions"] = []
        value["questions"][0]["status"] = "unreadable"
        self.assertEqual(validate_layout(value, "p1", ["q1"])["questions"][0]["status"], "unreadable")

    def test_other_question_formulas_are_not_forwarded(self):
        value = {"regions": [{"question_id": q, "ocr": {"text": q, "latex": [q]}}
                             for q in ("q1", "q2")], "coverage": [{"question_id": "q1"},
                             {"question_id": "q2"}], "text": "q1\nq2", "latex": ["q1", "q2"]}
        result = for_question(value, "q1")
        self.assertEqual(result["latex"], ["q1"])
        self.assertEqual(len(result["regions"]), 1)


class CropTests(unittest.TestCase):
    def test_native_pixels_padding_edges_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            source, dest = Path(directory) / "page.png", Path(directory) / "crop.png"
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 80), False)
            pix.clear_with(255)
            pix.set_pixel(50, 40, (255, 0, 0))
            pix.save(source)
            original = source.read_bytes()
            metadata = crop_image(source, [400, 400, 600, 600], dest, padding=0)
            self.assertEqual(metadata["bbox_pixels"], [40, 32, 60, 48])
            self.assertEqual(pymupdf.Pixmap(str(dest)).pixel(10, 8), (255, 0, 0))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(crop_image(source, [400, 400, 600, 600], dest, 0), metadata)
            edge = crop_image(source, [0, 0, 100, 100], Path(directory) / "edge.png")
            self.assertEqual(edge["bbox_pixels"], [0, 0, 22, 20])
            dest.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                crop_image(source, [400, 400, 600, 600], dest, 0)

    def test_graph_regions_are_not_sent_to_formula_model(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            value = layout()
            value["regions"][0]["kind"] = "graph"
            value["questions"][0]["status"] = "no_math"
            validate_layout(value, "p1", ["q1"])
            source = folder / "source.png"
            source.write_bytes(b"not-decoded-because-graph")
            def no_request(*args, **kwargs):
                self.fail("graph must not be sent to Uni-MuMER")
            result = process_regions({"page_id": "p1", "path": source}, {}, value, folder,
                                     {"models": {"math_ocr": {}}}, "prompt", no_request, object())
            self.assertEqual(result["latex"], [])
            self.assertEqual(result["coverage"][0]["status"], "no_math")
            self.assertTrue(result["uncertainties"])
            altered = copy.deepcopy(value)
            altered["questions"][0]["reason"] = "changed"
            with self.assertRaises(ValueError):
                process_regions({"page_id": "p1", "path": source}, {}, altered, folder,
                                {"models": {"math_ocr": {}}}, "prompt", no_request)


class RegionResumeTests(unittest.TestCase):
    def test_retry_only_failed_region_and_reject_modified_crop(self):
        import json
        from scoring.cli import checkpoint

        class Client:
            settings = {}
            generation = {}
            calls = 0

            def chat(self, prompt, materials, images):
                self.calls += 1
                if self.calls == 2:
                    return {"choices": [{"finish_reason": "length", "message": {"content": "x=2"}}]}
                return {"choices": [{"finish_reason": "stop", "message": {"content": "x=1"}}]}

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "source.png"
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
            pix.clear_with(255)
            pix.save(source)
            plan = layout()
            plan["regions"].append({**plan["regions"][0], "region_id": "r2",
                                    "bbox": [600, 600, 900, 800]})
            client = Client()
            args = ({"page_id": "p1", "path": source}, {}, plan, folder,
                    {"models": {"math_ocr": {}}}, "math prompt", checkpoint)
            process_regions(*args, client)
            self.assertTrue((folder / "p1.json").exists())
            result = process_regions(*args, client)
            self.assertEqual(client.calls, 2)
            self.assertEqual(len(result["regions"]), 2)
            self.assertEqual(process_regions(*args), result)
            self.assertEqual(json.loads((folder / "p1.json").read_text()), result)
            (folder / "regions/p1/r2.png").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                process_regions(*args)
