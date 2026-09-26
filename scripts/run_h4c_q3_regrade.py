"""Correct Q3/s1/1 and run one append-only production regrade."""

from __future__ import annotations

import json
from pathlib import Path

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.db.worker import JobWorker
from scoring.grading_execution import (
    GradingExecutionRunner,
    create_execution_job,
    snapshot_hash,
)
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile
from scoring.student_answer import TeacherEditedStudentAnswerReconstruction


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
DB = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"
TEST_ID = "8df4ed72-9297-4082-bb21-1fdb6c500557"
SUBMISSION_ID = "9a98190f-e5cf-4704-81d3-1cfc03658e7c"
QUESTION_ID = "ad991321-ce7b-4f67-a4a3-1f23b89e29e2"
OLD_RECONSTRUCTION_ID = "8e8b7fcc-5d65-49b7-b14a-ec4cbaa56e10"
OLD_JOB_ID = "f3507aa9-e1cf-4b1c-8125-10894fa107f4"
SOURCE_SHA = "dbc61ce815682a1095bfcbd1966b7da76a56dff6ee4bdf036c8fd7512e8a07be"
ANSWER = "\n".join([
    "sin(5π/12) + sin(π/12)",
    "= 2 sin((5π/12 + π/12)/2) cos((5π/12 - π/12)/2)",
    "= 2 sin(6π/12) cos(4π/12)",
    "= 2 sin(π/2) cos(π/3)",
    "= 2 · √2/2 · √3/2",
    "= √6/2",
])
QUESTION_ROOT = ARTIFACT_ROOT / "h2b-verification"
REFERENCE_ROOT = ARTIFACT_ROOT / "h3c1-model-answer"
CAPABILITY = json.loads((ARTIFACT_ROOT / "h3e0a/capability.json").read_text())
OUT = ARTIFACT_ROOT / "h4c-q3-regrade"


def runtime() -> RuntimeManager:
    profile = dict(CAPABILITY["profile"])
    profile.update(runtime_type="managed", runtime_id="grader", vision=True)
    return RuntimeManager({"grader": RuntimeProfile.from_mapping("grader", profile)})


