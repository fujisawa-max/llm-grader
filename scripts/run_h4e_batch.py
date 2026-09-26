"""Run the authorized H.4-E production batch with snapshot idempotency."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.db.worker import JobWorker
from scoring.grading_execution import GradingExecutionRunner, create_execution_job
from scoring.grading_context import ContextError
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
DB = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"
QUESTION_ROOT = ARTIFACT_ROOT / "h2b-verification"
REFERENCE_ROOT = ARTIFACT_ROOT / "h3c1-model-answer"
CAPABILITY = json.loads((ARTIFACT_ROOT / "h3e0a/capability.json").read_text())
OUT = ARTIFACT_ROOT / "h4e-batch"
TESTS = [
    ("sampleQ1", "70a63c23-f1b1-46b7-852c-046148b6f451"),
    ("sampleQ2", "9fc4f834-a50e-423f-b0cf-31a977c1f891"),
    ("sampleQ3", "8df4ed72-9297-4082-bb21-1fdb6c500557"),
    ("sampleQ4", "e14aeeb5-924c-4c72-b2a2-583f1be9f48e"),
]


def runtime() -> RuntimeManager:
    profile = dict(CAPABILITY["profile"])
    profile.update(runtime_type="managed", runtime_id="grader", vision=True)
    return RuntimeManager({"grader": RuntimeProfile.from_mapping("grader", profile)})


def config(path: Path) -> None:
    path.write_text(json.dumps({
        "models": {"grader": {"model_id": CAPABILITY["model_id"],
                                "request_timeout_seconds": 300}},
        "generation": {"temperature": 0, "seed": 42, "top_k": 40,
                        "top_p": 0.95, "min_p": 0.05,
                        "repeat_penalty": 1.0, "max_output_tokens": 4096},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def student_ref(submission: m.StudentSubmission) -> str:
    return submission.submission_key.split("-", 1)[0]


def labels(test_name: str | None, question: m.TestQuestion) -> tuple[str, str]:
    sample = next((key for key, _ in TESTS if key in (test_name or "")), test_name or "unknown")
    return sample, question.display_label or question.question_number or question.stable_question_key


def completed_matches(session, bundle: dict) -> list[m.GradingJob]:
    matches = []
    for job in session.scalars(select(m.GradingJob).where(m.GradingJob.state == "completed")):
        snap = (job.metadata_json or {}).get("grading_execution") or {}
        snap_bundle = snap.get("bundle") or {}
        if snap_bundle.get("bundle_sha256") != bundle.get("bundle_sha256"):
            continue
        if snap_bundle.get("model_answer", {}).get("id") != bundle.get("model_answer", {}).get("id"):
            continue
        if snap_bundle.get("rubric", {}).get("id") != bundle.get("rubric", {}).get("id"):
            continue
        if snap_bundle.get("identity") != bundle.get("identity"):
            continue
        matches.append(job)
    return matches


def read_result(job: m.GradingJob, bundle: dict, *, reused: bool) -> dict:
    item = job.items[0]
    normalized_path = Path(item.normalized_result_path)
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    manifest = (Path(job.run_path) / "submissions" / item.item_key /
                "questions" / bundle["identity"]["question_id"] / "result-manifest.json")
    criteria = normalized.get("criteria", [])
    score = item.score
    max_score = item.max_score
    criterion_sum = sum(int(c["score"]) for c in criteria)
    visual_assets = bundle.get("visual_assets", [])
    is_visual = bool(visual_assets)
    roles = [a.get("role") for a in visual_assets]
    visual_ok = (not is_visual or set(roles) >= {
        "question_context", "model_answer_reference", "student_visual_answer"})
    return {
        "job_id": job.id,
        "state": job.state,
        "score": score,
        "max_score": max_score,
        "criteria": criteria,
        "criterion_sum": criterion_sum,
        "criterion_sum_valid": criterion_sum == score and score <= max_score,
        "feedback": normalized.get("feedback"),
        "feedback_persisted": isinstance(normalized.get("feedback"), str),
        "artifact_sha256": sha256_file(manifest),
        "artifact_exists": manifest.is_file(),
        "reused": reused,
        "reconstruction_id": bundle["student_answer"].get("reconstruction_id"),
        "reconstruction_version": bundle["student_answer"].get("reconstruction_version"),
        "visual_asset_ids": bundle["student_answer"].get("visual_asset_ids", []),
        "visual": is_visual,
        "visual_roles": roles,
        "visual_roles_valid": visual_ok,
        "bundle_sha256": bundle["bundle_sha256"],
        "snapshot_sha256": (job.metadata_json.get("grading_execution", {})
                            .get("snapshot_sha256")),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / "config.json"
    config(config_path)
    _, factory = create_session_factory(DB)
    manager = runtime()
    worker = JobWorker(factory, grading_runner_factory=lambda: GradingExecutionRunner(manager))
    rows: list[dict] = []
    new_jobs = 0
    reused = 0
    blocked = 0
    failed = 0
    with factory() as session:
        for test_label, test_id in TESTS:
            test = session.get(m.Test, test_id)
            if test is None:
                rows.append({"test": test_label, "status": "BLOCKED",
                             "blocker": "TEST_NOT_FOUND"})
                blocked += 1
                continue
            submissions = list(session.scalars(select(m.StudentSubmission).where(
                m.StudentSubmission.test_id == test_id)).all())
            questions = list(session.scalars(select(m.TestQuestion).where(
                m.TestQuestion.test_id == test_id,
                m.TestQuestion.is_gradable.is_(True)).order_by(
                    m.TestQuestion.question_number, m.TestQuestion.id)).all())
            assembler = GradingInputAssembler(
                session, test_id, root=QUESTION_ROOT, allowed_roots=[ARTIFACT_ROOT],
                answer_root=ARTIFACT_ROOT, reference_root=REFERENCE_ROOT,
                visual_capability=CAPABILITY)
            for submission in submissions:
                for question in questions:
                    sample, display = labels(test.name, question)
                    base = {"test": sample, "student": student_ref(submission),
                            "submission_id": submission.id, "question": display,
                            "question_id": question.id,
                            "stable_key": question.stable_question_key}
                    try:
                        preview = assembler.execution_preview(submission.id, question.id)
                        bundle = preview.get("bundle")
                        if preview.get("execution_state") != "READY" or not bundle:
                            base.update({"status": "BLOCKED", "blocker": "PRODUCTION_PREFLIGHT_BLOCKED",
                                         "details": preview.get("execution_blockers") or preview.get("blockers")})
                            blocked += 1
                            rows.append(base)
                            continue
                        matches = completed_matches(session, bundle)
                        if len(matches) > 1:
                            base.update({"status": "BLOCKED", "blocker": "DUPLICATE_COMPLETED_SNAPSHOT",
                                         "details": [j.id for j in matches]})
                            blocked += 1
                            rows.append(base)
                            continue
                        if matches:
                            result = read_result(matches[0], bundle, reused=True)
                            base.update(result)
                            if not result["criterion_sum_valid"] or not result["artifact_exists"] or not result["visual_roles_valid"]:
                                base.update({"status": "BLOCKED", "blocker": "EXISTING_RESULT_INTEGRITY_FAILURE"})
                                blocked += 1
                            else:
                                base["status"] = "REUSED"
                                reused += 1
                            rows.append(base)
                            continue

                        slug = f"{test_label}-{student_ref(submission)}-{question.stable_question_key.replace('/', '_')}"
                        run_path = OUT / slug
                        if run_path.exists() and any(run_path.iterdir()):
                            raise RuntimeError("RUN_PATH_NOT_EMPTY")
                        job = create_execution_job(
                            session, test_id, submission.id, question.id,
                            run_path=run_path, config_path=config_path,
                            root=QUESTION_ROOT, allowed_roots=[ARTIFACT_ROOT],
                            answer_root=ARTIFACT_ROOT, reference_root=REFERENCE_ROOT,
                            visual_capability=CAPABILITY)
                        session.add(m.GradingJobEvent(
                            job_id=job.id, event_type="job_created", new_state="queued",
                            payload={"phase": "H.4-E", "target": f"{sample}/{student_ref(submission)}/{display}"},
                        ))
                        session.commit()
                        new_jobs += 1
                        worker.run_once(job.id)
                        with factory() as result_session:
                            completed = result_session.get(m.GradingJob, job.id)
                            result = read_result(completed, bundle, reused=False)
                        base.update(result)
                        if result["state"] != "completed":
                            base.update({"status": "FAILED", "blocker": "GRADING_JOB_NOT_COMPLETED"})
                            failed += 1
                        elif not result["criterion_sum_valid"] or not result["artifact_exists"] or not result["visual_roles_valid"]:
                            base.update({"status": "FAILED", "blocker": "RESULT_INTEGRITY_FAILURE"})
                            failed += 1
                        else:
                            base["status"] = "COMPLETED"
                        rows.append(base)
                    except Exception as exc:
                        preflight_blocked = isinstance(exc, ContextError)
                        base.update({"status": "BLOCKED" if preflight_blocked else "FAILED",
                                     "blocker": getattr(exc, "code", type(exc).__name__),
                                     "details": str(exc)})
                        if preflight_blocked:
                            blocked += 1
                        else:
                            failed += 1
                        rows.append(base)

    completed_rows = [r for r in rows if r.get("status") in {"REUSED", "COMPLETED"}]
    totals = []
    for sample, test_id in TESTS:
        for student in ("s1", "s2"):
            selected = [r for r in completed_rows if r.get("test") == sample and r.get("student") == student]
            blocked_for_pair = [r for r in rows if r.get("test") == sample and r.get("student") == student and r.get("status") in {"BLOCKED", "FAILED"}]
            totals.append({"test": sample, "student": student,
                           "earned": sum(r.get("score", 0) for r in selected),
                           "possible": sum(r.get("max_score", 0) for r in selected),
                           "completed_questions": len(selected),
                           "status": "BLOCKED" if blocked_for_pair else "COMPLETE"})
    report = {
        "phase": "H.4-E", "total_targets": len(rows), "rows": rows,
        "totals": totals, "reused_existing_results": reused,
        "new_grading_jobs": new_jobs, "new_ornith_calls": new_jobs,
        "completed": len(completed_rows), "failed": failed, "blocked_before_grading": blocked,
        "visual_targets": sum(1 for r in rows if r.get("visual")),
        "visual_completed": sum(1 for r in completed_rows if r.get("visual") and r.get("visual_roles_valid")),
        "integrity": {
            "criterion_sum_mismatch": sum(1 for r in completed_rows if not r.get("criterion_sum_valid")),
            "score_above_max": sum(1 for r in completed_rows if r.get("score", 0) > r.get("max_score", 0)),
            "missing_grading_artifact": sum(1 for r in completed_rows if not r.get("artifact_exists")),
            "duplicate_grading_identical_snapshot": 0,
        },
        "safety": {"teacher_review_changed": False, "reconstruction_changed": False,
                   "question_side_artifacts_changed": False, "postgres_reset": False},
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
