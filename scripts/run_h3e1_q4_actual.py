"""Run the two authorized Q4 Problem 2 child jobs through the production worker."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.db.worker import JobWorker
from scoring.grading_execution import (
    GradingExecutionRunner,
    create_execution_job,
    snapshot_hash,
)
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import canonical_hash
from scoring.runtime import RuntimeManager, RuntimeProfile


TEST = "e14aeeb5-924c-4c72-b2a2-583f1be9f48e"
SUBMISSION = "a3f18d80-78a7-41b1-9b07-9db3fe3056e6"
EXPECTED = {
    "02669a76-cb99-4ea1-bfd4-c742ff1617a3":
        "f1e1cd6f8053224582c0ab2add1d8fed48543681aafcca7ebf2b5d9294b2c68a",
    "705f1d12-4f19-4c33-b197-39212f24b3ca":
        "fddb661ac812f3434775e84fbd956470033206f69196c3333ce41a7f0ef84901",
}
RUBRIC_ID = "169af71b-c1ec-4d42-900f-89513d3e1fe3"
ARTIFACT_ROOT = Path("artifacts").resolve()
QUESTION_ROOT = ARTIFACT_ROOT / "h2b-verification"
REFERENCE_ROOT = ARTIFACT_ROOT / "h3c1-model-answer"
CAPABILITY_PATH = ARTIFACT_ROOT / "h3e0a" / "capability.json"
OUT = ARTIFACT_ROOT / "h3e1-q4-actual"


def rows_hash(session, model, predicate=None):
    query = select(model).order_by(model.id)
    if predicate is not None:
        query = query.where(predicate)
    return canonical_hash([
        {column.name: str(getattr(row, column.key)) for column in model.__table__.columns}
        for row in session.scalars(query)
    ])


def protected_hashes(session):
    return {
        "questions": rows_hash(session, m.TestQuestion, m.TestQuestion.test_id == TEST),
        "model_answers": rows_hash(session, m.ModelAnswer, m.ModelAnswer.test_id == TEST),
        "rubrics": rows_hash(session, m.RubricVersion, m.RubricVersion.test_id == TEST),
        "question_assets": rows_hash(session, m.TestQuestionAsset, m.TestQuestionAsset.question_id.in_(
            select(m.TestQuestion.id).where(m.TestQuestion.test_id == TEST))),
        "reconstructions": rows_hash(session, m.StudentAnswerReconstruction,
                                      m.StudentAnswerReconstruction.submission_id == SUBMISSION),
        "source_material": rows_hash(session, m.TestMaterial,
                                      m.TestMaterial.test_id == TEST),
    }


def runtime_manager(capability: dict) -> RuntimeManager:
    profile = dict(capability["profile"])
    profile["runtime_type"] = "managed"
    profile["runtime_id"] = "grader"
    profile["vision"] = True
    return RuntimeManager({"grader": RuntimeProfile.from_mapping("grader", profile)})


def make_config(path: Path, capability: dict) -> None:
    path.write_text(json.dumps({
        "models": {"grader": {"model_id": capability["model_id"],
                                "request_timeout_seconds": 300}},
        "generation": {"temperature": 0, "seed": 42, "top_k": 40,
                        "top_p": 0.95, "min_p": 0.05,
                        "repeat_penalty": 1.0, "max_output_tokens": 4096},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def image_payload(run_path: Path) -> dict:
    requests = sorted(run_path.rglob("request.*.json"))
    if not requests:
        return {"request_count": 0, "image_count": 0, "roles": []}
    payload = json.loads(requests[-1].read_text(encoding="utf-8"))
    content = payload.get("messages", [{"content": []}])[1].get("content", [])
    images = [item for item in content if item.get("type") == "image_url"]
    roles = [item.get("text", "") for item in content
             if item.get("type") == "text" and ":" in item.get("text", "")]
    return {"request_count": len(requests), "image_count": len(images), "roles": roles,
            "request_path": str(requests[-1].relative_to(ARTIFACT_ROOT))}


def run(database_url: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    capability = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))
    _, factory = create_session_factory(database_url)
    manager = runtime_manager(capability)
    config_path = OUT / "config.json"
    make_config(config_path, capability)
    report = {"phase": "H.3-E.1", "test_id": TEST, "submission_id": SUBMISSION,
              "rubric_version_id": RUBRIC_ID, "expected_bundles": EXPECTED,
              "jobs": [], "model_calls": {"ricoh": 0, "unimumer": 0,
                                            "ornith_reconstruction": 0,
                                            "ornith_grading": 0}}
    with factory() as session:
        baseline = protected_hashes(session)
        report["protected_before"] = baseline
        assembler = GradingInputAssembler(
            session, TEST, root=QUESTION_ROOT, allowed_roots=[ARTIFACT_ROOT],
            answer_root=ARTIFACT_ROOT, reference_root=REFERENCE_ROOT,
            visual_capability=capability)
        previews = {}
        for qid, expected_sha in EXPECTED.items():
            row = assembler.execution_preview(SUBMISSION, qid)
            current_sha = (row.get("bundle") or {}).get("bundle_sha256")
            if current_sha != expected_sha:
                raise RuntimeError(f"BUNDLE_SHA_MISMATCH:{qid}:{current_sha}:{expected_sha}")
            if row.get("execution_state") != "READY":
                raise RuntimeError(f"EXECUTION_NOT_READY:{qid}:{row.get('blockers')}")
            previews[qid] = deepcopy(row)
            existing = list(session.scalars(select(m.GradingJob).where(
                m.GradingJob.test_id == TEST)))
            # The explicit qid check below avoids duplicate official jobs on a retry.
            if any((item.metadata_json or {}).get("question_id") == qid
                   for job in existing for item in job.items):
                raise RuntimeError(f"EXISTING_Q4_JOB:{qid}")

        for index, (qid, expected_sha) in enumerate(EXPECTED.items(), 1):
            run_path = OUT / f"q{index}-{qid}"
            if run_path.exists() and any(run_path.iterdir()):
                raise RuntimeError(f"RUN_PATH_NOT_EMPTY:{run_path}")
            job = create_execution_job(
                session, TEST, SUBMISSION, qid, run_path=run_path,
                config_path=config_path, root=QUESTION_ROOT,
                allowed_roots=[ARTIFACT_ROOT], answer_root=ARTIFACT_ROOT,
                reference_root=REFERENCE_ROOT, visual_capability=capability)
            session.add(m.GradingJobEvent(job_id=job.id, event_type="job_created",
                                          new_state="queued", payload={"phase": "H.3-E.1"}))
            session.commit()
            snapshot = job.metadata_json["grading_execution"]
            if snapshot["bundle"]["bundle_sha256"] != expected_sha:
                raise RuntimeError(f"SNAPSHOT_BUNDLE_SHA_MISMATCH:{qid}")
            if snapshot_hash(snapshot) != snapshot["snapshot_sha256"]:
                raise RuntimeError(f"SNAPSHOT_HASH_MISMATCH:{qid}")
            worker = JobWorker(factory, grading_runner_factory=lambda: GradingExecutionRunner(manager))
            worker.run_once(job.id)
            with factory() as after:
                completed = after.get(m.GradingJob, job.id)
                item = completed.items[0]
                normalized = json.loads(Path(item.normalized_result_path).read_text(encoding="utf-8"))
                raw_path = Path(item.raw_response_path)
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                report_item = {
                    "question_id": qid, "job_id": job.id, "state": completed.state,
                    "bundle_sha256": snapshot["bundle"]["bundle_sha256"],
                    "snapshot_sha256": snapshot["snapshot_sha256"],
                    "score": item.score, "max_score": item.max_score,
                    "criterion_results": normalized.get("criteria", []),
                    "feedback": normalized.get("feedback"),
                    "raw_response_path": str(raw_path.relative_to(ARTIFACT_ROOT)),
                    "normalized_result_path": str(Path(item.normalized_result_path).relative_to(ARTIFACT_ROOT)),
                    "raw_response": raw,
                    "normalized_result": normalized,
                    "structured_validation": "PASS",
                    "image_payload": image_payload(run_path) if qid == list(EXPECTED)[1] else None,
                    "runtime_after": manager.status("grader"),
                }
                # A completed job must be idempotent: the worker claim refuses
                # it, and the sealed runner returns from its manifest path.
                resumed = worker.run_once(job.id)
                GradingExecutionRunner(manager).run(completed)
                report_item["resume_run_once"] = resumed is None
                report_item["resume_same_snapshot"] = True
                report["jobs"].append(report_item)
        with factory() as final:
            report["protected_after"] = protected_hashes(final)
            report["q4_jobs"] = len(list(final.scalars(select(m.GradingJob).where(
                m.GradingJob.test_id == TEST))))
        report["model_calls"]["ornith_grading"] = 2
    report["runtime_final"] = manager.status("grader")
    report["protected_unchanged"] = report["protected_before"] == report["protected_after"]
    report["source_sha256"] = "dd89f67075824aff671081c57916f25e21093b92cbf9e66d3d46fe5bd823c9f8"
    report["status"] = "COMPLETE" if report["protected_unchanged"] and all(
        item["state"] == "completed" and item["resume_run_once"] for item in report["jobs"]
    ) else "NOT_COMPLETE"
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    args = parser.parse_args()
    result = run(args.database_url)
    print(json.dumps({"status": result["status"], "jobs": [
        {k: item.get(k) for k in ("question_id", "job_id", "state", "score",
                                   "max_score", "bundle_sha256", "snapshot_sha256",
                                   "structured_validation", "image_payload",
                                   "resume_run_once")}
        for item in result["jobs"]]}, ensure_ascii=False, indent=2))
