"""Build a read-only H.3-E.0 final preflight report for Q4 Problem 2."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from scoring.db.database import create_session_factory
from scoring.db import models as m
from scoring.grading_execution import execution_rubric, snapshot_hash, validate_bundle
from scoring.grading_mapping import GradingInputAssembler
from scoring.grading_visual import snapshot_visual_assets
from scoring.pdf_native import canonical_hash, sha256_file


TEST = "e14aeeb5-924c-4c72-b2a2-583f1be9f48e"
SUBMISSION = "a3f18d80-78a7-41b1-9b07-9db3fe3056e6"
QUESTIONS = [
    "02669a76-cb99-4ea1-bfd4-c742ff1617a3",
    "705f1d12-4f19-4c33-b197-39212f24b3ca",
]


def worker_materials(bundle: dict, rubric: dict) -> dict:
    answer = bundle["student_answer"]
    materials = {
        "question_id": bundle["identity"]["question_id"],
        "question": bundle["question"]["context"]["effective_text"],
        "rubric": rubric,
        "reference_answer": bundle["model_answer"]["content"],
        "ocr": {page_id: {} for page_id in answer["page_ids"]},
        "grading_input_bundle_hash": bundle["bundle_sha256"],
    }
    if bundle.get("visual_assets"):
        materials["visual_assets"] = bundle["visual_assets"]
        materials["student_answer"] = {
            "source": "VISUAL_FROM_DOCUMENT",
            "asset_ids": answer["visual_asset_ids"],
            "source_page_ids": answer["page_ids"],
        }
    else:
        materials["reconstruction"] = {
            "id": answer["reconstruction_id"],
            "transcript": answer["answer_text"],
            "sha256": answer["sha256"],
        }
    return materials


def build(database_url: str, output: Path) -> dict:
    _, factory = create_session_factory(database_url)
    capability = json.loads(Path("artifacts/h3e0a/capability.json").read_text())
    question_root = Path("artifacts/h2b-verification").resolve()
    artifact_root = Path("artifacts").resolve()
    reference_root = (artifact_root / "h3c1-model-answer").resolve()
    # Match the production grader configuration, while never starting it.
    settings = {"model_id": capability["model_id"], "vision": True}
    generation = {"temperature": 0, "seed": 42, "top_k": 40, "top_p": 0.95,
                  "min_p": 0.05, "repeat_penalty": 1.0, "max_output_tokens": 4096}
    prompt = "selected-answer-grading.v1"
    rows = []
    with factory() as session:
        assembler = GradingInputAssembler(
            session, TEST, root=question_root, allowed_roots=[artifact_root],
            answer_root=artifact_root, reference_root=reference_root,
            visual_capability=capability)
        for qid in QUESTIONS:
            row = assembler.execution_preview(SUBMISSION, qid)
            if row["execution_state"] != "READY" or not row.get("bundle"):
                raise RuntimeError(f"preflight blocked for {qid}: {row['blockers']}")
            bundle = deepcopy(row["bundle"])
            validate_bundle(bundle)
            rubric = execution_rubric(bundle)
            assets = []
            if bundle.get("visual_assets"):
                assets = snapshot_visual_assets(
                    session, bundle, question_root=question_root,
                    answer_root=artifact_root, reference_root=reference_root)
            else:
                for ref in bundle.get("assets", []):
                    asset = session.get(m.TestQuestionAsset, ref["asset_id"])
                    # Q2(1) has no visual assets; this branch is retained for
                    # semantic parity with the production snapshot builder.
                    if asset is not None:
                        assets.append({"asset_id": asset.id, "sha256": ref["sha256"],
                                       "role": "question_context",
                                       "path": str((question_root / asset.artifact_ref).resolve())})
            snapshot = {
                "schema_version": "grading-execution.v1",
                "bundle": bundle,
                "prompt": prompt,
                "prompt_version": "selected-answer-grading.v1",
                "model_settings": settings,
                "generation": generation,
                # Production snapshots retain resolved paths for the worker;
                # snapshot_hash removes host paths before hashing.
                "assets": assets,
            }
            if bundle.get("visual_assets"):
                snapshot["visual_capability"] = capability
                snapshot["assets"] = assets
            snapshot["snapshot_sha256"] = snapshot_hash(snapshot)
            materials = worker_materials(bundle, rubric)
            image_payload = [
                {"role": ref.get("role"), "asset_id": ref["asset_id"],
                 "sha256": ref["sha256"], "mime_type": ref.get("mime_type")}
                for ref in bundle.get("visual_assets", [])
            ]
            rows.append({
                "question_id": qid,
                "mapping_state": row.get("mapping_state", "READY"),
                "execution_state": row["execution_state"],
                "blockers": row["blockers"],
                "bundle_sha256": bundle["bundle_sha256"],
                "bundle": bundle,
                "rubric_validation": "PASS",
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "snapshot": snapshot,
                "worker_visual_image_payload": image_payload,
                "worker_materials_has_visual_assets": "visual_assets" in materials,
                "worker_materials_student_visual_ids": materials.get("student_answer", {}).get("asset_ids", []),
            })
        jobs = list(session.scalars(select(m.GradingJob).where(m.GradingJob.test_id == TEST)))
        rub = session.scalar(select(m.RubricVersion).where(
            m.RubricVersion.test_id == TEST, m.RubricVersion.status == "approved"
        ).order_by(m.RubricVersion.version.desc()))
        result = {
            "phase": "H.3-E.0",
            "test_id": TEST,
            "submission_id": SUBMISSION,
            "rubric_version": {"id": rub.id, "version": rub.version,
                                "status": rub.status, "sha256": canonical_hash(rub.rubric_json)},
            "rows": rows,
            "visual_roles": ["question_context", "model_answer_reference", "student_visual_answer"],
            "visual_capability": {"model_id": capability["model_id"], "vision": capability["vision"]},
            "jobs_for_test": len(jobs),
            "grading_calls": 0,
            "score_feedback_created": 0,
            "source_sha256": "dd89f67075824aff671081c57916f25e21093b92cbf9e66d3d46fe5bd823c9f8",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_sha256"] = sha256_file(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    parser.add_argument("--output", default="artifacts/h3e0a/final-preflight.json")
    args = parser.parse_args()
    print(json.dumps(build(args.database_url, Path(args.output)), ensure_ascii=False, indent=2))
