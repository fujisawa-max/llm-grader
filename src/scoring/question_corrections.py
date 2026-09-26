"""Explicit, append-only authoritative corrections for imported questions.

This module deliberately treats formula transcriptions as opaque teacher text.  It
does not normalize or unescape LaTeX and it never edits Review/Confirmation rows.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from .db.models import (
    GradingJob,
    QuestionImportConfirmation,
    QuestionImportReview,
    TestQuestion,
    TestQuestionAsset,
    TestQuestionCorrection,
)
from .grading_context import EffectiveQuestionContextBuilder, ContextError
from .pdf_native import canonical_hash, sha256_file
from .question_import import write_artifact
from .question_reviews import QuestionReviewService, ReviewError


ACTIVE_JOB_STATES = {"queued", "pending", "preparing", "running", "paused", "resuming"}


def _question_text(content):
    return "".join(
        item.get("text", "") if item.get("type") == "text" else
        item.get("transcription", "") if item.get("type") == "formula" else
        "[図]" if item.get("type") == "figure" else ""
        for item in content.get("items", [])
    )


def _copy_question(question, content, digest):
    """Make a detached SQLAlchemy-compatible question for context planning."""
    detached = TestQuestion(**{c.name: deepcopy(getattr(question, c.name))
                               for c in TestQuestion.__table__.columns})
    detached.content = content
    detached.content_sha256 = digest
    detached.question_text = _question_text(content)
    return detached


class QuestionCorrectionService:
    def __init__(self, session, root):
        self.s, self.root = session, Path(root).resolve()

    def _question(self, question_id, *, lock=False):
        query = select(TestQuestion).where(TestQuestion.id == question_id)
        if lock:
            query = query.with_for_update()
        question = self.s.scalar(query)
        if not question:
            raise ReviewError("question_not_found", 404)
        if (question.provenance or {}).get("origin") != "review_import":
            raise ReviewError("correction_imported_questions_only", 409)
        if not isinstance(question.content, dict) or not isinstance(question.content.get("items"), list):
            raise ReviewError("correction_content_unresolvable", 409)
        if question.content_sha256 and canonical_hash(question.content) != question.content_sha256:
            raise ReviewError("correction_content_hash_mismatch", 409)
        return question

    @staticmethod
    def _validate_operations(question, operations):
        if not isinstance(operations, list) or not operations or len(operations) > 100:
            raise ReviewError("correction_operations_required", 422)
        if any(isinstance(op, dict) and op.get("type") == "set_text_segment" for op in operations):
            if len(operations) != 1:
                raise ReviewError("text_correction_must_be_standalone", 422)
            op = operations[0]
            index = op.get("item_index")
            items = question.content.get("items", [])
            if type(index) is not int or not 0 <= index < len(items) or items[index].get("type") != "text":
                raise ReviewError("text_target_not_found", 422)
            old, new = op.get("expected_old_text"), op.get("new_text")
            if not isinstance(old, str) or items[index].get("text") != old:
                raise ReviewError("correction_old_value_mismatch", 409)
            if not isinstance(new, str) or not new.strip() or len(new) > 20000:
                raise ReviewError("invalid_correction_text", 422)
            proposed = deepcopy(question.content)
            proposed["items"][index]["text"] = new
            return [{"type": "set_text_segment", "item_index": index,
                     "source_region_id": f"text-item:{index}", "previous": old, "new": new}], proposed
        if any(op.get("type") == "set_max_points" for op in operations if isinstance(op, dict)):
            if len(operations) != 1:
                raise ReviewError("max_points_correction_must_be_standalone", 422)
            op = operations[0]
            old = op.get("expected_old_value")
            if old is not None and getattr(question, "max_points") != old:
                raise ReviewError("correction_old_value_mismatch", 409)
            value = op.get("new_value")
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or value <= 0 or value != int(value)):
                raise ReviewError("invalid_max_points", 422)
            return [{"type": "set_max_points", "previous": getattr(question, "max_points"),
                     "new": float(value)}], deepcopy(question.content)
        if any(op.get("type") in {"set_display_label", "set_title"} for op in operations if isinstance(op, dict)):
            if len(operations) != 1:
                raise ReviewError("label_correction_must_be_standalone", 422)
            op = operations[0]
            field = "title" if op["type"] == "set_title" else "display_label"
            if getattr(question, field) != op.get("expected_old_value"):
                raise ReviewError("correction_old_value_mismatch", 409)
            value = op.get("new_value")
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ReviewError(f"invalid_{field}", 422)
            return [{"type": op["type"], "previous": getattr(question, field),
                     "new": value}], deepcopy(question.content)
        by_region = {
            item.get("source_region_id"): item
            for item in question.content.get("items", [])
            if item.get("type") == "formula" and isinstance(item.get("source_region_id"), str)
        }
        proposed = deepcopy(question.content)
        seen = set()
        normalized = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ReviewError("invalid_correction_operation", 422)
            region_id = operation.get("source_region_id")
            if not isinstance(region_id, str) or not region_id or region_id in seen:
                raise ReviewError("invalid_correction_target", 422)
            current = by_region.get(region_id)
            if current is None:
                raise ReviewError("formula_target_not_found", 404)
            old = operation.get("expected_old_transcription")
            new = operation.get("new_transcription")
            if not isinstance(old, str) or current.get("transcription") != old:
                raise ReviewError("correction_old_value_mismatch", 409)
            if not isinstance(new, str) or not new.strip() or len(new) > 20000:
                raise ReviewError("invalid_correction_transcription", 422)
            seen.add(region_id)
            normalized.append({"source_region_id": region_id, "previous": old, "new": new})
            for item in proposed["items"]:
                if item.get("type") == "formula" and item.get("source_region_id") == region_id:
                    item["transcription"] = new
                    break
        normalized.sort(key=lambda x: x["source_region_id"])
        return normalized, proposed

    def _context_hash(self, question, content, metadata=None):
        questions = list(self.s.scalars(select(TestQuestion).where(TestQuestion.test_id == question.test_id)))
        replacement = _copy_question(question, content, canonical_hash(content))
        if metadata is not None:
            setattr(replacement, metadata[0], metadata[1])
        questions = [replacement if q.id == question.id else q for q in questions]
        assets = list(self.s.scalars(select(TestQuestionAsset).join(TestQuestion)
                                     .where(TestQuestion.test_id == question.test_id)))
        try:
            return EffectiveQuestionContextBuilder(questions, assets, root=self.root).build(question.id)["context_sha256"]
        except ContextError as exc:
            raise ReviewError(f"correction_context_{exc.code.lower()}", 409) from exc

    def _source(self, question):
        provenance = question.provenance or {}
        cid = provenance.get("confirmation_id")
        confirmation = self.s.get(QuestionImportConfirmation, cid) if cid else None
        review = self.s.get(QuestionImportReview, confirmation.review_id) if confirmation else None
        if not confirmation or not review:
            raise ReviewError("correction_source_missing", 409)
        return confirmation, review

    def plan(self, question_id, *, expected_content_sha256, operations, reason_code, note=None):
        question = self._question(question_id)
        actual = canonical_hash(question.content)
        if expected_content_sha256 != actual or question.content_sha256 != actual:
            raise ReviewError("correction_content_conflict", 409)
        if not isinstance(reason_code, str) or not reason_code.strip() or len(reason_code) > 128:
            raise ReviewError("correction_reason_required", 422)
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ReviewError("invalid_correction_note", 422)
        normalized, content = self._validate_operations(question, operations)
        metadata_field = {"set_display_label": "display_label", "set_title": "title",
                          "set_max_points": "max_points"}.get(normalized[0].get("type"))
        confirmation, review = self._source(question)
        new_hash = canonical_hash(content)
        plan = {
            "schema_version": "test-question-correction-plan.v1",
            "question_id": question.id,
            "test_id": question.test_id,
            "confirmation_id": confirmation.id,
            "review_id": review.id,
            "review_revision": confirmation.review_revision_number,
            "current_content_sha256": actual,
            "operations": normalized,
            "reason_code": reason_code,
            "note": note,
            "new_content_sha256": new_hash,
            "new_question_text": question.question_text if metadata_field else _question_text(content),
            "resulting_context_sha256": self._context_hash(question, content, (metadata_field, normalized[0]["new"]) if metadata_field else None),
            "blockers": [],
        }
        if metadata_field:
            plan.update({f"current_{metadata_field}": getattr(question, metadata_field),
                         f"proposed_{metadata_field}": normalized[0]["new"]})
            plan.update(correction_type=normalized[0]["type"], changes=[metadata_field],
                        correction_version=self.s.scalar(select(func.max(TestQuestionCorrection.correction_version)).where(
                            TestQuestionCorrection.test_question_id == question.id)) or 0)
        elif normalized[0].get("type") == "set_text_segment":
            plan["correction_type"] = "set_text_segment"
        plan["plan_sha256"] = canonical_hash(plan)
        return plan

    def _assert_no_active_job(self, question):
        active = self.s.scalar(select(GradingJob.id).where(
            GradingJob.test_id == question.test_id, GradingJob.state.in_(ACTIVE_JOB_STATES)
        ).limit(1))
        if active:
            raise ReviewError("active_grading_job_exists", 409)

    def apply(self, question_id, *, expected_content_sha256, operations, reason_code,
              plan_sha256, note=None):
        try:
            question = self._question(question_id, lock=True)
            self._assert_no_active_job(question)
            plan = self.plan(question_id, expected_content_sha256=expected_content_sha256,
                             operations=operations, reason_code=reason_code, note=note)
            if plan["plan_sha256"] != plan_sha256:
                raise ReviewError("stale_correction_plan", 409)
            # Re-read under the row lock: plan() is intentionally read-only but its
            # detached question must not be allowed to race a concurrent correction.
            actual = canonical_hash(question.content)
            if actual != expected_content_sha256 or question.content_sha256 != actual:
                raise ReviewError("correction_content_conflict", 409)
            metadata_field = {"set_display_label": "display_label", "set_title": "title",
                              "set_max_points": "max_points"}.get(plan.get("correction_type"))
            content = deepcopy(question.content)
            for operation in plan["operations"]:
                if metadata_field:
                    continue
                if operation.get("type") == "set_text_segment":
                    content["items"][operation["item_index"]]["text"] = operation["new"]
                    continue
                for item in content["items"]:
                    if item.get("type") == "formula" and item.get("source_region_id") == operation["source_region_id"]:
                        item["transcription"] = operation["new"]
                        break
            previous = {x.get("source_region_id", metadata_field): x["previous"] for x in plan["operations"]}
            new_values = {x.get("source_region_id", metadata_field): x["new"] for x in plan["operations"]}
            version = (self.s.scalar(select(func.max(TestQuestionCorrection.correction_version)).where(
                TestQuestionCorrection.test_question_id == question.id
            )) or 0) + 1
            correction_id = str(uuid4())
            confirmation, review = self._source(question)
            ref = f"question-corrections/{correction_id}"
            correction = TestQuestionCorrection(
                id=correction_id, test_question_id=question.id, correction_version=version,
                correction_type=plan.get("correction_type", "set_formula_transcription"),
                source_region_ids=[] if metadata_field else [x["source_region_id"] for x in plan["operations"]],
                previous_content_sha256=actual, new_content_sha256=plan["new_content_sha256"],
                previous_value=previous, new_value=new_values, reason_code=reason_code, note=note,
                source_confirmation_id=confirmation.id, source_review_id=review.id,
                source_revision_number=confirmation.review_revision_number, artifact_ref=ref,
            )
            self.s.add(correction)
            if metadata_field:
                setattr(question, metadata_field, plan[f"proposed_{metadata_field}"])
            else:
                question.content = content
                question.content_sha256 = plan["new_content_sha256"]
                question.question_text = plan["new_question_text"]
            self.s.flush()
            # Correction artifacts are separate from the original confirmation namespace.
            draft, store, _, ir = QuestionReviewService(self.s, self.root)._draft(review.draft_id)
            base = store.path(ref)
            base.mkdir(parents=True, exist_ok=False)
            plan_hash = write_artifact(base / "plan.json", plan)
            correction_json = {
                "correction_id": correction_id, "question_id": question.id,
                "operations": plan["operations"], "reason_code": reason_code, "note": note,
                "previous_content_sha256": actual, "new_content_sha256": plan["new_content_sha256"],
            }
            correction_hash = write_artifact(base / "correction.json", correction_json)
            manifest = {
                "correction_id": correction_id, "test_id": question.test_id, "question_id": question.id,
                "confirmation_id": confirmation.id, "review_id": review.id,
                "review_revision": confirmation.review_revision_number,
                "source_pdf_sha256": ir["source"]["sha256"], "source_draft_sha256": draft.draft_sha256,
                "previous_content_sha256": actual, "new_content_sha256": plan["new_content_sha256"],
                "artifact_hashes": {"plan.json": plan_hash, "correction.json": correction_hash},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest_hash = write_artifact(base / "manifest.json", manifest)
            write_artifact(base / f"manifest-{manifest_hash}.json", manifest)
            correction.artifact_ref = f"{ref}/manifest-{manifest_hash}.json"
            self.s.flush()
            result = self._history_row(correction)
            self.s.commit()
            return result
        except Exception:
            self.s.rollback()
            raise

    @staticmethod
    def _history_row(row):
        return {"id": row.id, "question_id": row.test_question_id, "correction_version": row.correction_version,
                "correction_type": row.correction_type, "source_region_ids": row.source_region_ids,
                "previous_content_sha256": row.previous_content_sha256,
                "new_content_sha256": row.new_content_sha256, "previous_value": row.previous_value,
                "new_value": row.new_value, "reason_code": row.reason_code, "note": row.note,
                "confirmation_id": row.source_confirmation_id, "review_id": row.source_review_id,
                "review_revision": row.source_revision_number, "artifact_ref": row.artifact_ref,
                "created_at": row.created_at.isoformat() if row.created_at else None}

    def _verify_artifact(self, row):
        """Validate the correction manifest before exposing its history."""
        question = self.s.get(TestQuestion, row.test_question_id)
        confirmation, review = self._source(question)
        draft, store, _, _ = QuestionReviewService(self.s, self.root)._draft(review.draft_id)
        if not row.artifact_ref or not row.artifact_ref.startswith(f"question-corrections/{row.id}/"):
            raise ReviewError("correction_artifact_integrity_error")
        digest = Path(row.artifact_ref).stem.removeprefix("manifest-")
        manifest_path = QuestionReviewService._artifact(
            store, row.artifact_ref, digest, f"question-corrections/{row.id}/"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if canonical_hash(manifest) != digest or manifest.get("correction_id") != row.id:
            raise ReviewError("correction_artifact_integrity_error")
        base = manifest_path.parent
        for name, expected in manifest.get("artifact_hashes", {}).items():
            if name not in {"plan.json", "correction.json"} or sha256_file(base / name) != expected:
                raise ReviewError("correction_artifact_integrity_error")
        plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
        if (plan.get("question_id"), plan.get("current_content_sha256"), plan.get("new_content_sha256")) != (
            row.test_question_id, row.previous_content_sha256, row.new_content_sha256
        ) or plan.get("confirmation_id") != confirmation.id:
            raise ReviewError("correction_artifact_integrity_error")
        return True

    def history(self, question_id):
        self._question(question_id)
        rows = self.s.scalars(select(TestQuestionCorrection).where(
            TestQuestionCorrection.test_question_id == question_id
        ).order_by(TestQuestionCorrection.correction_version)).all()
        for row in rows:
            self._verify_artifact(row)
        return [self._history_row(row) for row in rows]
