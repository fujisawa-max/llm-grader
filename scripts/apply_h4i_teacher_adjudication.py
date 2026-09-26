"""Persist the two explicit H.4-I teacher adjudications.

This script never creates or runs a GradingJob. Existing failed/review-required
jobs remain immutable source snapshots for the append-only decisions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring.db.database import create_session_factory
from scoring.teacher_grading import create_teacher_grading_decision


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
TEACHER_ID = "99d3a635-8c60-47a4-99d8-aa11e4efe176"
DB = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"

Q2 = {
    "label": "Q2/s2/q3",
    "test_id": "9fc4f834-a50e-423f-b0cf-31a977c1f891",
    "submission_id": "58b55168-2750-45b1-8cc4-91ebc86da5dd",
    "question_id": "8c8c578c-1635-4f13-91e8-4b40dbe3e258",
    "source_job_id": "d60b50bc-022d-43ce-a494-19651eca81ee",
    "previous_job_ids": [
        "12220e0b-e58c-401d-bbda-2ddb51c7e82f",
        "d60b50bc-022d-43ce-a494-19651eca81ee",
    ],
    "rubric_version_id": "257145ea-57eb-4ffd-a592-b26e794c0662",
    "score": 10,
    "max_score": 20,
    "criterion_scores": [{"criterion_id": "sampleQ2-3-approved-1", "score": 10}],
    "teacher_reason": (
        "学生は (x+1)^3 = x^3 + 3x^2 + 3x + 1 と、-1を三重根とする式の構成および"
        "展開を正しく行っている。ただし、問題は三次方程式を要求しており、最終的に"
        "(x+1)^3 = 0 または x^3 + 3x^2 + 3x + 1 = 0 とする必要がある。学生答案には"
        "=0 がなく、方程式として完成していないため、Approved Rubricの部分点条件10点を適用する。"
    ),
}

Q3 = {
    "label": "Q3/s1/q3",
    "test_id": "8df4ed72-9297-4082-bb21-1fdb6c500557",
    "submission_id": "9a98190f-e5cf-4704-81d3-1cfc03658e7c",
    "question_id": "7fcbd8ee-1eee-4d93-a195-59ea995a0385",
    "source_job_id": "6196d9cf-7133-4e88-a9e5-d654d8c02fe7",
    "previous_job_ids": ["6196d9cf-7133-4e88-a9e5-d654d8c02fe7"],
    "rubric_version_id": "97fca117-1573-40ac-bd40-ef9a72d5176c",
    "score": 40,
    "max_score": 40,
    "criterion_scores": [
        {"criterion_id": "sampleQ3-3-approved-1", "score": 5},
        {"criterion_id": "sampleQ3-3-approved-2", "score": 5},
        {"criterion_id": "sampleQ3-3-approved-3", "score": 5},
        {"criterion_id": "sampleQ3-3-approved-4", "score": 5},
        {"criterion_id": "sampleQ3-3-approved-5", "score": 20},
    ],
    "teacher_reason": (
        "Student Answer y = 3 cos(x + π/2) はModelAnswerと完全一致している。上下移動なし、"
        "振幅3、xの係数1、x軸方向移動−π/2、最終式の全criterionを満たす。Ornithが"
        "criterion 5について振幅係数3が欠落と判定したのは、実際のStudent Answerと矛盾する"
        "grading model output errorである。"
    ),
}


def apply(database_url: str) -> dict:
    _, factory = create_session_factory(database_url)
    report = {"phase": "H.4-I", "targets": {}, "new_ornith_calls": 0,
              "new_grading_jobs": 0}
    with factory() as session:
        for target in (Q2, Q3):
            row, created = create_teacher_grading_decision(
                session, artifact_root=ARTIFACT_ROOT,
                source_grading_job_id=target["source_job_id"],
                test_id=target["test_id"], submission_id=target["submission_id"],
                question_id=target["question_id"], rubric_version_id=target["rubric_version_id"],
                score=target["score"], max_score=target["max_score"],
                criterion_scores=target["criterion_scores"],
                teacher_reason=target["teacher_reason"], teacher_user_id=TEACHER_ID,
                previous_job_ids=target["previous_job_ids"],
            )
            session.commit()
            report["targets"][target["label"]] = {
                "teacher_grading_decision_id": row.id,
                "decision_version": row.decision_version,
                "score": row.score, "max_score": row.max_score,
                "criterion_scores": row.criterion_scores,
                "artifact_ref": row.artifact_ref,
                "artifact_sha256": row.artifact_sha256,
                "input_snapshot_sha256": row.input_snapshot_sha256,
                "bundle_sha256": row.bundle_sha256,
                "created": created,
                "source_job_id": row.source_grading_job_id,
                "previous_job_ids": target["previous_job_ids"],
            }
    (ARTIFACT_ROOT / "h4i-teacher-adjudication" / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=DB)
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url), ensure_ascii=False, indent=2))
