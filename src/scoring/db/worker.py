from datetime import datetime, timezone
from ..adapters import StageRequest, RunArtifactAdapter
from ..orchestration.execution import build_orchestrator
from .models import DomainEvent
from .repository import JobRepository


class JobWorker:
    """Single-worker execution loop. It never imports or controls RuntimeManager."""

    def __init__(self, session_factory, *, orchestrator_factory=build_orchestrator, grading_runner_factory=None):
        self.session_factory = session_factory
        self.orchestrator_factory = orchestrator_factory
        self.grading_runner_factory = grading_runner_factory

    def run_once(self, job_id):
        with self.session_factory() as session:
            repo = JobRepository(session)
            # A process restart can leave a claimed job in a non-terminal
            # state. Requeue stale work before claiming the requested job; the
            # sealed snapshot and all prior events remain untouched.
            repo.recover_stale_jobs()
            session.commit()
            job = repo.get_job(job_id)
            if job is None or not repo.claim(job_id):
                session.rollback()
                return None
            session.commit()
            try:
                session.refresh(job)
                repo.transition(job, "preparing")
                session.commit()
                request = StageRequest(
                    job.assignment_path, job.run_path, job.config_path, runtime_endpoints=None,
                    domain_inputs=(job.metadata_json or {}).get("domain_inputs")
                )
                selected_answer = bool((job.metadata_json or {}).get("grading_execution"))
                regrade_request_id = (job.metadata_json or {}).get("regrade_request_id")
                if selected_answer:
                    from ..grading_execution import GradingExecutionRunner
                    orchestrator = (self.grading_runner_factory or GradingExecutionRunner)()
                else:
                    orchestrator = self.orchestrator_factory(job.execution_mode)
                if hasattr(orchestrator, "pause_check"):

                    def pause_requested():
                        with self.session_factory() as probe:
                            current = JobRepository(probe).get_job(job.id)
                            return bool(
                                current and (current.metadata_json or {}).get("pause_requested")
                            )

                    orchestrator.pause_check = pause_requested
                outcome = orchestrator.run(job if selected_answer else request)
                session.flush()
                session.refresh(job)
                states = getattr(outcome, "states", ["preparing", "completed"])
                item_errors = getattr(outcome, "item_errors", [])
                runtime_error = getattr(outcome, "runtime_error", None)
                final_state = getattr(outcome, "state", "completed")
                for state in states[1:]:
                    repo.transition(job, state)
                runtime_client = getattr(orchestrator, "runtime_client", None)
                runtime_ids = getattr(orchestrator, "runtime_ids", {})
                if runtime_client is not None:
                    for phase, runtime_id in runtime_ids.items():
                        try:
                            snapshot = getattr(orchestrator, "runtime_snapshots", {}).get(phase)
                            if not snapshot:
                                snapshot = runtime_client.status(runtime_id)
                            repo.add_snapshot(job.id, phase, snapshot)
                        except Exception as exc:
                            repo.append_event(
                                job.id, "runtime_snapshot_error", phase=phase, message=str(exc)
                            )
                job.item_error_count = len(item_errors)
                job.state = final_state
                job.error_type = "runtime" if runtime_error else None
                job.error_message = runtime_error
                job.completed_at = (
                    datetime.now(timezone.utc)
                    if final_state in {"completed", "item_errors"}
                    else None
                )
                job.updated_at = datetime.now(timezone.utc)
                repo.append_event(
                    job.id,
                    "job_completed"
                    if final_state == "completed"
                    else ("job_paused" if final_state == "paused" else "job_finished"),
                    new_state=final_state,
                    payload=(
                        outcome.as_dict()
                        if hasattr(outcome, "as_dict")
                        else {
                            "state": final_state,
                            "states": states,
                            "item_errors": item_errors,
                            "runtime_error": runtime_error,
                        }
                    ),
                )
                if regrade_request_id:
                    session.add(DomainEvent(
                        entity_type="regrade_request", entity_id=regrade_request_id,
                        event_type=("regrade_completed" if final_state == "completed"
                                    else "regrade_failed"),
                        payload={"request_id": regrade_request_id, "job_id": job.id,
                                 "status": "COMPLETED" if final_state == "completed" else "FAILED",
                                 "state": final_state},
                    ))
                artifact = RunArtifactAdapter(job.run_path)
                for item in job.items:
                    repo.sync_item_from_artifacts(item, artifact)
                job.completed_items = sum(item.state == "completed" for item in job.items)
                job.review_required_count = sum(item.needs_review for item in job.items)
                job.total_items = max(job.total_items, len(job.items))
                session.commit()
                return outcome
            except Exception as exc:
                session.rollback()
                job = repo.get_job(job_id)
                job.state = "failed"
                if "orchestrator" in locals() and selected_answer:
                    for phase, snapshot in orchestrator.runtime_snapshots.items():
                        repo.add_snapshot(job.id, phase, snapshot)
                    for item in job.items:
                        item.state = "item_error"
                        item.error_type = type(exc).__name__
                        item.error_message = str(exc)
                job.error_type = type(exc).__name__
                job.error_message = str(exc)
                repo.append_event(job.id, "job_failed", new_state="failed", message=str(exc))
                regrade_request_id = (job.metadata_json or {}).get("regrade_request_id")
                if regrade_request_id:
                    session.add(DomainEvent(
                        entity_type="regrade_request", entity_id=regrade_request_id,
                        event_type="regrade_failed",
                        payload={"request_id": regrade_request_id, "job_id": job.id,
                                 "status": "FAILED", "error_type": type(exc).__name__,
                                 "message": str(exc)},
                    ))
                session.commit()
                raise
