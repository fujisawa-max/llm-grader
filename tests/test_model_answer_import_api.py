import hashlib
import tempfile
import unittest
from uuid import uuid4
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi import HTTPException
from sqlalchemy import select

from scoring.api import create_app
from scoring.api.model_answer_imports import (
    ClassificationRequest,
    ConfirmRequest,
    DraftEdit,
    EntryEdit,
    ImportCreate,
    RubricRegistrationRequest,
)
from scoring.db import create_session_factory, init_database
from scoring.db.models import ModelAnswer, ModelAnswerImportDraft, RubricVersion
from scoring.domain import DomainService
from scoring.model_answer_classification import is_effectively_blank, split_source_segments
from scoring.model_answer_drafts import normalize_question_text


def _endpoint(app, path, method=None):
    return next(route.endpoint for route in app.routes
                if getattr(route, "path", None) == path
                and (method is None or method in getattr(route, "methods", set())))


class ModelAnswerImportApiTests(unittest.TestCase):
    def test_draft_discovery_is_source_scoped_newest_first_and_runtime_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, *_ = self.make_fixture(
                root, "Question 1\nAnswer one\nQuestion 2\n(1) Answer two one")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            discover = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-import-drafts")
            with factory() as session:
                older = create(test_id, ImportCreate(material_id=material_id), session)
                newer = create(test_id, ImportCreate(material_id=material_id), session)
                rows = discover(test_id, material_id, session)["drafts"]
                self.assertEqual([row["id"] for row in rows[:2]], [newer["id"], older["id"]])
                self.assertEqual(rows[0]["state"], "editing")
                self.assertTrue(rows[0]["resumable"])
                self.assertEqual(rows[0]["entry_count"], len(newer["entries"]))
                with self.assertRaises(HTTPException) as missing:
                    discover(test_id, "missing-material", session)
                self.assertEqual(missing.exception.status_code, 404)

    def test_saved_answer_load_reference_keeps_pdf_source_and_rejects_wrong_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, q21_id, _ = self.make_fixture(
                root, "Question 1\nAnswer one\nQuestion 2\n(1) Answer two one")
            with factory() as session:
                saved = DomainService(session).model_answer(test_id, question_id=q1_id,
                                                             answer_text="Earlier teacher answer")
                session.commit()
                saved_id = saved.id
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                entry = draft["entries"][0]
                self.assertEqual(draft["saved_answers"][0]["id"], saved_id)
                edited = update(draft["id"], DraftEdit(expected_revision=1, entries=[
                    EntryEdit(id=entry["id"], question_id=q1_id, answer_text="Earlier teacher answer",
                              loaded_model_answer_id=saved_id),
                    EntryEdit(id=draft["entries"][1]["id"], question_id=q21_id,
                              answer_text=draft["entries"][1]["answer_text"]),
                ]), session)
                self.assertEqual(edited["entries"][0]["loaded_model_answer"]["id"], saved_id)
                self.assertEqual(edited["entries"][0]["source"], entry["source"])
                with self.assertRaises(HTTPException) as wrong:
                    update(draft["id"], DraftEdit(expected_revision=2, entries=[
                        EntryEdit(id=entry["id"], question_id=q21_id, answer_text="Wrong",
                                  loaded_model_answer_id=saved_id),
                    ]), session)
                self.assertEqual(wrong.exception.status_code, 422)

    def test_disposition_manual_candidate_and_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, q21_id, _ = self.make_fixture(
                root, "Question 1\nAnswer one\nQuestion 2\n(1) Answer two one")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                original = draft["entries"]
                self.assertEqual(len(original), 2)
                manual_id = f"teacher-entry-{uuid4()}"
                edits = [
                    EntryEdit(id=original[0]["id"], question_id=q1_id, answer_text=original[0]["answer_text"],
                              disposition="excluded"),
                    EntryEdit(id=original[1]["id"], question_id=None, answer_text=original[1]["answer_text"],
                              disposition="unassigned"),
                    EntryEdit(id=manual_id, question_id=q1_id, answer_text="Teacher answer.",
                              disposition="include", answer_kind="primary"),
                ]
                edited = update(draft["id"], DraftEdit(expected_revision=1, entries=edits), session)
                self.assertEqual(edited["entries"][0]["source"], original[0]["source"])
                self.assertEqual(edited["entries"][0]["disposition"], "excluded")
                self.assertEqual(edited["entries"][1]["disposition"], "unassigned")
                self.assertEqual(edited["entries"][2]["source"]["kind"], "teacher_manual")
                self.assertIsNone(edited["entries"][2]["source"]["material_id"])
                saved = confirm(draft["id"], ConfirmRequest(expected_revision=2), session)
                self.assertEqual(saved["draft"]["state"], "editing")
                self.assertEqual(len(saved["model_answers"]), 1)
                answer = saved["model_answers"][0]
                self.assertEqual(answer["question_id"], q1_id)
                self.assertIsNone(answer["material_id"])
                self.assertEqual(answer["provenance_json"]["kind"], "teacher_manual_model_answer_import")
                self.assertIsNone(answer["provenance_json"]["source_sha256"])
                self.assertEqual(answer["provenance_json"]["review_material_id"], material_id)
                self.assertEqual(saved["draft"]["entries"][0]["source"], original[0]["source"])
                self.assertEqual(saved["draft"]["entries"][1]["question_id"], None)
                self.assertIn(manual_id, saved["draft"]["confirmed_entry_ids"])

    def test_manual_alternative_and_fake_target_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _, _ = self.make_fixture(root, "Question 1\nAnswer one")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                primary = EntryEdit(id=draft["entries"][0]["id"], question_id=q1_id, answer_text="Primary")
                alternative = EntryEdit(id=f"teacher-entry-{uuid4()}", question_id=q1_id,
                                        answer_text="Alternative", answer_kind="alternative")
                with self.assertRaises(HTTPException):
                    update(draft["id"], DraftEdit(expected_revision=1, entries=[primary, alternative.model_copy(
                        update={"question_id": "foreign-question"})]), session)
                session.rollback()
                edited = update(draft["id"], DraftEdit(expected_revision=1,
                                                        entries=[primary, alternative]), session)
                saved = confirm(draft["id"], ConfirmRequest(expected_revision=edited["revision"]), session)
                self.assertEqual(len(saved["model_answers"]), 1)
                self.assertEqual(saved["model_answers"][0]["provenance_json"]["review_alternatives"][0]["answer_text"],
                                 "Alternative")

    def test_remapping_preserves_teacher_edited_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, q21_id, _ = self.make_fixture(
                root, "Question 1\nOriginal answer")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                entry_id = draft["entries"][0]["id"]
                first = update(draft["id"], DraftEdit(expected_revision=1, entries=[EntryEdit(
                    id=entry_id, question_id=q1_id, answer_text="Teacher wording")]), session)
                second = update(draft["id"], DraftEdit(expected_revision=first["revision"], entries=[EntryEdit(
                    id=entry_id, question_id=q21_id, answer_text="Teacher wording")]), session)
                self.assertEqual(second["entries"][0]["answer_text"], "Teacher wording")
                self.assertEqual(second["entries"][0]["question_id"], q21_id)

    def make_pdf(self, path: Path, text: str):
        document = pymupdf.open()
        page = document.new_page(width=420, height=600)
        page.insert_textbox(pymupdf.Rect(30, 30, 390, 560), text, fontsize=14, lineheight=1.6)
        document.save(path)
        document.close()

    def make_fixture(self, root: Path, text: str, q1_question_text: str | None = None):
        engine, factory = create_session_factory(f"sqlite:///{root / 'isolated.sqlite'}")
        init_database(engine)
        with factory() as session:
            domain = DomainService(session)
            user = domain.user(display_name="Fixture teacher")
            course = domain.course(user.id, name="Isolated course")
            offering = domain.offering(course.id, academic_year=2026, term="fall")
            test = domain.test(offering.id, name="Isolated test", total_points=20)
            q1 = domain.question(test.id, question_number="1", display_label="問題1", sort_order=1,
                                 max_points=10, is_gradable=True, question_text=q1_question_text)
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

    def test_manual_mapping_applies_question_text_removal_after_target_is_selected(self):
        question_text = "Explain overfitting in machine learning and describe its effect on unseen data."
        answer_text = "The model fits training data too closely, reducing its performance on unseen data."
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _q21_id, _q22_id = self.make_fixture(
                root, f"Question 9\n{question_text}\n{answer_text}", q1_question_text=question_text,
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertIsNone(draft["entries"][0]["question_id"])
                self.assertTrue(normalize_question_text(draft["entries"][0]["answer_text"]).startswith(
                    normalize_question_text(question_text),
                ))
                updated = update(draft["id"], DraftEdit(expected_revision=1, entries=[EntryEdit(
                    id=draft["entries"][0]["id"], question_id=q1_id,
                    answer_text=draft["entries"][0]["answer_text"],
                )]), session)
                self.assertEqual(updated["entries"][0]["mapping_state"], "manual_mapped")
                self.assertEqual(normalize_question_text(updated["entries"][0]["answer_text"]),
                                 normalize_question_text(answer_text))
                self.assertEqual(updated["entries"][0]["question_text_removal"]["method"], "exact")
                self.assertTrue(updated["entries"][0]["source"]["segments"])

    def test_native_import_removes_question_text_and_persists_removal_provenance(self):
        question_text = "Explain overfitting in machine learning and describe its effect on unseen data."
        answer_text = "The model fits training data too closely, reducing its performance on unseen data."
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _q21_id, _q22_id = self.make_fixture(
                root, f"Question 1\n{question_text}\n{answer_text}", q1_question_text=question_text,
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual(len(draft["entries"]), 1)
                entry = draft["entries"][0]
                self.assertEqual(entry["question_id"], q1_id)
                self.assertEqual(normalize_question_text(entry["answer_text"]), normalize_question_text(answer_text))
                self.assertEqual(entry["question_text_removal"]["status"], "removed")
                self.assertTrue(entry["source"]["segments"])
                saved = confirm(draft["id"], ConfirmRequest(expected_revision=1), session)
                self.assertEqual(normalize_question_text(saved["model_answers"][0]["answer_text"]),
                                 normalize_question_text(answer_text))
                provenance = saved["model_answers"][0]["provenance_json"]
                self.assertEqual(provenance["question_text_removal"]["method"], "exact")
                self.assertTrue(provenance["segments"])

    def test_visual_difference_guides_native_text_draft_and_provenance(self):
        question_text = "Describe the purpose of regularization."
        answer_text = "It controls model complexity to reduce overfitting."
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _q21_id, _q22_id = self.make_fixture(
                root, f"Question 1\n{question_text}\n{answer_text}", q1_question_text=question_text,
            )
            question_pdf = root / "question.pdf"
            self.make_pdf(question_pdf, f"Question 1\n{question_text}")
            question_digest = hashlib.sha256(question_pdf.read_bytes()).hexdigest()
            question_source = root / "sources" / test_id / f"{question_digest}.pdf"
            question_source.parent.mkdir(parents=True, exist_ok=True)
            question_source.write_bytes(question_pdf.read_bytes())
            with factory() as session:
                DomainService(session).material(
                    test_id, material_type="question_sheet", storage_ref=str(question_source),
                    original_filename="question.pdf", mime_type="application/pdf", sha256=question_digest,
                )
                session.commit()

            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual(draft["extraction"]["status"], "used", draft["extraction"])
                self.assertEqual(draft["extraction"]["method"], "visual_difference_guided_native_text")
                self.assertEqual(len(draft["extraction"]["regions"]), 1)
                self.assertEqual(len(draft["entries"]), 1)
                entry = draft["entries"][0]
                self.assertEqual(entry["question_id"], q1_id)
                self.assertEqual(entry["answer_text"], answer_text)
                self.assertEqual(entry["extraction_method"], "visual_difference_guided_native_text")
                self.assertTrue(entry["source"]["segments"])
                saved = confirm(draft["id"], ConfirmRequest(expected_revision=1), session)
                provenance = saved["model_answers"][0]["provenance_json"]
                self.assertEqual(provenance["extraction_method"], "visual_difference_guided_native_text")
                self.assertEqual(provenance["extraction"]["question_material_id"],
                                 draft["extraction"]["question_material_id"])
                self.assertEqual(provenance["extraction"]["regions"][0]["page_index"], 0)

    def test_question_only_extraction_stays_unconfirmable(self):
        question_text = "Explain overfitting in machine learning and describe its effect on unseen data."
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, _q1_id, _q21_id, _q22_id = self.make_fixture(
                root, f"Question 1\n{question_text}", q1_question_text=question_text,
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual(len(draft["entries"]), 1)
                self.assertEqual(draft["entries"][0]["answer_text"], "")
                self.assertEqual(draft["entries"][0]["question_text_removal"]["status"], "removed")
                with self.assertRaises(HTTPException) as caught:
                    confirm(draft["id"], ConfirmRequest(expected_revision=1), session)
                self.assertEqual(caught.exception.status_code, 422)
                self.assertEqual(caught.exception.detail["error"]["code"], "EMPTY_ANSWER_TEXT")

    def test_source_grounded_classification_separates_rubric_and_alternative_without_llm_text(self):
        class FakeClassifier:
            def classify(self, *, question_context, candidate_text, source_segments=None):
                self.context = question_context
                segments = source_segments if source_segments is not None else split_source_segments(candidate_text)
                assignments = []
                for segment in segments:
                    text = segment["text"]
                    category = "rubric" if "points" in text else (
                        "alternative_answer" if "Alternative" in text else (
                            "question" if "Explain the issue" in text or "Question 1" in text else "model_answer"
                        )
                    )
                    assignments.append({"id": segment["id"], "category": category, "confidence": 0.98})
                return {"status": "classified", "confidence": 0.98, "threshold": 0.82,
                        "segments": assignments}

        source_text = (
            "Question 1\nExplain the issue and its effects.\n"
            "The model overfits the training data and performs poorly on new data.\n"
            "5 points: describe overfitting.\nAlternative: use a high-variance explanation."
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, _q21_id, _q22_id = self.make_fixture(root, source_text)
            classifier = FakeClassifier()
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root],
                                 model_answer_classifier=classifier)
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            classify = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/classify")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                self.assertEqual(draft["entries"][0]["semantic_classification"]["status"], "classified")
                self.assertTrue(draft["pipeline"]["geometry_first"])
                classified = classify(draft["id"], ClassificationRequest(expected_revision=1), session)
                entry = classified["entries"][0]
                self.assertEqual(classified["revision"], 2)
                self.assertEqual(entry["question_id"], q1_id)
                self.assertEqual(entry["semantic_classification"]["status"], "classified")
                self.assertEqual(entry["answer_text"], "The model overfits the training data and performs poorly\non new data.\n")
                self.assertEqual(entry["semantic_classification"]["question_segments"][0]["text"],
                                 "Question 1\nExplain the issue and its effects.\n")
                self.assertIn("5 points", entry["semantic_classification"]["rubric_candidates"][0]["text"])
                self.assertIn("Alternative", entry["semantic_classification"]["alternative_answers"][0]["text"])
                self.assertNotIn("answer_text", entry["semantic_classification"])

                edited = update(classified["id"], DraftEdit(expected_revision=2, entries=[EntryEdit(
                    id=entry["id"], question_id=entry["question_id"], answer_text=entry["answer_text"],
                    classification_segments=[
                        {"id": item["id"], "category": item["category"], "text": item["text"]}
                        for item in entry["semantic_classification"]["segments"]
                    ],
                    manual_alternative_answers=[{
                        "id": "teacher-alt-test", "text": "A teacher-authored second answer.",
                    }],
                )]), session)
                self.assertEqual(edited["revision"], 3)
                self.assertEqual(edited["entries"][0]["semantic_classification"]["status"], "teacher_reviewed")
                result = confirm(edited["id"], ConfirmRequest(expected_revision=3), session)
                saved = result["model_answers"][0]
                self.assertEqual(saved["answer_text"], entry["answer_text"])
                provenance = saved["provenance_json"]["semantic_classification"]
                self.assertEqual(provenance["rubric_candidates"], entry["semantic_classification"]["rubric_candidates"])
                self.assertEqual(provenance["alternative_answers"], entry["semantic_classification"]["alternative_answers"])
                self.assertEqual(provenance["manual_alternative_answers"], [{
                    "id": "teacher-alt-test", "text": "A teacher-authored second answer.",
                }])
                self.assertEqual(session.scalars(select(RubricVersion)).all(), [])

    def test_low_confidence_classification_is_advisory_for_valid_registration_content(self):
        class UncertainClassifier:
            def classify(self, *, question_context, candidate_text, source_segments=None):
                segments = source_segments if source_segments is not None else split_source_segments(candidate_text)
                return {"status": "needs_teacher_review", "confidence": 0.4, "threshold": 0.82,
                        "segments": [{"id": item["id"], "category": "uncertain", "confidence": 0.4}
                                     for item in segments]}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, _q1_id, _q21_id, _q22_id = self.make_fixture(
                root, "Question 1\nA source-grounded answer that needs teacher review."
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root],
                                 model_answer_classifier=UncertainClassifier())
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            classify = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/classify")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                original = draft["entries"][0]["answer_text"]
                classified = classify(draft["id"], ClassificationRequest(expected_revision=1), session)
                entry = classified["entries"][0]
                self.assertEqual(entry["semantic_classification"]["status"], "needs_teacher_review")
                self.assertEqual(entry["answer_text"], original)
                confirmed = confirm(classified["id"], ConfirmRequest(expected_revision=2), session)
                self.assertEqual(confirmed["draft"]["state"], "confirmed")
                self.assertEqual(confirmed["model_answers"][0]["answer_text"], original)

    def test_effectively_blank_recognizes_unicode_invisible_pdf_noise(self):
        for value in ("", "   ", "\r\n\t", "\u00a0", "\u200b", "\ufeff", "\x00\x1f", " \u200b\ufeff\x00\n"):
            with self.subTest(value=value):
                self.assertTrue(is_effectively_blank(value))
        self.assertFalse(is_effectively_blank("\u200b答案"))

    def test_import_rubric_registers_generated_version_without_autoapproval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, q1_id, q21_id, q22_id = self.make_fixture(
                root, "Question 1\nAnswer one\nQuestion 2\n(1) Answer two one\n(2) Answer two two")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            register = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/register-rubric", "POST")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                question_ids = [q1_id, q21_id, q22_id]
                points = [10, 5, 5]
                edits = []
                for index, (entry, question_id, point) in enumerate(zip(draft["entries"], question_ids, points)):
                    segment_id = f"rubric-source-{index}"
                    entry["semantic_classification"] = {"status": "needs_teacher_review", "segments": [
                        {"id": segment_id, "category": "rubric", "text": f"採点観点{index + 1}（{point}点）",
                         "source_text": f"採点観点{index + 1}（{point}点）"}],
                    }
                    edits.append(EntryEdit(id=entry["id"], question_id=question_id,
                        answer_text=entry["answer_text"], rubric_edits=[{"id": segment_id,
                            "description": f"採点観点{index + 1}", "points": point}]))
                draft_row = session.get(ModelAnswerImportDraft, draft["id"])
                draft_row.snapshot = {**draft_row.snapshot, "entries": draft["entries"]}
                session.commit()
                updated = update(draft["id"], DraftEdit(expected_revision=1, entries=edits), session)
                result = register(draft["id"], RubricRegistrationRequest(expected_revision=updated["revision"]), session)
                self.assertEqual(result["rubric"]["status"], "generated")
                self.assertEqual(result["rubric"]["rubric_json"]["provenance"]["material_id"], material_id)
                self.assertEqual(len(session.scalars(select(RubricVersion)).all()), 1)

    def test_teacher_text_edit_accepts_low_confidence_answer_without_classification_review(self):
        class UncertainClassifier:
            def classify(self, *, question_context, candidate_text, source_segments=None):
                segments = source_segments if source_segments is not None else split_source_segments(candidate_text)
                return {"status": "needs_teacher_review", "confidence": 0.4, "threshold": 0.82,
                        "segments": [{"id": item["id"], "category": "uncertain", "confidence": 0.4}
                                     for item in segments]}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, _q1_id, _q21_id, _q22_id = self.make_fixture(
                root, "Question 1\nAn answer the teacher will review directly.")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root],
                                 model_answer_classifier=UncertainClassifier())
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            classify = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/classify")
            update = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}", "PUT")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                classified = classify(draft["id"], ClassificationRequest(expected_revision=1), session)
                entry = classified["entries"][0]
                edits = [EntryEdit(id=item["id"], question_id=item["question_id"],
                                   answer_text="Teacher-confirmed formal answer." if item["id"] == entry["id"]
                                   else item["answer_text"], disposition=item.get("disposition"),
                                   answer_kind=item.get("answer_kind")) for item in classified["entries"]]
                edited = update(classified["id"], DraftEdit(expected_revision=2, entries=edits), session)
                self.assertEqual(edited["entries"][0]["semantic_classification"]["status"], "needs_teacher_review")
                self.assertTrue(edited["entries"][0]["teacher_correction"]["teacher_confirmed"])
                saved = confirm(edited["id"], ConfirmRequest(expected_revision=3), session)
                self.assertEqual(saved["model_answers"][0]["answer_text"], "Teacher-confirmed formal answer.")

    def test_blank_native_candidate_is_ignored_before_semantic_classification(self):
        calls = []

        class CountingClassifier:
            def classify(self, *, question_context, candidate_text, source_segments=None):
                calls.append(candidate_text)
                segments = source_segments if source_segments is not None else split_source_segments(candidate_text)
                return {"status": "classified", "confidence": 0.99, "threshold": 0.82,
                        "segments": [{"id": item["id"], "category": "model_answer", "confidence": 0.99}
                                     for item in segments]}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, *_ = self.make_fixture(
                root, "Question 1\nA real answer remains classified.")
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root],
                                 model_answer_classifier=CountingClassifier())
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                blank = dict(draft["entries"][0])
                blank.update({"id": "blank-noise", "candidate_text": " \n\t", "answer_text": " \n"})
                blank["source"] = {**blank["source"], "segments": [{"original_text": " \n\t"}]}
                entries = [blank, *draft["entries"]]
                # Reuse the review classifier path through a real draft row with a legacy/noisy entry.
                from scoring.db.models import ModelAnswerImportDraft
                row = session.get(ModelAnswerImportDraft, draft["id"])
                row.snapshot = {**row.snapshot, "entries": entries}
                session.commit()
                classify = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/classify")
                classified = classify(draft["id"], ClassificationRequest(expected_revision=1), session)
                ignored = next(item for item in classified["entries"] if item["id"] == "blank-noise")
                self.assertEqual(ignored["disposition"], "ignored")
                self.assertEqual(ignored["ignore_reason"], "blank_or_whitespace")
                self.assertNotIn(" \n\t", calls)

    def test_unavailable_classifier_keeps_native_text_and_preserves_existing_confirm_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            factory, test_id, material_id, _q1_id, _q21_id, _q22_id = self.make_fixture(
                root, "Question 1\nA complete native answer remains available for teacher editing."
            )
            with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
                app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root])
            create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
            classify = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/classify")
            confirm = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/confirm")
            with factory() as session:
                draft = create(test_id, ImportCreate(material_id=material_id), session)
                original_text = draft["entries"][0]["answer_text"]
                classified = classify(draft["id"], ClassificationRequest(expected_revision=1), session)
                entry = classified["entries"][0]
                self.assertEqual(entry["semantic_classification"]["status"], "fallback")
                self.assertEqual(entry["answer_text"], original_text)
                self.assertEqual(entry["semantic_classification"]["candidate_text"], entry["candidate_text"])
                saved = confirm(classified["id"], ConfirmRequest(expected_revision=2), session)
                self.assertEqual(saved["model_answers"][0]["answer_text"], original_text)

