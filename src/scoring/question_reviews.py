"""Append-only teacher review persistence and pinned evidence access. No inference."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .db.models import (QuestionImportDraft, QuestionImportExtraction, QuestionImportVisionRun,
                        QuestionImportVisionResult, QuestionImportReview,
                        QuestionImportReviewRevision, TestMaterial, Test)
from .pdf_native import canonical_hash, sha256_file
from .question_drafts import QuestionDraftService, DraftError
from .review_document import (SCHEMA, ReviewError, initial_snapshot, regions, review_summary,
                              validate_snapshot, warning_catalog)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def evidence_prefix(pin):
    if pin.get("evidence_source") == "teacher_review_evidence":
        UUID(pin["evidence_id"])
        return f"review-evidence/{pin['evidence_id']}/"
    return f"vision/{pin.get('run_id')}/"


class QuestionReviewService:
    def __init__(self, session, root):
        self.s, self.root = session, Path(root).resolve()

    def _draft(self, did):
        try:
            UUID(did)
        except (ValueError, TypeError):
            raise ReviewError("invalid_draft_id", 422) from None
        draft = self.s.get(QuestionImportDraft, did)
        if not draft:
            raise ReviewError("draft_not_found", 404)
        if draft.state != "completed":
            raise ReviewError("draft_not_completed")
        try:
            extraction = self.s.get(QuestionImportExtraction, draft.extraction_id)
            store, ir = QuestionDraftService(self.s, self.root)._source(extraction)
            path = store.path(f"structured/{did}/question-draft.json")
            value = _load(path)
            if (sha256_file(path) != draft.draft_sha256 or canonical_hash(value) != draft.draft_sha256
                    or canonical_hash(ir) != draft.source_ir_sha256
                    or sha256_file(store.path("source.pdf")) != ir["source"]["sha256"]):
                raise ValueError()
            return draft, store, value, ir
        except (OSError, ValueError, KeyError, TypeError, DraftError):
            raise ReviewError("source_draft_integrity_error") from None

    def _review(self, rid, *, lock=False):
        try:
            UUID(rid)
        except (TypeError, ValueError):
            raise ReviewError("review_not_found", 404) from None
        query = select(QuestionImportReview).where(QuestionImportReview.id == rid)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        review = self.s.scalar(query)
        if not review:
            raise ReviewError("review_not_found", 404)
        return review

    @staticmethod
    def _artifact(store, ref, digest, prefix=None):
        try:
            if (not isinstance(ref, str) or PurePosixPath(ref).is_absolute() or
                    ".." in PurePosixPath(ref).parts or "\\" in ref or
                    prefix is not None and not ref.startswith(prefix)):
                raise ValueError()
            path = store.path(ref)
            if not digest or sha256_file(path) != digest:
                raise ValueError()
            return path
        except (ValueError, OSError, TypeError):
            raise ReviewError("artifact_integrity_error") from None

    def _revision(self, review, store, number=None):
        number = review.current_revision if number is None else number
        row = self.s.scalar(select(QuestionImportReviewRevision).where(
            QuestionImportReviewRevision.review_id == review.id,
            QuestionImportReviewRevision.revision_number == number))
        if not row:
            raise ReviewError("revision_not_found", 404)
        # Early H.2-D hashed content before adding state/reviewed. Never rewrite
        # those artifacts; new revisions hash the full canonical snapshot.
        digest = canonical_hash(row.snapshot)
        legacy = "editing_contract" not in row.snapshot and row.revision_sha256 == canonical_hash(
            {k: v for k, v in row.snapshot.items() if k not in {"state", "reviewed"}})
        if digest != row.revision_sha256 and not legacy:
            raise ReviewError("revision_integrity_error")
        path = self._artifact(store, row.artifact_ref, digest, f"review/{review.id}/revisions/")
        if _load(path) != row.snapshot or row.source_draft_sha256 != review.source_draft_sha256:
            raise ReviewError("revision_integrity_error")
        if number == review.current_revision and row.revision_sha256 != review.current_revision_sha256:
            raise ReviewError("revision_integrity_error")
        return row

    def _vision_pin(self, draft, store):
        value = _load(store.path(f"structured/{draft.id}/question-draft.json"))
        if "review_evidence" in value:
            pin = deepcopy(value["review_evidence"])
            if pin.get("evidence_source") != "teacher_review_evidence" or pin.get("run_id") is not None:
                raise ReviewError("invalid_teacher_evidence")
            self._verify_pin(store, pin)
            return pin
        candidates = self.s.scalars(select(QuestionImportVisionRun).where(
            QuestionImportVisionRun.draft_id == draft.id, QuestionImportVisionRun.state == "completed"
        ).order_by(QuestionImportVisionRun.updated_at.desc(), QuestionImportVisionRun.id)).all()
        for run in candidates:
            plan = run.snapshot.get("plan", {})
            if plan.get("source_draft_sha256") != draft.draft_sha256:
                continue
            if canonical_hash(run.snapshot) != run.input_sha256:
                raise ReviewError("vision_input_integrity_error")
            pin = {"run_id": run.id, "input_sha256": run.input_sha256, "results": []}
            rows = self.s.scalars(select(QuestionImportVisionResult).where(
                QuestionImportVisionResult.run_id == run.id).order_by(QuestionImportVisionResult.region_id))
            for row in rows:
                e = row.evidence
                if row.state != "completed":
                    continue
                prefix = f"vision/{run.id}/"
                for name in ("crop", "raw", "normalized"):
                    self._artifact(store, e.get(f"{name}_ref"), e.get(f"{name}_sha256"), prefix)
                view = e.get("parsed_view")
                ref = view["artifact_ref"] if view else e["normalized_ref"]
                digest = view["artifact_sha256"] if view else e["normalized_sha256"]
                parsed = _load(self._artifact(store, ref, digest, prefix))
                if (parsed.get("region_id", row.region_id) != row.region_id or
                        parsed.get("source_raw_sha256", e["raw_sha256"]) != e["raw_sha256"]):
                    raise ReviewError("vision_view_integrity_error")
                output = parsed.get("output", {})
                candidate = parsed.get("transcription_normalized") or output.get("recognized_expression")
                pin["results"].append({
                    "result_id": row.id, "region_id": row.region_id, "region_type": row.region_type,
                    "question_stable_key": row.question_stable_key, "state": row.state,
                    "view_ref": ref, "view_sha256": digest,
                    "normalized_sha256": parsed.get("normalized_sha256", digest),
                    "parser_name": parsed.get("parser_name"), "parser_version": parsed.get("parser_version"),
                    "source_field": parsed.get("source_field"), "has_candidate": bool(candidate),
                    "candidate": candidate,
                    "parse_status": parsed.get("parse_status"), "structured": parsed.get("structured"),
                    "review_flags": sorted(set(parsed.get("review_flags", []) + parsed.get("parser_warnings", []))),
                    **{k: deepcopy(e[k]) for k in ("crop_ref", "crop_sha256", "raw_ref", "raw_sha256",
                                                   "normalized_ref", "crop", "model", "prompt")},
                })
            return pin
        return {"run_id": None, "results": []}

    def _verify_pin(self, store, pin):
        for p in pin.get("results", []):
            if "view_ref" not in p:
                # Legacy reviews containing actual vision require an explicit
                # migration, never implicit selection of a newer parser result.
                raise ReviewError("legacy_vision_pin_requires_migration")
            prefix = evidence_prefix(pin)
            for kind in ("crop", "raw", "view"):
                self._artifact(store, p.get(f"{kind}_ref"), p.get(f"{kind}_sha256"), prefix)

    def _write_revision(self, review, snap, store, parent, changed):
        number = (parent or 0) + 1
        ref = f"review/{review.id}/revisions/{number:06d}.json"
        digest = canonical_hash(snap)
        row = QuestionImportReviewRevision(id=str(uuid4()), review_id=review.id,
            revision_number=number, parent_revision_number=parent,
            source_draft_sha256=review.source_draft_sha256, schema_version=SCHEMA,
            revision_sha256=digest, artifact_ref=ref, snapshot=deepcopy(snap),
            change_metadata={"changed_nodes": changed, "state": snap["state"],
                             "hash_contract": "canonical-full-snapshot", "reviewer_id": None})
        self.s.add(row)
        self.s.flush()
        path = store.path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as out:
                out.write(_json(snap))
        except FileExistsError:
            if sha256_file(path) != digest:
                raise ReviewError("revision_artifact_conflict") from None
        if sha256_file(path) != digest:
            raise ReviewError("revision_artifact_integrity_error")
        review.current_revision, review.current_revision_sha256 = number, digest
        review.state = snap["state"]
        return row

    def _manifest(self, review, store, ir):
        revisions = self.s.scalars(select(QuestionImportReviewRevision).where(
            QuestionImportReviewRevision.review_id == review.id).order_by(
                QuestionImportReviewRevision.revision_number)).all()
        value = {"schema_version": SCHEMA, "review_id": review.id, "draft_id": review.draft_id,
                 "source_draft_sha256": review.source_draft_sha256,
                 "source_pdf_sha256": ir["source"]["sha256"], "source_ir_sha256": canonical_hash(ir),
                 "vision_pin": revisions[0].snapshot["vision_pin"],
                 "current_revision": review.current_revision,
                 "revisions": [{"number": x.revision_number, "sha256": x.revision_sha256,
                                "artifact_ref": x.artifact_ref} for x in revisions],
                 "created_at": review.created_at.isoformat()}
        path = store.path(f"review/{review.id}/manifest.json")
        temp = path.with_name(f".manifest-{uuid4()}.tmp")
        temp.write_text(_json(value), encoding="utf-8")
        temp.replace(path)

    def create(self, did):
        draft, store, value, ir = self._draft(did)
        existing = self.s.scalar(select(QuestionImportReview).where(QuestionImportReview.draft_id == did))
        if existing:
            return self.get(existing.id)
        pin = self._vision_pin(draft, store)
        rid = str(uuid4())
        review = QuestionImportReview(id=rid, draft_id=did, source_draft_sha256=draft.draft_sha256,
            vision_run_id=pin["run_id"], state="editing", current_revision=0, current_revision_sha256="",
            artifact_ref=f"question-imports/{draft.extraction_id}/review/{rid}")
        try:
            self.s.add(review)
            self.s.flush()
            self._write_revision(review, initial_snapshot(draft.draft_sha256, value, pin), store, None, [])
            self.s.flush()
            self._manifest(review, store, ir)
            self.s.commit()
        except IntegrityError:
            self.s.rollback()
            existing = self.s.scalar(select(QuestionImportReview).where(QuestionImportReview.draft_id == did))
            if existing:
                return self.get(existing.id)
            raise ReviewError("review_creation_conflict") from None
        return self.get(rid)

    def list_for_test(self, test_id):
        if not self.s.get(Test, test_id):
            raise ReviewError("test_not_found", 404)
        rows = self.s.execute(select(QuestionImportDraft, QuestionImportReview, TestMaterial)
            .join(QuestionImportExtraction, QuestionImportDraft.extraction_id == QuestionImportExtraction.id)
            .join(TestMaterial, QuestionImportExtraction.material_id == TestMaterial.id)
            .outerjoin(QuestionImportReview, QuestionImportReview.draft_id == QuestionImportDraft.id)
            .where(QuestionImportExtraction.test_id == test_id, QuestionImportDraft.state == "completed")
            .order_by(QuestionImportDraft.created_at.desc())).all()
        result = []
        for draft, review, material in rows:
            _, _, value, _ = self._draft(draft.id)
            current = self.get(review.id) if review else None
            result.append({"id": review.id if review else None, "draft_id": draft.id,
                "source_filename": material.original_filename, "draft_created_at": draft.created_at,
                "parser_version": draft.parser_version, "question_count": len(value["nodes"]),
                "review_required": draft.review_required, "warning_count":
                    current["summary"]["unresolved_warnings"] if current else len(value["review_flags"]),
                "has_vision": bool(self.s.scalar(select(QuestionImportVisionResult.id).join(
                    QuestionImportVisionRun, QuestionImportVisionResult.run_id == QuestionImportVisionRun.id)
                    .where(QuestionImportVisionRun.draft_id == draft.id,
                           QuestionImportVisionResult.state == "completed").limit(1))),
                "state": review.state if review else "not_started",
                "current_revision": review.current_revision if review else None,
                "source_draft_sha256": draft.draft_sha256})
        return result

    def get(self, rid, number=None):
        review = self._review(rid)
        draft, store, value, ir = self._draft(review.draft_id)
        if draft.draft_sha256 != review.source_draft_sha256:
            raise ReviewError("source_draft_mismatch")
        rev = self._revision(review, store, number)
        snap = deepcopy(rev.snapshot)
        pin = snap["vision_pin"]
        self._verify_pin(store, pin)
        extraction = self.s.get(QuestionImportExtraction, draft.extraction_id)
        return {"id": review.id, "draft_id": review.draft_id, "test_id": extraction.test_id,
                "state": snap["state"], "current_revision": review.current_revision,
                "revision_number": rev.revision_number, "current_revision_sha256": review.current_revision_sha256,
                "revision_sha256": rev.revision_sha256, "vision_run_id": review.vision_run_id,
                "artifact_ref": f"question-imports/{draft.extraction_id}/review/{review.id}", "snapshot": snap,
                "page_count": len(ir["pages"]), "source_pdf_sha256": ir["source"]["sha256"],
                "source_ir_sha256": canonical_hash(ir), "summary": review_summary(snap, value, pin),
                "warnings": warning_catalog(value, pin), "regions": regions(value),
                "automatic_nodes": value["nodes"],
                "source_regions": {n["stable_key"]: n["source_regions"] for n in value["nodes"]}}

    def save(self, rid, payload, *, mark=False):
        review = self._review(rid, lock=True)
        draft, store, value, ir = self._draft(review.draft_id)
        current = self._revision(review, store)
        self._verify_pin(store, current.snapshot["vision_pin"])
        if draft.draft_sha256 != review.source_draft_sha256:
            raise ReviewError("source_draft_mismatch")
        base = payload.get("base_revision")
        if base not in {review.current_revision, current.parent_revision_number}:
            raise ReviewError("revision_conflict")
        validation_base = self._revision(review, store, base) if base != review.current_revision else current
        snap = validate_snapshot(payload.get("snapshot"), validation_base.snapshot, value,
                                 current.snapshot["vision_pin"], mark=mark)
        digest = canonical_hash(snap)
        if digest == canonical_hash(current.snapshot) and base in {
                review.current_revision, current.parent_revision_number}:
            return self.get(rid)
        if base != review.current_revision:
            raise ReviewError("revision_conflict")
        changed = [n["review_node_id"] for n in snap["nodes"] if n not in current.snapshot["nodes"]]
        result = self.s.execute(update(QuestionImportReview).where(
            QuestionImportReview.id == rid, QuestionImportReview.current_revision == base
        ).values(current_revision=base + 1).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            self.s.rollback()
            raise ReviewError("revision_conflict")
        try:
            review.artifact_ref = f"question-imports/{draft.extraction_id}/review/{review.id}"
            self._write_revision(review, snap, store, base, changed)
            self.s.flush()
            self._manifest(review, store, ir)
            self.s.commit()
        except IntegrityError:
            self.s.rollback()
            raise ReviewError("revision_conflict") from None
        return self.get(rid)

    def revisions(self, rid):
        review = self._review(rid)
        _, store, _, _ = self._draft(review.draft_id)
        rows = self.s.scalars(select(QuestionImportReviewRevision).where(
            QuestionImportReviewRevision.review_id == rid).order_by(
                QuestionImportReviewRevision.revision_number)).all()
        for row in rows:
            self._revision(review, store, row.revision_number)
        return [{"revision_number": x.revision_number, "parent_revision_number": x.parent_revision_number,
                 "revision_sha256": x.revision_sha256, "artifact_ref": x.artifact_ref,
                 "created_at": x.created_at, "state": x.snapshot["state"],
                 "change_metadata": x.change_metadata} for x in rows]

    def mark_reviewed(self, rid, base):
        current = self.get(rid)
        if current["current_revision"] != base:
            raise ReviewError("revision_conflict")
        snap = deepcopy(current["snapshot"])
        snap.update(state="reviewed", reviewed=True)
        return self.save(rid, {"base_revision": base, "snapshot": snap}, mark=True)

    def _region(self, rid, region_id):
        review = self._review(rid)
        _, store, draft, ir = self._draft(review.draft_id)
        snap = self._revision(review, store).snapshot
        region = next((r for r in regions(draft) if r["region_id"] == region_id), None)
        if region is None:
            raise ReviewError("region_not_found", 404)
        pin = next((p for p in snap["vision_pin"]["results"] if p["region_id"] == region_id), None)
        if pin and (pin.get("question_stable_key") != region.get("assigned_question_key") or
                    pin.get("region_type") != region["region_type"]):
            raise ReviewError("pinned_evidence_mismatch")
        return store, ir, region, pin, evidence_prefix(snap["vision_pin"])

    def region_evidence(self, rid, region_id):
        store, ir, region, pin, run_id = self._region(rid, region_id)
        parsed = None
        if pin:
            parsed = _load(self._artifact(store, pin["view_ref"], pin["view_sha256"], run_id))
        elements = [e for p in ir["pages"] for e in p["elements"]
                    if e["element_id"] in region["source_element_ids"]]
        return {"region": region, "native_elements": elements, "pin": pin, "parsed_view": parsed,
                "crop_available": True, "crop_source": "pinned_vision" if pin else "review_preview",
                "raw_available": bool(pin)}

    def region_crop(self, rid, region_id):
        store, ir, region, pin, run_id = self._region(rid, region_id)
        if not pin:
            from .review_preview import native_region_preview

            return native_region_preview(store, ir, region)
        return self._artifact(store, pin["crop_ref"], pin["crop_sha256"], run_id)

    def region_raw(self, rid, region_id):
        store, _, _, pin, run_id = self._region(rid, region_id)
        if not pin:
            raise ReviewError("vision_raw_not_available", 404)
        return {"source_raw_sha256": pin["raw_sha256"], "result_id": pin["result_id"],
                "raw": _load(self._artifact(store, pin["raw_ref"], pin["raw_sha256"], run_id))}

    def preview(self, rid, page_index):
        from .review_preview import page_preview

        review = self._review(rid)
        _, store, draft, ir = self._draft(review.draft_id)
        self._revision(review, store)
        return page_preview(store, ir, draft, page_index)
