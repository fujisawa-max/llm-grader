"""Resolve the three H.4-G targets with append-only teacher corrections."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.db.worker import JobWorker
from scoring.grading_execution import GradingExecutionRunner, create_execution_job
from scoring.grading_mapping import GradingInputAssembler
from scoring.pdf_native import sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile
from scoring.reconstruction_artifacts import create_teacher_revision


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
DB = "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"
QUESTION_ROOT = ARTIFACT_ROOT / "h2b-verification"
REFERENCE_ROOT = ARTIFACT_ROOT / "h3c1-model-answer"
CAPABILITY = json.loads((ARTIFACT_ROOT / "h3e0a/capability.json").read_text())
OUT = ARTIFACT_ROOT / "h4g-resolution"

Q2 = {
    "label": "Q2/s2/q3",
    "test": "9fc4f834-a50e-423f-b0cf-31a977c1f891",
    "submission": "58b55168-2750-45b1-8cc4-91ebc86da5dd",
    "question": "8c8c578c-1635-4f13-91e8-4b40dbe3e258",
    "old_job": "12220e0b-e58c-401d-bbda-2ddb51c7e82f",
}
Q3 = {
    "label": "Q3/s1/q3",
    "test": "8df4ed72-9297-4082-bb21-1fdb6c500557",
    "submission": "9a98190f-e5cf-4704-81d3-1cfc03658e7c",
    "question": "7fcbd8ee-1eee-4d93-a195-59ea995a0385",
    "answer": "y = 3 cos(x + π/2)",
    "bbox": [0.5562172074283237, 0.7316886371924349,
             0.7288213011620541, 1.0],
}
Q4 = {
    "label": "Q4/s1/q1",
    "test": "e14aeeb5-924c-4c72-b2a2-583f1be9f48e",
    "submission": "82355f70-b0f3-4534-8ec2-d66802722776",
    "question": "ab3e65c7-7dca-4254-a4d9-757ebf675f28",
    "answer": "\n".join([
        r"= \begin{pmatrix}1&1\\0&2\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}"
        r" + \begin{pmatrix}1&2\\1&3\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}",
        r"= \begin{pmatrix}2&3\\1&5\end{pmatrix}\begin{pmatrix}3\\-1\end{pmatrix}",
        r"= \begin{pmatrix}6-3\\3-5\end{pmatrix}",
        r"= \begin{pmatrix}3\\-2\end{pmatrix}",
    ]),
    "bbox": [0.1799999999999999, 0.24,
             0.4211207371900911, 0.3949717102434817],
}


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


def assembler(session, test_id: str) -> GradingInputAssembler:
    return GradingInputAssembler(
        session, test_id, root=QUESTION_ROOT, allowed_roots=[ARTIFACT_ROOT],
        answer_root=ARTIFACT_ROOT, reference_root=REFERENCE_ROOT,
        visual_capability=CAPABILITY)


def create_job(session, target: dict, config_path: Path, phase: str):
    preview = assembler(session, target["test"]).execution_preview(
        target["submission"], target["question"])
    if preview.get("execution_state") != "READY" or not preview.get("bundle"):
        raise RuntimeError(f"PREVIEW_BLOCKED:{target['label']}:{preview}")
    run_path = OUT / target["label"].replace("/", "-") / "job"
    if run_path.exists() and any(run_path.iterdir()):
        raise RuntimeError(f"RUN_PATH_NOT_EMPTY:{run_path}")
    job = create_execution_job(
        session, target["test"], target["submission"], target["question"],
        run_path=run_path, config_path=config_path, root=QUESTION_ROOT,
        allowed_roots=[ARTIFACT_ROOT], answer_root=ARTIFACT_ROOT,
        reference_root=REFERENCE_ROOT, visual_capability=CAPABILITY)
    session.add(m.GradingJobEvent(
        job_id=job.id, event_type="job_created", new_state="queued",
        payload={"phase": phase, "target": target["label"]},
    ))
    session.commit()
    return job.id, preview["bundle"]


def normalized_for(session, job_id: str) -> dict | None:
    job = session.get(m.GradingJob, job_id)
    item = job.items[0]
    if not item.normalized_result_path or not Path(item.normalized_result_path).is_file():
        return None
    return json.loads(Path(item.normalized_result_path).read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / "config.json"
    write_config(config_path)
    _, factory = create_session_factory(DB)
    report: dict = {"phase": "H.4-G", "targets": {}}

    # Q2: exactly one new production regrade, with no retry on failure.
    with factory() as session:
        old = session.get(m.GradingJob, Q2["old_job"])
        if old is None or old.state != "failed":
            raise RuntimeError("Q2_OLD_FAILED_JOB_NOT_FOUND")
        existing = [j for j in session.scalars(select(m.GradingJob).where(
            m.GradingJob.test_id == Q2["test"],
            m.GradingJob.run_path.like(f"%{str(OUT / 'Q2-s2-q3')}%")
        )).all()]
        if len(existing) > 1:
            raise RuntimeError("Q2_DUPLICATE_H4G_JOB")
        if existing:
            job_id = existing[0].id
            preview = assembler(session, Q2["test"]).execution_preview(
                Q2["submission"], Q2["question"])
            bundle = preview["bundle"]
            job = existing[0]
        else:
            job_id, bundle = create_job(session, Q2, config_path, "H.4-G")
            job = session.get(m.GradingJob, job_id)
        report["targets"][Q2["label"]] = {
            "old_job": Q2["old_job"], "new_job": job_id,
            "bundle_sha": bundle["bundle_sha256"],
            "student_answer": bundle["student_answer"]["answer_text"],
            "rubric_id": bundle["rubric"]["id"],
            "model_answer_id": bundle["model_answer"]["id"],
        }
        already_failed = job.state == "failed"
    worker = JobWorker(factory, grading_runner_factory=lambda: GradingExecutionRunner(runtime()))
    if not already_failed:
        try:
            worker.run_once(report["targets"][Q2["label"]]["new_job"])
        except ValueError as exc:
            # The single permitted retry is allowed to fail at the existing
            # review gate; do not invoke the model again.
            if str(exc) != "GRADING_REVIEW_REQUIRED":
                raise
    with factory() as session:
        job = session.get(m.GradingJob, report["targets"][Q2["label"]]["new_job"])
        item = job.items[0]
        normalized = normalized_for(session, job.id)
        report["targets"][Q2["label"]].update({
            "state": job.state, "score": item.score, "max_score": item.max_score,
            "criteria": normalized.get("criteria", []) if normalized else None,
            "feedback": normalized.get("feedback") if normalized else None,
            "raw_response_path": item.raw_response_path,
            "normalized_result_path": item.normalized_result_path,
        })

    # Q3/Q4: source-faithful append-only teacher corrections, preview, regrade.
    for target in (Q3, Q4):
        with factory() as session:
            revisions = list(session.scalars(select(m.StudentAnswerReconstruction).where(
                m.StudentAnswerReconstruction.submission_id == target["submission"],
                m.StudentAnswerReconstruction.question_id == target["question"]
            ).order_by(m.StudentAnswerReconstruction.version.desc())))
            if not revisions:
                raise RuntimeError(f"NO_BASE_RECONSTRUCTION:{target['label']}")
            base = revisions[0]
            revised = create_teacher_revision(
                session, ARTIFACT_ROOT, base.id, target["answer"], action="EDIT",
                reason=f"H.4-G source-faithful Teacher transcription for {target['label']}",
                transcription_bbox=target["bbox"])
            session.add(m.DomainEvent(
                entity_type="student_answer_reconstruction", entity_id=revised.id,
                event_type="teacher_edit_revision_created",
                payload={"base_reconstruction_id": base.id,
                         "question_id": target["question"],
                         "provenance": "TEACHER_TRANSCRIPTION",
                         "reason": f"H.4-G source-faithful Teacher transcription for {target['label']}"},
            ))
            session.commit()
            preview = assembler(session, target["test"]).execution_preview(
                target["submission"], target["question"])
            if preview.get("execution_state") != "READY" or not preview.get("bundle"):
                raise RuntimeError(f"PREVIEW_BLOCKED:{target['label']}:{preview}")
            if preview["bundle"]["student_answer"]["answer_text"] != target["answer"]:
                raise RuntimeError(f"ANSWER_MISMATCH:{target['label']}")
            report["targets"][target["label"]] = {
                "base_reconstruction": base.id,
                "new_reconstruction": revised.id,
                "new_version": revised.version,
                "answer": target["answer"],
                "artifact_ref": revised.artifact_ref,
                "artifact_sha": sha256_file(ARTIFACT_ROOT / revised.artifact_ref / "reconstruction.json"),
                "bundle_sha": preview["bundle"]["bundle_sha256"],
                "preview": "PASS",
            }
            job_id, bundle = create_job(session, target, config_path, "H.4-G")
            report["targets"][target["label"]]["new_job"] = job_id
            report["targets"][target["label"]]["job_bundle_sha"] = bundle["bundle_sha256"]
    for target in (Q3, Q4):
        worker.run_once(report["targets"][target["label"]]["new_job"])
        with factory() as session:
            job = session.get(m.GradingJob, report["targets"][target["label"]]["new_job"])
            item = job.items[0]
            normalized = normalized_for(session, job.id)
            report["targets"][target["label"]].update({
                "state": job.state, "score": item.score, "max_score": item.max_score,
                "criteria": normalized.get("criteria", []) if normalized else None,
                "feedback": normalized.get("feedback") if normalized else None,
                "raw_response_path": item.raw_response_path,
                "normalized_result_path": item.normalized_result_path,
            })

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
