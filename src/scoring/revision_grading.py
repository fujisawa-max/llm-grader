"""Revision-only adapter for new Web grading inputs.

The adapter reads grading semantics exclusively from a verified confirmed
snapshot. Mutable formal Question rows are used only as frozen relational IDs
for student-specific OCR/reconstruction records.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from .db.models import (
    RubricVersion,
    Student,
    StudentAnswerExtractionResult,
    StudentAnswerExtractionRun,
    StudentAnswerReconstruction,
    StudentSubmission,
    Test,
    TestMaterial,
)
from .grading_context import ContextError
from .grading_definition import (
    confirmed_edition_label,
    confirmed_revision_for_test,
    read_reference_asset,
    revision_question_identity_map,
)
from .grading_mapping import answer_pages
from .grading_audit import resolve_selected_reconstruction
from .pdf_native import canonical_hash, sha256_file


def _frozen_reference(reference, *, question_id, role, model_answer_id=None):
    artifact = reference.get("immutable_artifact")
    if not isinstance(artifact, dict):
        raise ContextError("GRADING_DEFINITION_ARTIFACT_UNAVAILABLE")
    value = {**deepcopy(reference), "asset_id": reference["asset_id"],
             "question_id": question_id, "mime_type": reference.get("mime_type", "image/png"),
             "sha256": reference["sha256"], "artifact_ref": artifact["artifact_ref"],
             "role": role}
    if role == "question_context":
        value["source_question_id"] = question_id
    if model_answer_id:
        value["model_answer_id"] = model_answer_id
    return value


def _question_source_provenance(definition, question, question_id):
    source = definition.get("source_provenance") or {}
    key = question["question_key"]
    rows = source.get("questions") or []
    question_row = next((row for row in rows
        if row.get("id") == question_id
        or (row.get("provenance") or {}).get("authoring_stable_key") == key
        or row.get("stable_question_key") == key), {})
    answers = source.get("model_answers") or []
    answer_row = next((row for row in answers
        if row.get("question_id") == question_id
        or (row.get("provenance_json") or {}).get("authoring_stable_key") == key), {})
    return question_row, answer_row, deepcopy(source.get("rubric") or {})


def frozen_question_package(definition, revision_id, question, question_id, question_ids):
    """Project executable grading inputs from the confirmed snapshot only."""
    key = question["question_key"]
    context = deepcopy(question["context"])
    context["question_id"] = key
    question_refs = []
    for reference in context.get("assets", []):
        source_key = reference.get("source_question_id")
        question_refs.append(_frozen_reference(reference,
            question_id=question_ids.get(source_key, question_id), role="question_context"))
    answer_id = f"revision:{revision_id}:answer:{key}"
    answer_refs = [_frozen_reference(reference, question_id=question_id,
        role="model_answer_reference", model_answer_id=answer_id)
        for reference in question.get("visual_references", [])
        if reference.get("role") == "model_answer_reference"]
    answer = question.get("answer") or {}
    alternatives = answer.get("alternatives") or []
    if not isinstance(alternatives, list):
        raise ContextError("GRADING_DEFINITION_ANSWER_INVALID")
    criterion_rows = [{"id": criterion["executable_id"],
        "authoring_criterion_id": criterion["criterion_id"],
        "description": criterion["description"], "points": int(criterion["max_score"]),
        "levels": deepcopy(criterion["levels"])}
        for criterion in question.get("rubric", {}).get("criteria", [])]
    entry = {"question_id": question_id, "max_points": int(question["max_points"]),
             "aggregation": question["rubric"].get("aggregation", "sum"),
             "criteria": criterion_rows}
    question_source, answer_source, rubric_source = _question_source_provenance(
        definition, question, question_id)
    return {
        "question": {"context": context, "context_sha256": context["context_sha256"],
            "content_sha256": canonical_hash(question["content"]),
            "max_points": int(question["max_points"]),
            "provenance": deepcopy(question_source),
            "corrections": deepcopy(question.get("corrections", []))},
        "model_answer": {"id": answer_id, "question_id": question_id,
            "content": answer.get("primary", ""), "alternatives": deepcopy(alternatives),
            "sha256": canonical_hash(answer.get("primary", "")),
            "alternatives_sha256": canonical_hash(alternatives),
            "provenance": deepcopy(answer_source)},
        "rubric": {"question_id": question_id, "entry": entry,
            "entry_sha256": canonical_hash(entry), "provenance": rubric_source},
        "assets": question_refs + answer_refs,
        "visual_references": question_refs + answer_refs,
    }


def validate_revision_bound_bundle(bundle, revision, question_ids):
    """Fail closed if a job's cached bundle no longer matches its pinned snapshot."""
    from .grading_definition import confirmed_definition

    definition = confirmed_definition(revision)
    identity = bundle.get("identity") or {}
    key = identity.get("stable_question_key")
    question = next((item for item in definition["questions"]
                     if item.get("question_key") == key and item.get("gradable")), None)
    if (identity.get("test_id") != revision.test_id
            or identity.get("confirmed_authoring_revision_id") != revision.id
            or identity.get("confirmed_snapshot_sha256") != revision.snapshot_sha256
            or question is None or question_ids.get(key) != identity.get("question_id")):
        raise ValueError("WEB_GRADING_REVISION_BUNDLE_MISMATCH")
    expected = frozen_question_package(definition, revision.id, question,
                                       identity["question_id"], question_ids)
    if (bundle.get("question") != expected["question"]
            or bundle.get("model_answer") != expected["model_answer"]
            or bundle.get("rubric", {}).get("question_id") != expected["rubric"]["question_id"]
            or bundle.get("rubric", {}).get("entry") != expected["rubric"]["entry"]
            or bundle.get("rubric", {}).get("entry_sha256") != expected["rubric"]["entry_sha256"]
            or bundle.get("rubric", {}).get("provenance") != expected["rubric"]["provenance"]
            or bundle.get("assets") != expected["assets"]):
        raise ValueError("WEB_GRADING_REVISION_BUNDLE_MISMATCH")
    visual_assets = bundle.get("visual_assets")
    if visual_assets is not None:
        static_visual_assets = [row for row in visual_assets
                                if row.get("role") != "student_visual_answer"]
        if static_visual_assets != expected["visual_references"]:
            raise ValueError("WEB_GRADING_REVISION_BUNDLE_MISMATCH")
    return definition


