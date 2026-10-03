"""Teacher review endpoints for native-PDF model answer imports."""

from __future__ import annotations

import shutil
import time
import logging
from pathlib import Path
from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db.models import (
    Course,
    CourseOffering,
    ModelAnswer,
    ModelAnswerImportDraft,
    RubricVersion,
    Test,
    TestMaterial,
    TestQuestion,
)
from ..domain import DomainService
from ..model_answer_drafts import draft_view, question_choices, remove_question_text
from ..model_answer_geometry import PIPELINE_VERSION, build_geometry_entries
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
    CONFIDENCE_THRESHOLD,
    apply_teacher_segment_edits,
    fallback_classification,
    is_effectively_blank,
    validate_classifier_result,
)
from ..pdf_native import PyMuPdfNativeExtractor, sha256_file

logger = logging.getLogger(__name__)
AUTOMATIC_CLASSIFICATION_BUDGET_SECONDS = 600


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


class RubricCandidateEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=100000)
    points: int = Field(ge=0)


class EntryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question_id: str | None = None
    answer_text: str = Field(max_length=100000)
    disposition: Literal["include", "unassigned", "excluded", "ignored"] | None = None
    answer_kind: Literal["primary", "alternative"] | None = None
    loaded_model_answer_id: str | None = None
    classification_segments: list[ClassificationSegmentEdit] | None = None
    classification_reviewed: bool = False
    manual_alternative_answers: list[AlternativeAnswerEdit] | None = None
    rubric_edits: list[RubricCandidateEdit] | None = None


class DraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    entries: list[EntryEdit] = Field(min_length=1, max_length=500)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class RubricRegistrationRequest(BaseModel):
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
        saved = list(session.scalars(select(ModelAnswer).where(
            ModelAnswer.test_id == draft.test_id, ModelAnswer.is_current.is_(True))))
        return {**draft_view(draft, choices), "saved_answers": [
            {"id": answer.id, "question_id": answer.question_id, "answer_text": answer.answer_text,
             "version": answer.version} for answer in saved],
            "confirmed_entry_ids": draft.snapshot.get("confirmed_entry_ids", [])}

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

    def classify_entries(entries, questions, choices):
        deadline = time.monotonic() + AUTOMATIC_CLASSIFICATION_BUDGET_SECONDS
        by_id = {question.id: question for question in questions}
        labels = {choice["id"]: choice["label"] for choice in choices}
        updated = []
        for original in entries:
            entry = dict(original)
            if entry.get("teacher_correction", {}).get("teacher_confirmed"):
                # Teacher-authored choices are authoritative across a rerun.
                updated.append(entry)
                continue
            candidate = str(entry.get("candidate_text") or
                            (entry.get("semantic_classification") or {}).get("candidate_text") or
                            entry.get("answer_text") or "")
            if (is_effectively_blank(candidate) and not entry.get("teacher_correction")
                    and entry.get("source", {}).get("kind") != "teacher_manual"):
                # Preserve source/provenance while keeping empty extraction noise
                # out of semantic classification and teacher registration work.
                entry["disposition"] = "ignored"
                entry["ignore_reason"] = "blank_or_whitespace"
                entry["semantic_classification"] = {
                    **(entry.get("semantic_classification") or {}),
                    "status": "ignored", "reason": "blank_or_whitespace",
                }
                updated.append(entry)
                continue
            if entry.get("disposition") in {"excluded", "unassigned"} or entry.get("source", {}).get("kind") == "teacher_manual":
                updated.append(entry)
                continue
            question = by_id.get(entry.get("question_id"))
            native = entry.get("source", {}).get("segments", [])
            source_segments = None
            if native and all(item.get("id") and "original_text" in item for item in native):
                source_segments = []
                offset = 0
                for index, item in enumerate(native):
                    text = item["original_text"] + ("\n" if index < len(native) - 1 else "")
                    source_segments.append({**item, "text": text, "start": offset, "end": offset + len(text)})
                    offset += len(text)
            reason = None
            if not question or not question.is_gradable:
                reason = "question_mapping_required"
            elif classifier is None:
                reason = "classifier_unavailable"
            elif time.monotonic() >= deadline:
                reason = "classification_budget_exhausted"
            else:
                try:
                    context = question_context(question, labels.get(question.id, "設問"))
                    parent = by_id.get(question.parent_id)
                    context.update({"deadline_monotonic": deadline, "question_id": question.id,
                                    "parent": question_context(parent, parent.display_label) if parent else None})
                    kwargs = {"question_context": context, "candidate_text": candidate}
                    if source_segments is not None:
                        kwargs["source_segments"] = source_segments
                    result = classifier.classify(**kwargs)
                    classification = validate_classifier_result(
                        candidate, result, source_segments=source_segments,
                        threshold=getattr(classifier, "threshold", CONFIDENCE_THRESHOLD))
                    classification.update({key: result[key] for key in ("profile_id", "model_id", "runtime_type")
                                           if key in result})
                    previous = entry.get("semantic_classification") or {}
                    entry["semantic_classification"] = classification
                    categories = {segment.get("category") for segment in classification.get("segments", [])}
                    if (classification.get("status") == "classified"
                            and not classification.get("primary_answer_text", "").strip()
                            and categories and categories.issubset({"question", "note"})):
                        # Keep source evidence in the draft, but do not treat
                        # clearly non-answer material as a formal answer target.
                        entry["disposition"] = "excluded"
                        entry["ignore_reason"] = "classified_as_non_answer"
                    # Low confidence is advisory unless the teacher has not
                    # explicitly accepted or edited the registration content.
                    if previous.get("status") == "teacher_reviewed":
                        classification = apply_teacher_segment_edits(classification, [
                            {"id": item["id"], "category": item["category"], "text": item["text"]}
                            for item in previous.get("segments", [])
                        ])
                        classification["status"] = "teacher_reviewed"
                        classification["manual_alternative_answers"] = previous.get("manual_alternative_answers", [])
                        entry["semantic_classification"] = classification
                    if classification["status"] == "classified" and not entry.get("teacher_correction"):
                        entry["answer_text"] = classification["primary_answer_text"]
                except Exception as exc:
                    logger.info("Model-answer semantic classification fell back: %s", type(exc).__name__)
                    reason = "classification_failed"
            if reason:
                previous = original.get("semantic_classification") or {}
                if previous.get("status") == "teacher_reviewed":
                    entry["semantic_classification"] = {**previous, "retry_error": reason}
                else:
                    entry["semantic_classification"] = fallback_classification(
                        candidate, reason=reason, source_segments=source_segments)
            updated.append(entry)
        return updated

    def pipeline_status(entries):
        classifications = [entry.get("semantic_classification") or {} for entry in entries]
        used = any(item.get("status") in {"classified", "needs_teacher_review", "teacher_reviewed"}
                   for item in classifications)
        fallback = [item.get("reason") for item in classifications if item.get("status") == "fallback"]
        fallback.extend(item["retry_error"] for item in classifications if item.get("retry_error"))
        return {"version": PIPELINE_VERSION, "geometry_first": True,
                "semantic_classification_attempted": classifier is not None,
                "semantic_classification_used": used,
                "semantic_classification_fallback": bool(fallback), "fallback_reasons": sorted(set(fallback)),
                "profile_id": getattr(classifier, "profile_id", None),
                "status": "partial" if used and fallback else "complete" if used else "fallback"}

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
            question_ir = None
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
                    question_ir = PyMuPdfNativeExtractor().extract(
                        question_path, source_sha256=question_material_sha, material_id=question_material.id,
                        output_dir=output_dir / "question-native", options={"max_pages": 100},
                    ).as_dict()
                    visual_result = compare_model_answer_pages(question_path, source_path, ir)
                    allowed_ids = visual_result.pop("allowed_element_ids_by_page", {})
                    if visual_result.get("status") == "used":
                        allowed_element_ids_by_page = {
                            int(page_index): set(element_ids) if element_ids is not None else None
                            for page_index, element_ids in allowed_ids.items()
                        }
                    visual_result["question_material_id"] = question_material.id
                    visual_result["question_source_sha256"] = question_material_sha
                except Exception as exc:
                    question_ir = None
                    logger.info("Question geometry unavailable: %s", type(exc).__name__)
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

            entries, geometry_regions = build_geometry_entries(
                ir, questions, question_ir=question_ir,
                allowed_element_ids_by_page=allowed_element_ids_by_page,
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
            entries = classify_entries(entries, questions, question_choices(questions))
            snapshot = {
                "schema": "model-answer-review.v1",
                "page_count": ir.get("source", {}).get("page_count", len(ir.get("pages", []))),
                "parser": {**ir.get("parser", {}), "model_answer_extraction": visual_result},
                "extraction": visual_result,
                "pipeline": pipeline_status(entries), "question_regions": geometry_regions,
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

    @routes.get("/tests/{test_id}/model-answer-import-drafts")
    def list_drafts(test_id: str, material_id: str | None = None, session=Depends(db)):
        """List imports without invoking extraction or a model runtime."""
        owned_test(test_id, session)
        statement = select(ModelAnswerImportDraft).where(ModelAnswerImportDraft.test_id == test_id)
        if material_id:
            material = session.get(TestMaterial, material_id)
            if not material or material.test_id != test_id or material.material_type != "model_answer_source":
                fail(404, "SOURCE_MATERIAL_NOT_FOUND", "模範解答資料が見つかりません")
            statement = statement.where(ModelAnswerImportDraft.material_id == material_id)
        drafts = list(session.scalars(statement.order_by(
            ModelAnswerImportDraft.updated_at.desc(), ModelAnswerImportDraft.created_at.desc(),
            ModelAnswerImportDraft.id.desc())))
        summaries = []
        for draft in drafts:
            snapshot = draft.snapshot if isinstance(draft.snapshot, dict) else {}
            entries = snapshot.get("entries", [])
            summaries.append({
                "id": draft.id, "test_id": draft.test_id, "material_id": draft.material_id,
                "source_sha256": draft.source_sha256,
                "state": draft.state, "revision": draft.revision,
                "created_at": draft.created_at.isoformat(), "updated_at": draft.updated_at.isoformat(),
                "entry_count": len(entries),
                "confirmed_entry_count": len(snapshot.get("confirmed_entry_ids", [])),
                "pipeline": snapshot.get("pipeline"), "resumable": draft.state == "editing",
            })
        return {"drafts": summaries}

    @routes.get("/model-answer-import-drafts/{draft_id}")
    def get_draft(draft_id: str, session=Depends(db)):
        return view(owned_draft(draft_id, session), session)

    @routes.post("/model-answer-import-drafts/{draft_id}/classify")
    def classify_draft(draft_id: str, body: ClassificationRequest, session=Depends(db)):
        draft = owned_draft(draft_id, session)
        revision_check(draft, body.expected_revision)
        choices, questions = choices_for(draft.test_id, session)
        pending = [entry for entry in draft.snapshot.get("entries", [])
                   if entry.get("id") not in set(draft.snapshot.get("confirmed_entry_ids", []))]
        classified = {entry["id"]: entry for entry in classify_entries(pending, questions, choices)}
        entries = [classified.get(entry["id"], entry) for entry in draft.snapshot.get("entries", [])]
        draft.snapshot = {**draft.snapshot, "entries": entries, "pipeline": pipeline_status(entries)}
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
        confirmed_ids = set(draft.snapshot.get("confirmed_entry_ids", []))
        submitted_ids = [entry.id for entry in body.entries]
        if len(submitted_ids) != len(set(submitted_ids)) or not set(original_by_id).issubset(submitted_ids):
            fail(422, "DRAFT_ENTRIES_CHANGED", "解析した項目を削除・重複できません")
        for entry_id in set(submitted_ids) - set(original_by_id):
            try:
                if not entry_id.startswith("teacher-entry-"):
                    raise ValueError("invalid prefix")
                UUID(entry_id.removeprefix("teacher-entry-"))
            except ValueError:
                fail(422, "INVALID_MANUAL_ENTRY", "追加した模範解答の識別子を確認してください")
        choices, questions = choices_for(draft.test_id, session)
        valid_question_ids = {question.id for question in questions if question.is_gradable}
        mapped_ids = [entry.question_id for entry in body.entries if entry.question_id]
        if any(question_id not in valid_question_ids for question_id in mapped_ids):
            fail(422, "INVALID_QUESTION_MAPPING", "対応先にはこの試験の採点対象設問を選択してください")

        updated = []
        for edit in body.entries:
            if edit.id in confirmed_ids:
                original = original_by_id[edit.id]
                if (edit.question_id != original.get("question_id")
                        or edit.answer_text != original.get("answer_text")
                        or (edit.disposition and edit.disposition != original.get("disposition", "include"))
                        or (edit.answer_kind and edit.answer_kind != original.get("answer_kind", "primary"))):
                    fail(409, "CONFIRMED_ENTRY_IMMUTABLE", "登録済みの候補は変更できません")
                updated.append(original)
                continue
            entry = dict(original_by_id[edit.id]) if edit.id in original_by_id else {
                "id": edit.id, "question_id": None, "answer_text": "", "candidate_text": "",
                "mapping_state": "manual_mapped", "source": {"kind": "teacher_manual", "material_id": None,
                    "source_sha256": None, "segments": []}, "extraction_method": "teacher_manual"}
            previous_question = entry.get("question_id")
            disposition = edit.disposition or ("include" if edit.question_id else "unassigned")
            answer_kind = edit.answer_kind or entry.get("answer_kind") or "primary"
            if edit.loaded_model_answer_id:
                saved_answer = session.get(ModelAnswer, edit.loaded_model_answer_id)
                if (not saved_answer or saved_answer.test_id != draft.test_id
                        or saved_answer.question_id != edit.question_id or not saved_answer.is_current):
                    fail(422, "INVALID_SAVED_MODEL_ANSWER", "読み込む保存済み模範解答を確認してください")
                entry["loaded_model_answer"] = {"id": saved_answer.id, "version": saved_answer.version,
                                                "question_id": saved_answer.question_id}
            elif entry.get("loaded_model_answer") and edit.question_id != previous_question:
                entry.pop("loaded_model_answer", None)
            if disposition == "include" and not edit.question_id:
                fail(422, "INVALID_QUESTION_MAPPING", "取り込む候補には対応先の設問を指定してください")
            entry["disposition"] = disposition
            entry["answer_kind"] = answer_kind
            entry["question_id"] = edit.question_id
            entry["answer_text"] = edit.answer_text
            removal = entry.get("question_text_removal") or {}
            if (edit.question_id and removal.get("question_id") != edit.question_id
                    and not entry.get("teacher_correction") and edit.id in original_by_id
                    and edit.answer_text == original_by_id[edit.id].get("answer_text")):
                entry["answer_text"], entry["question_text_removal"] = remove_question_text(
                    next(question for question in questions if question.id == edit.question_id),
                    entry["answer_text"])
            prior_kind = original_by_id.get(edit.id, {}).get("answer_kind", "primary")
            prior_disposition = original_by_id.get(edit.id, {}).get("disposition", "include")
            original_classification = original_by_id.get(edit.id, {}).get("semantic_classification") or {}
            original_segments = original_classification.get("segments", [])
            classification_changed = edit.classification_segments is not None and [
                {"id": segment.get("id"), "category": segment.get("category"), "text": segment.get("text")}
                for segment in original_segments
            ] != [segment.model_dump() for segment in edit.classification_segments]
            original_rubric_edits = original_by_id.get(edit.id, {}).get("rubric_edits")
            submitted_rubric_edits = ([item.model_dump() for item in edit.rubric_edits]
                                      if edit.rubric_edits is not None else original_rubric_edits)
            if edit.rubric_edits is not None:
                rubric_segment_ids = {segment.get("id") for segment in
                    (entry.get("semantic_classification") or {}).get("segments", [])
                    if segment.get("category") == "rubric"}
                ids = [item["id"] for item in submitted_rubric_edits]
                if len(ids) != len(set(ids)) or any(item_id not in rubric_segment_ids for item_id in ids):
                    fail(422, "INVALID_RUBRIC_CANDIDATE", "採点基準候補の元文章を確認してください")
                entry["rubric_edits"] = submitted_rubric_edits
            rubric_changed = (edit.rubric_edits is not None
                and submitted_rubric_edits != original_rubric_edits)
            explicit_teacher_change = edit.id not in original_by_id or any((
                edit.question_id != original_by_id[edit.id].get("question_id"),
                edit.answer_text != original_by_id[edit.id].get("answer_text"),
                disposition != prior_disposition,
                answer_kind != prior_kind,
                edit.classification_reviewed,
                classification_changed,
                rubric_changed,
            ))
            if explicit_teacher_change:
                entry["teacher_correction"] = {"question_id": edit.question_id, "answer_text": edit.answer_text,
                                                "disposition": disposition, "answer_kind": answer_kind,
                                                "revision": draft.revision + 1,
                                                "teacher_confirmed": True}
            classification = entry.get("semantic_classification")
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
            # Teacher text is authoritative after editing. Re-mapping must not
            # strip or replace content the teacher has reviewed.
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
        primary_ids = [entry["question_id"] for entry in updated
                       if entry["disposition"] == "include" and entry["answer_kind"] == "primary"]
        if len(primary_ids) != len(set(primary_ids)):
            fail(422, "DUPLICATE_QUESTION_MAPPING", "同じ設問の主な模範解答は1件にしてください")
        draft.snapshot = {**draft.snapshot, "entries": updated}
        draft.revision += 1
        session.commit()
        session.refresh(draft)
        return view(draft, session)

    @routes.post("/model-answer-import-drafts/{draft_id}/register-rubric")
    def register_rubric(draft_id: str, body: RubricRegistrationRequest, session=Depends(db)):
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
        gradable = {question.id: question for question in questions if question.is_gradable}
        entries = draft.snapshot.get("entries", [])
        edited_by_question: dict[str, list[dict]] = {}
        for entry in entries:
            rubric_edits = entry.get("rubric_edits") or []
            if not rubric_edits:
                continue
            if entry.get("disposition", "include") != "include" or entry.get("question_id") not in gradable:
                fail(422, "RUBRIC_QUESTION_REQUIRED", "採点基準候補の対応先に採点対象設問を指定してください")
            allowed_ids = {segment.get("id") for segment in
                (entry.get("semantic_classification") or {}).get("segments", [])
                if segment.get("category") == "rubric"}
            if any(item.get("id") not in allowed_ids for item in rubric_edits):
                fail(422, "INVALID_RUBRIC_CANDIDATE", "採点基準候補の元文章を確認してください")
            edited_by_question.setdefault(entry["question_id"], []).extend(
                [{**item, "entry": entry} for item in rubric_edits])
        if not edited_by_question:
            fail(422, "NO_RUBRIC_CANDIDATES", "登録する採点基準候補がありません")

        latest = session.scalar(select(RubricVersion).where(
            RubricVersion.test_id == draft.test_id).order_by(RubricVersion.version.desc()))
        base_rows = {}
        if latest and isinstance(latest.rubric_json, dict):
            base_rows = {row.get("question_id"): row for row in latest.rubric_json.get("questions", [])
                         if isinstance(row, dict) and row.get("question_id")}
        rubric_questions = []
        provenance = {"kind": "model_answer_import_rubric", "draft_id": draft.id,
                      "material_id": material.id, "source_sha256": actual_sha, "questions": {}}
        for question_id, question in gradable.items():
            selected = edited_by_question.get(question_id)
            if selected:
                criteria = []
                source_records = []
                for index, item in enumerate(selected, 1):
                    if not str(item.get("description") or "").strip() or int(item.get("points", 0)) <= 0:
                        fail(422, "RUBRIC_CANDIDATE_INCOMPLETE", f"{question.display_label} の採点基準本文と配点を入力してください")
                    entry, segment_id = item["entry"], item["id"]
                    segment = next((value for value in
                        (entry.get("semantic_classification") or {}).get("segments", [])
                        if value.get("id") == segment_id and value.get("category") == "rubric"), {})
                    source_segment = next((value for value in entry.get("source", {}).get("segments", [])
                        if segment_id == value.get("id") or segment_id in value.get("element_ids", [])), {})
                    criterion_id = f"import-{entry['id'][:12]}-{index}"
                    criteria.append({"id": criterion_id, "description": item["description"].strip(),
                                     "points": item["points"]})
                    source_records.append({"criterion_id": criterion_id, "candidate_id": entry["id"],
                        "segment_id": segment_id, "original_text": segment.get("source_text") or segment.get("text"),
                        "teacher_text": item["description"], "page_index": source_segment.get("page_index"),
                        "bbox": source_segment.get("bbox")})
                provenance["questions"][question_id] = source_records
            else:
                criteria = (base_rows.get(question_id) or {}).get("criteria", [])
            if not criteria:
                fail(422, "RUBRIC_QUESTION_MISSING", f"{question.display_label} の採点基準がありません")
            points = sum(float(item.get("points", 0)) for item in criteria)
            if question.max_points is None or points != float(question.max_points):
                fail(422, "RUBRIC_SCORE_MISMATCH", f"{question.display_label} の採点基準合計を問題の配点に合わせてください")
            rubric_questions.append({"question_id": question_id, "max_points": question.max_points,
                                     "criteria": criteria})
        try:
            created = DomainService(session).rubric(draft.test_id,
                {"questions": rubric_questions, "provenance": provenance},
                source_type="model_answer_import")
            draft.snapshot = {**draft.snapshot, "rubric_registration": {
                "rubric_version_id": created.id, "version": created.version,
                "status": created.status, "source_sha256": actual_sha,
            }}
            draft.revision += 1
            session.commit()
            session.refresh(draft)
            return {"draft": view(draft, session), "rubric": {
                "id": created.id, "version": created.version, "status": created.status,
                "rubric_json": created.rubric_json}}
        except HTTPException:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            logger.exception("Model-answer import rubric registration failed", exc_info=exc)
            fail(422, "RUBRIC_SAVE_FAILED", "採点基準を登録できませんでした。設問と配点を確認してください")

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
        # Backward-compatible normalization for old drafts: whitespace-only
        # extraction artifacts are ignored without deleting their provenance.
        entries = [({**entry, "disposition": "ignored", "ignore_reason": "blank_or_whitespace",
                     "semantic_classification": {**(entry.get("semantic_classification") or {}),
                                                  "status": "ignored", "reason": "blank_or_whitespace"}}
                    if (is_effectively_blank(entry.get("answer_text")) and is_effectively_blank(entry.get("candidate_text"))
                        and not entry.get("teacher_correction")
                        and entry.get("source", {}).get("kind") != "teacher_manual")
                    else entry) for entry in entries]
        if not entries:
            fail(422, "EMPTY_DRAFT", "模範解答本文がありません")
        confirmed_ids = set(draft.snapshot.get("confirmed_entry_ids", []))
        included = [entry for entry in entries
                    if entry.get("disposition", "include" if entry.get("question_id") else "unassigned") == "include"
                    and entry.get("id") not in confirmed_ids
                    and not ((not str(entry.get("answer_text") or "").strip())
                             and (entry.get("semantic_classification") or {}).get("segments")
                             and {segment.get("category") for segment in
                                  entry["semantic_classification"]["segments"]}.issubset({"rubric", "question", "note"}))]
        mapped = [entry.get("question_id") for entry in included]
        if not included:
            fail(422, "NO_ANSWERS_TO_CONFIRM", "登録する模範解答を1件以上選んでください")
        if any(not question_id for question_id in mapped):
            fail(422, "UNMAPPED_ENTRIES", "取り込む候補の対応先を選択してください")
        primary = [entry for entry in included if entry.get("answer_kind", "primary") == "primary"]
        primary_ids = [entry["question_id"] for entry in primary]
        if len(primary_ids) != len(set(primary_ids)):
            fail(422, "DUPLICATE_QUESTION_MAPPING", "同じ設問の主な模範解答は1件にしてください")
        if set(mapped) != set(primary_ids):
            fail(422, "PRIMARY_ANSWER_REQUIRED", "別解を登録する設問には主な模範解答も必要です")
        if any(question_id not in question_by_id or not question_by_id[question_id].is_gradable for question_id in mapped):
            fail(422, "INVALID_QUESTION_MAPPING", "対応先にはこの試験の採点対象設問を選択してください")
        if any(is_effectively_blank(entry.get("answer_text")) for entry in included):
            count = sum(1 for entry in included if is_effectively_blank(entry.get("answer_text")))
            fail(422, "EMPTY_ANSWER_TEXT", f"模範解答本文が空の項目が{count}件あります")
        # Classification confidence is advisory. Registration is guarded by
        # mapped, non-empty, deduplicated formal answer content above.

        service = DomainService(session)
        created = []
        try:
            for entry in primary:
                alternatives = [other for other in included if other.get("question_id") == entry["question_id"]
                                and other.get("answer_kind") == "alternative"]
                manual = entry.get("source", {}).get("kind") == "teacher_manual"
                provenance = {
                    "kind": "teacher_manual_model_answer_import" if manual else "native_pdf_model_answer_import",
                    "draft_id": draft.id,
                    "material_id": None if manual else material.id,
                    "source_sha256": None if manual else actual_sha,
                    "review_material_id": material.id,
                    "parser": draft.snapshot.get("parser", {}),
                    "segments": entry.get("source", {}).get("segments", []),
                    "question_text_removal": entry.get("question_text_removal"),
                    "semantic_classification": entry.get("semantic_classification"),
                    "extraction_method": entry.get("extraction_method", "native_text_fallback"),
                    "extraction": draft.snapshot.get("extraction"),
                    "mapping_method": entry.get("mapping_state"),
                    "pipeline": draft.snapshot.get("pipeline"),
                    "geometry": entry.get("geometry"),
                    "teacher_correction": entry.get("teacher_correction"),
                    "loaded_model_answer": entry.get("loaded_model_answer"),
                    "review_alternatives": [
                        {"id": other["id"], "answer_text": other["answer_text"],
                         "source": other.get("source"), "teacher_correction": other.get("teacher_correction")}
                        for other in alternatives],
                }
                answer = service.model_answer(
                    draft.test_id,
                    question_id=entry["question_id"],
                    answer_text=entry["answer_text"],
                    material_id=None if manual else material.id,
                    provenance_json=provenance,
                )
                created.append(answer)
            remaining = [entry for entry in entries if entry.get("disposition") == "unassigned"]
            draft.state = "editing" if remaining else "confirmed"
            draft.snapshot = {
                **draft.snapshot,
                "confirmed_entry_ids": sorted(confirmed_ids | {entry["id"] for entry in included}),
                "confirmed_model_answers": [
                    {"id": answer.id, "question_id": answer.question_id, "version": answer.version}
                    for answer in created
                ],
            }
            draft.revision += 1
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
