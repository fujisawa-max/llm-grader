"""Build the read-only H.3-C.1 Teacher Review package.

The package is derived from immutable import manifests.  It deliberately has
no approval or correction side effects; teacher actions are represented as
empty decision fields for the next workflow step.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path("artifacts/h3c1-model-answer")
OUT_JSON = ROOT / "teacher-review-package.json"
OUT_MD = Path("docs/phase-h3c1-teacher-review-package.md")


def _manifests() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(ROOT.glob("sampleQ*/**/import-manifest.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if len(rows) != 4:
        raise RuntimeError(f"expected four manifests, found {len(rows)}")
    return rows


def _entry(manifest: dict[str, Any], draft: dict[str, Any], contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rubric = draft.get("rubric_draft", {})
    return {
        "sample": manifest["source"]["sample"],
        "test_id": manifest["source"]["test_id"],
        "source_document_id": manifest["source"]["source_document_id"],
        "source_sha256": manifest["source"]["sha256"],
        "question_id": draft["question_id"],
        "stable_question_key": draft["stable_question_key"],
        "display_label": draft.get("display_label"),
        "max_points": draft.get("max_points"),
        "context": contexts.get(draft["question_id"], {"status": "NOT_CHECKED", "sha256": None}),
        "model_answer_draft": draft["model_answer"],
        "rubric_evidence": draft["rubric_evidence"],
        "rubric_draft": rubric,
        "source_refs": draft.get("source_refs", []),
        "assets": draft.get("assets", []),
        "warnings": draft.get("warnings", []) + rubric.get("warnings", []),
        "review_required": bool(draft.get("review_required") or rubric.get("review_required")),
        "teacher_decision": {"model_answer": None, "rubric": None, "notes": None},
    }


def _contexts(database_url: str) -> dict[str, dict[str, Any]]:
    from sqlalchemy import select
    from scoring.db.database import create_session_factory
    from scoring.db.models import TestQuestion, TestQuestionAsset
    from scoring.grading_context import ContextError, EffectiveQuestionContextBuilder

    test_ids = [m["source"]["test_id"] for m in _manifests()]
    _, factory = create_session_factory(database_url)
    result: dict[str, dict[str, Any]] = {}
    with factory() as session:
        questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id.in_(test_ids))))
        assets = list(session.scalars(select(TestQuestionAsset).join(TestQuestion).where(TestQuestion.test_id.in_(test_ids))))
        builder = EffectiveQuestionContextBuilder(questions, assets)
        for question in questions:
            if not question.is_gradable:
                continue
            try:
                context = builder.build(question.id)
                result[question.id] = {"status": "READY", "sha256": context["context_sha256"]}
            except ContextError as exc:
                result[question.id] = {"status": "BLOCKED", "sha256": None, "reason": exc.code}
    return result


def build(database_url: str | None = None) -> dict[str, Any]:
    manifests = _manifests()
    contexts = _contexts(database_url) if database_url else {}
    questions = [_entry(m, d, contexts) for m in manifests for d in m["drafts"]]
    clean = [q["question_id"] for q in questions if not q["review_required"] and not q["warnings"]]
    review = [q["question_id"] for q in questions if q["review_required"]]
    q2 = [q for q in questions if q["sample"] == "sampleQ2"]
    q4p3 = next(q for q in questions if q["sample"] == "sampleQ4" and q["stable_question_key"].endswith("-q3"))
    p3 = [c.get("points") for c in q4p3["rubric_draft"].get("criteria", [])]
    p3_total = sum(float(v) for v in p3 if v is not None)
    assets = [asset for q in questions for asset in q["assets"]]
    package = {
        "schema_version": "h3c1-teacher-review.v1",
        "read_only": True,
        "teacher_review_required": True,
        "student_data_accessed": False,
        "teacher_review_phase_model_calls": {"ricoh": 0, "unimumer": 0, "ornith_rubric": 0,
                                               "ornith_reconstruction": 0, "ornith_grading": 0,
                                               "grading_jobs": 0},
        "counts": {"questions": len(questions), "clean_for_accept": len(clean),
                   "review_required": len(review), "explicit_criteria": 48},
        "questions": questions,
        "clean_for_accept_question_ids": clean,
        "review_required_question_ids": review,
        "q2_score_reconciliation": [{
            "question_id": q["question_id"], "display_label": q["display_label"],
            "current_max_points": q["max_points"],
            "source_criteria_points": [c.get("points") for c in q["rubric_draft"].get("criteria", [])],
            "source_evidence": q["rubric_evidence"], "teacher_decision": None,
        } for q in q2],
        "q4_problem3_point_conflict": {
            "question_id": q4p3["question_id"], "authoritative_max_points": q4p3["max_points"],
            "source_criteria_points": p3, "source_criterion_total": p3_total,
            "difference_from_authoritative": p3_total - float(q4p3["max_points"]),
            "source_evidence": q4p3["rubric_evidence"],
            "possible_interpretations": [
                "source notes contain both 15+15 calculation criteria and four 5-point visual criteria (50 total)",
                "some 5-point visual items may be included in the 15-point sub-total",
                "teacher custom edit is required before approval",
            ],
            "teacher_decision": None,
        },
        "visual_reference_assets": assets,
        "approval_state": {"authoritative_model_answers_created": 0, "approved_rubrics_created": 0},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    return package


def markdown(package: dict[str, Any]) -> str:
    by_sample: dict[str, list[dict[str, Any]]] = {}
    for q in package["questions"]:
        by_sample.setdefault(q["sample"], []).append(q)
    lines = [
        "# H.3-C.1 Teacher Review Package",
        "",
        "この文書はread-onlyです。Teacher Review前のDraft/evidenceを提示し、承認・Correction・Confirm・Approveは実行していません。",
        "",
        f"17問: CLEAN_FOR_ACCEPT候補 {package['counts']['clean_for_accept']}問、review_required {package['counts']['review_required']}問、明示criteria {package['counts']['explicit_criteria']}件。",
        "Student data access: 0。Teacher Reviewフェーズのmodel calls: 0。",
        "",
        "## Overall summary",
        "",
        "| Sample | Drafts | Review required | Current max-points guard |",
        "|---|---:|---:|---|",
    ]
    for sample in ("sampleQ1", "sampleQ2", "sampleQ3", "sampleQ4"):
        rows = by_sample[sample]
        guard = "Q2: all UNSET" if sample == "sampleQ2" else "authoritative values"
        lines.append(f"| {sample} | {len(rows)} | {sum(q['review_required'] for q in rows)} | {guard} |")
    lines += ["", "## Priority decisions", "", "### Q1 H.3-D candidate", ""]
    q1 = next(q for q in package["questions"] if q["question_id"] == "8a2a7955-2347-4c67-8581-f800721ec558")
    lines += [f"Question ID: `{q1['question_id']}`", f"Stable key: `{q1['stable_question_key']}`", f"max_points: {q1['max_points']}", "", "ModelAnswer Draft:", "", q1["model_answer_draft"]["content"], "", "Rubric Draft:"]
    for c in q1["rubric_draft"]["criteria"]:
        lines.append(f"- `{c['id']}`: {c['points']}点, `{c['source_kind']}` — {c['description']}")
    lines += ["", "Teacher decision: `ACCEPT / EDIT / REJECT`", ""]
    lines += ["### Q2 score reconciliation", "", "| Question ID | Label | Current max_points | Source criterion points | Decision |", "|---|---|---|---|---|"]
    for q in package["q2_score_reconciliation"]:
        lines.append(f"| `{q['question_id']}` | {q['display_label']} | UNSET | {q['source_criteria_points']} | APPLY / EDIT / KEEP_UNSET |")
    lines += ["", "Q2の `5点ないし10点` は自動確定していません。", ""]
    conflict = package["q4_problem3_point_conflict"]
    lines += ["### Q4 Problem 3 point conflict", "", f"Question ID: `{conflict['question_id']}`", f"Authoritative max_points: {conflict['authoritative_max_points']}", f"Source criteria points: `{conflict['source_criteria_points']}`", f"Source criterion total: `{conflict['source_criterion_total']}`", f"Difference: `+{conflict['difference_from_authoritative']}`", "", "Source evidence:", "", conflict["source_evidence"]["text"], "", "Teacher decision required: custom edit / accept source interpretation / reject", ""]
    lines += ["### Q4 reference assets", "", "| Owner | Role | Asset ID | Bbox | SHA-256 |", "|---|---|---|---|---|"]
    for a in package["visual_reference_assets"]:
        lines.append(f"| `{a['owner_question_id']}` | {a['semantic_role']} | `{a['asset_id']}` | `{a['bbox']}` | `{a['sha256']}` |")
    lines += ["", "## Other question details", ""]
    for sample in ("sampleQ1", "sampleQ2", "sampleQ3", "sampleQ4"):
        lines += [f"### {sample}", "", "| Question ID | Label | max_points | Context | Context SHA | Review | Warnings |", "|---|---|---:|---|---|---|---|"]
        for q in by_sample[sample]:
            warnings = "; ".join(q["warnings"]) or "NONE"
            context = q.get("context", {})
            lines.append(f"| `{q['question_id']}` | {q['display_label']} | {q['max_points'] if q['max_points'] is not None else 'UNSET'} | {context.get('status', 'NOT_CHECKED')} | `{context.get('sha256') or '-'}` | {'REVIEW_REQUIRED' if q['review_required'] else 'CLEAN_FOR_ACCEPT'} | {warnings} |")
        lines.append("")
    lines += ["## Response template", "", "Q1 clean: `ACCEPT_ALL / individual edits`", "", "Q1 H.3-D candidate ModelAnswer: `ACCEPT / EDIT / REJECT`", "", "Q1 H.3-D candidate Rubric: `ACCEPT / EDIT / REJECT`", "", "Q2 score reconciliation: `APPLY / EDIT / KEEP_UNSET` per question", "", "Q2 ambiguous criteria: teacher wording/points", "", "Q3 clean: `ACCEPT_ALL / edits`", "", "Q4 clean: `ACCEPT_ALL / edits`", "", "Q4 Problem 3 conflict: teacher decision", "", "Q4 reference images: `ACCEPT / RE-CROP`", "", "**Teacher responseがあるまで、ModelAnswer Confirm / Rubric Approve / Question Correctionを実行しません。**", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv(
        "DATABASE_URL", "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader"))
    args = parser.parse_args()
    result = build(args.database_url)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"json": str(OUT_JSON), "markdown": str(OUT_MD), "counts": result["counts"]}, ensure_ascii=False))
