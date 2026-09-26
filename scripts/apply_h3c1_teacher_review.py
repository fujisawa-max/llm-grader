"""Apply the explicit H.3-C.1 teacher decisions.

This is an append-only operation: Q2 score changes use
``QuestionCorrectionService``; accepted answers become new ModelAnswer
versions; and each test receives a new generated-then-approved RubricVersion.
No student or grading tables are read.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from scoring.db.database import create_session_factory
from scoring.db.models import DomainEvent, ModelAnswer, RubricVersion, TestQuestion, TestQuestionCorrection
from scoring.domain import DomainService
from scoring.pdf_native import canonical_hash
from scoring.question_corrections import QuestionCorrectionService


ROOT = Path("artifacts/h3c1-model-answer")
PACKAGE = ROOT / "teacher-review-package.json"
TEACHER_ID = "99d3a635-8c60-47a4-99d8-aa11e4efe176"
Q2_TEST = "9fc4f834-a50e-423f-b0cf-31a977c1f891"
Q2_MAX = {
    "24a42587-a730-408c-8565-1221cba11453": 20,
    "dbd8a6e7-8fdd-475c-adb7-652db377ab8a": 20,
    "5928d0e3-ea16-48e4-b9ff-a96209e4eb37": 40,
    "8c8c578c-1635-4f13-91e8-4b40dbe3e258": 20,
}


def _criteria(sample: str, q: dict[str, Any]) -> list[dict[str, Any]]:
    key = q["stable_question_key"].rsplit("-q", 1)[-1]
    def item(index: int, points: int, description: str, kind: str = "EXPLICIT_SOURCE",
             criterion_type: str = "concept", partial: str | None = None):
        source = q["rubric_evidence"]
        result = {"id": f"criterion_{index}", "description": description,
                  "points": points, "source_kind": kind, "provenance": kind,
                  "criterion_type": criterion_type, "review_required": False,
                  "source_refs": q.get("source_refs", []),
                  "source_evidence_sha256": source.get("text_sha256")}
        if partial:
            result["partial_credit_conditions"] = partial
        return result

    if sample == "sampleQ1" and key == "3.1":
        return [item(1, 5, "入力データと対応する正解ラベルがあることを説明できている。"),
                item(2, 5, "予測と正解の誤差が小さくなるようにモデルを学習・調整することを説明できている。")]
    if sample == "sampleQ2":
        if key in {"1.1", "1.2"}:
            label = "因数分解" if key == "1.1" else "解法の式変形"
            return [item(1, 10, f"{label}の解法・式変形が概ね正しく、正答へ到達できる。", "TEACHER_EDITED", "calculation", "正しい考え方や有効な式変形が一部できているが完全な解法に至らない場合は5点。"),
                    item(2, 10, "全ての解が正しい。", "TEACHER_EDITED", "final_answer")]
        if key == "2":
            return [item(1, 20, "正しく因数分解できている。", "TEACHER_EDITED", "calculation", "正しい方向で途中までできている場合は10点。"),
                    item(2, 20, "正しく平方完成できている。", "TEACHER_EDITED", "calculation", "正しい方向で途中までできている場合は10点。")]
        return [item(1, 20, "最終的な方程式が正しい。", "TEACHER_EDITED", "final_answer", "−1を三重根として(x+1)^3=0を構成する方向が正しいが、展開や最終式に誤りがある場合は10点。")]
    if sample == "sampleQ4":
        if key == "1":
            return [item(1, 15, "計算の途中式が正しい。"), item(2, 15, "計算の最終答えが正しい。")]
        if key == "2.1":
            return [item(1, 10, "因数分解が正しい。"), item(2, 10, "平方完成が正しい。")]
        if key == "2.2":
            return [item(1, 5, "放物線の向きが正しい。", criterion_type="visual_geometry"),
                    item(2, 5, "頂点の座標が正しい。", criterion_type="visual_geometry"),
                    item(3, 5, "x軸との交点が正しい。", criterion_type="visual_geometry"),
                    item(4, 5, "y軸との交点が正しい。", criterion_type="visual_geometry")]
        return [item(1, 5, "複素数の絶対値 r を正しく求めている.", criterion_type="calculation"),
                item(2, 5, "偏角 θ を正しく求めている.", criterion_type="calculation"),
                item(3, 10, "極形式 2√3(cos(π/6) + i sin(π/6)) を正しく求めている.", criterion_type="final_answer"),
                item(4, 5, "複素平面上で実軸方向の値 3 を正しく示している.", criterion_type="visual_annotation"),
                item(5, 5, "複素平面上で虚軸方向の値 √3 を正しく示している.", criterion_type="visual_annotation"),
                item(6, 5, "複素平面上で長さ r を適切に示している.", criterion_type="visual_annotation"),
                item(7, 5, "複素平面上で角度 θ を適切に示している.", criterion_type="visual_annotation")]
    # Q1/Q3 clean entries use the source-structured points unchanged.
    result = []
    for i, criterion in enumerate(q["rubric_draft"]["criteria"], 1):
        result.append(item(i, int(criterion["points"]), criterion["description"],
                           "EXPLICIT_SOURCE", "concept"))
    return result


def _rubric_for_test(sample: str, entries: list[dict[str, Any]], source_ids: dict[str, str],
                     source_shas: dict[str, str], review_ref: str) -> dict[str, Any]:
    questions = []
    for q in entries:
        criteria = _criteria(sample, q)
        max_points = q["max_points"]
        if max_points is None and sample == "sampleQ2":
            max_points = Q2_MAX[q["question_id"]]
        questions.append({"question_id": q["question_id"], "max_points": int(max_points),
                          "criteria": criteria, "teacher_reviewed": True,
                          "model_answer_sha256": q["model_answer_draft"]["content_sha256"]})
    metadata = {"schema_version": "h3c1-teacher-approved.v1", "teacher_user_id": TEACHER_ID,
                "review_revision_ref": review_ref, "source_document_ids": source_ids,
                "source_pdf_sha256": source_shas, "student_data_accessed": False,
                "llm_proposed_criteria_accepted": 0}
    if sample == "sampleQ4":
        p3 = next(q for q in entries if q["stable_question_key"].endswith("-q3"))
        metadata["source_ownership_corrections"] = [{
            "question_id": p3["question_id"], "removed_from_question": ["途中式15点", "正答15点"],
            "assigned_source_owner": next(q["question_id"] for q in entries if q["stable_question_key"].endswith("-q1")),
            "raw_evidence_sha256": p3["rubric_evidence"]["text_sha256"],
            "reason": "cross_question_native_rubric_segmentation_correction",
        }]
        metadata["reference_assets"] = [a for q in entries for a in q.get("assets", [])]
    return {"schema_version": "approved-rubric.v1", "questions": questions,
            "teacher_review": metadata}


def apply(database_url: str, question_root: Path) -> dict[str, Any]:
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    by_sample: dict[str, list[dict[str, Any]]] = {}
    for q in package["questions"]:
        by_sample.setdefault(q["sample"], []).append(q)
    review_ref = "h3c1-model-answer/teacher-review-revision-1.json"
    revision = {"schema_version": "h3c1-teacher-review-revision.v1", "teacher_user_id": TEACHER_ID,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "package_sha256": canonical_hash(package), "decisions": {
                    "q1": "ACCEPT_ALL", "q1_candidate": "ACCEPT", "q2_score": Q2_MAX,
                    "q2_partial_credit": "TEACHER_EDITED", "q3": "ACCEPT_ALL",
                    "q4": "ACCEPT_ALL", "q4_problem3_segmentation": "ACCEPT",
                    "q4_reference_assets": "ACCEPT"}}
    revision_path = ROOT / "teacher-review-revision-1.json"
    revision_path.write_text(json.dumps(revision, ensure_ascii=False, indent=2), encoding="utf-8")

    _, factory = create_session_factory(database_url)
    result: dict[str, Any] = {"review_revision": review_ref, "corrections": [], "model_answers": [], "rubrics": []}
    with factory() as session:
        # Apply Q2 score reconciliation through the existing append-only correction service.
        correction_service = QuestionCorrectionService(session, question_root)
        for qid, target in Q2_MAX.items():
            q = session.get(TestQuestion, qid)
            if q is None or q.test_id != Q2_TEST:
                raise ValueError(f"Q2 mapping mismatch: {qid}")
            if q.max_points is not None:
                if float(q.max_points) != float(target):
                    raise ValueError(f"unexpected existing max_points for {qid}: {q.max_points}")
                existing = session.scalar(select(TestQuestionCorrection).where(
                    TestQuestionCorrection.test_question_id == qid,
                    TestQuestionCorrection.reason_code == "model_answer_source_score_reconciliation"
                ).order_by(TestQuestionCorrection.correction_version.desc()))
                result["corrections"].append({"question_id": qid, "correction_id": existing.id if existing else None,
                                               "status": "already_applied", "after": target})
                continue
            expected = q.content_sha256
            note = json.dumps({"source_document_id": "a85599a9-d24e-4ce9-8d6d-fefc5c927f01",
                               "source_pdf_sha256": "8e9a066d9e5b3d269ecd1b3d43bff1bc8b2d9092e281b719f5d967e8a8c23d09",
                               "teacher_user_id": TEACHER_ID, "teacher_decision": "APPLY",
                               "reason": "model_answer_source_score_reconciliation"}, ensure_ascii=False)
            plan = correction_service.plan(qid, expected_content_sha256=expected,
                                           operations=[{"type": "set_max_points", "expected_old_value": None,
                                                        "new_value": target}],
                                           reason_code="model_answer_source_score_reconciliation", note=note)
            applied = correction_service.apply(qid, expected_content_sha256=expected,
                                               operations=[{"type": "set_max_points", "expected_old_value": None,
                                                            "new_value": target}],
                                               reason_code="model_answer_source_score_reconciliation",
                                               plan_sha256=plan["plan_sha256"], note=note)
            result["corrections"].append({"question_id": qid, "correction_id": applied["id"],
                                           "status": "applied", "before": None, "after": target})

        # Re-read corrected questions before creating any authoritative rows.
        session.expire_all()
        source_ids = {m["source"]["sample"]: m["source"]["source_document_id"]
                      for m in (json.loads(p.read_text(encoding="utf-8"))
                                for p in sorted(ROOT.glob("sampleQ*/**/import-manifest.json")))}
        source_shas = {m["source"]["sample"]: m["source"]["sha256"]
                       for m in (json.loads(p.read_text(encoding="utf-8"))
                                 for p in sorted(ROOT.glob("sampleQ*/**/import-manifest.json")))}
        domain = DomainService(session, artifact_root=question_root)
        for sample, entries in by_sample.items():
            test_id = entries[0]["test_id"]
            material_id = source_ids[sample]
            for entry in entries:
                existing = session.scalar(select(ModelAnswer).where(
                    ModelAnswer.test_id == test_id, ModelAnswer.question_id == entry["question_id"],
                    ModelAnswer.is_current.is_(True)))
                if existing:
                    result["model_answers"].append({"question_id": entry["question_id"], "id": existing.id,
                                                    "status": "already_present", "version": existing.version})
                    continue
                answer = domain.model_answer(test_id, question_id=entry["question_id"],
                                             answer_text=entry["model_answer_draft"]["content"],
                                             material_id=material_id)
                session.add(DomainEvent(entity_type="model_answer", entity_id=answer.id,
                                        event_type="teacher_review_accepted", actor_user_id=TEACHER_ID,
                                        payload={"review_revision_ref": review_ref,
                                                 "source_sha256": source_shas[sample],
                                                 "content_sha256": entry["model_answer_draft"]["content_sha256"],
                                                 "decision": "ACCEPT"}))
                result["model_answers"].append({"question_id": entry["question_id"], "id": answer.id,
                                                "status": "created", "version": answer.version,
                                                "content_sha256": entry["model_answer_draft"]["content_sha256"]})
            rubric_json = _rubric_for_test(sample, entries, source_ids, source_shas, review_ref)
            approved = session.scalar(select(RubricVersion).where(
                RubricVersion.test_id == test_id, RubricVersion.status == "approved").order_by(RubricVersion.version.desc()))
            if approved:
                result["rubrics"].append({"test_id": test_id, "id": approved.id, "status": "already_present", "version": approved.version})
            else:
                rubric = domain.rubric(test_id, rubric_json, source_type="teacher_reviewed",
                                       rubric_text="Teacher-approved H.3-C.1 rubric",
                                       generated_by_model=None,
                                       generation_metadata=rubric_json["teacher_review"])
                approved = domain.approve_rubric(rubric.id, TEACHER_ID)
                result["rubrics"].append({"test_id": test_id, "id": approved.id,
                                          "status": approved.status, "version": approved.version,
                                          "rubric_sha256": canonical_hash(approved.rubric_json)})
        session.commit()
    result["review_revision_sha256"] = canonical_hash(revision)
    (ROOT / "teacher-review-apply-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    parser.add_argument("--question-root", default="artifacts/h2b-verification")
    args = parser.parse_args()
    print(json.dumps(apply(args.database_url, Path(args.question_root)), ensure_ascii=False, indent=2))
