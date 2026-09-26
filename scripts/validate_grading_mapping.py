"""Read-only sample audit; --create-fixture adds only a named isolated H.2-G Test.

No jobs, model calls, migrations, or sample modifications. Connection is supplied
by environment, never embedded in report artifacts. Run from repository root.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scoring.db import Base, create_session_factory
from scoring.db.models import StudentSubmission, Test, TestQuestion
from scoring.grading_mapping import GradingInputAssembler, prepare_submission_bundles
from scoring.pdf_native import canonical_hash, sha256_file
from tests.mapping_fixture import create_mapping_fixture


def snapshot(session):
    return {table.name: {str(row["id"]): canonical_hash(json.loads(json.dumps(dict(row), default=str)))
                        for row in session.execute(select(table)).mappings()}
            for table in Base.metadata.sorted_tables if "id" in table.c}


def processes():
    return subprocess.run(["pgrep", "-ax", "llama-server"], capture_output=True, text=True).stdout.splitlines()


def verify(before, after):
    for table, rows in before.items():
        for key, digest in rows.items():
            assert after[table].get(key) == digest, ("EXISTING_ROW_CHANGED", table, key)
    for table in ("grading_jobs", "grading_job_items", "grading_job_events", "grading_runtime_snapshots"):
        if table in before:
            assert before[table] == after[table], table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-fixture", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", default="/tmp/h2g-real-validation.json")
    parser.add_argument("--root", default="artifacts/h2b-verification")
    args = parser.parse_args()
    engine, factory = create_session_factory(os.environ["LLM_GRADER_DATABASE_URL"])
    output = Path(args.output)
    with factory() as s:
        if args.verify:
            report = json.loads(output.read_text())
            verify(report["before"], snapshot(s))
            assert all(sha256_file(Path(p)) == h for p, h in report["files"].items())
            assert processes() == report["llama_processes_before"]
            report["existing_rows_and_artifacts_unchanged"] = True
            report["llama_processes_after"] = processes()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print("Existing rows/artifacts/jobs and llama-server processes unchanged")
            return
        if output.exists():
            raise SystemExit("Use a new output path; baseline must not be overwritten")
        report = {"before": snapshot(s), "files": {
            str(p.resolve()): sha256_file(p) for p in Path(args.root).rglob("*") if p.is_file()},
            "llama_processes_before": processes(),
            "postgresql": s.execute(text("select version(), current_database()")).one()._asdict(),
            "alembic_head": s.execute(text("select version_num from alembic_version")).scalar(), "samples": []}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        for t in s.scalars(select(Test).where(Test.name.like("H.2-B verification sample%"))):
            qs = s.scalars(select(TestQuestion).where(TestQuestion.test_id == t.id)).all()
            if not qs:
                continue
            assembler = GradingInputAssembler(s, t.id, root=args.root)
            subs = s.scalars(select(StudentSubmission).where(StudentSubmission.test_id == t.id)).all()
            report["samples"].append({"test_id": t.id, "name": t.name, "readiness": assembler.readiness,
                "submission_count": len(subs), "mapping": [assembler.evaluate(sub.id) for sub in subs],
                "questions": [{"id": q.id, "node": (q.provenance or {}).get("review_node_id"),
                    "display_label": q.display_label, "title": q.title, "parent_id": q.parent_id,
                    "stable_question_key": q.stable_question_key, "max_points": q.max_points,
                    "is_gradable": q.is_gradable, "content_sha256": q.content_sha256,
                    "context": assembler.contexts.build(q.id),
                    "formulas": [v for v in (q.content or {}).get("items", []) if v.get("type") == "formula"]}
                    for q in qs]})
        if args.create_fixture:
            root = Path("artifacts/h2g-validation") / str(uuid4())
            fixture = create_mapping_fixture(s, root.resolve())
            s.commit()
            assembler = GradingInputAssembler(s, fixture["test"].id, allowed_roots=[root])
            result = assembler.evaluate(fixture["submission"].id)
            assert result["can_build_all_inputs"]
            dry = prepare_submission_bundles(s, fixture["test"].id, [fixture["submission"]], root)
            assert sorted(b["bundle_sha256"] for b in dry) == sorted(r["bundle"]["bundle_sha256"] for r in result["questions"])
            report["fixture"] = {"test_id": fixture["test"].id, "submission_id": fixture["submission"].id,
                "root": str(root.resolve()), "question_ids": {k: q.id for k, q in fixture["questions"].items()},
                "result": result, "snapshot_equivalence": True}
        verify(report["before"], snapshot(s))
        assert all(sha256_file(Path(p)) == h for p, h in report["files"].items())
        report["existing_rows_and_artifacts_unchanged"] = True
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(json.dumps({"samples": [{"test_id": v["test_id"], "name": v["name"],
                         "gradable": v["readiness"]["gradable_count"], "submissions": v["submission_count"]}
                         for v in report["samples"]], "fixture": report.get("fixture", {}).get("test_id"),
                         "audit": str(output)}, ensure_ascii=False, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
