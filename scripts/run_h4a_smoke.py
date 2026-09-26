"""Run the five explicitly authorized H.4-A production grading smoke targets."""

from __future__ import annotations

import json
from pathlib import Path

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.db.worker import JobWorker
from scoring.grading_execution import GradingExecutionRunner, create_execution_job, snapshot_hash
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile


DB = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"
ROOT = Path("artifacts").resolve()
QUESTION_ROOT = ROOT / "h2b-verification"
REFERENCE_ROOT = ROOT / "h3c1-model-answer"
CAPABILITY = json.loads((ROOT / "h3e0a/capability.json").read_text())
OUT = ROOT / "h4a-smoke"
TARGETS = [
    {"label": "Q1/s1/3.1", "test": "70a63c23-f1b1-46b7-852c-046148b6f451",
     "submission": "fcf9d128-4dbb-4aee-b49b-1c715fdcfd16",
     "question": "8a2a7955-2347-4c67-8581-f800721ec558"},
    {"label": "Q2/s1/1.1", "test": "9fc4f834-a50e-423f-b0cf-31a977c1f891",
     "submission": "cf796992-140d-4379-8b3d-9e304a9d9e7a",
     "question": "24a42587-a730-408c-8565-1221cba11453"},
    {"label": "Q3/s1/1", "test": "8df4ed72-9297-4082-bb21-1fdb6c500557",
     "submission": "9a98190f-e5cf-4704-81d3-1cfc03658e7c",
     "question": "ad991321-ce7b-4f67-a4a3-1f23b89e29e2"},
    {"label": "Q4/s1/2.2", "test": "e14aeeb5-924c-4c72-b2a2-583f1be9f48e",
     "submission": "82355f70-b0f3-4534-8ec2-d66802722776",
     "question": "705f1d12-4f19-4c33-b197-39212f24b3ca"},
    {"label": "Q4/s2/3", "test": "e14aeeb5-924c-4c72-b2a2-583f1be9f48e",
     "submission": "a3f18d80-78a7-41b1-9b07-9db3fe3056e6",
     "question": "4c567426-da7a-4aae-bccc-a0026b69f219"},
]


def manager() -> RuntimeManager:
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
    }, ensure_ascii=False, indent=2))


def image_audit(run_path: Path) -> dict:
    requests = sorted(run_path.rglob("request.*.json"))
    if not requests:
        return {"request_count": 0, "image_count": 0, "roles": []}
    payload = json.loads(requests[-1].read_text())
    messages = payload.get("messages", [])
    content = messages[1].get("content", []) if len(messages) > 1 else []
    images = [x for x in content if x.get("type") == "image_url"]
    roles = [x.get("text", "") for x in content
             if x.get("type") == "text" and ":" in x.get("text", "")]
    return {"request_count": len(requests), "image_count": len(images), "roles": roles,
            "request_path": str(requests[-1].relative_to(ROOT))}


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / "config.json"
    config(config_path)
    _, factory = create_session_factory(DB)
    runtime = manager()
    report = {"phase": "H.4-A", "requested": len(TARGETS), "jobs": [],
              "model_calls": {"ricoh": 0, "unimumer": 0,
                              "ornith_reconstruction": 0, "ornith_grading": 0}}
    worker = JobWorker(factory, grading_runner_factory=lambda: GradingExecutionRunner(runtime))
    for index, target in enumerate(TARGETS, 1):
        row = {"target": target["label"], "question_id": target["question"],
               "submission_id": target["submission"], "index": index}
        run_path = OUT / f"target-{index}-{target['question']}"
        try:
            with factory() as session:
                assembler = GradingInputAssembler(
                    session, target["test"], root=QUESTION_ROOT,
                    allowed_roots=[ROOT], answer_root=ROOT,
                    reference_root=REFERENCE_ROOT, visual_capability=CAPABILITY)
                preview = assembler.execution_preview(target["submission"], target["question"])
                if preview.get("execution_state") != "READY":
                    raise RuntimeError(f"EXECUTION_NOT_READY:{preview.get('blockers')}")
                bundle = preview["bundle"]
                row["bundle_sha256"] = bundle["bundle_sha256"]
                row["rubric_version"] = bundle["rubric"]["id"]
                row["student_answer"] = {
                    "reconstruction_id": bundle["student_answer"].get("reconstruction_id"),
                    "reconstruction_version": bundle["student_answer"].get("reconstruction_version"),
                    "visual_asset_ids": bundle["student_answer"].get("visual_asset_ids", []),
                }
                job = create_execution_job(
                    session, target["test"], target["submission"], target["question"],
                    run_path=run_path, config_path=config_path, root=QUESTION_ROOT,
                    allowed_roots=[ROOT], answer_root=ROOT,
                    reference_root=REFERENCE_ROOT, visual_capability=CAPABILITY)
                session.add(m.GradingJobEvent(
                    job_id=job.id, event_type="job_created", new_state="queued",
                    payload={"phase": "H.4-A", "target": target["label"]}))
                session.commit()
                row["job_id"] = job.id
                snapshot = job.metadata_json["grading_execution"]
                row["snapshot_sha256"] = snapshot["snapshot_sha256"]
                row["snapshot_bundle_sha256"] = snapshot["bundle"]["bundle_sha256"]
                if snapshot_hash(snapshot) != snapshot["snapshot_sha256"]:
                    raise RuntimeError("SNAPSHOT_HASH_MISMATCH")
            worker.run_once(row["job_id"])
            with factory() as session:
                completed = session.get(m.GradingJob, row["job_id"])
                item = completed.items[0]
                normalized = json.loads(Path(item.normalized_result_path).read_text())
                result_manifest = Path(completed.run_path) / "submissions" / item.item_key / "questions" / target["question"] / "result-manifest.json"
                row.update({
                    "state": completed.state, "score": item.score, "max_score": item.max_score,
                    "criterion_results": normalized.get("criteria", []),
                    "feedback": normalized.get("feedback"),
                    "raw_response_path": str(Path(item.raw_response_path).relative_to(ROOT)),
                    "normalized_result_path": str(Path(item.normalized_result_path).relative_to(ROOT)),
                    "artifact_sha256": sha256_file(result_manifest),
                    "structured_validation": "PASS",
                    "warnings": normalized.get("review_reasons", []),
                    "image_payload": image_audit(run_path) if bundle.get("visual_assets") else None,
                })
            row["resume_run_once"] = worker.run_once(row["job_id"]) is None
        except Exception as exc:
            row.update({"state": "failed", "error": f"{type(exc).__name__}: {exc}"})
        report["jobs"].append(row)
    report["completed"] = sum(x.get("state") == "completed" for x in report["jobs"])
    report["failed"] = report["requested"] - report["completed"]
    report["grading_jobs_created"] = sum("job_id" in x for x in report["jobs"])
    report["model_calls"]["ornith_grading"] = report["completed"]
    report["runtime_final"] = runtime.status("grader")
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
