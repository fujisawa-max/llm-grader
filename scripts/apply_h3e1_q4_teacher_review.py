"""Persist the authorized Q4 grading review as append-only events/artifacts.

The AI GradingJobItem rows and their normalized results are deliberately left
unchanged.  Teacher decisions are a separate review revision that can be
audited and superseded by a later revision.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from scoring.db.database import create_session_factory
from scoring.db.models import DomainEvent, GradingJob, GradingJobItem
from scoring.pdf_native import canonical_hash, sha256_file


TEST_ID = "e14aeeb5-924c-4c72-b2a2-583f1be9f48e"
TEACHER_ID = "99d3a635-8c60-47a4-99d8-aa11e4efe176"
Q21 = "02669a76-cb99-4ea1-bfd4-c742ff1617a3"
Q22 = "705f1d12-4f19-4c33-b197-39212f24b3ca"
RUBRIC_ID = "169af71b-c1ec-4d42-900f-89513d3e1fe3"
ROOT = Path("artifacts/h3e1-q4-actual")


def _load_item(session, qid: str):
    row = session.scalar(select(GradingJobItem).join(
        GradingJob, GradingJobItem.job_id == GradingJob.id
    ).where(GradingJob.test_id == TEST_ID,
            GradingJob.rubric_version_id == RUBRIC_ID,
            GradingJobItem.metadata_json["question_id"].as_string() == qid))
    if row is None:
        raise RuntimeError(f"GRADING_ITEM_NOT_FOUND:{qid}")
    if row.state != "completed":
        raise RuntimeError(f"GRADING_NOT_COMPLETED:{qid}:{row.state}")
    raw = json.loads(Path(row.raw_response_path).read_text(encoding="utf-8"))
    normalized = json.loads(Path(row.normalized_result_path).read_text(encoding="utf-8"))
    return row, raw, normalized


def _raw_content(raw: dict) -> dict:
    return json.loads(raw["choices"][0]["message"]["content"])


def apply(database_url: str) -> dict:
    _, factory = create_session_factory(database_url)
    ROOT.mkdir(parents=True, exist_ok=True)
    with factory() as session:
        q21_item, q21_raw, q21_normalized = _load_item(session, Q21)
        q22_item, q22_raw, q22_normalized = _load_item(session, Q22)
        q21_output = _raw_content(q21_raw)
        q22_output = _raw_content(q22_raw)
        q21_criteria = {x["criterion_id"]: x for x in q21_output["criteria"]}
        q22_criteria = {x["criterion_id"]: x for x in q22_output["criteria"]}
        if q21_criteria.get("criterion_1_factorization", {}).get("score") != 0:
            raise RuntimeError("UNEXPECTED_Q21_AI_SCORE")
        if q21_criteria.get("criterion_2_completing_square", {}).get("score") != 10:
            raise RuntimeError("UNEXPECTED_Q21_AI_SCORE")
        if q22_normalized.get("score") != 10:
            raise RuntimeError("UNEXPECTED_Q22_AI_SCORE")

        q21_input = json.loads((ROOT / "q1-02669a76-cb99-4ea1-bfd4-c742ff1617a3" /
                                "submissions" / "s2-e14aeeb5-dd89f67075824aff" /
                                "questions" / Q21 / "input.json").read_text(encoding="utf-8"))
        criteria_defs = {x["id"]: x for x in
                         q21_input["bundle"]["rubric"]["entry"]["criteria"]}
        allowed = {key: [level["score"] for level in value["levels"]]
                   for key, value in criteria_defs.items()}
        if allowed.get("criterion_1_factorization") != [10, 5, 0]:
            raise RuntimeError("FIVE_POINT_LEVEL_NOT_IN_PAYLOAD")
        q21_audit = {
            "criterion_id": "criterion_1_factorization",
            "allowed_scores_in_grading_payload": allowed["criterion_1_factorization"],
            "raw_model_score": q21_criteria["criterion_1_factorization"]["score"],
            "raw_model_reason": q21_criteria["criterion_1_factorization"]["reason"],
            "raw_model_explicitly_selected_five": False,
            "validator_result": "PASS",
            "interpretation": "The 5-point level was present and allowed; the model selected 0 based on its correctness judgment. Teacher review overrides that judgment to 5.",
        }

        revision = {
            "schema_version": "h3e1-teacher-grading-review.v1",
            "review_id": str(uuid4()),
            "teacher_user_id": TEACHER_ID,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "test_id": TEST_ID,
            "rubric_version_id": RUBRIC_ID,
            "decisions": [
                {
                    "question_id": Q21,
                    "job_id": q21_item.job_id,
                    "item_id": q21_item.id,
                    "decision": "EDIT",
                    "original_result_sha256": sha256_file(Path(q21_item.normalized_result_path)),
                    "original_score": q21_normalized["score"],
                    "teacher_score": 15,
                    "criterion_overrides": [
                        {"criterion_id": "criterion_1_factorization", "before": 0, "after": 5,
                         "max_score": 10,
                         "reason": "誤って得た二次式に対する因数分解の方法・途中過程は妥当である。"},
                        {"criterion_id": "criterion_2_completing_square", "before": 10, "after": 10,
                         "max_score": 10, "reason": "変更なし。"},
                    ],
                    "teacher_reason": "最初の式変形には誤りがあるが、誤って得た二次式を正しく因数分解しており、5点levelに該当する。",
                    "audit": q21_audit,
                },
                {
                    "question_id": Q22,
                    "job_id": q22_item.job_id,
                    "item_id": q22_item.id,
                    "decision": "ACCEPT",
                    "original_result_sha256": sha256_file(Path(q22_item.normalized_result_path)),
                    "original_score": q22_normalized["score"],
                    "teacher_score": 10,
                    "criterion_scores": [
                        {"criterion_id": key, "score": value["score"]}
                        for key, value in q22_criteria.items()
                    ],
                    "teacher_reason": "AI result 10/20を承認。",
                },
            ],
            "summary": {"problem2_1_teacher_score": 15,
                        "problem2_2_teacher_score": 10,
                        "problem2_teacher_total": 25,
                        "problem2_max_total": 40},
            "original_ai_results_unchanged": True,
        }
        revision["revision_sha256"] = canonical_hash(revision)
        artifact = ROOT / "teacher-review" / f"{revision['review_id']}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(revision, ensure_ascii=False, indent=2), encoding="utf-8")
        for decision in revision["decisions"]:
            existing = session.scalar(select(DomainEvent).where(
                DomainEvent.entity_type == "grading_job_item",
                DomainEvent.entity_id == decision["item_id"],
                DomainEvent.event_type == "teacher_grading_review_revision",
            ))
            if existing:
                if existing.payload.get("revision_sha256") != revision["revision_sha256"]:
                    raise RuntimeError("CONFLICTING_TEACHER_REVIEW_REVISION")
                continue
            session.add(DomainEvent(
                entity_type="grading_job_item", entity_id=decision["item_id"],
                event_type="teacher_grading_review_revision", actor_user_id=TEACHER_ID,
                payload={"review_id": revision["review_id"],
                         "revision_sha256": revision["revision_sha256"],
                         "artifact_ref": str(artifact.relative_to(ROOT)),
                         "question_id": decision["question_id"],
                         "decision": decision["decision"],
                         "teacher_score": decision["teacher_score"],
                         "original_score": decision["original_score"],
                         "provenance": "TEACHER_REVIEWED"},
            ))
        session.add(DomainEvent(
            entity_type="grading_review", entity_id=revision["review_id"],
            event_type="teacher_grading_review_summary", actor_user_id=TEACHER_ID,
            payload={"revision_sha256": revision["revision_sha256"],
                     "problem2_teacher_total": 25, "question_ids": [Q21, Q22]},
        ))
        session.commit()
        return revision


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url), ensure_ascii=False, indent=2))
