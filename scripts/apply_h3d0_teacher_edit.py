"""Apply the explicit H.3-D.0 teacher reconstruction edit and preview input."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scoring.db.models import DomainEvent, StudentAnswerReconstruction
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.student_answer import TeacherEditedStudentAnswerReconstruction


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
DATABASE_URL = os.environ.get(
    "LLM_GRADER_DATABASE_URL",
    "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader",
)
SUBMISSION_ID = "fcf9d128-4dbb-4aee-b49b-1c715fdcfd16"
QUESTION_ID = "8a2a7955-2347-4c67-8581-f800721ec558"
BASE_RECONSTRUCTION_ID = "4476a8b1-3aa9-454e-833a-8c5bd1c36080"
TEST_ID = "70a63c23-f1b1-46b7-852c-046148b6f451"
ANSWER = (
    "入力と、その入力に対する正しい答えである教師データをもとに学習を行う機械学習である。"
    "学習では誤差が小さくなるように修正を行う。"
)
SOURCE_SHA = "aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba"


def main():
    engine = create_engine(DATABASE_URL)
    with Session(engine) as session:
        before = session.get(StudentAnswerReconstruction, BASE_RECONSTRUCTION_ID)
        if before is None:
            raise RuntimeError("BASE_RECONSTRUCTION_NOT_FOUND")
        source = ROOT / "artifacts/student-submissions/70a63c23-f1b1-46b7-852c-046148b6f451" / f"{SOURCE_SHA}.png"
        source_before = sha256_file(source)
        if source_before != SOURCE_SHA:
            raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_before}")
        if before.answer_text == ANSWER and before.status == "COMPLETE":
            revised = session.scalar(select(StudentAnswerReconstruction).where(
                StudentAnswerReconstruction.submission_id == before.submission_id,
                StudentAnswerReconstruction.question_id == QUESTION_ID,
                StudentAnswerReconstruction.version > before.version,
            ).order_by(StudentAnswerReconstruction.version.desc()))
            if revised is None:
                raise RuntimeError("TEACHER_EDIT_REVISION_NOT_FOUND")
            run = None
            extraction = None
            edited = {"answer_text": revised.answer_text, "output_sha256": revised.output_sha256}
        else:
            run, extraction, revised, edited = TeacherEditedStudentAnswerReconstruction(
                session, artifact_root=ARTIFACT_ROOT).apply(
                    BASE_RECONSTRUCTION_ID, ANSWER,
                    reason="teacher_explicit_reconstruction_edit",
                )
            session.add(DomainEvent(
                entity_type="student_answer_reconstruction",
                entity_id=revised.id,
                event_type="teacher_edit_revision_created",
                payload={"base_reconstruction_id": BASE_RECONSTRUCTION_ID,
                         "question_id": QUESTION_ID,
                         "provenance": "TEACHER_EDITED",
                         "reason": "teacher_explicit_reconstruction_edit"},
            ))
            session.commit()
        source_after = sha256_file(source)
        if source_after != source_before:
            raise RuntimeError("SOURCE_IMAGE_MUTATED")
        assembler = GradingInputAssembler(
            session, TEST_ID, root=ARTIFACT_ROOT, allowed_roots=[ARTIFACT_ROOT]
        )
        preview = assembler.evaluate_selected_question(SUBMISSION_ID, QUESTION_ID)
        preview_path = ARTIFACT_ROOT / "h3d0-reconstruction" / SUBMISSION_ID / "grading-input-preview.json"
        preview_path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
        bundle = preview["questions"][0].get("bundle")
        report = {
            "submission_id": SUBMISSION_ID,
            "question_id": QUESTION_ID,
            "base_reconstruction_id": BASE_RECONSTRUCTION_ID,
            "selected_reconstruction_id": revised.id,
            "selected_reconstruction_version": revised.version,
            "selected_reconstruction_status": revised.status,
            "selected_reconstruction_sha256": revised.output_sha256,
            "source_sha256_before": source_before,
            "source_sha256_after": source_after,
            "teacher_edit": {"old": before.answer_text, "new": ANSWER,
                             "provenance": "TEACHER_EDITED"},
            "preview": {"state": preview["questions"][0]["state"],
                        "blockers": preview["questions"][0]["blockers"],
                        "bundle_sha256": bundle.get("bundle_sha256") if bundle else None,
                        "path": str(preview_path.relative_to(ROOT))},
            "grading_job_created": 0,
            "ornith_grading_calls": 0,
            "score_generated": False,
            "feedback_generated": False,
        }
        report_path = ARTIFACT_ROOT / "h3d0-reconstruction" / SUBMISSION_ID / "teacher-edit-preview.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
