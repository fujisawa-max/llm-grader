import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from scoring.db import create_session_factory, init_database, JobRepository
from scoring.db.worker import JobWorker
from scoring.db.models import DomainEvent


class DbTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.factory = create_session_factory("sqlite:///:memory:")
        init_database(self.engine)

    def test_job_items_events_snapshot_and_atomic_claim(self):
        with self.factory() as s:
            r = JobRepository(s)
            j = r.create_job(
                external_id="j1",
                execution_mode="resident_serial",
                assignment_path="a",
                run_path="r",
                config_path="c",
            )
            r.add_item(j.id, item_key="s00")
            r.append_event(j.id, "job_created")
            s.commit()
            self.assertTrue(r.claim(j.id))
            s.commit()
            self.assertFalse(r.claim(j.id))
            s.rollback()
            r.add_snapshot(
                j.id,
                "ricoh",
                {
                    "runtime_id": "r",
                    "state": "ready",
                    "profile": {
                        "runtime_id": "r",
                        "runtime_type": "managed",
                        "generation": {"seed": 42},
                    },
                },
            )
            s.commit()
            self.assertEqual(len(r.get_job(j.id).events), 1)

    def test_artifact_sync_and_worker_claim(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "submissions/s00/questions/q1").mkdir(parents=True)
            (run / "submissions/s00/questions/q1/grading.json").write_text("{}")
            with self.factory() as s:
                r = JobRepository(s)
                j = r.create_job(
                    external_id="j2",
                    execution_mode="resident_serial",
                    assignment_path="a",
                    run_path=str(run),
                    config_path="c",
                )
                i = r.add_item(j.id, item_key="s00")
                s.commit()
                r.sync_item_from_artifacts(
                    i,
                    __import__(
                        "scoring.adapters", fromlist=["RunArtifactAdapter"]
                    ).RunArtifactAdapter(run),
                )
                s.commit()
                self.assertEqual(i.state, "completed")

    def test_worker_claims_and_persists_orchestration_result(self):
        class Outcome:
            state = "completed"
            states = ["preparing", "completed"]
            item_errors = []
            runtime_error = None

            def as_dict(self):
                return {"state": self.state, "states": self.states}

        def build(mode):
            class FakeOrchestrator:
                def run(self, request):
                    return Outcome()

            return FakeOrchestrator()

        with tempfile.TemporaryDirectory() as d, self.factory() as s:
            r = JobRepository(s)
            j = r.create_job(
                external_id="j3",
                execution_mode="resident_serial",
                assignment_path="a",
                run_path=d,
                config_path="c",
            )
            s.commit()
            job_id = j.id
        worker = JobWorker(self.factory, orchestrator_factory=build)
        result = worker.run_once(job_id)
        self.assertEqual(result.state, "completed")
        with self.factory() as s:
            self.assertEqual(
                s.get(
                    __import__("scoring.db.models", fromlist=["GradingJob"]).GradingJob, job_id
                ).state,
                "completed",
            )

    def test_regrade_worker_emits_completion_event(self):
        class Outcome:
            state = "completed"
            states = ["preparing", "completed"]
            item_errors = []
            runtime_error = None

            def as_dict(self):
                return {"state": self.state, "states": self.states}

        def build(mode):
            class FakeOrchestrator:
                def run(self, request):
                    return Outcome()

            return FakeOrchestrator()

        request_id = str(uuid4())
        with tempfile.TemporaryDirectory() as d, self.factory() as s:
            r = JobRepository(s)
            j = r.create_job(external_id="j-regrade", execution_mode="resident_serial",
                            assignment_path="a", run_path=d, config_path="c",
                            metadata_json={"regrade_request_id": request_id})
            s.commit()
            job_id = j.id
        JobWorker(self.factory, orchestrator_factory=build).run_once(job_id)
        with self.factory() as s:
            event = s.scalar(select(DomainEvent).where(
                DomainEvent.entity_id == request_id, DomainEvent.event_type == "regrade_completed"))
            self.assertIsNotNone(event)


if __name__ == "__main__":
    unittest.main()
