"""Read-only identity validation of domain associations and legacy answer pages.

StudentSubmission identifies an attempt, not a current-answer version. Its
registered TestMaterial may be a legacy submission JSON. PDFs alone do not
supply question mappings. No OCR/reconstruction or model calls occur here.
"""

from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path

from sqlalchemy import select

from .db.models import (
    ModelAnswer,
    RubricVersion,
    Student,
    StudentSubmission,
    StudentAnswerReconstruction,
    StudentAnswerExtractionRun,
    StudentAnswerExtractionResult,
    Test,
    TestMaterial,
    TestQuestion,
    TestQuestionAsset,
    TestQuestionCorrection,
)
from .grading_context import (
    ContextError,
    EffectiveQuestionContextBuilder,
    GradingReadinessService,
    reason,
)
from .pdf_native import canonical_hash, sha256_file
from .grading_audit import resolve_selected_reconstruction


class QuestionIdentityResolver:
    def __init__(self, questions):
        self.questions = list(questions)

    def resolve(self, identity):
        # Explicit fields must agree; weaker fields cannot override a stronger ID.
        matches, methods = [], []
        for field, attr in (
            ("test_question_id", "id"),
            ("stable_question_key", "stable_question_key"),
            ("question_number", "question_number"),
        ):
            if field in identity:
                found = [q for q in self.questions if getattr(q, attr) == identity[field]]
                if len(found) != 1:
                    raise ContextError(
                        "AMBIGUOUS_QUESTION_MAPPING" if found else "QUESTION_MAPPING_NOT_FOUND"
                    )
                matches.append(found[0])
                methods.append(field)
        if "question_id" in identity:
            key = identity["question_id"]
            for attr, method in (
                ("id", "test_question_id"),
                ("stable_question_key", "stable_question_key"),
                ("question_number", "question_number"),
            ):
                found = [q for q in self.questions if getattr(q, attr) == key]
                if found:
                    if len(found) != 1:
                        raise ContextError("AMBIGUOUS_QUESTION_MAPPING")
                    matches.append(found[0])
                    methods.append(method)
                    break
            else:
                raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        if not matches:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        if len({q.id for q in matches}) != 1:
            raise ContextError("QUESTION_IDENTITY_MISMATCH")
        method = min(
            methods, key=("test_question_id", "stable_question_key", "question_number").index
        )
        warnings = (
            [
                {
                    "code": "LEGACY_QUESTION_NUMBER_MAPPING",
                    "severity": "warning",
                    "message": "同一Test内の一意なquestion_numberで対応しています。",
                }
            ]
            if method == "question_number"
            else []
        )
        return matches[0], method, warnings


def answer_pages(document, base):
    """Decode the existing pages/answers contract, retaining ordered page hashes."""
    if not isinstance(document, dict) or not isinstance(document.get("answers"), list):
        raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE")
    pages = {}
    for page in document.get("pages", []):
        pid = page["page_id"]
        if pid in pages:
            raise ContextError("DUPLICATE_ANSWER_PAGE")
        path = (base / page["image"]).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():
            raise ContextError("STUDENT_ANSWER_ASSET_MISSING")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ContextError("STUDENT_ANSWER_ASSET_UNSUPPORTED")
        pages[pid] = {
            "page_id": pid,
            "sha256": sha256_file(path),
            "mime_type": "image/png" if path.suffix.lower() == ".png" else "image/jpeg",
        }
    result = []
    for entry in document["answers"]:
        ids = entry.get("page_ids", [])
        if not ids or len(ids) != len(set(ids)) or any(pid not in pages for pid in ids):
            raise ContextError("STUDENT_ANSWER_PAGE_MAPPING_INVALID")
        result.append(
            {
                "identity": {
                    k: entry[k]
                    for k in (
                        "question_id",
                        "test_question_id",
                        "stable_question_key",
                        "question_number",
                    )
                    if k in entry
                },
                "pages": [pages[pid] for pid in ids],
                "ownership": {
                    k: entry[k] for k in ("test_id", "student_id", "submission_id") if k in entry
                },
            }
        )
    return result


