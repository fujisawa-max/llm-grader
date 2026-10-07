import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from fastapi import HTTPException

from scoring.api import create_app
from scoring.db import create_session_factory, init_database
from scoring.domain import DomainService
from scoring.pdf_native import IR_SCHEMA_VERSION, PyMuPdfNativeExtractor, canonical_hash


class _Request:
    def __init__(self, body, filename="question.pdf", content_type="application/pdf"):
        self._body = body
        self.headers = {"x-filename": filename, "content-type": content_type}

    async def body(self):
        return self._body


def _endpoint(app, path):
    return next(r.endpoint for r in app.routes if getattr(r, "path", None) == path)


class PdfNativeTests(unittest.TestCase):
    def make_pdf(self, folder, *, image=False, rotated=False):
        path = Path(folder) / "source.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=400)
        if rotated:
            page.set_rotation(90)
        page.insert_text((30, 50), "問1（20点）\n次の式を説明しなさい。", fontsize=12)
        page.draw_rect(pymupdf.Rect(20, 100, 100, 160))
        if image:
            image_path = Path(folder) / "embedded.png"
            pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 20, 20), False)
            pix.clear_with(0x336699)
            pix.save(str(image_path))
            page.insert_image(pymupdf.Rect(150, 100, 250, 180), filename=str(image_path))
        doc.save(str(path))
        doc.close()
        return path

    def test_native_ir_contains_layout_image_vector_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.make_pdf(folder, image=True, rotated=True)
            output = Path(folder) / "native"
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            ir = PyMuPdfNativeExtractor().extract(
                source, source_sha256=source_hash, material_id="m1", output_dir=output
            ).as_dict()
            self.assertEqual(ir["schema_version"], IR_SCHEMA_VERSION)
            self.assertEqual(ir["coordinate_space"]["unit"], "PDF_point")
            page = ir["pages"][0]
            self.assertTrue(page["quality_signals"]["has_text_layer"])
            self.assertTrue(any(e["type"] == "text" and e["native"]["font"] for e in page["elements"]))
            self.assertTrue(any(e["type"] == "image" for e in page["elements"]))
            self.assertGreaterEqual(page["quality_signals"]["vector_count"], 1)
            self.assertEqual(json.loads((output / "document-ir.json").read_text())["source"], ir["source"])
            self.assertEqual(json.loads((output / "manifest.json").read_text())["ir_sha256"], canonical_hash(ir))
            self.assertTrue((output / "pages" / "page-0001.json").is_file())
            self.assertTrue((output.parent / "diagnostics" / "quality.json").is_file())
            self.assertNotIn(str(Path(folder).resolve()), json.dumps(ir["pages"]))

    def test_api_registers_material_and_returns_summary_without_absolute_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine, session_factory = create_session_factory(f"sqlite:///{root / 'db.sqlite'}")
            init_database(engine)
            with session_factory() as session:
                domain = DomainService(session)
                user = domain.user(display_name="Teacher")
                course = domain.course(user.id, name="PDF")
                offering = domain.offering(course.id, academic_year=2026, term="fall")
                test = domain.test(offering.id, name="Question sheet", total_points=20)
                session.commit()
                test_id = test.id
            source = self.make_pdf(root, image=True)
            app = create_app(session_factory, question_import_root=root / "artifacts")
            with session_factory() as session:
                route = _endpoint(app, "/api/v1/tests/{test_id}/question-materials")
                result = asyncio.run(route(test_id, _Request(source.read_bytes()), session))
                self.assertEqual(result["state"], "completed")
                self.assertEqual(result["page_count"], 1)
                self.assertEqual(result["parser"]["backend"], "pymupdf")
                self.assertNotIn(str(root), json.dumps(result, default=str))
                doc_route = _endpoint(app, "/api/v1/question-imports/{extraction_id}/document")
                summary = doc_route(result["id"], None, session)
                self.assertEqual(summary["schema_version"], IR_SCHEMA_VERSION)
                self.assertEqual(summary["pages"][0]["element_count"], 3)

    def test_same_test_same_sha_reuses_completed_extraction_but_different_test_is_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine, session_factory = create_session_factory(f"sqlite:///{root / 'db.sqlite'}")
            init_database(engine)
            with session_factory() as session:
                domain = DomainService(session)
                user = domain.user(display_name="Teacher")
                course = domain.course(user.id, name="PDF")
                offering = domain.offering(course.id, academic_year=2026, term="fall")
                first = domain.test(offering.id, name="A", total_points=1)
                second = domain.test(offering.id, name="B", total_points=1)
                session.commit()
                first_id, second_id = first.id, second.id
            source = self.make_pdf(root)
            app = create_app(session_factory, question_import_root=root / "artifacts")
            route = _endpoint(app, "/api/v1/tests/{test_id}/question-materials")
            with session_factory() as session:
                first = asyncio.run(route(first_id, _Request(source.read_bytes()), session))
                self.assertEqual(first["state"], "completed")
            with session_factory() as session:
                repeated = asyncio.run(route(first_id, _Request(source.read_bytes()), session))
                self.assertEqual(repeated["id"], first["id"])
                self.assertEqual(repeated["state"], "completed")
            with session_factory() as session:
                other = asyncio.run(route(second_id, _Request(source.read_bytes()), session))
                self.assertEqual(other["state"], "completed")
                self.assertNotEqual(other["id"], first["id"])

    def test_upload_rejects_traversal_and_non_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine, session_factory = create_session_factory(f"sqlite:///{root / 'db.sqlite'}")
            init_database(engine)
            with session_factory() as session:
                domain = DomainService(session)
                user = domain.user(display_name="Teacher")
                course = domain.course(user.id, name="PDF")
                offering = domain.offering(course.id, academic_year=2026, term="fall")
                test = domain.test(offering.id, name="A", total_points=1)
                session.commit()
            route = _endpoint(create_app(session_factory, question_import_root=root / "artifacts"),
                              "/api/v1/tests/{test_id}/question-materials")
            with session_factory() as session:
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(route(test.id, _Request(b"%PDF-x", filename="../escape.pdf"), session))
                self.assertEqual(caught.exception.status_code, 422)
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(route(test.id, _Request(b"not a pdf"), session))
                self.assertEqual(caught.exception.status_code, 422)

    def test_encrypted_pdf_is_rejected_by_native_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "encrypted.pdf"
            doc = pymupdf.open()
            doc.new_page().insert_text((20, 20), "secret")
            doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
            doc.close()
            with self.assertRaisesRegex(ValueError, "encrypted"):
                PyMuPdfNativeExtractor().extract(path, source_sha256="a" * 64,
                                                  material_id="m", output_dir=Path(folder) / "out")

    def test_multi_page_empty_page_and_page_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "multi.pdf"
            doc = pymupdf.open()
            doc.new_page()
            doc.new_page().insert_text((20, 20), "second page")
            doc.save(str(path))
            doc.close()
            ir = PyMuPdfNativeExtractor(max_pages=2).extract(
                path, source_sha256="b" * 64, material_id="m", output_dir=Path(folder) / "out"
            ).as_dict()
            self.assertEqual(len(ir["pages"]), 2)
            self.assertFalse(ir["pages"][0]["quality_signals"]["has_text_layer"])
            self.assertTrue(ir["pages"][0]["quality_signals"]["no_text_layer"])
            # A genuinely blank page has no evidence of a scan; this is
            # distinct from an image-backed scanned page.
            self.assertFalse(ir["pages"][0]["quality_signals"]["scanned_page_candidate"])
            self.assertFalse(ir["pages"][1]["quality_signals"]["no_text_layer"])
            self.assertFalse(ir["pages"][1]["quality_signals"]["scanned_page_candidate"])
            self.assertIn("no_text_layer", ir["pages"][0]["review_flags"])
            with self.assertRaisesRegex(ValueError, "page count"):
                PyMuPdfNativeExtractor(max_pages=1).extract(
                    path, source_sha256="b" * 64, material_id="m", output_dir=Path(folder) / "limited"
                )

    def test_math_font_and_text_signals_are_explicit_without_marking_prose(self):
        math = PyMuPdfNativeExtractor._span_element(
            0, 0, 0, 0,
            {"text": "sin 𝑥 = π", "bbox": [10, 10, 80, 20],
             "font": "CambriaMath", "size": 14}, 0,
        )
        prose = PyMuPdfNativeExtractor._span_element(
            0, 0, 0, 1,
            {"text": "sinについて説明しなさい。", "bbox": [10, 30, 120, 40],
             "font": "MS-Mincho", "size": 11}, 1,
        )
        self.assertTrue(math["quality_signals"]["math_font_candidate"])
        self.assertTrue(math["quality_signals"]["math_text_candidate"])
        self.assertTrue(math["quality_signals"]["math_like_candidate"])
        self.assertFalse(prose["quality_signals"]["math_font_candidate"])
        self.assertFalse(prose["quality_signals"]["math_text_candidate"])
        self.assertFalse(prose["quality_signals"]["math_like_candidate"])

    def test_vertical_offset_signals_use_nearby_math_evidence(self):
        base = PyMuPdfNativeExtractor._span_element(
            0, 0, 0, 0,
            {"text": "x", "bbox": [40, 20, 50, 34],
             "font": "CambriaMath", "size": 14}, 0,
        )
        superscript = PyMuPdfNativeExtractor._span_element(
            0, 0, 0, 1,
            {"text": "2", "bbox": [51, 17, 57, 25],
             "font": "CambriaMath", "size": 9}, 1,
        )
        prose_number = PyMuPdfNativeExtractor._span_element(
            0, 0, 1, 0,
            {"text": "2026", "bbox": [10, 100, 45, 110],
             "font": "MS-Mincho", "size": 10}, 2,
        )
        elements = [base, superscript, prose_number]
        PyMuPdfNativeExtractor._apply_geometry_signals(elements)
        self.assertTrue(superscript["quality_signals"]["superscript_candidate"])
        self.assertFalse(prose_number["quality_signals"]["superscript_candidate"])

    def test_image_only_page_exposes_scan_and_occupancy_booleans(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image_path = root / "scan.png"
            pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 100, 100), False)
            pix.clear_with(0xFFFFFF)
            pix.save(str(image_path))
            source = root / "scan.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=300, height=400)
            page.insert_image(pymupdf.Rect(0, 0, 300, 400), filename=str(image_path))
            doc.save(str(source))
            doc.close()
            ir = PyMuPdfNativeExtractor().extract(
                source, source_sha256="c" * 64, material_id="m",
                output_dir=root / "out",
            ).as_dict()
            signals = ir["pages"][0]["quality_signals"]
            self.assertFalse(signals["has_text_layer"])
            self.assertTrue(signals["no_text_layer"])
            self.assertTrue(signals["scanned_page_candidate"])
            self.assertTrue(signals["large_image_occupancy"])


if __name__ == "__main__":
    unittest.main()
