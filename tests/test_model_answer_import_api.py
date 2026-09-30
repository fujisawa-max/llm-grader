import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi import HTTPException
from sqlalchemy import select

from scoring.api import create_app
from scoring.api.model_answer_imports import ConfirmRequest, DraftEdit, EntryEdit, ImportCreate
from scoring.db import create_session_factory, init_database
from scoring.db.models import ModelAnswer
from scoring.domain import DomainService


def _endpoint(app, path, method=None):
    return next(route.endpoint for route in app.routes
                if getattr(route, "path", None) == path
                and (method is None or method in getattr(route, "methods", set())))


class ModelAnswerImportApiTests(unittest.TestCase):
    def make_pdf(self, path: Path, text: str):
        document = pymupdf.open()
        page = document.new_page(width=420, height=600)
        page.insert_textbox(pymupdf.Rect(30, 30, 390, 560), text, fontsize=14, lineheight=1.6)
        document.save(path)
        document.close()

    def make_fixture(self, root: Path, text: str):
        engine, factory = create_session_factory(f"sqlite:///{root / 'isolated.sqlite'}")
        init_database(engine)
        with factory() as session:
            domain = DomainService(session)
            user = domain.user(display_name="Fixture teacher")
            course = domain.course(user.id, name="Isolated course")
            offering = domain.offering(course.id, academic_year=2026, term="fall")
            test = domain.test(offering.id, name="Isolated test", total_points=20)
            q1 = domain.question(test.id, question_number="1", display_label="問題1", sort_order=1,
                                 max_points=10, is_gradable=True)
            q2 = domain.question(test.id, question_number="2", display_label="問題2", sort_order=2,
                                 max_points=None, is_gradable=False)
            q21 = domain.question(test.id, question_number="2.1", display_label="(1)", sort_order=1,
                                  parent_id=q2.id, max_points=5, is_gradable=True)
            q22 = domain.question(test.id, question_number="2.2", display_label="(2)", sort_order=2,
                                  parent_id=q2.id, max_points=5, is_gradable=True)
            session.flush()
            pdf_path = root / "answer.pdf"
            self.make_pdf(pdf_path, text)
            digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            source = root / "sources" / test.id / f"{digest}.pdf"
            source.parent.mkdir(parents=True)
            source.write_bytes(pdf_path.read_bytes())
            material = domain.material(test.id, material_type="model_answer_source",
                                       storage_ref=str(source), original_filename="answer.pdf",
                                       mime_type="application/pdf", sha256=digest)
            session.commit()
            return factory, test.id, material.id, q1.id, q21.id, q22.id

    def test_native_draft_edit_confirm_provenance_and_versioning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, q21_id, q22_id = self.make_fixture(
                root,
                "Question 1\nAnswer one\nQuestion 2\n(1) Answer two one\n(2) Answer two two",
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual([entry["question_id"] for entry in draft["entries"]], [q1_id, q21_id, q22_id])
                self.assertEqual([entry["mapping_state"] for entry in draft["entries"]], ["automatic"] * 3)
                entries = [EntryEdit(id=entry["id"], question_id=entry["question_id"],
                                     answer_text=entry["answer_text"] + " revised")
                           for entry in draft["entries"]]
                updated = update(draft["id"], DraftEdit(expected_revision=1, entries=entries), session)
                self.assertEqual(updated["revision"], 2)
                saved = confirm(draft["id"], ConfirmRequest(expected_revision=2), session)
                self.assertEqual(len(saved["model_answers"]), 3)
                self.assertEqual({item["question_id"] for item in saved["model_answers"]}, {q1_id, q21_id, q22_id})
                for answer in saved["model_answers"]:
                    self.assertEqual(answer["material_id"], material_id)
                    self.assertEqual(answer["provenance_json"]["source_sha256"], draft["source_sha256"])
                    self.assertTrue(answer["provenance_json"]["segments"])
                self.assertEqual(saved["draft"]["state"], "confirmed")

                second = create(test_id, ImportCreate(material_id=material_id), session)
                second_entries = [EntryEdit(id=entry["id"], question_id=entry["question_id"],
                                            answer_text=entry["answer_text"] + " version two")
                                  for entry in second["entries"]]
                second = update(second["id"], DraftEdit(expected_revision=1, entries=second_entries), session)
                second_saved = confirm(second["id"], ConfirmRequest(expected_revision=2), session)
                self.assertEqual({item["version"] for item in second_saved["model_answers"]}, {2})
                rows = list(session.scalars(select(ModelAnswer).where(ModelAnswer.test_id == test_id)))
                self.assertEqual(len(rows), 6)
                self.assertEqual(sum(row.is_current for row in rows if row.question_id == q1_id), 1)
                current_q1 = next(row for row in rows if row.question_id == q1_id and row.is_current)
                self.assertIn("version two", current_q1.answer_text)

    def test_manual_mapping_accepts_owned_question_and_rejects_fake_question(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _q21_id, _q22_id = self.make_fixture(
                root, "Question 9\nAn answer requiring teacher mapping",
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual(draft["entries"][0]["mapping_state"], "needs_review")
                with self.assertRaises(HTTPException) as caught:
                    update(draft["id"], DraftEdit(expected_revision=1, entries=[EntryEdit(
                        id=draft["entries"][0]["id"], question_id="foreign-question", answer_text="answer",
                    )]), session)
                self.assertEqual(caught.exception.status_code, 422)
                session.rollback()
                updated = update(draft["id"], DraftEdit(expected_revision=1, entries=[EntryEdit(
                    id=draft["entries"][0]["id"], question_id=q1_id, answer_text="Teacher-mapped answer",
                )]), session)
                self.assertEqual(updated["entries"][0]["mapping_state"], "manual_mapped")
                self.assertEqual(updated["entries"][0]["question_id"], q1_id)


if __name__ == "__main__":
    unittest.main()
