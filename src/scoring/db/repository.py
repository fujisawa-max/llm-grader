import json
import csv
from datetime import datetime, timezone, timedelta
from sqlalchemy import update
from .models import GradingJob, GradingJobEvent, GradingJobItem, GradingRuntimeSnapshot


def _db_timestamp(value):
    """Convert Runtime Manager monotonic timestamps to DB wall-clock values."""
    if value is None or hasattr(value, "tzinfo"):
        return value
    return datetime.now(timezone.utc)


class JobRepository:
    """Transactional repository; filesystem artifacts remain authoritative."""

    def __init__(self, session):
        self.session = session

    def create_job(self, **values):
        job = GradingJob(**values)
        self.session.add(job)
        self.session.flush()
        return job

    def add_item(self, job_id, **values):
        item = GradingJobItem(job_id=job_id, **values)
        self.session.add(item)
        self.session.flush()
        return item

    def append_event(self, job_id, event_type, **values):
        event = GradingJobEvent(job_id=job_id, event_type=event_type, **values)
        self.session.add(event)
        self.session.flush()
        return event

    def claim(self, job_id):
        """Atomically transition one queued job to preparing."""
        result = self.session.execute(
            update(GradingJob)
            .where(GradingJob.id == job_id, GradingJob.state == "queued")
            .values(state="preparing", started_at=datetime.now(timezone.utc))
        )
        self.session.flush()
        return result.rowcount == 1

    def transition(self, job, state, *, phase=None, message=None, payload=None):
        previous = job.state
        job.state = state
        if phase is not None:
            job.current_phase = phase
        job.updated_at = datetime.now(timezone.utc)
        self.append_event(
            job.id,
            "state_transition",
            phase=phase,
            previous_state=previous,
            new_state=state,
            message=message,
            payload=payload or {},
        )
        return job

    def add_snapshot(self, job_id, phase, snapshot):
        profile = snapshot.get("profile", snapshot)
        row = GradingRuntimeSnapshot(
            job_id=job_id,
            phase=phase,
            runtime_id=profile.get("runtime_id", snapshot.get("runtime_id", "")),
            runtime_type=profile.get("runtime_type", "managed"),
            model_id=profile.get("model_id"),
            model_path=profile.get("model_path"),
            model_sha256=profile.get("model_sha256"),
            ftype=profile.get("expected_ftype"),
            mmproj_path=profile.get("mmproj_path"),
            mmproj_sha256=profile.get("mmproj_sha256"),
            llama_cpp_binary=profile.get("server_binary"),
            llama_cpp_version=profile.get("llama_version"),
            endpoint=profile.get("endpoint"),
            allocated_port=snapshot.get("allocated_port"),
            pid=snapshot.get("pid"),
            runtime_command=snapshot.get("command"),
            runtime_arguments={"additional_args": profile.get("additional_args", [])},
            generation_parameters=profile.get("generation", {}),
            seed=profile.get("generation", {}).get("seed"),
            started_at=_db_timestamp(snapshot.get("started_at")),
            stopped_at=_db_timestamp(snapshot.get("stopped_at")),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def sync_item_from_artifacts(self, item, artifact):
        """Best-effort projection of completed grading artifacts into the DB."""
        root = artifact.run / "submissions" / item.item_key
        grades = list((root / "questions").glob("*/grading.json"))
        if (item.metadata_json or {}).get("bundle_sha256"):
            from ..grading_execution import validate_result
            from ..pdf_native import canonical_hash, sha256_file
            if len(grades) != 1:
                raise ValueError("GRADING_RESULT_MISSING")
            folder = grades[0].parent
            manifest = json.loads((folder / "result-manifest.json").read_text())
            snapshot = item.job.metadata_json["grading_execution"]
            if manifest["snapshot_sha256"] != snapshot["snapshot_sha256"]:
                raise ValueError("SNAPSHOT_HASH_MISMATCH")
            for name, expected in manifest["files"].items():
                path = folder / name
                if path.name != name or not path.is_file() or sha256_file(path) != expected:
                    raise ValueError("RESULT_HASH_MISMATCH")
            raw_path = folder / next(n for n in manifest["files"] if n.endswith(".raw.json"))
            result = validate_result(json.loads(raw_path.read_text()), snapshot["bundle"])
            if result != json.loads(grades[0].read_text()):
                raise ValueError("RESULT_VALIDATION_MISMATCH")
            item.state = "completed"
            item.error_type = None
            item.error_message = None
            item.score = result["score"]
            item.max_score = snapshot["bundle"]["question"]["max_points"]
            item.needs_review = result["needs_review"]
            item.reconstruction_hash = snapshot["bundle"]["student_answer"]["sha256"]
            item.grading_hash = canonical_hash(result)
            item.normalized_result_hash = manifest["files"]["grading.json"]
            item.normalized_result_path = str(grades[0])
            item.raw_response_path = str(raw_path)
            item.completed_at = item.completed_at or datetime.now(timezone.utc)
            item.metadata_json = {**(item.metadata_json or {}), "result": result,
                "snapshot_sha256": snapshot["snapshot_sha256"], "manifest": manifest,
                "manifest_sha256": canonical_hash(manifest)}
            return item
        if not grades:
            return item
        item.state = "completed"
        item.completed_at = datetime.now(timezone.utc)
        totals = artifact.run / "totals.json"
        if totals.is_file():
            scores = json.loads(totals.read_text(encoding="utf-8")).get("provisional_scores", {})
            item.score = scores.get(item.item_key)
        summary = artifact.run / "summary.csv"
        if summary.is_file():
            with summary.open(encoding="utf-8-sig", newline="") as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("submission_id") == item.item_key]
            if rows:
                item.max_score = sum(float(r.get("max_score") or 0) for r in rows)
                item.needs_review = any(r.get("status") == "needs_review" for r in rows)
        reconstructions = list((root / "questions").glob("*/reconstruction.json"))
        item.reconstruction_hash = (
            __import__("hashlib")
            .sha256(b"".join(p.read_bytes() for p in sorted(reconstructions)))
            .hexdigest()
            if reconstructions
            else None
        )
        item.grading_hash = (
            __import__("hashlib")
            .sha256(b"".join(p.read_bytes() for p in sorted(grades)))
            .hexdigest()
        )
        item.normalized_result_path = str(grades[0])
        item.normalized_result_hash = artifact.checksum(str(grades[0].relative_to(artifact.run)))
        item.metadata_json = {"artifact_root": str(root), "grading_files": [str(p) for p in grades]}
        return item

    def get_job(self, job_id):
        return self.session.get(GradingJob, job_id)

    def pause(self, job_id):
        job = self.get_job(job_id)
        if job and job.state == "queued":
            return self.transition(job, "paused", message="pause requested")
        if job and job.state not in {"completed", "failed", "cancelled", "paused"}:
            job.metadata_json = {**(job.metadata_json or {}), "pause_requested": True}
            self.append_event(job.id, "pause_requested", message="pause at next checkpoint")
        return job

    def resume(self, job_id):
        job = self.get_job(job_id)
        if job and job.state == "paused":
            job.state = "queued"
            job.metadata_json = {k: v for k, v in (job.metadata_json or {}).items()
                                 if k != "pause_requested"}
            self.append_event(job.id, "resume", previous_state="paused", new_state="queued")
        return job

    def retry(self, job_id, item_id=None):
        job = self.get_job(job_id)
        if item_id:
            item = self.session.get(GradingJobItem, item_id)
            if item and item.job_id == job_id and item.state == "item_error":
                item.state = "pending"
                item.error_type = None
                item.error_message = None
                self.append_event(job_id, "item_retry", item_id=item_id, new_state="pending")
        elif job and job.state in {"failed", "runtime_failed", "paused"}:
            previous = job.state
            job.state = "queued"
            for item in job.items:
                if item.state == "item_error":
                    item.state = "pending"
                    item.error_type = None
                    item.error_message = None
            self.append_event(job.id, "job_retry", previous_state=previous, new_state="queued")
        return job

    def recover_stale_jobs(self, *, stale_after_seconds=300, now=None):
        """Requeue jobs left mid-flight by a process restart.

        The sealed grading snapshot is untouched.  Only non-terminal state is
        moved back to the normal claim path, with an audit event explaining
        why the recovery occurred.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=stale_after_seconds)
        recovered = []
        for job in self.session.query(GradingJob).where(
                GradingJob.state.in_(["preparing", "grading_running", "running"])).all():
            updated = job.updated_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated is not None and updated > cutoff:
                continue
            previous = job.state
            job.state = "queued"
            job.updated_at = now
            for item in job.items:
                if item.state in {"pending", "item_error"}:
                    item.state = "pending"
                    item.error_type = None
                    item.error_message = None
            self.append_event(job.id, "job_recovered_after_restart",
                              previous_state=previous, new_state="queued")
            recovered.append(job)
        self.session.flush()
        return recovered
