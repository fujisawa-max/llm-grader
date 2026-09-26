"""Read-only and explicitly bounded student-answer reconstruction API."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from ..db.models import (
    StudentAnswerExtractionResult,
    StudentAnswerExtractionRun,
    StudentAnswerReconstruction,
    StudentSubmission,
    TestMaterial,
    TestQuestion,
)
from ..student_answer import StudentAnswerError, StudentAnswerReconstructionInputBuilder
from ..student_answer import answer_pages
import json
from ..pdf_native import sha256_file
from ..student_identity import StudentIdentityService


class ReconstructionRunRequest(BaseModel):
    execute: bool = False


def router(db, artifact_root):
    r = APIRouter(prefix="/api/v1")

    def submission_or_404(test_id, submission_id, session):
        sub = session.get(StudentSubmission, submission_id)
        if sub is None or sub.test_id != test_id:
            raise HTTPException(404, "submission_not_found")
        return sub

    @r.get("/tests/{test_id}/submissions/{submission_id}/answer-reconstruction-input/{question_id}")
    def reconstruction_input(test_id, submission_id, question_id, s=Depends(db)):
        submission_or_404(test_id, submission_id, s)
        q = s.get(TestQuestion, question_id)
        if q is None or q.test_id != test_id:
            raise HTTPException(404, "question_not_found")
        try:
            return StudentAnswerReconstructionInputBuilder(
                s, submission_id, root=artifact_root).build(question_id).as_dict()
        except StudentAnswerError as exc:
            raise HTTPException(409, {"error": {"code": exc.code, "message": str(exc)}})

    @r.post("/tests/{test_id}/submissions/{submission_id}/answer-reconstruction-runs")
    def create_run(test_id, submission_id, value: ReconstructionRunRequest, s=Depends(db)):
        submission_or_404(test_id, submission_id, s)
        if value.execute:
            # Runtime ownership and role adapters are deliberately injected by
            # the worker; an HTTP request must never start a model implicitly.
            raise HTTPException(409, {"error": {"code": "RECONSTRUCTION_RUNTIME_NOT_CONFIGURED",
                                                "message": "workerのRuntimeManager経由で明示実行してください"}})
        raise HTTPException(422, {"error": {"code": "RECONSTRUCTION_EXECUTE_REQUIRED",
                                             "message": "dry-runはrunを作成しません"}})

    @r.get("/tests/{test_id}/submissions/{submission_id}/answer-artifacts/{page_id}")
    def answer_artifact(test_id, submission_id, page_id, s=Depends(db)):
        submission_or_404(test_id, submission_id, s)
        try:
            builder = StudentAnswerReconstructionInputBuilder(s, submission_id, root=artifact_root)
            document = json.loads(builder.source.read_text(encoding="utf-8"))
            page = next((v for v in document.get("pages", []) if v.get("page_id") == page_id), None)
            if page is None:
                raise HTTPException(404, "answer_page_not_found")
            path = (builder.source.parent / page["image"]).resolve()
            if not path.is_relative_to(builder.root) or not path.is_file() or sha256_file(path) != next(
                    v["sha256"] for v in answer_pages(document, builder.source.parent)
                    for p in v["pages"] if p["page_id"] == page_id):
                raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
            return FileResponse(path, media_type="image/png" if path.suffix.lower() == ".png" else "image/jpeg")
        except StopIteration:
            raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
        except StudentAnswerError as exc:
            raise HTTPException(409, exc.code)

    @r.get("/tests/{test_id}/submissions/{submission_id}/answer-pages")
    def answer_page_list(test_id, submission_id, s=Depends(db)):
        """Return the immutable source-page index for the teacher preview.

        The endpoint exposes page identifiers and provenance only; image bytes
        remain behind ``answer-artifacts/{page_id}``, which performs the same
        root and SHA checks as every other source-artifact read.
        """
        submission_or_404(test_id, submission_id, s)
        try:
            # A registered source image is always previewable, even before a
            # reconstruction run has produced its page mapping.  This keeps
            # teacher source inspection independent from extraction state.
            submission = s.get(StudentSubmission, submission_id)
            material = s.get(TestMaterial, submission.material_id) if submission else None
            if material and material.material_type == "student_answer_source_image":
                image = Path(material.storage_ref).resolve()
                root = Path(artifact_root).resolve()
                if not image.is_relative_to(root) or not image.is_file() or sha256_file(image) != material.sha256:
                    raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
                return {"submission_id": submission_id, "source_sha256": material.sha256,
                        "page_count": 1, "pages": [{"page_id": "source", "sha256": material.sha256,
                        "mime_type": material.mime_type or "image/png"}]}
            builder = StudentAnswerReconstructionInputBuilder(s, submission_id, root=artifact_root)
            document = json.loads(builder.source.read_text(encoding="utf-8"))
            pages = []
            for page in document.get("pages", []):
                image = (builder.source.parent / str(page.get("image", ""))).resolve()
                if not image.is_relative_to(builder.root) or not image.is_file():
                    raise HTTPException(409, "SOURCE_ANSWER_ARTIFACT_MISSING")
                digest = next(
                    v["sha256"] for v in answer_pages(document, builder.source.parent)
                    for p in v["pages"] if p["page_id"] == page.get("page_id")
                )
                if sha256_file(image) != digest:
                    raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
                pages.append({"page_id": page.get("page_id"), "sha256": digest,
                              "mime_type": "image/png" if image.suffix.lower() == ".png" else "image/jpeg"})
            return {"submission_id": submission_id, "source_sha256": document.get("source_sha256"),
                    "page_count": len(pages), "pages": pages}
        except StopIteration:
            raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
        except StudentAnswerError as exc:
            raise HTTPException(409, exc.code)

    @r.get("/tests/{test_id}/submissions/{submission_id}/student-identity")
    def student_identity(test_id, submission_id, s=Depends(db)):
        submission_or_404(test_id, submission_id, s)
        try:
            value = StudentIdentityService(s, root=artifact_root).load(submission_id)
        except ValueError as exc:
            raise HTTPException(409, {"error": {"code": str(exc), "message": "学生情報を確認できません"}}) from exc
        if value is None:
            return {"status": "REVIEW_REQUIRED", "student_number": "", "student_name": "",
                    "display_label": "学生情報未確認", "review_required": True,
                    "source_bbox": {"header_bbox": [0.56, 0.02, 0.92, 0.17]}}
        return value

    @r.get("/tests/{test_id}/student-identities")
    def student_identities(test_id, s=Depends(db)):
        submissions = list(s.scalars(select(StudentSubmission).where(StudentSubmission.test_id == test_id)))
        service = StudentIdentityService(s, root=artifact_root)
        values = []
        for submission in submissions:
            try:
                value = service.load(submission.id)
            except ValueError:
                value = None
            values.append(value or {"submission_id": submission.id, "student_number": "",
                                   "student_name": "", "display_label": "学生情報未確認",
                                   "review_required": True})
        values.sort(key=lambda value: (
            not bool(value.get("student_number")),
            value.get("student_number") or "",
            value.get("submission_id") or "",
        ))
        return values

    @r.get("/tests/{test_id}/submissions/{submission_id}/source-pages/{page_id}")
    def source_page(test_id, submission_id, page_id, s=Depends(db)):
        submission = submission_or_404(test_id, submission_id, s)
        material = s.get(TestMaterial, submission.material_id)
        if material is None or material.material_type != "student_answer_source_image" or page_id != "source":
            raise HTTPException(404, "source_page_not_found")
        path = Path(material.storage_ref).resolve()
        root = Path(artifact_root).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != material.sha256:
            raise HTTPException(409, "SOURCE_ANSWER_HASH_MISMATCH")
        return FileResponse(path, media_type=material.mime_type or "image/png")

    @r.get("/tests/{test_id}/submissions/{submission_id}/answer-reconstruction-runs")
    def list_runs(test_id, submission_id, s=Depends(db)):
        submission_or_404(test_id, submission_id, s)
        return [{"id": run.id, "status": run.status, "source_sha256": run.source_sha256,
                 "pipeline_version": run.pipeline_version, "config_sha256": run.config_sha256,
                 "selected": run.selected, "created_at": run.created_at}
                for run in s.scalars(select(StudentAnswerExtractionRun).where(
                    StudentAnswerExtractionRun.submission_id == submission_id).order_by(StudentAnswerExtractionRun.created_at))]

    @r.get("/answer-reconstruction-runs/{run_id}")
    def get_run(run_id, s=Depends(db)):
        run = s.get(StudentAnswerExtractionRun, run_id)
        if run is None:
            raise HTTPException(404, "reconstruction_run_not_found")
        return {"id": run.id, "submission_id": run.submission_id, "test_id": run.test_id,
                "status": run.status, "source_sha256": run.source_sha256,
                "pipeline_version": run.pipeline_version, "config_sha256": run.config_sha256,
                "selected": run.selected, "artifact_ref": run.artifact_ref}

    @r.get("/answer-reconstruction-runs/{run_id}/results")
    def get_results(run_id, s=Depends(db)):
        run = s.get(StudentAnswerExtractionRun, run_id)
        if run is None:
            raise HTTPException(404, "reconstruction_run_not_found")
        values = []
        for result in s.scalars(select(StudentAnswerExtractionResult).where(
                StudentAnswerExtractionResult.run_id == run_id)):
            current = s.scalar(select(StudentAnswerReconstruction).where(
                StudentAnswerReconstruction.extraction_result_id == result.id).order_by(
                StudentAnswerReconstruction.version.desc()))
            values.append({"id": result.id, "question_id": result.question_id, "status": result.status,
                           "source_sha256": result.source_sha256, "normalized_sha256": result.normalized_sha256,
                           "reconstruction": None if current is None else {
                               "id": current.id, "version": current.version, "status": current.status,
                               "answer_text": current.answer_text, "output_sha256": current.output_sha256,
                               "context_sha256": current.context_sha256,
                           }})
        return {"run_id": run_id, "results": values}

    @r.post("/answer-reconstruction-runs/{run_id}/select")
    def select_run(run_id, s=Depends(db)):
        run = s.get(StudentAnswerExtractionRun, run_id)
        if run is None or run.status != "completed":
            raise HTTPException(409, "reconstruction_run_not_completed")
        s.query(StudentAnswerExtractionRun).filter(
            StudentAnswerExtractionRun.submission_id == run.submission_id,
            StudentAnswerExtractionRun.selected.is_(True)).update({"selected": False})
        run.selected = True
        s.commit()
        return {"id": run.id, "selected": True}

    return r
