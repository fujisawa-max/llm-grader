"""Create the append-only Q4 Problem 2 teacher rubric clarification.

The existing approved rubric is never edited.  DomainService creates a new
version and approval supersedes only the status pointer, preserving the old
version and all source evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from sqlalchemy import select

from scoring.db.database import create_session_factory
from scoring.db.models import DomainEvent, RubricVersion
from scoring.domain import DomainService
from scoring.pdf_native import canonical_hash


TEST_ID = "e14aeeb5-924c-4c72-b2a2-583f1be9f48e"
Q21 = "02669a76-cb99-4ea1-bfd4-c742ff1617a3"
Q22 = "705f1d12-4f19-4c33-b197-39212f24b3ca"
TEACHER_ID = "99d3a635-8c60-47a4-99d8-aa11e4efe176"


def _levels(scores: list[tuple[int, str]]) -> list[dict]:
    return [{"score": score, "condition": condition} for score, condition in scores]


def apply(database_url: str) -> dict:
    _, factory = create_session_factory(database_url)
    with factory() as session:
        current = session.scalar(select(RubricVersion).where(
            RubricVersion.test_id == TEST_ID, RubricVersion.status == "approved"
        ).order_by(RubricVersion.version.desc()))
        if current is None:
            raise RuntimeError("Q4 approved rubric not found")
        old_id = current.id
        old_hash = canonical_hash(current.rubric_json)
        rubric = json.loads(json.dumps(current.rubric_json, ensure_ascii=False))
        entries = {q["question_id"]: q for q in rubric["questions"]}

        q21 = entries[Q21]
        q21["criteria"] = [
            {
                "id": "criterion_1_factorization",
                "description": "正しい因数分解まで到達している",
                "points": 10,
                "criterion_type": "calculation",
                "source_kind": "TEACHER_EDITED",
                "provenance": "TEACHER_EDITED",
                "teacher_reviewed": True,
                "review_required": False,
                "levels": _levels([
                    (10, "正しい因数分解まで到達している"),
                    (5, "因数分解の方法・途中過程に妥当な内容があるが、計算ミス等により正答に至っていない"),
                    (0, "妥当な因数分解の過程が確認できない"),
                ]),
            },
            {
                "id": "criterion_2_completing_square",
                "description": "正しい平方完成まで到達している",
                "points": 10,
                "criterion_type": "calculation",
                "source_kind": "TEACHER_EDITED",
                "provenance": "TEACHER_EDITED",
                "teacher_reviewed": True,
                "review_required": False,
                "levels": _levels([
                    (10, "正しい平方完成まで到達している"),
                    (5, "平方完成の方法・途中過程に妥当な内容があるが、計算ミス等により正答に至っていない"),
                    (0, "妥当な平方完成の過程が確認できない"),
                ]),
            },
        ]

        q22 = entries[Q22]
        descriptions = [
            ("criterion_1_direction", "放物線の開く向きが正しい"),
            ("criterion_2_vertex", "頂点の位置・座標が正しい"),
            ("criterion_3_x_intercepts", "x軸との交点が正しい"),
            ("criterion_4_y_intercept", "y軸との交点が正しい"),
        ]
        q22["criteria"] = []
        for criterion_id, description in descriptions:
            q22["criteria"].append({
                "id": criterion_id,
                "description": description,
                "points": 5,
                "criterion_type": "visual_geometry",
                "source_kind": "TEACHER_EDITED",
                "provenance": "TEACHER_EDITED",
                "teacher_reviewed": True,
                "review_required": False,
                "levels": _levels([(5, description), (0, "正しくない")]),
            })

        clarification = {
            "schema_version": "h3e0a-q4-problem2-teacher-clarification.v1",
            "provenance": "TEACHER_EDITED",
            "teacher_user_id": TEACHER_ID,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "base_rubric_version_id": old_id,
            "base_rubric_sha256": old_hash,
            "question_clarifications": [Q21, Q22],
            "machine_safe_criterion_ids": True,
            "student_data_accessed": False,
        }
        rubric["teacher_review"] = {
            **rubric.get("teacher_review", {}),
            "q4_problem2_clarification": clarification,
        }
        # The rubric domain validator verifies the full test total and exact
        # question IDs before the new version is persisted.
        domain = DomainService(session)
        created = domain.rubric(
            TEST_ID, rubric,
            source_type="teacher_reviewed",
            rubric_text="Q4 Problem 2 teacher clarification",
            generated_by_model=None,
            generation_metadata=clarification,
        )
        approved = domain.approve_rubric(created.id, TEACHER_ID)
        session.add(DomainEvent(
            entity_type="rubric", entity_id=approved.id,
            event_type="teacher_rubric_clarification_applied",
            actor_user_id=TEACHER_ID,
            payload={"base_rubric_version_id": old_id,
                     "base_rubric_sha256": old_hash,
                     "clarification_sha256": canonical_hash(clarification),
                     "question_ids": [Q21, Q22]},
        ))
        session.commit()
        return {
            "old": {"id": old_id, "version": current.version, "status": "superseded", "sha256": old_hash},
            "new": {"id": approved.id, "version": approved.version,
                    "status": approved.status, "sha256": canonical_hash(approved.rubric_json)},
            "clarification_sha256": canonical_hash(clarification),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url), ensure_ascii=False, indent=2))
