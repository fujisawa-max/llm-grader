"""Isolated, deterministic grading harness for local revision acceptance tests.

This module is test support, not an API or a production worker. Every operation
requires a file-backed SQLite database, config, and run directory under one
caller-supplied disposable root. Synthetic jobs are executed only by a worker
bound to that separate database and an explicit Test allowlist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from scoring.db.models import GradingJob, GradingJobEvent, StudentSubmission, Test
from scoring.db.worker import JobWorker
from scoring.grading_execution import (
    build_revision_execution_snapshot,
    persist_execution_result,
    verify_existing_execution_result,
    verify_sealed_revision_execution_job,
)
from scoring.orchestration.phased_auto import PhaseExecutionResult
from scoring.core import write_json
from scoring.revision_grading import assemble_revision_execution_package


def _inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    value = path.resolve()
    if not value.is_relative_to(root):
        raise ValueError("SYNTHETIC_VALIDATION_PATH_OUTSIDE_DISPOSABLE_ROOT")
    return value


def _require_disposable_sqlite(session_or_factory, root: Path, expected_database_path: Path) -> None:
    factory = session_or_factory
    if hasattr(factory, "get_bind"):
        engine = factory.get_bind()
    else:
        engine = getattr(factory, "kw", {}).get("bind")
    if engine is None or engine.dialect.name != "sqlite":
        raise ValueError("SYNTHETIC_VALIDATION_REQUIRES_DISPOSABLE_SQLITE")
    database = engine.url.database
    if not database or database == ":memory:":
        raise ValueError("SYNTHETIC_VALIDATION_REQUIRES_FILE_BACKED_SQLITE")
    actual = _inside(root, Path(database))
    expected = _inside(root, Path(expected_database_path))
    if actual != expected:
        raise ValueError("SYNTHETIC_VALIDATION_DATABASE_IDENTITY_MISMATCH")


def create_synthetic_validation_job(
    session,
    *,
    disposable_root: Path,
    validation_database_path: Path,
    allowlisted_test_id: str,
    test_id: str,
    submission_id: str,
    question_id: str,
    synthetic_answer_text: str,
    job_name: str,
    question_root: Path | None = None,
    answer_root: Path | None = None,
    visual_capability: dict | None = None,
):
    """Create a pending standard Web Job from the J1a in-memory package path."""
    root = Path(disposable_root).resolve()
    _require_disposable_sqlite(session, root, validation_database_path)
    if not allowlisted_test_id or test_id != allowlisted_test_id:
        raise PermissionError("SYNTHETIC_VALIDATION_TEST_NOT_ALLOWLISTED")
    test = session.get(Test, test_id)
    submission = session.scalar(select(StudentSubmission).where(
        StudentSubmission.id == submission_id).with_for_update().execution_options(populate_existing=True))
    if test is None or submission is None or submission.test_id != test_id:
        raise ValueError("SUBMISSION_NOT_FOUND")

    config_path = _inside(root, root / f"synthetic-{job_name}.json")
    config_path.write_text(json.dumps({"models": {"grader": {
        "model_id": "synthetic-validation-no-runtime",
        "base_url": "http://127.0.0.1:9/v1",
    }}}), encoding="utf-8")
    run_path = _inside(root, root / f"synthetic-run-{job_name}")
    package = assemble_revision_execution_package(
        session, test_id, submission_id, question_id,
        synthetic_answer_text=synthetic_answer_text,
        question_root=_inside(root, question_root) if question_root else None,
        answer_root=_inside(root, answer_root) if answer_root else None,
        allowed_roots=[root],
        visual_capability=visual_capability,
        submission=submission,
    )
    if not package.get("synthetic_input"):
        raise ValueError("SYNTHETIC_VALIDATION_INPUT_NOT_MARKED")
    snapshot = build_revision_execution_snapshot(package, config_path=config_path,
                                                 visual_capability=visual_capability)

    # This is the ordinary revision-bound Job and JobItem shape. The extra
    # marker is audit metadata only; worker isolation comes from the checked,
    # separate disposable database and explicit Test allowlist above.
    from scoring.grading_execution import _insert_revision_execution_job

    job = _insert_revision_execution_job(
        session, test_id, submission, question_id, package, snapshot,
        run_path=run_path, config_path=config_path,
    )
    job.metadata_json = {
        **job.metadata_json,
        "synthetic_validation": {
            "schema_version": "isolated-synthetic-grading.v1",
            "test_id": test_id,
            "submission_id": submission_id,
            "question_id": question_id,
            "synthetic_answer_sha256": hashlib.sha256(
                synthetic_answer_text.encode("utf-8")).hexdigest(),
            "purpose": "local acceptance only; never publish",
        },
    }
    session.add(GradingJobEvent(job_id=job.id, event_type="job_created",
                                new_state="queued", payload={"synthetic_validation": True}))
    session.flush()
    return job, package


def _synthetic_score(levels: list[dict]) -> int:
    scores = sorted(level["score"] for level in levels)
    if len(scores) < 2:
        raise ValueError("SYNTHETIC_VALIDATION_RUBRIC_LEVELS_INVALID")
    positive = [score for score in scores if score > 0]
    if not positive:
        raise ValueError("SYNTHETIC_VALIDATION_RUBRIC_LEVELS_INVALID")
    # Two-level policies get the full score (A: 10); policies with an explicit
    # partial level get the lowest positive score (B: 5). No level is invented.
    return max(positive) if len(scores) == 2 else min(positive)


class SyntheticValidationGradingRunner:
    """Deterministic response producer; all policy checks/artifact writes are shared."""

    def run(self, job):
        snapshot, bundle, _rubric, folder, _images = verify_sealed_revision_execution_job(job)
        folder.mkdir(parents=True, exist_ok=True)
        if verify_existing_execution_result(job, snapshot, bundle, folder):
            return PhaseExecutionResult(state="completed", states=["preparing", "completed"])
        write_json(folder / "input.json", snapshot)
        answer = bundle["student_answer"]["answer_text"]
        page_ids = bundle["student_answer"]["page_ids"]
        if not page_ids:
            raise ValueError("SYNTHETIC_VALIDATION_PAGE_EVIDENCE_REQUIRED")
        criteria = []
        for criterion in bundle["rubric"]["entry"]["criteria"]:
            level = _synthetic_score(criterion.get("levels", []))
            criteria.append({
                "criterion_id": criterion["id"],
                "score": level,
                "max_score": max(row["score"] for row in criterion["levels"]),
                "evidence": [{"page_id": page_ids[0],
                              "quote": f"SYNTHETIC VALIDATION ONLY: {answer[:200]}"}],
                "reason": "合成検証結果です。実採点ではなく、確定版の得点段階を検証しています。",
            })
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "question_id": bundle["identity"]["question_id"],
            "criteria": criteria,
            "needs_review": False,
            "review_reasons": [],
        }, ensure_ascii=False)}}]}
        persist_execution_result(job, snapshot, bundle, folder, raw,
                                  raw_filename="grading.synthetic.raw.json")
        return PhaseExecutionResult(state="completed",
                                    states=["preparing", "grading_running", "completed"])


class IsolatedSyntheticValidationWorker:
    """Allowlisted test worker whose DB cannot see ordinary production Jobs."""

    def __init__(self, session_factory, *, disposable_root: Path,
                 validation_database_path: Path, allowed_test_ids: set[str]):
        _require_disposable_sqlite(session_factory, Path(disposable_root), validation_database_path)
        if not allowed_test_ids:
            raise ValueError("SYNTHETIC_VALIDATION_TEST_ALLOWLIST_REQUIRED")
        self.session_factory = session_factory
        self.disposable_root = Path(disposable_root).resolve()
        self.validation_database_path = Path(validation_database_path).resolve()
        self.allowed_test_ids = frozenset(allowed_test_ids)

    def _is_allowlisted_synthetic_job(self, job):
        marker = (job.metadata_json or {}).get("synthetic_validation") or {}
        snapshot = (job.metadata_json or {}).get("grading_execution") or {}
        bundle = snapshot.get("bundle") or {}
        items = job.items or []
        answer = bundle.get("student_answer") or {}
        return bool(
            job.test_id in self.allowed_test_ids
            and marker.get("schema_version") == "isolated-synthetic-grading.v1"
            and marker.get("test_id") == job.test_id
            and len(items) == 1
            and marker.get("submission_id") == (items[0].metadata_json or {}).get("submission_id")
            and marker.get("question_id") == (items[0].metadata_json or {}).get("question_id")
            and job.execution_mode == "phased_auto"
            and job.confirmed_authoring_revision_id
            and snapshot.get("confirmed_authoring_revision_id") == job.confirmed_authoring_revision_id
            and bundle.get("identity", {}).get("confirmed_authoring_revision_id")
            == job.confirmed_authoring_revision_id
            and answer.get("source") == "RECONSTRUCTED_FROM_DOCUMENT"
            and answer.get("reconstruction_id") == "synthetic-preview"
            and hashlib.sha256(str(answer.get("answer_text", "")).encode("utf-8")).hexdigest()
            == marker.get("synthetic_answer_sha256")
        )

    def run_once(self, job_id: str):
        _require_disposable_sqlite(
            self.session_factory, self.disposable_root, self.validation_database_path)
        with self.session_factory() as session:
            job = session.get(GradingJob, job_id)
            if job is None or not self._is_allowlisted_synthetic_job(job):
                return None
            _inside(self.disposable_root, Path(job.run_path))
            _inside(self.disposable_root, Path(job.config_path))
            # JobWorker's crash recovery intentionally scans its whole database.
            # Refuse to invoke it unless every row in this physical DB is also
            # an allowlisted validation job, so recovery cannot touch normal work.
            all_jobs = session.scalars(select(GradingJob)).all()
            if any(not self._is_allowlisted_synthetic_job(row) for row in all_jobs):
                raise ValueError("SYNTHETIC_VALIDATION_DATABASE_CONTAINS_NORMAL_JOB")
        worker = JobWorker(self.session_factory,
            grading_runner_factory=SyntheticValidationGradingRunner)
        return worker.run_once(job_id)
