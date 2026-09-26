"""Append-only persistence for explicit teacher grading adjudications."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from .db import models as m
from .grading_execution import snapshot_hash
from .pdf_native import canonical_hash, sha256_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_once(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("TEACHER_GRADING_ARTIFACT_CONFLICT")
    else:
        path.write_text(encoded, encoding="utf-8")
    return sha256_file(path)


def _criterion_definitions(bundle: dict) -> dict[str, dict]:
    entry = bundle.get("rubric", {}).get("entry", {})
    criteria = entry.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("TEACHER_GRADING_RUBRIC_MISSING")
    result = {}
    for criterion in criteria:
        criterion_id = criterion.get("id")
        if not criterion_id or criterion_id in result:
            raise ValueError("TEACHER_GRADING_CRITERION_ID_INVALID")
        levels = criterion.get("levels")
        if not isinstance(levels, list) or not levels:
            raise ValueError("TEACHER_GRADING_LEVELS_MISSING")
        result[criterion_id] = criterion
    return result


def _validate_decision(*, session, job, snapshot: dict, criterion_scores: list[dict],
                       score: int, max_score: int, rubric_version_id: str,
                       test_id: str, submission_id: str, question_id: str) -> dict:
    bundle = snapshot.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("TEACHER_GRADING_SNAPSHOT_MISSING")
    if snapshot_hash(snapshot) != snapshot.get("snapshot_sha256"):
        raise ValueError("TEACHER_GRADING_SNAPSHOT_HASH_MISMATCH")
    identity = bundle.get("identity", {})
    student = bundle.get("student_answer", {})
    if (identity.get("test_id"), identity.get("question_id")) != (test_id, question_id):
        raise ValueError("TEACHER_GRADING_SNAPSHOT_IDENTITY_MISMATCH")
    if student.get("submission_id") != submission_id:
        raise ValueError("TEACHER_GRADING_SNAPSHOT_SUBMISSION_MISMATCH")
    if job.test_id != test_id or (
        job.rubric_version_id is not None and job.rubric_version_id != rubric_version_id
    ):
        raise ValueError("TEACHER_GRADING_JOB_IDENTITY_MISMATCH")
    rubric = session.get(m.RubricVersion, rubric_version_id)
    if rubric is None or rubric.status != "approved":
        raise ValueError("TEACHER_GRADING_RUBRIC_NOT_APPROVED")
    entry = bundle.get("rubric", {}).get("entry", {})
    if entry.get("question_id") != question_id or int(entry.get("max_points", -1)) != max_score:
        raise ValueError("TEACHER_GRADING_MAX_POINTS_MISMATCH")
    if int(score) < 0 or int(score) > int(max_score):
        raise ValueError("TEACHER_GRADING_SCORE_OUT_OF_RANGE")
    definitions = _criterion_definitions(bundle)
    seen = set()
    normalized = []
    for item in criterion_scores:
        criterion_id = item.get("criterion_id")
        value = item.get("score")
        if criterion_id not in definitions or criterion_id in seen:
            raise ValueError("TEACHER_GRADING_CRITERION_INVALID")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("TEACHER_GRADING_SCORE_INVALID")
        allowed = {int(level.get("score")) for level in definitions[criterion_id]["levels"]}
        if value not in allowed:
            raise ValueError("TEACHER_GRADING_SCORE_NOT_ALLOWED")
        normalized.append({"criterion_id": criterion_id, "score": value,
                           "max_score": int(definitions[criterion_id]["points"])})
        seen.add(criterion_id)
    if seen != set(definitions):
        raise ValueError("TEACHER_GRADING_CRITERION_SET_MISMATCH")
    if sum(x["score"] for x in normalized) != int(score):
        raise ValueError("TEACHER_GRADING_CRITERION_SUM_MISMATCH")
    return {
        "bundle_sha256": bundle.get("bundle_sha256"),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "student_answer_sha256": student.get("sha256"),
        "rubric_entry_sha256": bundle.get("rubric", {}).get("entry_sha256"),
        "criteria": normalized,
    }


def create_teacher_grading_decision(
    session,
    *,
    artifact_root: str | Path,
    source_grading_job_id: str,
    test_id: str,
    submission_id: str,
    question_id: str,
    rubric_version_id: str,
    score: int,
    max_score: int,
    criterion_scores: list[dict],
    teacher_reason: str,
    teacher_note: str | None = None,
    teacher_user_id: str | None = None,
    previous_job_ids: list[str] | None = None,
) -> tuple[m.TeacherGradingDecision, bool]:
    """Persist one explicit decision without mutating any grading job.

    Repeating the exact decision returns the existing row. A different decision
    creates a new append-only version for the same submission/question.
    """
    if not teacher_reason.strip():
        raise ValueError("TEACHER_GRADING_REASON_REQUIRED")
    job = session.get(m.GradingJob, source_grading_job_id)
    if job is None:
        raise ValueError("TEACHER_GRADING_SOURCE_JOB_NOT_FOUND")
    snapshot = deepcopy((job.metadata_json or {}).get("grading_execution"))
    if snapshot is None:
        raise ValueError("TEACHER_GRADING_SNAPSHOT_MISSING")
    checked = _validate_decision(
        session=session, job=job, snapshot=snapshot, criterion_scores=criterion_scores,
        score=score, max_score=max_score, rubric_version_id=rubric_version_id,
        test_id=test_id, submission_id=submission_id, question_id=question_id,
    )
    semantic = {
        "schema_version": "h4i-teacher-grading-decision.v1",
        "test_id": test_id, "submission_id": submission_id, "question_id": question_id,
        "source_grading_job_id": source_grading_job_id,
        "previous_job_ids": list(previous_job_ids or []),
        "rubric_version_id": rubric_version_id,
        "score": int(score), "max_score": int(max_score),
        "criterion_scores": checked["criteria"], "teacher_reason": teacher_reason,
        "teacher_note": teacher_note or "",
        "teacher_user_id": teacher_user_id,
        "input_snapshot_sha256": checked["snapshot_sha256"],
        "bundle_sha256": checked["bundle_sha256"],
        "student_answer_sha256": checked["student_answer_sha256"],
        "rubric_entry_sha256": checked["rubric_entry_sha256"],
    }
    fingerprint = canonical_hash(semantic)
    legacy_semantic = dict(semantic)
    legacy_semantic.pop("teacher_note", None)
    legacy_fingerprint = canonical_hash(legacy_semantic)
    existing_rows = list(session.scalars(select(m.TeacherGradingDecision).where(
        m.TeacherGradingDecision.submission_id == submission_id,
        m.TeacherGradingDecision.question_id == question_id,
    ).order_by(m.TeacherGradingDecision.decision_version)).all())
    for existing in existing_rows:
        if (existing.provenance or {}).get("decision_fingerprint") in {fingerprint, legacy_fingerprint}:
            artifact = (Path(artifact_root).resolve() / existing.artifact_ref).resolve()
            if not artifact.is_file() or sha256_file(artifact) != existing.artifact_sha256:
                raise ValueError("TEACHER_GRADING_ARTIFACT_MISSING_OR_TAMPERED")
            return existing, False
    version = (existing_rows[-1].decision_version if existing_rows else 0) + 1
    decision_id = str(uuid4())
    payload = {
        **semantic,
        "decision_id": decision_id,
        "decision_version": version,
        "status": "COMPLETE",
        "created_at": _now(),
        "previous_decision_ids": [row.id for row in existing_rows],
        "source_snapshot": {
            "job_id": source_grading_job_id,
            "snapshot_sha256": checked["snapshot_sha256"],
            "bundle_sha256": checked["bundle_sha256"],
        },
    }
    payload["decision_fingerprint"] = fingerprint
    relative = Path("h4i-teacher-adjudication") / test_id / question_id / f"{decision_id}.json"
    path = Path(artifact_root).resolve() / relative
    artifact_sha = _write_once(path, payload)
    row = m.TeacherGradingDecision(
        id=decision_id, test_id=test_id, submission_id=submission_id,
        question_id=question_id, source_grading_job_id=source_grading_job_id,
        rubric_version_id=rubric_version_id, decision_version=version,
        status="COMPLETE", score=int(score), max_score=int(max_score),
        criterion_scores=checked["criteria"], teacher_reason=teacher_reason,
        input_snapshot_sha256=checked["snapshot_sha256"],
        bundle_sha256=checked["bundle_sha256"], artifact_ref=str(relative),
        artifact_sha256=artifact_sha,
        provenance={"decision_fingerprint": fingerprint,
                    "previous_job_ids": list(previous_job_ids or []),
                    "source": "TEACHER_ADJUDICATION", "teacher_note": teacher_note or ""},
        teacher_user_id=teacher_user_id,
    )
    session.add(row)
    session.flush()
    session.add(m.DomainEvent(
        entity_type="teacher_grading_decision", entity_id=decision_id,
        event_type="teacher_grading_decision_created", actor_user_id=teacher_user_id,
        payload={"decision_id": decision_id, "decision_version": version,
                 "test_id": test_id, "submission_id": submission_id,
                 "source_grading_job_id": source_grading_job_id,
                 "question_id": question_id, "score": int(score), "max_score": int(max_score),
                 "artifact_ref": str(relative), "artifact_sha256": artifact_sha,
                 "input_snapshot_sha256": checked["snapshot_sha256"],
                 "bundle_sha256": checked["bundle_sha256"]},
    ))
    session.flush()
    return row, True
