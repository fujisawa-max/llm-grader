"""Teacher-accept Q4 Problem 2(1) reconstruction without changing its text."""

from __future__ import annotations

import argparse
import json

from scoring.db.database import create_session_factory
from scoring.student_answer import TeacherAcceptedStudentAnswerReconstruction


RECONSTRUCTION_ID = "225a70bd-5094-47db-b7ae-321611852255"


def apply(database_url: str, artifact_root: str) -> dict:
    _, factory = create_session_factory(database_url)
    with factory() as session:
        run, extraction, revision, accepted = TeacherAcceptedStudentAnswerReconstruction(
            session, artifact_root=artifact_root
        ).apply(RECONSTRUCTION_ID, reason="teacher_accept_version_1_without_answer_edit")
        session.commit()
        return {
            "base_reconstruction_id": RECONSTRUCTION_ID,
            "base_version": 1,
            "selected_run_id": run.id,
            "selected_reconstruction_id": revision.id,
            "selected_version": revision.version,
            "selected_output_sha256": revision.output_sha256,
            "answer_text": revision.answer_text,
            "source_sha256": revision.source_sha256,
            "status": revision.status,
            "extraction_id": extraction.id,
            "provenance": revision.model_identity,
            "content_preserved": revision.answer_text == accepted["answer_text"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url, args.artifact_root), ensure_ascii=False, indent=2))