def verify_revision_job_contract(session, job, submission):
    """Verify a persisted Web job against its Submission's frozen revision."""
    revision_id = submission.confirmed_authoring_revision_id
    if (not revision_id or job.confirmed_authoring_revision_id != revision_id
            or submission.test_id != job.test_id):
        raise ValueError("WEB_GRADING_REVISION_BINDING_MISMATCH")
    from .db.models import ConfirmedAuthoringRevision
    from .grading_execution import snapshot_hash
    from .grading_definition import confirmed_definition, revision_question_identity_map

    revision = session.get(ConfirmedAuthoringRevision, revision_id)
    if revision is None or revision.test_id != submission.test_id:
        raise ValueError("WEB_GRADING_REVISION_TEST_MISMATCH")
    definition = confirmed_definition(revision)
    snapshot = (job.metadata_json or {}).get("grading_execution") or {}
    bundle = snapshot.get("bundle") or {}
    if (definition.get("complete") is not True
            or snapshot.get("confirmed_authoring_revision_id") != revision.id
            or snapshot.get("confirmed_snapshot_sha256") != revision.snapshot_sha256
            or snapshot_hash(snapshot) != snapshot.get("snapshot_sha256")
            or canonical_hash({k: v for k, v in bundle.items() if k != "bundle_sha256"})
            != bundle.get("bundle_sha256")
            or (bundle.get("student_answer") or {}).get("submission_id") != submission.id
            or bundle.get("rubric", {}).get("id") != job.rubric_version_id
            or len(job.items) != 1):
        raise ValueError("WEB_GRADING_REVISION_BINDING_MISMATCH")
    item = job.items[0]
    item_metadata = item.metadata_json or {}
    identity = bundle.get("identity") or {}
    if (identity.get("confirmed_authoring_revision_id") != revision.id
            or identity.get("confirmed_snapshot_sha256") != revision.snapshot_sha256
            or item_metadata.get("submission_id") != submission.id
            or item_metadata.get("question_id") != identity.get("question_id")
            or item_metadata.get("stable_question_key") != identity.get("stable_question_key")
            or item_metadata.get("confirmed_authoring_revision_id") != revision.id
            or item_metadata.get("confirmed_snapshot_sha256") != revision.snapshot_sha256
            or item_metadata.get("bundle_sha256") != bundle.get("bundle_sha256")):
        raise ValueError("WEB_GRADING_REVISION_BINDING_MISMATCH")
    question_ids = revision_question_identity_map(session, job.test_id, definition)
    validate_revision_bound_bundle(bundle, revision, question_ids)
    return revision, definition, snapshot, bundle


