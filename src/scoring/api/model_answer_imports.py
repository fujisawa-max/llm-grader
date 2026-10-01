"""Teacher review endpoints for native-PDF model answer imports."""

from __future__ import annotations

import shutil
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db.models import (
    Course,
    CourseOffering,
    ModelAnswerImportDraft,
    Test,
    TestMaterial,
    TestQuestion,
)
from ..domain import DomainService
from ..model_answer_drafts import (
    build_model_answer_entries,
    draft_view,
    question_choices,
    remove_question_text,
)
from ..model_answer_visual import (
    BINARIZE_THRESHOLD,
    COMPARISON_SIZE,
    PADDING_CELLS,
    SHIFT_TOLERANCE_CELLS,
    compare_model_answer_pages,
    select_question_text_material,
)
from ..model_answer_classification import (
    ClassificationOutputError,
    apply_teacher_segment_edits,
    fallback_classification,
    validate_classifier_result,
)
from ..pdf_native import PyMuPdfNativeExtractor, sha256_file

logger = logging.getLogger(__name__)


class ImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_id: str


class ClassificationSegmentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: str
    text: str = Field(max_length=100000)


class AlternativeAnswerEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=100000)


class EntryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question_id: str | None = None
    answer_text: str = Field(max_length=100000)
    classification_segments: list[ClassificationSegmentEdit] | None = None
    classification_reviewed: bool = False
    manual_alternative_answers: list[AlternativeAnswerEdit] | None = None


class DraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    entries: list[EntryEdit] = Field(min_length=1, max_length=500)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


