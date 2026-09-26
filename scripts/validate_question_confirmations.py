"""Read/verify H.2 sample confirmations; retry Q1 only with its stored exact request.

Requires an existing before snapshot. Never edits a Review or confirms blocked plans.
"""

import argparse
import json
from pathlib import Path
from sqlalchemy import select, text, inspect
import httpx
from scoring.db.database import create_session_factory
from scoring.db.models import QuestionImportConfirmation, QuestionImportReview, QuestionImportDraft
from scoring.pdf_native import sha256_file, canonical_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:18051/api/v1")
    parser.add_argument("--before", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    before = json.loads(Path(args.before).read_text())
    engine, sf = create_session_factory(args.database_url)
    report = {}
    with sf() as session, httpx.Client(timeout=30) as client:
        report["postgresql"] = (
            session.execute(text("SELECT version(), current_database()")).first()._asdict()
        )
        report["alembic"] = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        report["constraints"] = {
            "foreign_keys": inspect(engine).get_foreign_keys("test_questions"),
            "indexes": inspect(engine).get_indexes("test_questions"),
        }
        report["samples"] = {}
        for rid, original in before.items():
            if rid in {"before", "source_files"}:
                continue
            plan = client.post(f"{args.api}/question-import-reviews/{rid}/import-plan")
            plan.raise_for_status()
            result = {
                "test": original["test"],
                "pre_confirm_plan": original["plan"],
                "current_plan": plan.json(),
            }
            revision = client.get(f"{args.api}/question-import-reviews/{rid}").json()
            result["native_audit"] = []
            for node in revision["snapshot"]["nodes"]:
                for region_id, decision in node["formula_decisions"].items():
                    region = next(r for r in revision["regions"] if r["region_id"] == region_id)
                    result["native_audit"].append(
                        {
                            "region_id": region_id,
                            "decision": decision["decision"],
                            "teacher_transcription": decision.get("teacher_transcription"),
                            "fragments": [
                                f.get("native_text") for f in region.get("text_fragments", [])
                            ],
                            "safe_single_span": len(region.get("text_fragments", [])) == 1,
                        }
                    )
            conf = session.scalar(
                select(QuestionImportConfirmation).where(
                    QuestionImportConfirmation.review_id == rid
                )
            )
            if conf:
                count = session.execute(text("SELECT count(*) FROM test_questions")).scalar()
                payload = {
                    "expected_revision": conf.review_revision_number,
                    "expected_revision_sha256": conf.review_revision_sha256,
                    "import_plan_sha256": conf.import_plan_sha256,
                    "mode": "append",
                }
                first = client.post(
                    f"{args.api}/question-import-reviews/{rid}/confirm", json=payload
                )
                second = client.post(
                    f"{args.api}/question-import-reviews/{rid}/confirm", json=payload
                )
                assert first.status_code == second.status_code == 200, (first.text, second.text)
                assert first.json()["id"] == second.json()["id"] == conf.id
                assert (
                    session.execute(text("SELECT count(*) FROM test_questions")).scalar() == count
                )
                bad = client.post(
                    f"{args.api}/question-import-reviews/{rid}/confirm",
                    json={**payload, "expected_revision": payload["expected_revision"] + 1},
                )
                assert bad.status_code == 409
                detail = client.get(f"{args.api}/question-import-confirmations/{conf.id}")
                detail.raise_for_status()
                assert all(x not in detail.text for x in ["/opt/", "/home/", "/tmp/"])
                review = session.get(QuestionImportReview, rid)
                draft = session.get(QuestionImportDraft, review.draft_id)
                base = (
                    Path("artifacts/h2b-verification")
                    / draft.extraction_id
                    / Path(conf.artifact_ref).parent
                )
                manifest = json.loads((base / "manifest.json").read_text())
                hashes = {
                    name: sha256_file(base / name)
                    for name in ["manifest.json", "mapping.json", "import-plan.json"]
                }
                for name, digest in manifest["artifact_hashes"].items():
                    assert hashes[name] == digest
                mapping = json.loads((base / "mapping.json").read_text())
                rows = (
                    session.execute(
                        text("SELECT * FROM test_questions WHERE test_id=:test"),
                        {"test": original["test"]["id"]},
                    )
                    .mappings()
                    .all()
                )
                gradable = [row for row in rows if row["is_gradable"]]
                result.update(
                    confirmation=detail.json(),
                    idempotent_count_delta=0,
                    conflict_status=bad.status_code,
                    artifact_hashes=hashes,
                    mapping=mapping,
                    grading_selection=[q["id"] for q in gradable],
                    scores=[q["max_points"] for q in gradable],
                )
            else:
                result["confirmation"] = None
                assert result["current_plan"]["blockers"]
            report["samples"][rid] = result
        checks = {}
        for table, values in before["before"].items():
            after = [
                dict(row)
                for row in session.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            after = json.loads(json.dumps(after, default=str))
            if table == "test_questions":
                originals = {v["id"] for v in values}
                after = [v for v in after if v["id"] in originals]
            checks[table] = values == after
        assert all(checks.values()), checks
        report["source_records_unchanged"] = checks
        changed = [
            path
            for path, digest in before["source_files"].items()
            if sha256_file(Path(path)) != digest
        ]
        assert not changed, changed
        report["source_file_count"] = len(before["source_files"])
        report["source_files_unchanged"] = not changed
        report["audit_sha256"] = canonical_hash(json.loads(json.dumps(report, default=str)))
    Path(args.output).write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "alembic": report["alembic"],
                "sources_unchanged": all(checks.values()) and not changed,
                "source_files": report["source_file_count"],
                "output": args.output,
            }
        )
    )


if __name__ == "__main__":
    main()