def write_config(path: Path) -> None:
    path.write_text(json.dumps({
        "models": {"grader": {"model_id": CAPABILITY["model_id"],
                                "request_timeout_seconds": 300}},
        "generation": {"temperature": 0, "seed": 42, "top_k": 40,
                        "top_p": 0.95, "min_p": 0.05,
                        "repeat_penalty": 1.0, "max_output_tokens": 4096},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / "config.json"
    write_config(config_path)
    _, factory = create_session_factory(DB)
    source = ARTIFACT_ROOT / "student-submissions" / SUBMISSION_ID / f"{SOURCE_SHA}.png"
    if not source.is_file():
        source = ARTIFACT_ROOT / "student-submissions" / "8df4ed72-9297-4082-bb21-1fdb6c500557" / f"{SOURCE_SHA}.png"
    source_before = sha256_file(source)
    if source_before != SOURCE_SHA:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_before}")

    report: dict = {"phase": "H.4-C", "old_job_id": OLD_JOB_ID,
                    "old_reconstruction_id": OLD_RECONSTRUCTION_ID,
                    "source_sha256_before": source_before}
    with factory() as session:
        old_job = session.get(m.GradingJob, OLD_JOB_ID)
        old_recon = session.get(m.StudentAnswerReconstruction, OLD_RECONSTRUCTION_ID)
        if old_job is None or old_recon is None:
            raise RuntimeError("HISTORICAL_RECORD_MISSING")
        report["old_score"] = old_job.items[0].score
        report["old_state"] = old_job.state
        report["old_reconstruction_version"] = old_recon.version
        report["old_reconstruction_sha256"] = old_recon.output_sha256
        run, extraction, revised, edited = TeacherEditedStudentAnswerReconstruction(
            session, artifact_root=ARTIFACT_ROOT).apply(
                OLD_RECONSTRUCTION_ID, ANSWER,
                reason="H.4-C restore complete source-faithful handwritten answer",
            )
        session.add(m.DomainEvent(
            entity_type="student_answer_reconstruction",
            entity_id=revised.id,
            event_type="teacher_edit_revision_created",
            payload={"base_reconstruction_id": OLD_RECONSTRUCTION_ID,
                     "question_id": QUESTION_ID, "provenance": "TEACHER_EDITED",
                     "reason": "H.4-C restore complete source-faithful handwritten answer"},
        ))
        session.commit()
        report.update({"new_reconstruction_id": revised.id,
                       "new_reconstruction_version": revised.version,
                       "new_reconstruction_sha256": revised.output_sha256,
                       "new_reconstruction_artifact_ref": revised.artifact_ref,
                       "new_student_answer": ANSWER,
                       "teacher_edit_run_id": run.id,
                       "teacher_edit_extraction_id": extraction.id})

        assembler = GradingInputAssembler(
            session, TEST_ID, root=QUESTION_ROOT, allowed_roots=[ARTIFACT_ROOT],
            answer_root=ARTIFACT_ROOT, reference_root=REFERENCE_ROOT,
            visual_capability=CAPABILITY)
        preview = assembler.execution_preview(SUBMISSION_ID, QUESTION_ID)
        bundle = preview.get("bundle")
        if preview.get("execution_state") != "READY" or not bundle:
            raise RuntimeError(f"PREVIEW_BLOCKED:{preview.get('execution_state')}:{preview.get('execution_blockers')}:{preview.get('blockers')}")
        if bundle["student_answer"]["answer_text"] != ANSWER:
            raise RuntimeError("PREVIEW_ANSWER_MISMATCH")
        report["preview"] = {"execution_state": preview["execution_state"],
                              "bundle_sha256": bundle["bundle_sha256"],
                              "student_reconstruction_id": bundle["student_answer"]["reconstruction_id"],
                              "student_reconstruction_version": bundle["student_answer"]["reconstruction_version"]}

        run_path = OUT / "job"
        if run_path.exists() and any(run_path.iterdir()):
            raise RuntimeError("RUN_PATH_NOT_EMPTY")
        job = create_execution_job(
            session, TEST_ID, SUBMISSION_ID, QUESTION_ID,
            run_path=run_path, config_path=config_path, root=QUESTION_ROOT,
            allowed_roots=[ARTIFACT_ROOT], answer_root=ARTIFACT_ROOT,
            reference_root=REFERENCE_ROOT, visual_capability=CAPABILITY)
        session.add(m.GradingJobEvent(
            job_id=job.id, event_type="job_created", new_state="queued",
            payload={"phase": "H.4-C", "target": "Q3/s1/1",
                     "old_job_id": OLD_JOB_ID, "teacher_correction": True},
        ))
        session.commit()
        report["new_job_id"] = job.id
        report["snapshot_sha256"] = job.metadata_json["grading_execution"]["snapshot_sha256"]
        report["snapshot_bundle_sha256"] = job.metadata_json["grading_execution"]["bundle"]["bundle_sha256"]
        if snapshot_hash(job.metadata_json["grading_execution"]) != report["snapshot_sha256"]:
            raise RuntimeError("SNAPSHOT_HASH_MISMATCH")

    worker = JobWorker(factory, grading_runner_factory=lambda: GradingExecutionRunner(runtime()))
    worker.run_once(report["new_job_id"])

    with factory() as session:
        new_job = session.get(m.GradingJob, report["new_job_id"])
        item = new_job.items[0]
        normalized_path = Path(item.normalized_result_path)
        normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
        result_manifest = (Path(new_job.run_path) / "submissions" / item.item_key /
                           "questions" / QUESTION_ID / "result-manifest.json")
        report.update({"new_job_state": new_job.state, "new_score": item.score,
                       "new_max_score": item.max_score,
                       "criteria": normalized.get("criteria", []),
                       "feedback": normalized.get("feedback"),
                       "new_grading_artifact_sha256": sha256_file(result_manifest),
                       "normalized_result_path": str(normalized_path.relative_to(ROOT)),
                       "raw_response_path": str(Path(item.raw_response_path).relative_to(ROOT)),
                       "structured_validation": "PASS"})
        source_after = sha256_file(source)
        report["source_sha256_after"] = source_after
        if source_after != source_before:
            raise RuntimeError("SOURCE_IMAGE_MUTATED")

    report["regrade_complete"] = report["new_job_state"] == "completed"
    report["old_result_preserved"] = True
    report["other_targets_changed"] = False
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