class GradingInputAssembler:
    def __init__(self, session, test_id, *, root=None, allowed_roots=None,
                 answer_root=None, reference_root=None, visual_capability=None):
        self.s, self.test_id = session, test_id
        self.answer_root = Path(answer_root or root or Path.cwd()).resolve()
        self.reference_root = Path(reference_root or root or Path.cwd()).resolve()
        self.visual_capability = visual_capability
        self.test = session.get(Test, test_id)
        if self.test is None:
            raise ContextError("TEST_NOT_FOUND")
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [Path.cwd()])]
        self.questions = list(
            session.scalars(
                select(TestQuestion)
                .where(TestQuestion.test_id == test_id)
                .order_by(TestQuestion.sort_order, TestQuestion.id)
            )
        )
        self.by_id = {q.id: q for q in self.questions}
        self.resolver = QuestionIdentityResolver(self.questions)
        assets = session.scalars(
            select(TestQuestionAsset).join(TestQuestion).where(TestQuestion.test_id == test_id)
        ).all()
        self.contexts = EffectiveQuestionContextBuilder(self.questions, assets, root=root)
        self.corrections = defaultdict(list)
        for c in session.scalars(
            select(TestQuestionCorrection)
            .join(TestQuestion)
            .where(TestQuestion.test_id == test_id)
            .order_by(TestQuestionCorrection.correction_version)
        ):
            self.corrections[c.test_question_id].append(
                {
                    "id": c.id,
                    "version": c.correction_version,
                    "previous_content_sha256": c.previous_content_sha256,
                    "new_content_sha256": c.new_content_sha256,
                }
            )
        self.answers = defaultdict(list)
        for a in session.scalars(
            select(ModelAnswer).where(
                ModelAnswer.test_id == test_id, ModelAnswer.is_current.is_(True)
            )
        ):
            self.answers[a.question_id].append(a)
        self.reconstructions = {}
        self.verified_reconstructions = {}
        self.root = Path(root or Path.cwd()).resolve()
        rubrics = session.scalars(
            select(RubricVersion).where(
                RubricVersion.test_id == test_id, RubricVersion.status == "approved"
            )
        ).all()
        self.rubric = rubrics[0] if len(rubrics) == 1 else None
        self.global_codes = ["AMBIGUOUS_APPROVED_RUBRIC"] if len(rubrics) > 1 else []
        self.entries = defaultdict(list)
        self.orphan_rubric_count = 0
        raw = (
            self.rubric.rubric_json.get("questions", [])
            if self.rubric and isinstance(self.rubric.rubric_json, dict)
            else []
        )
        if not isinstance(raw, list):
            raw = []
            self.global_codes.append("INVALID_RUBRIC")
        foreign_ids = [
            v.get("question_id")
            for v in raw
            if isinstance(v, dict) and v.get("question_id") not in self.by_id
        ]
        foreign = (
            set(
                session.scalars(
                    select(TestQuestion.id).where(TestQuestion.id.in_(foreign_ids))
                ).all()
            )
            if foreign_ids
            else set()
        )
        for entry in raw:
            if not isinstance(entry, dict) or not isinstance(entry.get("question_id"), str):
                self.global_codes.append("INVALID_RUBRIC")
                self.orphan_rubric_count += 1
                continue
            qid = entry["question_id"]
            self.entries[qid].append(entry)
            q = self.by_id.get(qid)
            if q is None or not q.is_gradable:
                self.orphan_rubric_count += 1
                self.global_codes.append(
                    "CROSS_TEST_RUBRIC_MAPPING"
                    if qid in foreign
                    else "UNKNOWN_RUBRIC_QUESTION"
                    if q is None
                    else "RUBRIC_MAPPED_TO_STRUCTURAL_QUESTION"
                )
        for entries in self.entries.values():
            if len(entries) > 1:
                self.global_codes.append("DUPLICATE_RUBRIC_ENTRY")
        self.readiness = GradingReadinessService(session, root=root).evaluate(test_id)
        self.ready_rows = {row["question_id"]: row for row in self.readiness["questions"]}

    def question_part(self, question_id):
        q = self.by_id.get(question_id)
        if q is None:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        if not q.is_gradable:
            raise ContextError("ANSWER_MAPPED_TO_STRUCTURAL_QUESTION")
        answers = self.answers[q.id]
        if len(answers) != 1:
            raise ContextError("AMBIGUOUS_MODEL_ANSWER" if answers else "MISSING_MODEL_ANSWER")
        a = answers[0]
        if a.question_id != q.id or a.test_id != self.test_id:
            raise ContextError("MODEL_ANSWER_QUESTION_MISMATCH")
        entries = self.entries[q.id]
        if len(entries) != 1 or self.rubric is None:
            raise ContextError("DUPLICATE_RUBRIC_ENTRY" if len(entries) > 1 else "MISSING_RUBRIC")
        if self.global_codes:
            raise ContextError(self.global_codes[0])
        context = self.contexts.build(q.id)
        return {
            "identity": {
                "test_id": self.test_id,
                "question_id": q.id,
                "stable_question_key": q.stable_question_key,
            },
            "question": {
                "context": context,
                "context_sha256": context["context_sha256"],
                "content_sha256": q.content_sha256,
                "max_points": q.max_points,
                "provenance": {
                    k: v
                    for k, v in (q.provenance or {}).items()
                    if k
                    in {
                        "origin",
                        "confirmation_id",
                        "review_id",
                        "revision",
                        "revision_sha256",
                        "review_node_id",
                    }
                },
                "corrections": self.corrections[q.id],
            },
            "model_answer": {
                "id": a.id,
                "question_id": a.question_id,
                "version": a.version,
                "content": a.answer_text,
                "sha256": canonical_hash(a.answer_text),
            },
            "rubric": {
                "id": self.rubric.id,
                "version": self.rubric.version,
                "question_id": q.id,
                "entry": deepcopy(entries[0]),
                "entry_sha256": canonical_hash(entries[0]),
            },
            "assets": context["assets"],
        }

    def _validate_reconstruction(self, reconstruction, sub, answer):
        material = self.s.get(TestMaterial, sub.material_id)
        if reconstruction.source_sha256 != material.sha256:
            raise ContextError("RECONSTRUCTION_SOURCE_HASH_MISMATCH")
        from .reconstruction_artifacts import load_repaired
        try:
            repaired = load_repaired(self.s, reconstruction, self.answer_root)
        except ValueError as exc:
            raise ContextError(str(exc)) from exc
        if repaired is not None:
            source = repaired['input']['source_answer']
            if (source['submission_id'] != sub.id or source['question_id'] != reconstruction.question_id
                    or source['student_id'] != sub.student_id or source['pages'] != answer['pages']
                    or source['source_sha256'] != material.sha256):
                raise ContextError('RECONSTRUCTION_SOURCE_IDENTITY_MISMATCH')
            normalized = repaired['normalized']
            if normalized['output_sha256'] != canonical_hash({k: v for k, v in normalized.items() if k != 'output_sha256'}):
                raise ContextError('RECONSTRUCTION_HASH_MISMATCH')
            self.verified_reconstructions[reconstruction.id] = normalized
            return
        path = (self.answer_root / reconstruction.artifact_ref / "reconstruction.json").resolve()
        if not path.is_relative_to(self.answer_root) or not path.is_file():
            raise ContextError("RECONSTRUCTION_ARTIFACT_MISSING")
        try:
            normalized = json.loads(path.read_text())
            if (normalized.get("question_id") != reconstruction.question_id
                    or normalized.get("answer_text") != reconstruction.answer_text
                    or normalized.get("status") != reconstruction.status
                    or normalized.get("output_sha256") != reconstruction.output_sha256
                    or canonical_hash({k:v for k,v in normalized.items() if k != "output_sha256"})
                    != reconstruction.output_sha256):
                raise ContextError("RECONSTRUCTION_HASH_MISMATCH")
            inputs = json.loads(path.with_name("reconstruction-input.json").read_text())
            source = inputs["source_answer"]
            if (source["submission_id"] != sub.id or source["question_id"] != reconstruction.question_id
                    or source["student_id"] != sub.student_id or source["pages"] != answer["pages"]
                    or source["source_sha256"] != material.sha256):
                raise ContextError("RECONSTRUCTION_SOURCE_IDENTITY_MISMATCH")
        except (OSError, ValueError, KeyError) as exc:
            if isinstance(exc, ContextError):
                raise
            raise ContextError("RECONSTRUCTION_HASH_MISMATCH") from None
        self.verified_reconstructions[reconstruction.id] = normalized

    def load_submission(self, submission_id):
        sub = self.s.get(StudentSubmission, submission_id)
        if sub is None or sub.test_id != self.test_id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        siblings = self.s.scalars(
            select(StudentSubmission.id).where(
                StudentSubmission.test_id == self.test_id,
                StudentSubmission.submission_key == sub.submission_key,
            )
        ).all()
        if len(siblings) != 1:
            raise ContextError("AMBIGUOUS_SUBMISSION_MAPPING")
        student = self.s.get(Student, sub.student_id)
        mat = self.s.get(TestMaterial, sub.material_id)
        if student is None or student.course_offering_id != self.test.course_offering_id:
            raise ContextError("CROSS_STUDENT_ANSWER_MAPPING")
        if mat is None or mat.test_id != self.test_id:
            raise ContextError("CROSS_TEST_ANSWER_MAPPING")
        path = Path(mat.storage_ref).resolve()
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise ContextError("STUDENT_ANSWER_SOURCE_UNAVAILABLE")
        if not path.is_file() or path.suffix.lower() != ".json":
            raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE")
        if mat.sha256 and sha256_file(path) != mat.sha256:
            raise ContextError("STUDENT_ANSWER_SOURCE_HASH_MISMATCH")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            self._ownership(doc, sub, document=True)
            return sub, answer_pages(doc, path.parent)
        except ContextError:
            raise
        except (ValueError, OSError, TypeError, KeyError):
            raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE") from None

    def _ownership(self, entry, sub, *, document=False):
        for field, expected, code in (
            ("test_id", self.test_id, "CROSS_TEST_ANSWER_MAPPING"),
            ("student_id", sub.student_id, "CROSS_STUDENT_ANSWER_MAPPING"),
            ("submission_id", sub.submission_key, "CROSS_SUBMISSION_ANSWER_MAPPING"),
        ):
            if (document and field == "submission_id" or field in entry) and entry.get(
                field
            ) != expected:
                raise ContextError(code)

    def evaluate(self, submission_id):
        # Do not expose whether an ID belonging to another Test exists.
        sub = self.s.get(StudentSubmission, submission_id)
        if sub is None or sub.test_id != self.test_id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        global_codes = list(self.global_codes)
        mapped, orphans = defaultdict(list), []
        try:
            sub, answers = self.load_submission(submission_id)
            self.reconstructions = {}
            for reconstruction in self.s.scalars(select(StudentAnswerReconstruction).join(
                    StudentAnswerExtractionResult, StudentAnswerReconstruction.extraction_result_id == StudentAnswerExtractionResult.id
                ).join(StudentAnswerExtractionRun, StudentAnswerExtractionResult.run_id == StudentAnswerExtractionRun.id).where(
                    StudentAnswerReconstruction.submission_id == submission_id,
                    StudentAnswerExtractionRun.selected.is_(True),
                    StudentAnswerExtractionRun.status == "completed",
                    StudentAnswerExtractionRun.test_id == self.test_id).order_by(
                    StudentAnswerReconstruction.question_id,
                    StudentAnswerExtractionRun.selected.desc(),
                    StudentAnswerReconstruction.version.desc())):
                if reconstruction.question_id in self.reconstructions:
                    raise ContextError("AMBIGUOUS_SELECTED_RECONSTRUCTION")
                self.reconstructions[reconstruction.question_id] = reconstruction
            referenced = [
                a["identity"].get("test_question_id", a["identity"].get("question_id"))
                for a in answers
            ]
            foreign = set(
                self.s.scalars(
                    select(TestQuestion.id).where(
                        TestQuestion.id.in_(referenced), TestQuestion.test_id != self.test_id
                    )
                ).all()
            )
            for answer in answers:
                try:
                    if any(
                        answer["identity"].get(k) in foreign
                        for k in ("test_question_id", "question_id")
                    ):
                        raise ContextError("CROSS_TEST_ANSWER_MAPPING")
                    self._ownership(answer["ownership"], sub)
                    q, method, warnings = self.resolver.resolve(answer["identity"])
                    if not q.is_gradable:
                        raise ContextError("ANSWER_MAPPED_TO_STRUCTURAL_QUESTION")
                    mapped[q.id].append((answer, method, warnings))
                except ContextError as exc:
                    orphans.append({"code": exc.code})
            if orphans:
                global_codes.extend(["ORPHAN_STUDENT_ANSWER", *[v["code"] for v in orphans]])
        except ContextError as exc:
            global_codes.append(exc.code)
        rows = []
        for q in self.questions:
            if not q.is_gradable:
                continue
            codes = global_codes + [v["code"] for v in self.ready_rows[q.id]["blockers"]]
            matched = mapped[q.id]
            if len(matched) != 1:
                codes.append("DUPLICATE_STUDENT_ANSWER" if matched else "MISSING_STUDENT_ANSWER")
            row = {
                "question_id": q.id,
                "display_label": q.display_label or q.question_number,
                "stable_question_key": q.stable_question_key,
                "student_answer_mapped": len(matched) == 1,
                "model_answer_mapped": len(self.answers[q.id]) == 1,
                "rubric_mapped": len(self.entries[q.id]) == 1,
                "bundle": None,
                "context": None,
                "warnings": matched[0][2] if len(matched) == 1 else [],
                "reconstruction": None,
            }
            reconstruction = self.reconstructions.get(q.id)
            if reconstruction is not None:
                row["reconstruction"] = {"id": reconstruction.id, "version": reconstruction.version,
                    "status": reconstruction.status, "source_sha256": reconstruction.source_sha256,
                    "output_sha256": reconstruction.output_sha256}
                if reconstruction.status == "REVIEW_REQUIRED":
                    codes.append("ANSWER_RECONSTRUCTION_REVIEW_REQUIRED")
                elif reconstruction.status == "FAILED":
                    codes.append("ANSWER_RECONSTRUCTION_FAILED")
            try:
                row["context"] = self.contexts.build(q.id)
            except ContextError as exc:
                codes.append(exc.code)
            if reconstruction is not None and len(matched) == 1:
                try:
                    self._validate_reconstruction(reconstruction, sub, matched[0][0])
                except ContextError as exc:
                    codes.append(exc.code)
            if not codes:
                part = self.question_part(q.id)
                answer, method, warnings = matched[0]
                value = {
                    "schema_version": "grading-input-bundle.v1",
                    **part,
                    "input_stage": "answer_pages_before_reconstruction",
                    "student_answer": {
                        "id": f"{sub.id}:{q.id}",
                        "submission_id": sub.id,
                        "submission_key": sub.submission_key,
                        "student_id": sub.student_id,
                        "question_id": q.id,
                        "material_id": sub.material_id,
                        "attempt_number": sub.attempt_number,
                        "representation": "image_pages",
                        "pages": answer["pages"],
                        "sha256": canonical_hash(answer["pages"]),
                    },
                    "mapping": {"resolution_method": method, "warnings": warnings},
                }
                reconstruction = self.reconstructions.get(q.id)
                if reconstruction and reconstruction.status in {"COMPLETE", "REVIEW_REQUIRED"}:
                    value["input_stage"] = "reconstructed_answer"
                    value["student_answer"] = {
                        "id": reconstruction.id,
                        "submission_id": sub.id,
                        "source_answer_id": f"{sub.id}:{q.id}",
                        "test_id": self.test_id,
                        "student_id": sub.student_id,
                        "question_id": q.id,
                        "representation": "reconstructed",
                        "source": "RECONSTRUCTED_FROM_DOCUMENT",
                        "answer_text": reconstruction.answer_text,
                        "source_sha256": reconstruction.source_sha256,
                        "reconstruction_id": reconstruction.id,
                        "reconstruction_version": reconstruction.version,
                        "reconstruction_status": reconstruction.status,
                        "page_ids": [p["page_id"] for p in answer["pages"]],
                        "source_pages": answer["pages"],
                        "reconstruction_context_sha256": reconstruction.context_sha256,
                        "normalized_reconstruction": self.verified_reconstructions[reconstruction.id],
                        "sha256": self.verified_reconstructions[reconstruction.id]["output_sha256"],
                    }
                value["bundle_sha256"] = canonical_hash(value)
                row["bundle"] = value
            row["blockers"] = [reason(code) for code in sorted(set(codes))]
            row["state"] = "BLOCKED" if codes else "READY"
            rows.append(row)
        ready = sum(r["state"] == "READY" for r in rows)
        return {
            "test_id": self.test_id,
            "submission_id": sub.id,
            "gradable_count": len(rows),
            "mapped_student_answer_count": sum(r["student_answer_mapped"] for r in rows),
            "model_answer_count": sum(r["model_answer_mapped"] for r in rows),
            "rubric_entry_count": sum(r["rubric_mapped"] for r in rows),
            "ready_bundle_count": ready,
            "blocked_bundle_count": len(rows) - ready,
            "orphan_answer_count": len(orphans),
            "orphan_rubric_entry_count": self.orphan_rubric_count,
            "can_build_all_inputs": bool(rows) and ready == len(rows),
            "test_can_start_grading": self.readiness["can_start_grading"],
            "input_stage": "answer_pages_before_reconstruction",
            "questions": rows,
            "blockers": [reason(c) for c in sorted(set(global_codes))],
        }

    def execution_preview(self, submission_id, question_id):
        """Same semantic bundle and production validation used by job creation."""
        from .grading_execution import validate_bundle, execution_rubric
        sub = self.s.get(StudentSubmission, submission_id)
        if sub is None or sub.test_id != self.test_id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        material = self.s.get(TestMaterial, sub.material_id)
        if material and (material.mime_type or "").startswith("image/"):
            result = self.evaluate_selected_question(submission_id, question_id)
        else:
            result = self.evaluate(submission_id)
        row = next((r for r in result["questions"] if r["question_id"] == question_id), None)
        if row is None:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        row["execution_state"] = "BLOCKED"
        if row["state"] == "READY" and row["bundle"]:
            try:
                validate_bundle(row["bundle"])
                execution_rubric(row["bundle"])
                if row['bundle'].get('visual_assets'):
                    from .grading_visual import validate_capability
                    validate_capability(self.visual_capability)
            except (ValueError, KeyError, TypeError) as exc:
                row["blockers"].append({**reason("PRODUCTION_INPUT_INVALID"), "detail": str(exc)})
                row['execution_blockers'] = [str(exc)]
                # Preserve mapping/semantic preview while reporting execution blocked.
                row["mapping_state"] = row["state"]
                row["state"] = "BLOCKED"
                if not row['bundle'].get('visual_assets'):
                    row['bundle'] = None
            else:
                row["execution_state"] = "READY"
        return row

    def _visual_question(self, sub, q, page, asset):
        from .grading_visual import reference_assets
        part = self.question_part(q.id)
        codes = [v['code'] for v in self.ready_rows[q.id]['blockers']]
        if asset['review_required']:
            codes.append('STUDENT_VISUAL_REVIEW_REQUIRED')
        refs = reference_assets(self.rubric, self.answers[q.id][0], self.reference_root)
        if not refs:
            codes.append('MODEL_ANSWER_REFERENCE_ASSET_MISSING')
        question_refs = [{**a, 'role': 'question_context', 'question_id': a['source_question_id']}
                         for a in part['assets']]
        value = {'schema_version': 'grading-input-bundle.v1', **part,
                 'input_stage': 'student_visual_answer',
                 'student_answer': {'id': asset['asset_id'], 'submission_id': sub.id,
                     'test_id': self.test_id, 'student_id': sub.student_id, 'question_id': q.id,
                     'source': 'VISUAL_FROM_DOCUMENT', 'representation': 'visual',
                     'source_sha256': asset['source_sha256'], 'sha256': asset['sha256'],
                     'page_ids': [page['page_id']], 'source_pages': [page],
                     'visual_asset_ids': [asset['asset_id']]},
                 'visual_assets': question_refs + refs + [asset],
                 'mapping': {'resolution_method': 'explicit_selected_question', 'warnings': []}}
        value['bundle_sha256'] = canonical_hash(value)
        return {'test_id': self.test_id, 'submission_id': sub.id, 'questions': [{
            'question_id': q.id, 'stable_question_key': q.stable_question_key,
            'state': 'BLOCKED' if codes else 'READY', 'mapping_state': 'READY',
            'context': part['question']['context'], 'bundle': value,
            'student_answer_mapped': True, 'reconstruction': {'status': 'NOT_REQUIRED_VISUAL'},
            'blockers': [reason(c) for c in codes], 'warnings': []}]}

    def evaluate_selected_question(self, submission_id, question_id):
        """Build a read-only preview for an explicitly selected image answer.

        H.3-D.-1 registers a whole answer-sheet image without inventing
        question-level answer JSON.  After a selected reconstruction exists,
        this method binds that one image page to the teacher-selected question
        and reuses the normal question/model-answer/rubric bundle validation.
        It never creates a mapping row or a grading job.
        """
        sub = self.s.get(StudentSubmission, submission_id)
        q = self.by_id.get(question_id)
        if sub is None or sub.test_id != self.test_id:
            raise ContextError("SUBMISSION_NOT_FOUND")
        if q is None:
            raise ContextError("QUESTION_MAPPING_NOT_FOUND")
        if not q.is_gradable:
            raise ContextError("ANSWER_MAPPED_TO_STRUCTURAL_QUESTION")
        material = self.s.get(TestMaterial, sub.material_id)
        if material is None or material.test_id != self.test_id:
            raise ContextError("CROSS_TEST_ANSWER_MAPPING")
        path = Path(material.storage_ref).resolve()
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise ContextError("STUDENT_ANSWER_SOURCE_UNAVAILABLE")
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ContextError("STUDENT_ANSWER_MAPPING_UNAVAILABLE")
        if material.sha256 and sha256_file(path) != material.sha256:
            raise ContextError("STUDENT_ANSWER_SOURCE_HASH_MISMATCH")
        page = {"page_id": f"submission-source-{material.sha256[:16]}",
                "sha256": material.sha256, "mime_type": material.mime_type or "image/png"}
        answer = {"identity": {"question_id": question_id}, "pages": [page],
                  "ownership": {"test_id": self.test_id, "student_id": sub.student_id,
                                "submission_id": sub.submission_key}}
        from .student_visual import StudentVisualAssetService
        visuals = StudentVisualAssetService(self.s, self.answer_root).for_question(sub.id, q.id)
        if len(visuals) > 1:
            raise ContextError('AMBIGUOUS_STUDENT_VISUAL_ASSET')
        if visuals:
            visual_result = self._visual_question(sub, q, page, visuals[0])
            if visuals[0].get('teacher_accepted') or not visuals[0].get('provenance', {}).get('requires_reconstruction'):
                return visual_result
        else:
            visual_result = None
        selected = list(self.s.scalars(select(StudentAnswerReconstruction).join(
            StudentAnswerExtractionResult,
            StudentAnswerReconstruction.extraction_result_id == StudentAnswerExtractionResult.id,
        ).join(
            StudentAnswerExtractionRun,
            StudentAnswerExtractionResult.run_id == StudentAnswerExtractionRun.id,
        ).where(
            StudentAnswerReconstruction.submission_id == submission_id,
            StudentAnswerReconstruction.question_id == question_id,
            StudentAnswerExtractionRun.selected.is_(True),
            StudentAnswerExtractionRun.status == "completed",
        ).order_by(StudentAnswerReconstruction.version.desc())))
        try:
            reconstruction = resolve_selected_reconstruction(selected)
        except ValueError as exc:
            if visual_result is not None:
                vr = visual_result['questions'][0]
                vr['state'] = 'BLOCKED'
                code = str(exc)
                vr['blockers'].append(reason(code))
                return visual_result
            raise ContextError(str(exc)) from exc
        codes = [v["code"] for v in self.ready_rows[question_id]["blockers"]]
        row = {
            "question_id": question_id,
            "display_label": q.display_label or q.question_number,
            "stable_question_key": q.stable_question_key,
            "student_answer_mapped": True,
            "model_answer_mapped": len(self.answers[question_id]) == 1,
            "rubric_mapped": len(self.entries[question_id]) == 1,
            "bundle": None,
            "context": None,
            "warnings": [],
            "reconstruction": {"id": reconstruction.id, "version": reconstruction.version,
                                "status": reconstruction.status,
                                "source_sha256": reconstruction.source_sha256,
                                "output_sha256": reconstruction.output_sha256},
        }
        if reconstruction.status == "REVIEW_REQUIRED":
            codes.append("ANSWER_RECONSTRUCTION_REVIEW_REQUIRED")
        elif reconstruction.status == "FAILED":
            codes.append("ANSWER_RECONSTRUCTION_FAILED")
        try:
            row["context"] = self.contexts.build(question_id)
        except ContextError as exc:
            codes.append(exc.code)
        try:
            self._validate_reconstruction(reconstruction, sub, answer)
        except ContextError as exc:
            codes.append(exc.code)
        if not codes:
            part = self.question_part(question_id)
            value = {
                "schema_version": "grading-input-bundle.v1",
                **part,
                "input_stage": "reconstructed_answer",
                "student_answer": {
                    "id": reconstruction.id,
                    "submission_id": sub.id,
                    "source_answer_id": f"{sub.id}:{question_id}",
                    "test_id": self.test_id,
                    "student_id": sub.student_id,
                    "question_id": question_id,
                    "representation": "reconstructed",
                    "source": "RECONSTRUCTED_FROM_DOCUMENT",
                    "answer_text": reconstruction.answer_text,
                    "source_sha256": reconstruction.source_sha256,
                    "reconstruction_id": reconstruction.id,
                    "reconstruction_version": reconstruction.version,
                    "reconstruction_status": reconstruction.status,
                    "page_ids": [page["page_id"]],
                    "source_pages": [page],
                    "reconstruction_context_sha256": reconstruction.context_sha256,
                    "normalized_reconstruction": self.verified_reconstructions[reconstruction.id],
                    "sha256": self.verified_reconstructions[reconstruction.id]["output_sha256"],
                },
                "mapping": {"resolution_method": "explicit_selected_question", "warnings": []},
            }
            value["bundle_sha256"] = canonical_hash(value)
            row["bundle"] = value
        if visual_result is not None:
            vr = visual_result['questions'][0]
            vr['blockers'].extend(reason(code) for code in sorted(set(codes)))
            vr['state'] = 'BLOCKED' if vr['blockers'] else 'READY'
            vr['reconstruction'] = row['reconstruction']
            if row['bundle']:
                vr['bundle']['student_answer']['reconstruction'] = row['bundle']['student_answer']
                vr['bundle'].pop('bundle_sha256', None)
                vr['bundle']['bundle_sha256'] = canonical_hash(vr['bundle'])
            return visual_result
        row["blockers"] = [reason(code) for code in sorted(set(codes))]
        row["state"] = "BLOCKED" if codes else "READY"
        return {
            "test_id": self.test_id,
            "submission_id": submission_id,
            "selected_question_id": question_id,
            "gradable_count": 1,
            "mapped_student_answer_count": 1 if not codes else 0,
            "model_answer_count": int(row["model_answer_mapped"]),
            "rubric_entry_count": int(row["rubric_mapped"]),
            "ready_bundle_count": int(row["state"] == "READY"),
            "blocked_bundle_count": int(row["state"] != "READY"),
            "can_build_all_inputs": row["state"] == "READY",
            "test_can_start_grading": self.readiness["can_start_grading"],
            "input_stage": "reconstructed_answer",
            "questions": [row],
            "blockers": [],
        }


