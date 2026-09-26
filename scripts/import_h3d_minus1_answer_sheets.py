"""Register the eight H.3-D.-1 answer-sheet sources.

The script intentionally stops at source registration.  It never creates a
question-level answer document and never invokes OCR, reconstruction, or
grading.  All database mutations go through StudentSubmissionImportService.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from scoring.db.database import create_session_factory
from scoring.db.models import (
    GradingJob,
    ModelAnswer,
    QuestionImportConfirmation,
    RubricVersion,
    Student,
    StudentSubmission,
    Test,
    TestMaterial,
    TestQuestion,
    TestQuestionAsset,
    TestQuestionCorrection,
)
from scoring.pdf_native import canonical_hash
from scoring.student_submission_import import (
    AnswerSheetSpec,
    ImportResult,
    StudentSubmissionImportError,
    StudentSubmissionImportService,
    write_manifest,
)


Q1_ID = "70a63c23-f1b1-46b7-852c-046148b6f451"
SAMPLES = ("sampleQ1", "sampleQ2", "sampleQ3", "sampleQ4")
STUDENTS = ("s1", "s2")


def _questions(session, test_id: str) -> list[TestQuestion]:
    return list(
        session.scalars(
            select(TestQuestion).where(TestQuestion.test_id == test_id).order_by(
                TestQuestion.sort_order, TestQuestion.id
            )
        )
    )


def resolve_authoritative_tests(session) -> dict[str, Test]:
    """Resolve current sample Tests by identity and authoritative shape."""
    q1 = session.get(Test, Q1_ID)
    if q1 is None or not q1.name.endswith("sampleQ1") or len(_questions(session, q1.id)) != 8:
        raise RuntimeError("AUTHORITATIVE_SAMPLEQ1_NOT_FOUND")

    candidates = {}
    for key, expected_count, expected_max, expected_total in (
        # The authoritative tree is stored by hierarchy sort order: Q1(1),
        # structural Q1 parent, Q2, Q3, then Q1(2).
        ("sampleQ2", 5, [20.0, None, 40.0, 20.0, 20.0], 100.0),
        ("sampleQ3", 3, [30.0, 30.0, 40.0], 100.0),
    ):
        values = []
        for test in session.scalars(select(Test).where(Test.name.like(f"%{key}"))):
            qs = _questions(session, test.id)
            if (
                test.course_offering_id == q1.course_offering_id
                and len(qs) == expected_count
                and [q.max_points for q in qs] == expected_max
                and float(test.total_points) == expected_total
            ):
                values.append(test)
        if len(values) != 1:
            raise RuntimeError(f"AUTHORITATIVE_{key.upper()}_AMBIGUOUS")
        candidates[key] = values[0]

    q4_values = []
    for test in session.scalars(select(Test).where(Test.name == "H.2-H sampleQ4")):
        qs = _questions(session, test.id)
        if (
            test.course_offering_id == q1.course_offering_id
            and len(qs) == 5
            and [q.max_points for q in qs] == [30.0, None, 20.0, 20.0, 40.0]
            and float(test.total_points) == 110.0
        ):
            q4_values.append(test)
    if len(q4_values) != 1:
        raise RuntimeError("AUTHORITATIVE_SAMPLEQ4_AMBIGUOUS")
    candidates["sampleQ1"] = q1
    candidates["sampleQ4"] = q4_values[0]
    return {key: candidates[key] for key in SAMPLES}


def _question_side_snapshot(session, tests: dict[str, Test]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    test_ids = [t.id for t in tests.values()]
    questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id.in_(test_ids))))
    result["tests"] = {
        t.id: {"name": t.name, "total_points": t.total_points, "course_offering_id": t.course_offering_id}
        for t in tests.values()
    }
    result["questions"] = {
        q.id: {
            "test_id": q.test_id,
            "content_sha256": q.content_sha256,
            "max_points": q.max_points,
            "parent_id": q.parent_id,
            "stable_question_key": q.stable_question_key,
            "node_type": q.node_type,
            "is_gradable": q.is_gradable,
        }
        for q in questions
    }
    result["model_answers"] = {
        a.id: {"test_id": a.test_id, "question_id": a.question_id, "version": a.version,
               "is_current": a.is_current, "sha256": canonical_hash(a.answer_text or "")}
        for a in session.scalars(select(ModelAnswer).where(ModelAnswer.test_id.in_(test_ids)))
    }
    result["rubrics"] = {
        r.id: {"test_id": r.test_id, "version": r.version, "status": r.status,
               "sha256": canonical_hash(r.rubric_json)}
        for r in session.scalars(select(RubricVersion).where(RubricVersion.test_id.in_(test_ids)))
    }
    result["corrections"] = {
        c.id: {"test_question_id": c.test_question_id, "version": c.correction_version,
               "previous": c.previous_content_sha256, "new": c.new_content_sha256}
        for c in session.scalars(
            select(TestQuestionCorrection).join(TestQuestion).where(TestQuestion.test_id.in_(test_ids))
        )
    }
    result["confirmations"] = {
        c.id: {"test_id": c.test_id, "revision": c.review_revision_number,
               "review_sha": c.review_revision_sha256, "plan_sha": c.import_plan_sha256}
        for c in session.scalars(
            select(QuestionImportConfirmation).where(QuestionImportConfirmation.test_id.in_(test_ids))
        )
    }
    result["assets"] = {
        a.id: {"question_id": a.question_id, "sha256": a.sha256, "provenance": a.provenance}
        for a in session.scalars(
            select(TestQuestionAsset).join(TestQuestion).where(TestQuestion.test_id.in_(test_ids))
        )
    }
    return result


def _source_specs(root: Path, tests: dict[str, Test]) -> list[AnswerSheetSpec]:
    source_dir = root / "testData" / "SampleQ" / "answerSheet"
    expected = {
        f"{sample}_answerSheet_{student}.png"
        for sample in SAMPLES
        for student in STUDENTS
    }
    actual = {path.name for path in source_dir.glob("*.png")}
    missing = sorted(expected - actual)
    if missing:
        raise StudentSubmissionImportError("SOURCE_FILE_NOT_FOUND", ", ".join(missing))
    specs = []
    for sample in SAMPLES:
        for student in STUDENTS:
            path = source_dir / f"{sample}_answerSheet_{student}.png"
            specs.append(AnswerSheetSpec(student, tests[sample].id, path))
    return specs


def _inventory(session, tests: dict[str, Test]) -> list[dict[str, Any]]:
    rows = []
    for sample, test in tests.items():
        for submission in session.scalars(
            select(StudentSubmission).where(StudentSubmission.test_id == test.id).order_by(
                StudentSubmission.submission_key, StudentSubmission.id
            )
        ):
            material = session.get(TestMaterial, submission.material_id)
            student = session.get(Student, submission.student_id)
            rows.append(
                {
                    "sample": sample,
                    "test_id": test.id,
                    "submission_id": submission.id,
                    "student_id": student.id if student else None,
                    "student_ref": student.student_identifier if student else None,
                    "classification": "REAL",
                    "source_type": material.mime_type if material else None,
                    "source_sha256": material.sha256 if material else None,
                    "status": submission.status,
                    "question_level_extraction": "NOT_STARTED",
                    "mapping": "NOT_YET_EXTRACTED",
                    "reconstruction": "NOT_STARTED",
                    "blockers": ["ANSWER_EXTRACTION_NOT_STARTED"],
                }
            )
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve()
    engine, factory = create_session_factory(args.database_url)
    with factory() as session:
        tests = resolve_authoritative_tests(session)
        before = _question_side_snapshot(session, tests)
        specs = _source_specs(root, tests)
        first: list[ImportResult] = []
        for spec in specs:
            first.append(
                StudentSubmissionImportService(
                    session, artifact_root=args.artifact_root
                ).import_one(spec)
            )
        session.commit()

    with factory() as session:
        second: list[ImportResult] = []
        for spec in specs:
            second.append(
                StudentSubmissionImportService(
                    session, artifact_root=args.artifact_root
                ).import_one(spec)
            )
        session.commit()

    with factory() as session:
        after = _question_side_snapshot(session, tests)
        if before != after:
            raise RuntimeError("QUESTION_SIDE_MUTATION_DETECTED")
        inventory = _inventory(session, tests)
        counts = {
            sample: sum(row["sample"] == sample for row in inventory) for sample in SAMPLES
        }
        if counts != {sample: 2 for sample in SAMPLES}:
            raise RuntimeError(f"SUBMISSION_COUNT_MISMATCH:{counts}")
        student_groups = {
            student: {
                row["student_id"]
                for row in inventory
                if row["student_ref"] == student
            }
            for student in STUDENTS
        }
        if any(len(ids) != 1 for ids in student_groups.values()) or student_groups["s1"] == student_groups["s2"]:
            raise RuntimeError("STUDENT_IDENTITY_REUSE_MISMATCH")
        all_jobs = session.scalar(select(func.count()).select_from(GradingJob))
        target_jobs = session.scalar(
            select(func.count()).select_from(GradingJob).where(
                GradingJob.test_id.in_([t.id for t in tests.values()])
            )
        )

    first_dict = [r.as_dict() for r in first]
    second_dict = [r.as_dict() for r in second]
    result = {
        "phase": "H.3-D.-1",
        "tests": {sample: {"id": tests[sample].id, "name": tests[sample].name} for sample in SAMPLES},
        "first_import": first_dict,
        "second_import": second_dict,
        "inventory": inventory,
        "counts": counts,
        "student_groups": {student: sorted(ids) for student, ids in student_groups.items()},
        "question_side_unchanged": True,
        "question_level_extraction": 0,
        "model_calls": {"ricoh": 0, "unimumer": 0, "ornith_reconstruction": 0,
                         "ornith_grading": 0, "runtime_manager_starts": 0},
        "grading_jobs_created": 0,
        "grading_jobs_existing_total": all_jobs,
        "grading_jobs_existing_target_tests": target_jobs,
    }
    write_manifest(Path(args.artifact_root) / "h3d-minus1" / "import-report.json", first, phase="H.3-D.-1")
    report = Path(args.artifact_root) / "h3d-minus1" / "completion-audit.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-root", default="artifacts")
    parser.add_argument(
        "--database-url",
        default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader",
    )
    args = parser.parse_args()
    try:
        result = run(args)
    except StudentSubmissionImportError as exc:
        raise SystemExit(f"{exc.code}: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