class RevisionGradingInputAssembler:
    def __init__(self, session, test_id, submission_id, *, question_root=None,
                 answer_root=None, allowed_roots=None, visual_capability=None):
        self.s = session
        self.test_id = test_id
        self.submission = session.get(StudentSubmission, submission_id)
        if self.submission is None or self.submission.test_id != test_id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        roots = {"question_import": question_root, "answer_import": answer_root}
        try:
            self.revision, self.definition = confirmed_revision_for_test(
                session, test_id, self.submission.confirmed_authoring_revision_id,
                artifact_roots=roots,
            )
        except ValueError as exc:
            raise ContextError(str(exc)) from exc
        self.revision_roots = {k: Path(v).resolve() for k, v in roots.items() if v is not None}
        self.question_ids = revision_question_identity_map(session, test_id, self.definition)
        self.questions = {q["question_key"]: q for q in self.definition["questions"]}
        self.keys_by_id = {value: key for key, value in self.question_ids.items()}
        self.visual_capability = visual_capability
        self.question_root = Path(question_root).resolve() if question_root else None
        self.answer_root = Path(answer_root).resolve() if answer_root else None
        self.allowed_roots = [Path(v).resolve() for v in (allowed_roots or [])]
        for root in (self.question_root, self.answer_root):
            if root and root not in self.allowed_roots:
                self.allowed_roots.append(root)
        self.test = session.get(Test, test_id)
        self.material = session.get(TestMaterial, self.submission.material_id)
        if self.material is None or self.material.test_id != test_id:
            raise ContextError("CROSS_TEST_ANSWER_MAPPING")
        self.student = session.get(Student, self.submission.student_id)
        if self.student is None or self.student.course_offering_id != self.test.course_offering_id:
            raise ContextError("CROSS_STUDENT_ANSWER_MAPPING")
        self.source_path = Path(self.material.storage_ref)
        if not self.source_path.is_absolute():
            base = self.answer_root or self.question_root
            if base is None:
                raise ContextError("STUDENT_ANSWER_SOURCE_UNAVAILABLE")
            self.source_path = base / self.source_path
        self.source_path = self.source_path.resolve()
        if (not self.allowed_roots or not any(self.source_path.is_relative_to(root) for root in self.allowed_roots)
                or not self.source_path.is_file()):
            raise ContextError("STUDENT_ANSWER_SOURCE_UNAVAILABLE")
        if self.material.sha256 and sha256_file(self.source_path) != self.material.sha256:
            raise ContextError("STUDENT_ANSWER_SOURCE_HASH_MISMATCH")
        self.source_sha256 = self.material.sha256 or sha256_file(self.source_path)
        self.document = self._load_document()
        self.pages = self._pages()
        self.answer_by_key = self._answers_by_key()
        self.rubric_version_id = self._rubric_compatibility_id()

    def _load_document(self):
        if self.source_path.suffix.lower() != ".json":
            return None
        try:
            value = json.loads(self.source_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE") from exc
        for field, expected, code in (
            ("test_id", self.test_id, "CROSS_TEST_ANSWER_MAPPING"),
            ("student_id", self.submission.student_id, "CROSS_STUDENT_ANSWER_MAPPING"),
            ("submission_id", self.submission.submission_key, "CROSS_SUBMISSION_ANSWER_MAPPING"),
        ):
            if value.get(field) is not None and value[field] != expected:
                raise ContextError(code)
        return value

    def _pages(self):
        if self.document is not None:
            try:
                # Registration-only manifests carry pages but deliberately have
                # no Question mapping. Verify their bytes here, then bind the
                # selected pages only through the pinned revision's Question.
                if self.document.get("registration_only"):
                    pages = []
                    for page in self.document.get("pages", []):
                        path = (self.source_path.parent / str(page.get("image", ""))).resolve()
                        if (not path.is_relative_to(self.source_path.parent.resolve())
                                or not path.is_file()
                                or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}
                                or sha256_file(path) != page.get("sha256")):
                            raise ContextError("SOURCE_ANSWER_HASH_MISMATCH")
                        pages.append({"page_id": page["page_id"], "sha256": page["sha256"],
                                      "mime_type": "image/png" if path.suffix.lower() == ".png"
                                      else "image/jpeg"})
                    return pages
                mapped = answer_pages({**self.document, "answers": self.document.get("answers", [])},
                                      self.source_path.parent)
                return [page for entry in mapped for page in entry["pages"]]
            except ContextError:
                raise
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE") from exc
        digest = self.material.sha256 or sha256_file(self.source_path)
        return [{"page_id": f"submission-source-{digest[:16]}", "sha256": digest,
                 "mime_type": self.material.mime_type or "image/png"}]

    def _resolve_key(self, identity):
        found = []
        if "stable_question_key" in identity:
            key = identity["stable_question_key"]
            if key not in self.questions:
                raise ContextError("QUESTION_MAPPING_NOT_FOUND")
            found.append(key)
        for field in ("question_id", "test_question_id"):
            if field not in identity:
                continue
            value = identity[field]
            key = value if value in self.questions else self.keys_by_id.get(value)
            if key is None:
                raise ContextError("QUESTION_MAPPING_NOT_FOUND")
            found.append(key)
        if "question_number" in identity:
            by_number = self._question_numbers()
            key = by_number.get(identity["question_number"])
            if key is None:
                raise ContextError("QUESTION_MAPPING_NOT_FOUND")
            found.append(key)
        if not found:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        if len(set(found)) != 1:
            raise ContextError("QUESTION_IDENTITY_MISMATCH")
        return found[0]

    def _question_numbers(self):
        by_key = self.questions
        result = {}
        for key, question in by_key.items():
            labels, seen, current = [], set(), question
            while current:
                current_key = current["question_key"]
                if current_key in seen:
                    raise ContextError("GRADING_DEFINITION_HIERARCHY_INVALID")
                seen.add(current_key)
                labels.append(str(current.get("label", {}).get("raw") or current_key))
                parent = current.get("parent_key")
                current = by_key.get(parent) if parent else None
            number = " ".join(reversed(labels))[:32]
            if number in result and result[number] != key:
                raise ContextError("AMBIGUOUS_QUESTION_MAPPING")
            result[number] = key
        return result

    def _answers_by_key(self):
        result = {}
        for answer in (self.document or {}).get("answers", []):
            key = self._resolve_key({k: answer[k] for k in (
                "question_id", "test_question_id", "stable_question_key", "question_number")
                if k in answer})
            if key in result:
                raise ContextError("DUPLICATE_STUDENT_ANSWER")
            result[key] = answer
        return result

    def _rubric_compatibility_id(self):
        """Resolve only the legacy audit FK, never the executable rubric.

        GradingJob keeps a nullable RubricVersion FK for compatibility with
        historical teacher-decision records. The linked version identity is
        selected by its authoring-revision provenance; its mutable rubric JSON
        is not loaded. An unlinked historical projection is not guessed.
        """
        rows = list(self.s.execute(select(
            RubricVersion.id, RubricVersion.generation_metadata
        ).where(RubricVersion.test_id == self.test_id)))
        linked = [row.id for row in rows if (row.generation_metadata or {}).get(
            "authoring_revision_id") == self.revision.authoring_revision_id]
        if len(linked) != 1:
            raise ContextError("WEB_GRADING_RUBRIC_REFERENCE_UNAVAILABLE")
        return linked[0]

    def _selected_reconstruction(self, question_id):
        rows = list(self.s.scalars(select(StudentAnswerReconstruction).join(
            StudentAnswerExtractionResult,
            StudentAnswerReconstruction.extraction_result_id == StudentAnswerExtractionResult.id,
        ).join(StudentAnswerExtractionRun,
            StudentAnswerExtractionResult.run_id == StudentAnswerExtractionRun.id,
        ).where(
            StudentAnswerReconstruction.submission_id == self.submission.id,
            StudentAnswerReconstruction.question_id == question_id,
            StudentAnswerExtractionRun.test_id == self.test_id,
            StudentAnswerExtractionRun.selected.is_(True),
            StudentAnswerExtractionRun.status == "completed",
        ).order_by(StudentAnswerReconstruction.version.desc())))
        if not rows:
            return None
        try:
            return resolve_selected_reconstruction(rows)
        except ValueError as exc:
            raise ContextError(str(exc)) from exc

    def _verified_reconstruction(self, reconstruction, question, page_list):
        if reconstruction.status != "COMPLETE":
            raise ContextError("ANSWER_RECONSTRUCTION_REVIEW_REQUIRED")
        context = question["context"]
        if reconstruction.context_sha256 != context.get("context_sha256"):
            raise ContextError("RECONSTRUCTION_CONTEXT_REVISION_MISMATCH")
        source_sha = self.source_sha256
        if self.document and self.document.get("registration_only"):
            if len(page_list) != 1:
                raise ContextError("STUDENT_ANSWER_PAGE_SELECTION_REQUIRED")
            source_sha = page_list[0]["sha256"]
        if reconstruction.source_sha256 != source_sha:
            raise ContextError("RECONSTRUCTION_SOURCE_HASH_MISMATCH")
        if not self.answer_root:
            raise ContextError("RECONSTRUCTION_ARTIFACT_MISSING")
        path = (self.answer_root / reconstruction.artifact_ref / "reconstruction.json").resolve()
        if not path.is_relative_to(self.answer_root) or not path.is_file():
            raise ContextError("RECONSTRUCTION_ARTIFACT_MISSING")
        try:
            normalized = json.loads(path.read_text(encoding="utf-8"))
            source_input = json.loads(path.with_name("reconstruction-input.json").read_text(encoding="utf-8"))
            question_input = source_input["question"]
            source_answer = source_input["source_answer"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ContextError("RECONSTRUCTION_HASH_MISMATCH") from exc
        if (normalized.get("question_id") != reconstruction.question_id
                or normalized.get("answer_text") != reconstruction.answer_text
                or normalized.get("status") != "COMPLETE"
                or normalized.get("output_sha256") != reconstruction.output_sha256
                or canonical_hash({k: v for k, v in normalized.items() if k != "output_sha256"})
                != reconstruction.output_sha256):
            raise ContextError("RECONSTRUCTION_HASH_MISMATCH")
        if (question_input.get("stable_question_key") != question["question_key"]
                or question_input.get("context_sha256") != context.get("context_sha256")
                or source_answer.get("submission_id") != self.submission.id
                or source_answer.get("question_id") != reconstruction.question_id
                or source_answer.get("source_sha256") != source_sha
                or source_answer.get("pages") != page_list):
            raise ContextError("RECONSTRUCTION_SOURCE_IDENTITY_MISMATCH")
        return normalized

    def _reference(self, ref, *, question_id, role, model_answer_id=None):
        read_reference_asset(ref, self.revision_roots)
        return _frozen_reference(ref, question_id=question_id, role=role,
                                 model_answer_id=model_answer_id)

    def _question_part(self, question):
        key = question["question_key"]
        question_id = self.question_ids[key]
        package = frozen_question_package(self.definition, self.revision.id, question,
                                          question_id, self.question_ids)
        return {
            "identity": {"test_id": self.test_id, "question_id": question_id,
                         "stable_question_key": key,
                         "confirmed_authoring_revision_id": self.revision.id,
                         "confirmed_snapshot_sha256": self.revision.snapshot_sha256},
            **package,
            "rubric": {**package["rubric"], "id": self.rubric_version_id, "version": None},
        }

    def _student_pages_for(self, question_key):
        if self.document is None:
            page = self.pages[0]
            return [page], {"identity": {"question_id": self.question_ids[question_key]},
                            "pages": [page], "ownership": {"test_id": self.test_id,
                            "student_id": self.submission.student_id,
                            "submission_id": self.submission.submission_key}}
        if self.document.get("registration_only"):
            if not self.pages:
                raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE")
            return self.pages, None
        entries = []
        for entry in self.document.get("answers", []):
            identity = {k: entry[k] for k in ("question_id", "test_question_id",
                "stable_question_key", "question_number") if k in entry}
            if self._resolve_key(identity) == question_key:
                entries.append(entry)
        if len(entries) != 1:
            raise ContextError("DUPLICATE_STUDENT_ANSWER" if entries else "MISSING_STUDENT_ANSWER")
        mapped = answer_pages({**self.document, "answers": [entries[0]]}, self.source_path.parent)[0]
        return mapped["pages"], mapped

    def execution_preview(self, submission_id, question_id, *, synthetic_answer_text=None):
        if submission_id != self.submission.id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        question_key = self.keys_by_id.get(question_id)
        if question_key is None:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        question = self.questions[question_key]
        if not question.get("gradable"):
            raise ContextError("ANSWER_MAPPED_TO_STRUCTURAL_QUESTION")
        if synthetic_answer_text is not None and (
                not isinstance(synthetic_answer_text, str)
                or not synthetic_answer_text.strip()
                or len(synthetic_answer_text) > 20000):
            raise ContextError("SYNTHETIC_ANSWER_TEXT_INVALID")
        pages, mapped = self._student_pages_for(question_key)
        reconstruction = (None if synthetic_answer_text is not None
                          else self._selected_reconstruction(question_id))
        visual = []
        if synthetic_answer_text is None and (
                (self.material.mime_type and self.material.mime_type.startswith("image/"))
                or (self.document and self.document.get("registration_only"))):
            from .student_visual import StudentVisualAssetService, safe_file
            visual_rows = StudentVisualAssetService(self.s, self.answer_root or self.source_path.parent).for_question(
                self.submission.id, question_id)
            if len(visual_rows) > 1:
                raise ContextError("AMBIGUOUS_STUDENT_VISUAL_ASSET")
            if visual_rows:
                row = visual_rows[0]
                source_page = pages[0]
                if row.get("teacher_accepted") or not row.get("provenance", {}).get("requires_reconstruction"):
                    safe_file(self.answer_root or self.source_path.parent,
                              row["artifact_ref"], row["sha256"])
                    visual.append({**row, "role": "student_visual_answer", "question_id": question_id,
                        "test_id": self.test_id, "submission_id": self.submission.id,
                        "source_sha256": row.get("source_sha256", self.source_sha256),
                        "page_ids": [source_page["page_id"]], "review_required": False})
                    visual[-1].pop("metadata_sha256", None)
                    visual[-1]["metadata_sha256"] = canonical_hash(visual[-1])
        if reconstruction is None and synthetic_answer_text is None and not visual:
            raise ContextError("ANSWER_RECONSTRUCTION_MISSING")
        bundle = {"schema_version": "grading-input-bundle.v1",
                  **self._question_part(question), "input_stage": "reconstructed_answer"}
        bundle["revision"] = {"confirmed_authoring_revision_id": self.revision.id,
                              "snapshot_sha256": self.revision.snapshot_sha256,
                              "schema_version": self.definition["schema_version"],
                              "interpreter_version": self.definition["interpreter_version"]}
        if synthetic_answer_text is not None:
            source_sha = self.source_sha256
            if self.document and self.document.get("registration_only"):
                if len(pages) != 1:
                    raise ContextError("STUDENT_ANSWER_PAGE_SELECTION_REQUIRED")
                source_sha = pages[0]["sha256"]
            normalized = {
                "schema_version": "student-answer-reconstruction.v1",
                "question_id": question_id,
                "answer_text": synthetic_answer_text,
                "segments": [],
                "uncertainties": [],
                "source_refs": [],
                "status": "COMPLETE",
            }
            normalized["output_sha256"] = canonical_hash(normalized)
            student_answer = {"id": "synthetic-preview", "submission_id": self.submission.id,
                "source_answer_id": f"{self.submission.id}:{question_id}", "test_id": self.test_id,
                "student_id": self.submission.student_id, "question_id": question_id,
                "stable_question_key": question_key, "representation": "reconstructed",
                "source": "RECONSTRUCTED_FROM_DOCUMENT", "answer_text": synthetic_answer_text,
                "source_sha256": source_sha, "reconstruction_id": "synthetic-preview",
                "reconstruction_version": 0, "reconstruction_status": "COMPLETE",
                "page_ids": [p["page_id"] for p in pages], "source_pages": pages,
                "reconstruction_context_sha256": question["context"].get("context_sha256"),
                "normalized_reconstruction": normalized, "sha256": normalized["output_sha256"]}
        elif reconstruction is not None:
            normalized = self._verified_reconstruction(reconstruction, question, pages)
            student_answer = {"id": reconstruction.id, "submission_id": self.submission.id,
                "source_answer_id": f"{self.submission.id}:{question_id}", "test_id": self.test_id,
                "student_id": self.submission.student_id, "question_id": question_id,
                "stable_question_key": question_key, "representation": "reconstructed",
                "source": "RECONSTRUCTED_FROM_DOCUMENT", "answer_text": reconstruction.answer_text,
                "source_sha256": reconstruction.source_sha256,
                "reconstruction_id": reconstruction.id, "reconstruction_version": reconstruction.version,
                "reconstruction_status": reconstruction.status, "page_ids": [p["page_id"] for p in pages],
                "source_pages": pages, "reconstruction_context_sha256": reconstruction.context_sha256,
                "normalized_reconstruction": normalized, "sha256": reconstruction.output_sha256}
        else:
            student_answer = {"id": visual[0]["asset_id"], "submission_id": self.submission.id,
                "test_id": self.test_id, "student_id": self.submission.student_id,
                "question_id": question_id, "stable_question_key": question_key,
                "source": "VISUAL_FROM_DOCUMENT", "representation": "visual",
                "source_sha256": visual[0]["source_sha256"], "sha256": visual[0]["sha256"],
                "page_ids": [p["page_id"] for p in pages], "source_pages": pages,
                "visual_asset_ids": [visual[0]["asset_id"]]}
            bundle["input_stage"] = "student_visual_answer"
        bundle["student_answer"] = student_answer
        if visual:
            bundle["visual_assets"] = bundle.pop("visual_references") + visual
        else:
            bundle.pop("visual_references", None)
        bundle["mapping"] = {"resolution_method": "pinned_revision_question_identity",
                              "warnings": [], "confirmed_revision_id": self.revision.id}
        bundle["bundle_sha256"] = canonical_hash(bundle)
        return {"test_id": self.test_id, "submission_id": self.submission.id,
                "questions": [{"question_id": question_id, "stable_question_key": question_key,
                    "display_label": question["label"]["raw"], "state": "READY",
                    "execution_state": "READY", "mapping_state": "READY", "bundle": bundle,
                    "context": question["context"], "student_answer_mapped": True,
                    "model_answer_mapped": bool(question["answer"].get("primary") or question["visual_references"]),
                    "rubric_mapped": bool(question["rubric"].get("criteria")),
                    "reconstruction": {"id": reconstruction.id, "version": reconstruction.version,
                        "status": reconstruction.status} if reconstruction else
                        ({"status": "SYNTHETIC_PREVIEW"} if synthetic_answer_text is not None
                         else {"status": "NOT_REQUIRED_VISUAL"}),
                    "blockers": [], "warnings": []}], "gradable_count": 1,
                "ready_bundle_count": 1, "blocked_bundle_count": 0,
                "confirmed_authoring_revision_id": self.revision.id,
                "confirmed_revision_label": confirmed_edition_label(self.s, self.revision)}

    def evaluate_readiness(self, submission_id):
        rows = []
        for question in self.definition["questions"]:
            if not question.get("gradable"):
                continue
            question_id = self.question_ids[question["question_key"]]
            try:
                preview = self.execution_preview(submission_id, question_id)
                rows.extend(preview["questions"])
            except ContextError as exc:
                rows.append({"question_id": question_id, "stable_question_key": question["question_key"],
                    "display_label": question["label"]["raw"], "state": "BLOCKED",
                    "execution_state": "BLOCKED", "mapping_state": "BLOCKED", "bundle": None,
                    "blockers": [{"code": exc.code}], "warnings": []})
        ready = sum(row["state"] == "READY" for row in rows)
        return {"test_id": self.test_id, "submission_id": submission_id,
            "confirmed_authoring_revision_id": self.revision.id,
            "confirmed_edition_label": confirmed_edition_label(self.s, self.revision),
            "gradable_count": len(rows), "ready_bundle_count": ready,
            "blocked_bundle_count": len(rows) - ready,
            "can_build_all_inputs": bool(rows) and ready == len(rows),
            "questions": rows, "input_stage": "revision_bound"}


def immutable_asset_rows(bundle, artifact_roots):
    rows = []
    for reference in bundle.get("visual_assets", bundle.get("assets", [])):
        if reference.get("role") == "student_visual_answer":
            from .student_visual import safe_file
            root = artifact_roots.get("student_visual_answer") or artifact_roots.get("answer_import")
            if root is None:
                raise ValueError("STUDENT_VISUAL_ASSET_UNAVAILABLE")
            path = safe_file(root, reference["artifact_ref"], reference["sha256"])
        else:
            path = read_reference_asset(reference, artifact_roots)
        rows.append({"asset_id": reference["asset_id"], "sha256": reference["sha256"],
                     "role": reference.get("role"), "path": str(path)})
    return rows


def assemble_revision_execution_package(session, test_id, submission_id, question_id, *,
                                        question_root=None, answer_root=None,
                                        allowed_roots=None, visual_capability=None,
                                        synthetic_answer_text=None, submission=None):
    """Build the exact revision-bound bundle shared by Job creation and diagnostics.

    This service is inference-free and does not read grader configuration or
    create persistent grading records. A synthetic answer is supplied only for
    an explicit diagnostic preview and exists in memory.
    """
    from .db.models import StudentSubmission
    from .grading_definition import confirmed_revision_for_test
    from .grading_execution import execution_rubric, validate_bundle

    submission = submission or session.get(StudentSubmission, submission_id)
    if submission is None or submission.id != submission_id or submission.test_id != test_id:
        raise ContextError("SUBMISSION_NOT_FOUND")
    if not submission.confirmed_authoring_revision_id:
        raise ContextError("WEB_GRADING_REVISION_REQUIRED")

    roots = {"question_import": question_root, "answer_import": answer_root,
             "student_visual_answer": answer_root}
    try:
        revision, definition = confirmed_revision_for_test(
            session, test_id, submission.confirmed_authoring_revision_id,
            artifact_roots=roots)
        assembler = RevisionGradingInputAssembler(
            session, test_id, submission_id, question_root=question_root,
            answer_root=answer_root, allowed_roots=allowed_roots,
            visual_capability=visual_capability)
        preview = assembler.execution_preview(
            submission_id, question_id, synthetic_answer_text=synthetic_answer_text)
        row = next((value for value in preview.get("questions", [])
                    if value.get("question_id") == question_id), None)
        if row is None or row.get("execution_state") != "READY" or not row.get("bundle"):
            return {"ready": False, "blockers": deepcopy((row or {}).get("blockers", [])),
                    "submission": submission, "revision": revision,
                    "definition": definition, "edition_label": preview.get("confirmed_revision_label"),
                    "bundle": None, "assets": [],
                    "synthetic_input": synthetic_answer_text is not None}
        bundle = deepcopy(row["bundle"])
        validate_bundle(bundle)
        execution_rubric(bundle)
        validate_revision_bound_bundle(bundle, revision, assembler.question_ids)
        assets = immutable_asset_rows(bundle, roots)
        return {"ready": True, "blockers": [], "submission": submission,
                "revision": revision, "definition": definition,
                "edition_label": preview["confirmed_revision_label"],
                "question": deepcopy(assembler.questions[assembler.keys_by_id[question_id]]),
                "bundle": bundle, "assets": assets,
                "synthetic_input": synthetic_answer_text is not None}
    except ContextError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise ContextError(str(exc)) from exc