def prepare_submission_bundles(session, test_id, submissions, assignment_path, *, root=None):
    """Dry-run snapshot used before job creation; no files or database rows written."""
    from .core import load_assignment

    _, _, legacy = load_assignment(assignment_path)
    assembler = GradingInputAssembler(session, test_id, root=root, allowed_roots=[assignment_path])
    keys = [sub.submission_key for sub in submissions]
    if len(keys) != len(set(keys)) or set(keys) != {sub["submission_id"] for sub in legacy}:
        raise ContextError("CROSS_SUBMISSION_ANSWER_MAPPING")
    results = []
    for sub in submissions:
        result = assembler.evaluate(sub.id)
        if not result["can_build_all_inputs"]:
            raise ContextError("GRADING_INPUT_MAPPING_BLOCKED")
        source = next(v for v in legacy if v["submission_id"] == sub.submission_key)
        pages = {p["page_id"]: p for p in source["pages"]}
        expected = {row["question_id"]: row["bundle"] for row in result["questions"]}
        seen = set()
        for answer in source["answers"]:
            q, _, _ = assembler.resolver.resolve(answer)
            if q.id in seen or q.id not in expected:
                raise ContextError("DUPLICATE_STUDENT_ANSWER")
            seen.add(q.id)
            actual = [
                {
                    "page_id": pid,
                    "sha256": sha256_file(pages[pid]["path"]),
                    "mime_type": "image/png"
                    if pages[pid]["path"].suffix.lower() == ".png"
                    else "image/jpeg",
                }
                for pid in answer["page_ids"]
            ]
            if actual != expected[q.id]["student_answer"]["pages"]:
                raise ContextError("STUDENT_ANSWER_SNAPSHOT_MISMATCH")
        if seen != set(expected):
            raise ContextError("MISSING_STUDENT_ANSWER")
        results.extend(expected.values())
    return results