if __name__ == "__main__":
    unittest.main()


def test_automatic_invalid_classification_preserves_pdf_sources_and_mechanical_answer(tmp_path, monkeypatch):
    class InvalidClassifier:
        def classify(self, **kwargs):
            return {'status': 'classified', 'confidence': .99, 'segments': [
                {'id': 'invented', 'category': 'model_answer', 'confidence': .99},
            ], 'primary_answer_text': 'Hallucinated answer'}
    helper = ModelAnswerImportApiTests()
    factory, tid, mid, qid, *_ = helper.make_fixture(tmp_path, 'Question 1\nOriginal answer.')
    monkeypatch.setenv('LLM_GRADER_ARTIFACT_ROOT', str(tmp_path))
    app = create_app(factory, question_import_root=tmp_path / 'question-imports', allowed_roots=[tmp_path],
                     model_answer_classifier=InvalidClassifier())
    create = _endpoint(app, '/api/v1/tests/{test_id}/model-answer-imports')
    with factory() as session:
        draft = create(tid, ImportCreate(material_id=mid), session)
        entry = draft['entries'][0]
        assert entry['question_id'] == qid
        assert entry['answer_text'] == 'Original answer.'
        assert draft['pipeline']['status'] == 'fallback'
        assert entry['semantic_classification']['reason'] == 'classification_failed'
        assert entry['semantic_classification']['segments'][0]['id'] == entry['source']['segments'][0]['id']
        assert 'Hallucinated' not in str(entry)


