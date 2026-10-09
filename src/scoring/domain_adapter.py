"""Boundary between domain snapshots and the legacy filesystem grading job."""
from .db.models import GradingJob, GradingJobItem
from uuid import uuid4

class DomainGradingJobAdapter:
    def __init__(self, session, *, artifact_root=None): self.session = session; self.artifact_root = artifact_root
    def create_legacy_job(self, test, rubric, questions, policy, submissions, *, model_answers=(), assignment_path, run_path, config_path, execution_mode="phased_auto"):
        from .grading_inputs import prepare_inputs
        from .grading_mapping import prepare_submission_bundles
        bundles = prepare_submission_bundles(self.session, test.id, submissions, assignment_path,
                                             root=self.artifact_root) if submissions else []
        inputs = prepare_inputs(self.session, test.id, questions, model_answers, rubric,
                                assignment_path, run_path, root=self.artifact_root)
        manifest = {"test_id": test.id, "rubric_version_id": rubric.id, "rubric_version": rubric.version,
                    "confirmed_authoring_revision_id": (submissions[0].confirmed_authoring_revision_id
                        if submissions and len({s.confirmed_authoring_revision_id for s in submissions}) == 1 else None),
                    "model_answer_versions": [{"id": a.id, "version": a.version} for a in model_answers],
                    "grading_policy": {"id": policy.id, "version": policy.version},
                    "question_ids": [q.id for q in questions if q.is_gradable], "submission_ids": [s.id for s in submissions],
                    "effective_contexts": [v["context"] for v in inputs.values()],
                    "grading_input_bundle_hashes": [v["bundle_sha256"] for v in bundles]}
        pinned = {s.confirmed_authoring_revision_id for s in submissions}
        if len(pinned) > 1:
            raise ValueError("MIXED_CONFIRMED_AUTHORING_REVISIONS")
        confirmed_revision_id = next(iter(pinned)) if pinned else None
        job = GradingJob(external_id=str(uuid4()), execution_mode=execution_mode,
                         assignment_path=assignment_path, run_path=run_path, config_path=config_path,
                         total_items=len(submissions), test_id=test.id, rubric_version_id=rubric.id,
                         confirmed_authoring_revision_id=confirmed_revision_id,
                         metadata_json={"grading_input_manifest": manifest, "domain_inputs": inputs, "grading_input_bundles": bundles})
        self.session.add(job); self.session.flush()
        for sub in submissions: self.session.add(GradingJobItem(job_id=job.id, item_key=sub.submission_key))
        return job, manifest
