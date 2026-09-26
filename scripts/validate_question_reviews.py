"""Opt-in H.2-D.1 sample regression using HTTP TestClient and an existing database.

Writes teacher *test* revisions only. Never invokes a model. Source fingerprints and
step checkpoints are recorded so an interrupted validation can safely resume.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from scoring.api import create_app
from scoring.db import create_session_factory
from scoring.db.models import (QuestionImportDraft, QuestionImportDraftNode, QuestionImportExtraction,
                               QuestionImportVisionRun, QuestionImportVisionResult, TestQuestion)
from scoring.pdf_native import canonical_hash, sha256_file

SAMPLES = {"sampleQ1": "0e7c29b8-766b-4758-9294-dbba6f2f759c",
           "sampleQ2": "dfc5f69e-a423-441b-90bf-4ed122009d9b",
           "sampleQ3": "0f487e91-d57f-432d-be14-e6447790a4bb"}


def fingerprint(sf, root):
    result = {"tables": {}, "files": {}}
    with sf() as s:
        for cls in (QuestionImportExtraction, QuestionImportDraft, QuestionImportDraftNode,
                    QuestionImportVisionRun, QuestionImportVisionResult, TestQuestion):
            rows = [{c.name: getattr(r, c.name) for c in cls.__table__.columns}
                    for r in s.scalars(select(cls).order_by(cls.id))]
            serial = json.loads(json.dumps(rows, default=str))
            result["tables"][cls.__tablename__] = {"count": len(rows), "sha256": canonical_hash(serial)}
    for p in root.glob("*/*"):
        if p.name == "review":
            continue
        if p.is_file() and p.name == "source.pdf":
            result["files"][str(p.relative_to(root))] = sha256_file(p)
        elif p.is_dir() and p.name in {"native", "structured", "vision"}:
            for f in p.rglob("*"):
                if f.is_file():
                    result["files"][str(f.relative_to(root))] = sha256_file(f)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    engine, sf = create_session_factory(os.environ["DATABASE_URL"])
    audit = json.loads(args.report.read_text()) if args.report.exists() else {"samples": {}, "steps": []}

    def checkpoint():
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str))

    with sf() as s:
        audit["alembic_head"] = s.execute(text("select version_num from alembic_version")).scalar_one()
    if "before" not in audit:
        audit["before"] = fingerprint(sf, args.artifact_root)
        checkpoint()
    client = TestClient(create_app(sf, question_import_root=args.artifact_root))

    def request(method, url, **kw):
        r = client.request(method, "/api/v1" + url, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {url} {r.status_code}: {r.text}")
        audit.setdefault("http", {})[f"{method} {url}"] = r.status_code
        return r

    for sample, did in SAMPLES.items():
        data = request("POST", f"/question-import-drafts/{did}/reviews").json()
        url = f"/question-import-reviews/{data['id']}"
        audit["samples"].setdefault(sample, {})
        info = audit["samples"][sample]
        info.update(review_id=data["id"], draft_id=did, test_id=data["test_id"])
        request("GET", f"/tests/{data['test_id']}/question-import-reviews")
        plan = request("POST", f"/question-import-drafts/{did}/vision-plan").json()
        info["routing_count"] = plan["vision_request_count"]
        assert info["routing_count"] == {"sampleQ1": 0, "sampleQ2": 3, "sampleQ3": 4}[sample]
        for page in range(data["page_count"]):
            metadata = request("GET", url + f"/pages/{page}/metadata").json()
            preview = request("GET", url + f"/pages/{page}/preview")
            assert preview.content.startswith(b"\x89PNG")
            info.setdefault("previews", {})[str(page)] = metadata
        info["evidence"] = {}
        for region in data["regions"]:
            key = region["region_id"]
            evidence = request("GET", url + f"/regions/{key}/evidence").json()
            crop = request("GET", url + f"/regions/{key}/crop")
            assert crop.content.startswith(b"\x89PNG")
            if evidence["raw_available"]:
                request("GET", url + f"/regions/{key}/vision-raw")
            info["evidence"][key] = evidence
        checkpoint()
        if args.inspect_only:
            continue

        def step(name, modify):
            nonlocal data
            stepid = sample + ":" + name
            if stepid in audit["steps"]:
                data = request("GET", url).json()
                return
            snap = deepcopy(data["snapshot"])
            snap.update(state="editing", reviewed=False)
            modify(snap)
            data = request("POST", url + "/revisions", json={"base_revision": data["current_revision"], "snapshot": snap}).json()
            audit["steps"].append(stepid)
            checkpoint()

        if sample == "sampleQ2":
            step("text", lambda s: s["nodes"][0]["ordered_content"][1].update(
                text=s["nodes"][0]["ordered_content"][1]["text"] + " （レビュー保存検証）"))
            step("score", lambda s: s["nodes"][0].update(score_semantics="ambiguous", score_points=None))
            step("score-unset", lambda s: s["nodes"][0].update(score_semantics="unset", score_points=None))

            def add(s):
                if any(n["stable_key"] == "teacher-validation" for n in s["nodes"]):
                    return
                n = deepcopy(s["nodes"][0])
                n.update(stable_key="teacher-validation", review_node_id="teacher-validation",
                         source_draft_stable_key=None, source_draft_node_id=None, parent_key=None,
                         label={"raw": "検証用追加問題", "normalized": "検証用追加問題"},
                         sort_order=100, review_flags=[], formula_decisions={}, figure_decisions={},
                         ordered_content=[{"type": "text", "order": 0, "text": "保存確認専用"}])
                s["nodes"].append(n)
            step("add", add)
            step("reparent", lambda s: next(n for n in s["nodes"] if n["stable_key"] == "teacher-validation").update(parent_key="q1", node_type="subquestion"))
            step("reorder", lambda s: next(n for n in s["nodes"] if n["stable_key"] == "teacher-validation").update(sort_order=99))
            step("exclude", lambda s: next(n for n in s["nodes"] if n["stable_key"] == "teacher-validation").update(included=False))

        def decisions(s):
            for n in s["nodes"]:
                for r in data["regions"]:
                    if r["assigned_question_key"] != n["source_draft_stable_key"]:
                        continue
                    kind, key = r["region_type"], r["region_id"]
                    d = {"decision": "use_native" if kind == "formula" else "accepted_as_evidence",
                         "note": "H.2-D.1 workflow検証用。教師による正誤確定を示さない。"}
                    if sample == "sampleQ2" and key == "formula-0001":
                        d.update(decision="teacher_edit", teacher_transcription="2x^3 - 21x^2 + 69x - 70 = 0")
                    n[f"{kind}_decisions"][key] = d
        step("decisions", decisions)
        step("warnings", lambda s: s.update(warning_states={w["id"]: {"state": "acknowledged", "note": "workflow検証"} for w in data["warnings"]}))
        stepid = sample + ":reviewed"
        if stepid not in audit["steps"]:
            data = request("POST", url + "/mark-reviewed", json={"base_revision": data["current_revision"]}).json()
            assert data["state"] == "reviewed"
            audit["steps"].append(stepid)
            checkpoint()
        history = request("GET", url + "/revisions").json()["revisions"]
        info["history"] = history
        info["summary"] = data["summary"]
        info["current_revision"] = data["current_revision"]
        for r in history:
            snapshot = request("GET", url + f"/revisions/{r['revision_number']}").json()
            if snapshot["snapshot"].get("editing_contract"):
                assert canonical_hash(snapshot["snapshot"]) == r["revision_sha256"]
        checkpoint()
    audit["after"] = fingerprint(sf, args.artifact_root)
    audit["sources_unchanged"] = audit["before"] == audit["after"]
    checkpoint()
    assert audit["sources_unchanged"], "Source evidence changed"
    print(json.dumps({"head": audit["alembic_head"], "sources_unchanged": True,
                      "samples": {k: {field: v.get(field) for field in ("review_id", "current_revision", "summary", "routing_count")} for k, v in audit["samples"].items()}}, ensure_ascii=False, indent=2))
    client.close()
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