def test_automatic_fallback_can_be_edited_saved_and_confirmed_without_llm(tmp_path, monkeypatch):
    helper = ModelAnswerImportApiTests()
    factory, tid, mid, qid, *_ = helper.make_fixture(tmp_path, 'Question 1\nNative answer.')
    monkeypatch.setenv('LLM_GRADER_ARTIFACT_ROOT', str(tmp_path))
    app = create_app(factory, question_import_root=tmp_path / 'question-imports', allowed_roots=[tmp_path])
    create = _endpoint(app, '/api/v1/tests/{test_id}/model-answer-imports')
    update = _endpoint(app, '/api/v1/model-answer-import-drafts/{draft_id}', 'PUT')
    confirm = _endpoint(app, '/api/v1/model-answer-import-drafts/{draft_id}/confirm')
    with factory() as session:
        draft = create(tid, ImportCreate(material_id=mid), session)
        entry = draft['entries'][0]
        assert entry['semantic_classification']['status'] == 'fallback'
        saved = update(draft['id'], DraftEdit(expected_revision=1, entries=[EntryEdit(
            id=entry['id'], question_id=qid, answer_text='Teacher reviewed native answer.',
            classification_segments=[{'id': item['id'], 'category': item['category'], 'text': item['text']}
                                     for item in entry['semantic_classification']['segments']],
        )]), session)
        assert saved['entries'][0]['semantic_classification']['status'] == 'fallback'
        result = confirm(draft['id'], ConfirmRequest(expected_revision=2), session)
        assert result['model_answers'][0]['answer_text'] == 'Teacher reviewed native answer.'


def test_invalid_question_pdf_falls_back_without_losing_answer_draft(tmp_path, monkeypatch):
    helper = ModelAnswerImportApiTests()
    factory, tid, mid, qid, *_ = helper.make_fixture(tmp_path, 'Question 1\nOriginal answer.')
    with factory() as session:
        invalid = tmp_path / 'invalid-question.pdf'
        invalid.write_bytes(b'not a PDF')
        DomainService(session).material(tid, material_type='question_sheet', storage_ref=str(invalid),
                                        mime_type='application/pdf', original_filename='invalid.pdf',
                                        sha256=hashlib.sha256(invalid.read_bytes()).hexdigest())
        session.commit()
    monkeypatch.setenv('LLM_GRADER_ARTIFACT_ROOT', str(tmp_path))
    app = create_app(factory, question_import_root=tmp_path / 'question-imports', allowed_roots=[tmp_path])
    with factory() as session:
        draft = _endpoint(app, '/api/v1/tests/{test_id}/model-answer-imports')(
            tid, ImportCreate(material_id=mid), session)
        assert draft['entries'][0]['question_id'] == qid
        assert draft['entries'][0]['answer_text'] == 'Original answer.'
        assert draft['extraction']['status'] == 'fallback'