def router(db, artifact_root, classifier=None):
    routes = APIRouter(prefix="/api/v1")
    root = Path(artifact_root).resolve()
    draft_root = root / "model-answer-imports"

    def fail(status: int, code: str, message: str):
        raise HTTPException(status, detail={"error": {"code": code, "message": message}})

    def owned_test(test_id: str, session):
        test = session.get(Test, test_id)
        if not test:
            fail(404, "TEST_NOT_FOUND", "試験が見つかりません")
        offering = session.get(CourseOffering, test.course_offering_id)
        course = session.get(Course, offering.course_id) if offering else None
        actor = session.info.get("auth_user")
        if not course or (actor and actor.role != "admin" and course.owner_user_id != actor.id):
            fail(404, "TEST_NOT_FOUND", "試験が見つかりません")
        return test

    def owned_draft(draft_id: str, session):
        draft = session.get(ModelAnswerImportDraft, draft_id)
        if not draft:
            fail(404, "DRAFT_NOT_FOUND", "模範解答の確認内容が見つかりません")
        owned_test(draft.test_id, session)
        return draft

    def choices_for(test_id: str, session):
        questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)))
        return question_choices(questions), questions

    def view(draft, session):
        choices, _ = choices_for(draft.test_id, session)
        return draft_view(draft, choices)

    def question_context(question, label):
        parts = []
        content = question.content if isinstance(question.content, dict) else {}
        items = content.get("items", []) if isinstance(content.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item.get("type") == "formula":
                parts.append(str(item.get("transcription") or item.get("latex") or ""))
        body = "".join(parts).strip() or str(question.question_text or "")
        return {"label": label, "body": body}

    def resolve_material_file(material: TestMaterial):
        path = Path(material.storage_ref)
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_file() or not (path == root or root in path.parents):
            fail(404, "MATERIAL_FILE_NOT_FOUND", "登録済みPDFを取得できません")
        if material.sha256 and sha256_file(path) != material.sha256:
            fail(409, "MATERIAL_INTEGRITY_ERROR", "登録済みPDFの内容が一致しません")
        return path

    def revision_check(draft, expected):
        if draft.state != "editing":
            fail(409, "DRAFT_NOT_EDITABLE", "確定済みの確認内容は編集できません")
        if draft.revision != expected:
            fail(409, "REVISION_CONFLICT", "別の画面で内容が更新されています。最新の内容を再読み込みしてください")

    @routes.post("/tests/{test_id}/model-answer-imports", status_code=201)
    def create(test_id: str, body: ImportCreate, session=Depends(db)):
        owned_test(test_id, session)
        material = session.get(TestMaterial, body.material_id)
        if not material or material.test_id != test_id or material.material_type != "model_answer_source":
            fail(404, "MODEL_ANSWER_MATERIAL_NOT_FOUND", "この試験の模範解答PDFを選択してください")
        if material.mime_type != "application/pdf" or Path(material.original_filename or "").suffix.lower() != ".pdf":
            fail(422, "PDF_REQUIRED", "解析には登録済みのPDFを選択してください")
        source_path = resolve_material_file(material)
        digest = sha256_file(source_path)
        if material.sha256 and digest != material.sha256:
            fail(409, "MATERIAL_INTEGRITY_ERROR", "登録済みPDFの内容が一致しません")

        draft_id = str(uuid4())
        output_dir = draft_root / draft_id / "native"
        try:
            ir = PyMuPdfNativeExtractor(max_pages=100).extract(
                source_path,
                source_sha256=digest,
                material_id=material.id,
                output_dir=output_dir,
            ).as_dict()
            questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)))
            question_materials = list(session.scalars(select(TestMaterial).where(
                TestMaterial.test_id == test_id,
                TestMaterial.material_type == "question_sheet",
            )))
            question_material = select_question_text_material(question_materials)
            visual_result = {
                "status": "fallback",
                "reason": "question_sheet_not_unique" if question_materials else "question_sheet_missing",
                "method": "native_text",
                "comparison_size": COMPARISON_SIZE,
                "threshold": BINARIZE_THRESHOLD,
                "shift_tolerance_cells": SHIFT_TOLERANCE_CELLS,
                "padding_cells": PADDING_CELLS,
                "regions": [],
                "selected_span_count": 0,
                "page_diagnostics": [],
            }
            allowed_element_ids_by_page = None
            question_material_sha = None
            if question_material is not None:
                try:
                    question_path = resolve_material_file(question_material)
                    question_material_sha = sha256_file(question_path)
                    visual_result = compare_model_answer_pages(question_path, source_path, ir)
                    allowed_ids = visual_result.pop("allowed_element_ids_by_page", {})
                    if visual_result.get("status") == "used":
                        allowed_element_ids_by_page = {
                            int(page_index): set(element_ids) if element_ids is not None else None
                            for page_index, element_ids in allowed_ids.items()
                        }
                    visual_result["question_material_id"] = question_material.id
                    visual_result["question_source_sha256"] = question_material_sha
                except HTTPException:
                    # An unavailable or invalid comparison source must not
                    # block the existing teacher-review native-text workflow.
                    logger.info("Question-sheet visual comparison unavailable for model-answer draft")
                    visual_result = {
                        "status": "fallback", "reason": "question_sheet_unavailable",
                        "method": "native_text", "comparison_size": COMPARISON_SIZE,
                        "threshold": BINARIZE_THRESHOLD,
                        "shift_tolerance_cells": SHIFT_TOLERANCE_CELLS,
                        "padding_cells": PADDING_CELLS,
                        "regions": [], "selected_span_count": 0, "page_diagnostics": [],
                        "question_material_id": question_material.id,
                    }
                    allowed_element_ids_by_page = None

            entries = build_model_answer_entries(
                ir, questions, allowed_element_ids_by_page=allowed_element_ids_by_page,
            )
            if visual_result.get("status") == "used":
                visual_pages = {item["page_index"] for item in visual_result.get("page_diagnostics", [])
                                if item.get("status") == "visual_difference"}
                for entry in entries:
                    entry["extraction_method"] = (
                        "visual_difference_guided_native_text"
                        if any(segment.get("page_index") in visual_pages
                               for segment in entry.get("source", {}).get("segments", []))
                        else "native_text_fallback"
                    )
            else:
                for entry in entries:
                    entry["extraction_method"] = "native_text_fallback"
            snapshot = {
                "schema": "model-answer-review.v1",
                "page_count": ir.get("source", {}).get("page_count", len(ir.get("pages", []))),
                "parser": {**ir.get("parser", {}), "model_answer_extraction": visual_result},
                "extraction": visual_result,
                "entries": entries,
            }
            relative_ir = (output_dir / "document-ir.json").relative_to(root).as_posix()
            draft = ModelAnswerImportDraft(
                id=draft_id,
                test_id=test_id,
                material_id=material.id,
                source_sha256=digest,
                artifact_ref=relative_ir,
                state="editing",
                revision=1,
                snapshot=snapshot,
            )
            session.add(draft)
            session.commit()
            session.refresh(draft)
            return view(draft, session)
        except HTTPException:
            session.rollback()
            shutil.rmtree(output_dir.parent, ignore_errors=True)
            raise
        except Exception as exc:
            logger.exception("Native model-answer extraction failed", exc_info=exc)
            session.rollback()
            shutil.rmtree(output_dir.parent, ignore_errors=True)
            fail(422, "NATIVE_EXTRACTION_FAILED", "PDFから文字を読み取れませんでした。PDF形式と文字データを確認してください")

    @routes.get("/model-answer-import-drafts/{draft_id}")
    def get_draft(draft_id: str, session=Depends(db)):
        return view(owned_draft(draft_id, session), session)

    @routes.post("/model-answer-import-drafts/{draft_id}/classify")
    def classify_draft(draft_id: str, body: ClassificationRequest, session=Depends(db)):
        draft = owned_draft(draft_id, session)
        revision_check(draft, body.expected_revision)
        choices, questions = choices_for(draft.test_id, session)
        question_by_id = {question.id: question for question in questions}
        label_by_id = {choice["id"]: choice["label"] for choice in choices}
        entries = []
        for original in draft.snapshot.get("entries", []):
            entry = dict(original)
            question_id = entry.get("question_id")
            question = question_by_id.get(question_id)
            candidate_text = str(
                (entry.get("semantic_classification") or {}).get("candidate_text")
                or entry.get("answer_text") or ""
            )
            if not question or not question.is_gradable:
                entry["semantic_classification"] = fallback_classification(
                    candidate_text, reason="question_mapping_required",
                )
                entries.append(entry)
                continue
            if classifier is None:
                entry["semantic_classification"] = fallback_classification(
                    candidate_text, reason="classifier_unavailable",
                )
                entries.append(entry)
                continue
            try:
                result = classifier.classify(
                    question_context=question_context(question, label_by_id.get(question_id, "設問")),
                    candidate_text=candidate_text,
                )
                classification = validate_classifier_result(candidate_text, result)
                entry["semantic_classification"] = classification
                if classification["status"] == "classified":
                    entry["answer_text"] = classification["primary_answer_text"]
            except Exception as exc:
                logger.info("Model-answer semantic classification fell back: %s", type(exc).__name__)
                entry["semantic_classification"] = fallback_classification(
                    candidate_text, reason="classification_failed",
                )
            entries.append(entry)
        draft.snapshot = {**draft.snapshot, "entries": entries}
        draft.revision += 1
        session.commit()
        session.refresh(draft)
        return view(draft, session)

    @routes.put("/model-answer-import-drafts/{draft_id}")
    def update_draft(draft_id: str, body: DraftEdit, session=Depends(db)):
        draft = owned_draft(draft_id, session)
        revision_check(draft, body.expected_revision)
        original_entries = draft.snapshot.get("entries", [])
        original_by_id = {entry.get("id"): entry for entry in original_entries}
        if len(body.entries) != len(original_entries) or {entry.id for entry in body.entries} != set(original_by_id):
            fail(422, "DRAFT_ENTRIES_CHANGED", "解析した項目の構成は変更できません")
        choices, questions = choices_for(draft.test_id, session)
        valid_question_ids = {question.id for question in questions if question.is_gradable}
        question_by_id = {question.id: question for question in questions}
        mapped_ids = [entry.question_id for entry in body.entries if entry.question_id]
        if any(question_id not in valid_question_ids for question_id in mapped_ids):
            fail(422, "INVALID_QUESTION_MAPPING", "対応先にはこの試験の採点対象設問を選択してください")
        if len(mapped_ids) != len(set(mapped_ids)):
            fail(422, "DUPLICATE_QUESTION_MAPPING", "同じ設問に複数の模範解答を対応させることはできません")

        updated = []
        for edit in body.entries:
            entry = dict(original_by_id[edit.id])
            previous_question = entry.get("question_id")
            entry["question_id"] = edit.question_id
            entry["answer_text"] = edit.answer_text
            classification = entry.get("semantic_classification")
            if classification and previous_question != edit.question_id:
                entry["answer_text"] = str(classification.get("candidate_text") or entry["answer_text"])
                classification = None
                entry.pop("semantic_classification", None)
            if classification and edit.classification_segments is not None:
                try:
                    classification = apply_teacher_segment_edits(
                        classification,
                        [segment.model_dump() for segment in edit.classification_segments],
                    )
                except ClassificationOutputError:
                    fail(422, "INVALID_CLASSIFICATION_EDIT", "分類内容を確認してください")
                entry["semantic_classification"] = classification
            if classification and edit.classification_reviewed:
                if any(item.get("category") == "uncertain" for item in classification.get("segments", [])):
                    fail(422, "UNCERTAIN_CLASSIFICATION_SEGMENTS", "未分類の文章を確認してください")
                entry["semantic_classification"] = {**classification, "status": "teacher_reviewed"}
            if classification and edit.manual_alternative_answers is not None:
                alternatives = [item.model_dump() for item in edit.manual_alternative_answers]
                alternative_ids = [item["id"] for item in alternatives]
                existing_ids = {item.get("id") for item in classification.get("manual_alternative_answers", [])}
                allowed_new_ids = {item_id for item_id in alternative_ids
                                   if item_id.startswith("teacher-alt-")}
                if (len(alternative_ids) != len(set(alternative_ids))
                        or any(item_id not in existing_ids and item_id not in allowed_new_ids
                               for item_id in alternative_ids)
                        or len(alternatives) > 50):
                    fail(422, "INVALID_ALTERNATIVE_ANSWER_EDIT", "別解候補の編集内容を確認してください")
                entry["semantic_classification"] = {
                    **entry["semantic_classification"],
                    "manual_alternative_answers": alternatives,
                }
            removal = entry.get("question_text_removal") or {}
            if edit.question_id and removal.get("question_id") != edit.question_id:
                entry["answer_text"], entry["question_text_removal"] = remove_question_text(
                    question_by_id[edit.question_id], entry["answer_text"],
                )
            if not edit.question_id:
                entry["mapping_state"] = "needs_review"
            elif edit.question_id == previous_question and entry.get("mapping_state") == "automatic":
                entry["mapping_state"] = "automatic"
            else:
                entry["mapping_state"] = "manual_mapped"
            entry["mapped_question_label"] = (
                next((choice["label"] for choice in choices if choice["id"] == edit.question_id), None)
            )
            updated.append(entry)
        draft.snapshot = {**draft.snapshot, "entries": updated}
        draft.revision += 1
        session.commit()
        session.refresh(draft)
        return view(draft, session)

    @routes.post("/model-answer-import-drafts/{draft_id}/confirm")
    def confirm(draft_id: str, body: ConfirmRequest, session=Depends(db)):
        draft = owned_draft(draft_id, session)
        revision_check(draft, body.expected_revision)
        material = session.get(TestMaterial, draft.material_id)
        if not material or material.test_id != draft.test_id or material.material_type != "model_answer_source":
            fail(409, "SOURCE_MATERIAL_CHANGED", "元の模範解答資料を確認できません")
        source_path = resolve_material_file(material)
        actual_sha = sha256_file(source_path)
        if actual_sha != draft.source_sha256 or (material.sha256 and actual_sha != material.sha256):
            fail(409, "SOURCE_MATERIAL_CHANGED", "解析後に元の模範解答資料が変更されています")
        _, questions = choices_for(draft.test_id, session)
        question_by_id = {question.id: question for question in questions}
        entries = draft.snapshot.get("entries", [])
        if not entries:
            fail(422, "EMPTY_DRAFT", "模範解答本文がありません")
        mapped = [entry.get("question_id") for entry in entries]
        if any(not question_id for question_id in mapped):
            count = sum(1 for question_id in mapped if not question_id)
            fail(422, "UNMAPPED_ENTRIES", f"対応先が未設定の模範解答が{count}件あります")
        if len(mapped) != len(set(mapped)):
            fail(422, "DUPLICATE_QUESTION_MAPPING", "同じ設問に複数の模範解答が対応しています")
        if any(question_id not in question_by_id or not question_by_id[question_id].is_gradable for question_id in mapped):
            fail(422, "INVALID_QUESTION_MAPPING", "対応先にはこの試験の採点対象設問を選択してください")
        if any(not str(entry.get("answer_text") or "").strip() for entry in entries):
            count = sum(1 for entry in entries if not str(entry.get("answer_text") or "").strip())
            fail(422, "EMPTY_ANSWER_TEXT", f"模範解答本文が空の項目が{count}件あります")
        pending_classification = sum(
            1 for entry in entries
            if (entry.get("semantic_classification") or {}).get("status") == "needs_teacher_review"
        )
        if pending_classification:
            fail(422, "CLASSIFICATION_REVIEW_REQUIRED",
                 f"分類結果を確認していない模範解答が{pending_classification}件あります")

        service = DomainService(session)
        created = []
        try:
            for entry in entries:
                provenance = {
                    "kind": "native_pdf_model_answer_import",
                    "draft_id": draft.id,
                    "material_id": material.id,
                    "source_sha256": actual_sha,
                    "parser": draft.snapshot.get("parser", {}),
                    "segments": entry.get("source", {}).get("segments", []),
                    "question_text_removal": entry.get("question_text_removal"),
                    "semantic_classification": entry.get("semantic_classification"),
                    "extraction_method": entry.get("extraction_method", "native_text_fallback"),
                    "extraction": draft.snapshot.get("extraction"),
                    "mapping_method": entry.get("mapping_state"),
                }
                answer = service.model_answer(
                    draft.test_id,
                    question_id=entry["question_id"],
                    answer_text=entry["answer_text"],
                    material_id=material.id,
                    provenance_json=provenance,
                )
                created.append(answer)
            draft.state = "confirmed"
            draft.snapshot = {
                **draft.snapshot,
                "confirmed_model_answers": [
                    {"id": answer.id, "question_id": answer.question_id, "version": answer.version}
                    for answer in created
                ],
            }
            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except Exception as exc:
            logger.exception("Model-answer import confirmation failed", exc_info=exc)
            session.rollback()
            fail(422, "MODEL_ANSWER_SAVE_FAILED", "模範解答を登録できませんでした。入力内容を確認して再試行してください")
        return {"draft": view(draft, session), "model_answers": [
            {"id": answer.id, "question_id": answer.question_id, "answer_text": answer.answer_text,
             "material_id": answer.material_id, "provenance_json": answer.provenance_json,
             "version": answer.version, "is_current": answer.is_current}
            for answer in created
        ]}

    return routes
