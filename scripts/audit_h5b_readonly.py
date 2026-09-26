"""Read-only H.5-B audit against the persistent sample grading database."""

from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scoring.db import models as m
from scoring.grading_audit import (
    aggregate_authoritative_results,
    grading_response_warnings,
    has_matrix_vector_structure,
    require_visual_roles,
    resolve_authoritative_result,
    resolve_selected_reconstruction,
)


URL = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"
TESTS = {
    "sampleQ1": "70a63c23-f1b1-46b7-852c-046148b6f451",
    "sampleQ2": "9fc4f834-a50e-423f-b0cf-31a977c1f891",
    "sampleQ3": "8df4ed72-9297-4082-bb21-1fdb6c500557",
    "sampleQ4": "e14aeeb5-924c-4c72-b2a2-583f1be9f48e",
}


def read_raw(run_path: str):
    paths = sorted(Path(run_path).rglob("*.raw.json"))
    if not paths:
        return None
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def main():
    session = sessionmaker(create_engine(URL))()
    resolved = []
    selected = {}
    visual_checks = []
    for sample, test_id in TESTS.items():
        questions = list(session.scalars(select(m.TestQuestion).where(
            m.TestQuestion.test_id == test_id, m.TestQuestion.is_gradable.is_(True),
        ).order_by(m.TestQuestion.sort_order)))
        submissions = list(session.scalars(select(m.StudentSubmission).where(
            m.StudentSubmission.test_id == test_id)))
        for sub in submissions:
            student = session.get(m.Student, sub.student_id).student_identifier
            for question in questions:
                target = f"{sample}/{student}/{question.question_number}"
                revisions = list(session.scalars(select(m.StudentAnswerReconstruction).join(
                    m.StudentAnswerExtractionResult,
                    m.StudentAnswerReconstruction.extraction_result_id == m.StudentAnswerExtractionResult.id,
                ).join(
                    m.StudentAnswerExtractionRun,
                    m.StudentAnswerExtractionResult.run_id == m.StudentAnswerExtractionRun.id,
                ).where(
                    m.StudentAnswerReconstruction.submission_id == sub.id,
                    m.StudentAnswerReconstruction.question_id == question.id,
                    m.StudentAnswerExtractionRun.selected.is_(True),
                    m.StudentAnswerExtractionRun.status == "completed",
                ).order_by(m.StudentAnswerReconstruction.version.desc())))
                if revisions:
                    current = resolve_selected_reconstruction(revisions)
                    selected[target] = {"id": current.id, "version": current.version,
                                        "answer": current.answer_text}

                jobs = []
                for job in session.scalars(select(m.GradingJob).where(
                    m.GradingJob.test_id == test_id)).all():
                    for item in job.items:
                        meta = item.metadata_json or {}
                        if meta.get("submission_id") != sub.id or meta.get("question_id") != question.id:
                            continue
                        if job.state != "completed" or item.score is None or item.needs_review:
                            continue
                        snapshot = (job.metadata_json or {}).get("grading_execution", {})
                        bundle = snapshot.get("bundle", {})
                        jobs.append((job, item, bundle))
                jobs.sort(key=lambda row: row[0].created_at)
                teacher = list(session.scalars(select(m.TeacherGradingDecision).where(
                    m.TeacherGradingDecision.submission_id == sub.id,
                    m.TeacherGradingDecision.question_id == question.id,
                    m.TeacherGradingDecision.status == "COMPLETE",
                ).order_by(m.TeacherGradingDecision.decision_version)))
                model_rows = [{"id": job.id, "target": target, "state": job.state,
                               "score": item.score, "max_score": item.max_score,
                               "completed_at": job.completed_at,
                               "needs_review": item.needs_review,
                               "snapshot_sha256": (job.metadata_json or {}).get(
                                   "grading_execution", {}).get("snapshot_sha256"),
                               "bundle_sha256": (item.metadata_json or {}).get("bundle_sha256"),
                               "superseded": False}
                              for job, item, _bundle in jobs]
                decision_rows = [{"id": row.id, "target": target, "status": row.status,
                                  "score": row.score, "max_score": row.max_score,
                                  "decision_version": row.decision_version,
                                  "created_at": row.created_at}
                                 for row in teacher]
                current_snapshot = None
                current_bundle = None
                if jobs:
                    latest_job, latest_item, latest_bundle = jobs[-1]
                    current_snapshot = (latest_job.metadata_json or {}).get(
                        "grading_execution", {}).get("snapshot_sha256")
                    current_bundle = (latest_item.metadata_json or {}).get("bundle_sha256")
                final = resolve_authoritative_result(
                    target, teacher_decisions=decision_rows, model_results=model_rows,
                    current_snapshot_sha=current_snapshot,
                    current_bundle_sha=current_bundle,
                )
                resolved.append({"target": target, "test_id": sample,
                                 "student_id": student, "score": final.score,
                                 "max_score": final.max_score, "source": final.source,
                                 "result_id": final.result_id})
                if sample == "sampleQ4" and question.question_number in {"2.2", "3"}:
                    if jobs:
                        roles = [asset.get("role") for asset in jobs[-1][2].get("visual_assets", [])]
                        require_visual_roles(jobs[-1][2].get("visual_assets", []))
                        visual_checks.append({"target": target, "roles": roles})

    expected = {
        "sampleQ1/s1": 100, "sampleQ1/s2": 100,
        "sampleQ2/s1": 100, "sampleQ2/s2": 100,
        "sampleQ3/s1": 100, "sampleQ3/s2": 100,
        "sampleQ4/s1": 110, "sampleQ4/s2": 110,
    }
    aggregate = aggregate_authoritative_results(
        resolved, test_totals=expected, expected_targets=[row["target"] for row in resolved])
    q3q1 = selected["sampleQ3/s1/1"]
    q4q1 = selected["sampleQ4/s1/1"]
    assert q3q1["id"] == "461a1daf-d16d-4dfa-a011-ff22c576c6d7"
    assert q4q1["id"] == "f08bf635-7f1e-46dd-8256-fbffec9d82f1"
    assert has_matrix_vector_structure(q4q1["answer"])
    q2q3 = next(row for row in resolved if row["target"] == "sampleQ2/s2/3")
    q3q3 = next(row for row in resolved if row["target"] == "sampleQ3/s1/3")
    assert q2q3["score"] == 10 and q2q3["source"] == "TEACHER_ADJUDICATION"
    assert q3q3["score"] == 40 and q3q3["source"] == "TEACHER_ADJUDICATION"

    # The contradiction guards are audited against the two original raw jobs.
    q2_job = session.get(m.GradingJob, "d60b50bc-022d-43ce-a494-19651eca81ee")
    q2_bundle = q2_job.metadata_json["grading_execution"]["bundle"]
    q2_answer = q2_bundle["student_answer"]["answer_text"]
    q2_raw = read_raw(q2_job.run_path)
    q2_result = json.loads(q2_raw["choices"][0]["message"]["content"])
    q3_job = session.get(m.GradingJob, "6196d9cf-7133-4e88-a9e5-d654d8c02fe7")
    q3_bundle = q3_job.metadata_json["grading_execution"]["bundle"]
    q3_raw = read_raw(q3_job.run_path)
    q3_result = json.loads(q3_raw["choices"][0]["message"]["content"])
    warnings = {
        "q2": grading_response_warnings(q2_result, q2_bundle),
        "q3": grading_response_warnings(q3_result, q3_bundle),
    }
    assert q2_answer.strip() and warnings["q2"]
    assert warnings["q3"]
    print(json.dumps({"results": resolved, "totals": aggregate["totals"],
                      "selected": selected, "visual": visual_checks,
                      "warnings": warnings, "count": len(resolved)},
                     ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
