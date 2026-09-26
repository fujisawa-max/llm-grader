"""H.2-F: read-only sample audit and an isolated, explicitly synthetic READY fixture.

Requires LLM_GRADER_DATABASE_URL and a local API running against that database.
No worker, model, Review or Confirmation action is invoked.
"""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select, text

from scoring.db import create_session_factory
from scoring.db.models import (
    TestQuestion, ModelAnswer, RubricVersion, QuestionImportDraft, QuestionImportDraftNode,
    QuestionImportExtraction, QuestionImportVisionRun, QuestionImportVisionResult,
    QuestionImportReviewRevision,
)
from scoring.domain import DomainService
from scoring.pdf_native import canonical_hash, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:18052/api/v1")
    parser.add_argument("--root", default="artifacts/h2b-verification")
    parser.add_argument("--refresh-report", action="store_true", help="Read-only HTTP refresh of existing audit")
    args = parser.parse_args()
    if args.refresh_report:
        target = Path(args.root) / "h2f-validation.json"
        report = json.loads(target.read_text())
        with httpx.Client(base_url=args.api, timeout=30) as client:
            for name in ("sampleQ1", "sampleQ2", "sampleQ3"):
                prior = report[name]
                tid = prior["readiness"]["test_id"]
                response = client.get(f"/tests/{tid}/grading-readiness")
                response.raise_for_status()
                ready = response.json()
                contexts = {}
                for row in ready["questions"]:
                    if not row["is_gradable"]:
                        continue
                    response = client.get(f"/test-questions/{row['question_id']}/effective-grading-context")
                    response.raise_for_status()
                    ctx = response.json()
                    assert [s["content_sha256"] for s in ctx["segments"]] == [
                        s["content_sha256"] for s in prior["contexts"][row["question_id"]]["segments"]]
                    contexts[row["question_id"]] = ctx
                report[name] = {"readiness": ready, "contexts": contexts}
            response = client.get(f"/tests/{report['validation']['test_id']}/grading-readiness")
            response.raise_for_status()
            report["validation"]["final"] = response.json()
            response = client.get(f"/tests/{report['sampleQ3']['readiness']['test_id']}/questions")
            response.raise_for_status()
            report["formula_literal_audit"] = [{"region_id": i["source_region_id"],
                "stored_transcription": i["transcription"],
                "leading_backslash_count": len(i["transcription"]) - len(i["transcription"].lstrip("\\")),
                "preserved_without_correction": True}
                for q in response.json() for i in q["content"]["items"]
                if i["type"] == "formula" and i.get("resolution_source") == "teacher_edit"]
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print("Read-only report refresh: authoritative content hashes unchanged")
        return
    _, factory = create_session_factory(os.environ["LLM_GRADER_DATABASE_URL"])
    root = Path(args.root)
    models = [TestQuestion, ModelAnswer, RubricVersion, QuestionImportDraft,
              QuestionImportDraftNode, QuestionImportExtraction, QuestionImportVisionRun,
              QuestionImportVisionResult, QuestionImportReviewRevision]

    def records(session):
        return {m.__tablename__: {r.id: canonical_hash({
            c.name: str(getattr(r, c.name)) if hasattr(getattr(r, c.name), "isoformat")
            else getattr(r, c.name) for c in m.__table__.columns})
            for r in session.scalars(select(m))} for m in models}

    with factory() as s:
        before = records(s)
        out = {"postgresql": s.scalar(text("select version()")),
               "database": s.scalar(text("select current_database()")),
               "alembic": s.scalar(text("select version_num from alembic_version"))}
        files = {str(p): sha256_file(p) for p in root.glob("*/*/**/*") if p.is_file()}
        d = DomainService(s)
        tag = str(uuid4())[:8]
        u = d.user(display_name=f"H.2-F synthetic validation {tag}")
        c = d.course(u.id, name=f"H.2-F validation {tag}")
        o = d.offering(c.id, academic_year=2026, term="fall")
        t = d.test(o.id, name=f"H.2-F synthetic readiness {tag}", total_points=10)
        parent = d.question(t.id, question_number="stem", display_label="Fixture parent",
                            is_gradable=False, max_points=None, question_text="Synthetic parent context")
        child = d.question(t.id, question_number="leaf", display_label="Fixture child",
                           parent_id=parent.id, max_points=10, question_text="Synthetic child context")
        s.commit()
        out["validation"] = {"test_id": t.id, "parent_id": parent.id,
                             "child_id": child.id, "user_id": u.id}

    with httpx.Client(base_url=args.api, timeout=30) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        for name, tid in {
            "sampleQ1": "70a63c23-f1b1-46b7-852c-046148b6f451",
            "sampleQ2": "9fc4f834-a50e-423f-b0cf-31a977c1f891",
            "sampleQ3": "8df4ed72-9297-4082-bb21-1fdb6c500557",
        }.items():
            result = get(f"/tests/{tid}/grading-readiness")
            contexts = {q["question_id"]: get(f"/test-questions/{q['question_id']}/effective-grading-context")
                        for q in result["questions"] if q["is_gradable"]}
            out[name] = {"readiness": result, "contexts": contexts}
        out["validation"]["before"] = get(f"/tests/{t.id}/grading-readiness")
        blocked = client.post(f"/tests/{t.id}/grading-jobs", json={})
        assert blocked.status_code == 409
        denied = client.post(f"/tests/{t.id}/model-answers", json={
            "question_id": parent.id, "answer_text": "Must not be stored"})
        assert denied.status_code == 400
        answer = client.post(f"/tests/{t.id}/model-answers", json={
            "question_id": child.id, "answer_text": "Synthetic fixture response, not a real exam answer"})
        answer.raise_for_status()
        rubric = client.post(f"/tests/{t.id}/rubrics", json={"source_type": "manual", "rubric_json": {
            "questions": [{"question_id": child.id, "max_points": 10, "criteria": [
                {"id": "fixture", "description": "Synthetic fixture criterion", "points": 10}]}]}})
        rubric.raise_for_status()
        rid = rubric.json()["id"]
        client.post(f"/rubrics/{rid}/approve", json={"approved_by_user_id": u.id}).raise_for_status()
        ready = get(f"/tests/{t.id}/grading-readiness")
        assert ready["can_start_grading"]
        out["validation"]["ready"] = ready
        client.delete(f"/model-answers/{answer.json()['id']}").raise_for_status()
        after_delete = get(f"/tests/{t.id}/grading-readiness")
        assert not after_delete["can_start_grading"]
        out["validation"]["answer_retired"] = after_delete
        client.post(f"/tests/{t.id}/model-answers", json={"question_id": child.id,
            "answer_text": "Synthetic fixture response, restored association"}).raise_for_status()
        client.delete(f"/rubrics/{rid}").raise_for_status()
        out["validation"]["rubric_retired"] = get(f"/tests/{t.id}/grading-readiness")
        assert not out["validation"]["rubric_retired"]["can_start_grading"]
        replacement = client.post(f"/tests/{t.id}/rubrics", json={"source_type": "manual",
                                    "rubric_json": rubric.json()["rubric_json"]})
        replacement.raise_for_status()
        client.post(f"/rubrics/{replacement.json()['id']}/approve",
                    json={"approved_by_user_id": u.id}).raise_for_status()
        out["validation"]["final"] = get(f"/tests/{t.id}/grading-readiness")
        out["validation"]["context"] = get(f"/test-questions/{child.id}/effective-grading-context")
        for ctx in out["sampleQ3"]["contexts"].values():
            for asset in ctx["assets"]:
                response = client.get(asset["url"].removeprefix("/api/v1"))
                response.raise_for_status()
                import hashlib
                assert hashlib.sha256(response.content).hexdigest() == asset["sha256"]

    with factory() as s:
        after = records(s)
        out["existing_records_unchanged"] = all(
            after[table].get(i) == checksum for table, rows in before.items() for i, checksum in rows.items())
    out["source_artifacts_unchanged"] = all(sha256_file(Path(p)) == checksum for p, checksum in files.items())
    assert out["existing_records_unchanged"] and out["source_artifacts_unchanged"]
    target = root / "h2f-validation.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(target), "validation_test": t.id,
                      "existing_records_unchanged": True, "source_artifacts_unchanged": True}))


if __name__ == "__main__":
    main()
