"""Operator-invoked, isolated acceptance. Never connects to a source database."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from scoring.api import create_app
from scoring.auth import SESSION_COOKIE, create_session
from scoring.db.database import create_session_factory
from scoring.db import models as m
from scoring.grading_execution import GradingClient, GradingExecutionRunner, RuntimeManagerClient
from scoring.publishing import ResultPublicationService
from scoring.student_answer import SelectedImageStudentAnswerReconstruction
from scoring.validation_staging import SYNTHETIC_INPUTS, verify_staged_database
from tests.synthetic_validation import IsolatedSyntheticValidationWorker, create_synthetic_validation_job


def run_acceptance(root, policy, *, expected_manifest_sha256):
    root = Path(root)
    manifest = verify_staged_database(root, policy, expected_manifest_sha256=expected_manifest_sha256)
    if (root / "acceptance.json").exists():
        raise ValueError("STAGING_ACCEPTANCE_ALREADY_RUN")
    db = root / "validation.sqlite"
    engine, sf = create_session_factory(f"sqlite:///{db}")
    question_root, answer_root = root / "artifacts/question_import", root / "artifacts/answer_import"
    question_root.mkdir(parents=True, exist_ok=True)
    answer_root.mkdir(parents=True, exist_ok=True)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("STAGING_MODEL_OCR_OR_PUBLICATION_FORBIDDEN")

    try:
        with sf() as session:
            if session.scalar(select(func.count()).select_from(m.GradingJob)) != 0:
                raise ValueError("STAGING_ACCEPTANCE_REQUIRES_EMPTY_JOB_DATABASE")
        results = []
        with ExitStack() as stack:
            for cls, method in (
                (RuntimeManagerClient, "__init__"), (GradingClient, "__init__"),
                (GradingClient, "chat"), (GradingExecutionRunner, "__init__"),
                (SelectedImageStudentAnswerReconstruction, "run"),
                (ResultPublicationService, "publish_submission"),
                (ResultPublicationService, "publish_test"),
            ):
                stack.enter_context(patch.object(cls, method, forbidden))
            stack.enter_context(patch.dict(os.environ, {
                "LLM_GRADER_ARTIFACT_ROOT": str(answer_root), "STUDENT_PORTAL_ENABLED": "false"}))
            app = create_app(sf, allowed_roots=[root], question_import_root=question_root,
                student_portal_enabled=False,
                grading_visual_config={"answer_root": str(answer_root), "reference_root": str(question_root)})
            client = stack.enter_context(TestClient(app))
            with sf() as session:
                user = session.get(m.User, policy["teacher_id"])
                cookie = create_session(session, user)
                session.commit()
            client.cookies.set(SESSION_COOKIE, cookie)
            worker = IsolatedSyntheticValidationWorker(sf, disposable_root=root,
                validation_database_path=db, allowed_test_ids={policy["test_id"]})
            prefix = f"/api/v1/tests/{policy['test_id']}"
            for index, (submission, revision, synthetic) in enumerate(zip(
                    policy["submissions"], policy["revisions"], SYNTHETIC_INPUTS)):
                with sf() as session:
                    job, package = create_synthetic_validation_job(session, disposable_root=root,
                        validation_database_path=db, allowlisted_test_id=policy["test_id"],
                        test_id=policy["test_id"], submission_id=submission["id"],
                        question_id=policy["question_ids"][0], synthetic_answer_text=synthetic,
                        job_name=f"staged-edition-{index+1}", question_root=question_root, answer_root=answer_root)
                    job_id = job.id
                    snapshot_hash = job.metadata_json["grading_execution"]["snapshot_sha256"]
                    session.commit()
                outcome = worker.run_once(job_id)
                if outcome is None or outcome.state != "completed" or worker.run_once(job_id) is not None:
                    raise ValueError("STAGING_EXECUTION_FAILED")
                response = client.get(prefix + f"/grading/{submission['id']}")
                if response.status_code != 200:
                    raise ValueError("STAGING_REVIEW_FAILED")
                review = response.json()
                q = review["questions"][0]
                expected_score = 10 if index == 0 else 5
                if (review["submission"]["confirmed_authoring_revision_id"] != revision["id"]
                        or review["submission"]["confirmed_revision_label"] != f"第{index+1}版"
                        or q["question"]["text"] != revision["question_text"]
                        or q["model_answer"]["content"] != revision["model_answer"]
                        or [v["score"] for v in q["rubric"]["entry"]["criteria"][0]["levels"]] != revision["levels"]
                        or q["authoritative"]["score"] != expected_score
                        or q["authoritative"]["max_score"] != 10):
                    raise ValueError("STAGING_REVIEW_POLICY_MISMATCH")
                finalization = client.post(prefix + f"/grading/{submission['id']}/finalize", json={})
                repeated = client.post(prefix + f"/grading/{submission['id']}/finalize", json={})
                if (finalization.status_code != 200 or repeated.status_code != 200
                        or repeated.json()["created"] is not False
                        or finalization.json()["confirmed_authoring_revision_id"] != revision["id"]):
                    raise ValueError("STAGING_FINALIZE_FAILED")
                results.append({"submission_id": submission["id"], "revision_id": revision["id"],
                    "edition_label": f"第{index+1}版", "job_id": job_id,
                    "package_sha256": package["bundle"]["bundle_sha256"],
                    "snapshot_sha256": snapshot_hash, "score": expected_score, "maximum": 10,
                    "finalization_id": finalization.json()["finalization_id"]})
            with sf() as session:
                if (session.scalar(select(func.count()).select_from(m.StudentAnswerReconstruction)) != 0
                        or session.scalar(select(func.count()).select_from(m.DomainEvent).where(
                            m.DomainEvent.event_type == "results_published")) != 0):
                    raise ValueError("STAGING_UNEXPECTED_SIDE_EFFECT")
                for sub in policy["submissions"]:
                    if ResultPublicationService(session, root=answer_root).publication_state(
                            policy["test_id"], sub["id"])["published"]:
                        raise ValueError("STAGING_PUBLICATION_FORBIDDEN")
            verify_staged_database(root, policy, expected_manifest_sha256=expected_manifest_sha256)
            result = {"status": "ISOLATED_ACCEPTANCE_PASSED", "source_manifest_sha256": manifest["manifest_sha256"],
                      "results": results, "real_model_calls": 0, "ocr_calls": 0,
                      "production_jobs": 0, "published": False}
            with (root / "acceptance.json").open("x", encoding="utf-8") as file:
                json.dump(result, file, ensure_ascii=False, sort_keys=True)
            (root / "acceptance.json").chmod(0o600)
            return result
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        result = run_acceptance(args.root, json.loads(args.allowlist.read_text()),
            expected_manifest_sha256=args.expected_manifest_sha256)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        parser.exit(1, "STAGING_ISOLATED_ACCEPTANCE_FAILED\n")


if __name__ == "__main__":
    main()
