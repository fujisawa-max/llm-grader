"""Run the explicitly authorized H.3-D.0 reconstruction for one submission."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scoring.db.models import StudentSubmission, TestMaterial
from scoring.pdf_native import sha256_file
from scoring.runtime import RuntimeManager, RuntimeProfile
from scoring.student_answer import SelectedImageStudentAnswerReconstruction
from scoring.student_answer_runtime import RuntimeStudentAnswerStages


ROOT = Path("/opt/llm-scoring")
ARTIFACT_ROOT = ROOT / "artifacts"
DATABASE_URL = os.environ.get(
    "LLM_GRADER_DATABASE_URL",
    "postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader",
)
SUBMISSION_ID = "fcf9d128-4dbb-4aee-b49b-1c715fdcfd16"
QUESTION_ID = "8a2a7955-2347-4c67-8581-f800721ec558"
EXPECTED_SOURCE_SHA = "aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba"
AUDIT_DIR = ARTIFACT_ROOT / "h3d0-reconstruction" / SUBMISSION_ID


def runtime_setup():
    registry = {
        item["name"]: item
        for item in json.loads(Path("/opt/llm-eval/vision-models.json").read_text())["models"]
    }
    roles = {
        "ocr": "ricoh-qwen3vl-8b-q8",
        "math_ocr": "unimumer-qwen35-4b-q4km",
        "ornith_reconstruction": "ornith15-35b-q4km",
    }
    profiles = {}
    config = {
        "models": {},
        "generation": {
            "temperature": 0,
            "seed": 42,
            "top_k": 40,
            "top_p": 0.95,
            "min_p": 0.05,
            "repeat_penalty": 1.0,
            "max_output_tokens": 4096,
        },
    }
    for role, name in roles.items():
        model = registry[name]
        profiles[role] = RuntimeProfile.from_mapping(
            role,
            {
                "runtime_type": "managed",
                "model_id": name,
                "model_path": model["model"],
                "mmproj_path": model["mmproj"],
                "server_binary": model["server"],
                "context_size": model["context"],
                "batch_size": model["batch"],
                "ubatch_size": model["ubatch"],
                "startup_timeout_seconds": 180,
                "stop_timeout_seconds": 10,
                "vision": True,
                "log_path": str(AUDIT_DIR / f"{role}.log"),
                "additional_args": ["--reasoning-budget", "0"],
            },
        )
        config["models"][role] = {
            "model_id": name,
            "request_timeout_seconds": 300,
        }
    return RuntimeManager(profiles), config


def main():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL)
    manager, config = runtime_setup()
    events = []
    calls = {"ricoh": 0, "unimumer": 0, "ornith_reconstruction": 0}
    forbidden = {
        "model_answer", "rubric", "max_points", "score", "grading_policy",
        "grading_feedback", "previous_grading_result",
    }

    def audit(event):
        events.append(event)
        if event.get("event") == "call":
            calls[event["role"]] = calls.get(event["role"], 0) + 1
        if event.get("event") == "request":
            payload = event.get("payload", {})
            # The reconstruction request is the only request whose payload is
            # audited for grading-data leakage; evidence text itself is untrusted.
            if event.get("role") == "ornith_reconstruction":
                serialized = json.dumps(payload, ensure_ascii=False).lower()
                leaked = sorted(k for k in forbidden if k in serialized)
                if leaked:
                    raise RuntimeError(f"RECONSTRUCTION_GRADING_DATA_LEAK:{leaked}")
            (AUDIT_DIR / f"event-{len(events):04d}-{event.get('event')}-{event.get('role', 'system')}.json").write_text(
                json.dumps(event, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )

    with Session(engine) as session:
        submission = session.get(StudentSubmission, SUBMISSION_ID)
        if submission is None:
            raise RuntimeError("SUBMISSION_NOT_FOUND")
        material = session.get(TestMaterial, submission.material_id)
        source = Path(material.storage_ref).resolve()
        before = sha256_file(source)
        if before != EXPECTED_SOURCE_SHA:
            raise RuntimeError(f"SOURCE_SHA_MISMATCH:{before}")
        source_bytes_before = hashlib.sha256(source.read_bytes()).hexdigest()
        (AUDIT_DIR / "baseline.json").write_text(
            json.dumps({"submission_id": SUBMISSION_ID, "question_id": QUESTION_ID,
                        "source_sha256": before, "source_path_relative": material.storage_ref,
                        "source_bytes_sha256": source_bytes_before}, indent=2), encoding="utf-8"
        )

        def resolve_images(payload):
            pages = payload["source_answer"]["pages"]
            return [(pages[0]["page_id"], source)]

        stages = RuntimeStudentAnswerStages(
            manager, config,
            runtime_ids={"ricoh": "ocr", "unimumer": "math_ocr",
                         "ornith_reconstruction": "ornith_reconstruction"},
            image_resolver=resolve_images,
            audit=audit,
        )
        service = SelectedImageStudentAnswerReconstruction(session, artifact_root=ARTIFACT_ROOT)
        run, output = service.run(
            SUBMISSION_ID, QUESTION_ID, ricoh=stages.ricoh,
            unimumer=stages.unimumer,
            ornith_reconstruction=stages.ornith_reconstruction,
            config={"phase": "H.3-D.0", "selected_question": QUESTION_ID,
                    "runtime_models": {k: v["model_id"] for k, v in config["models"].items()}},
        )
        session.commit()
        after = sha256_file(source)
        source_bytes_after = hashlib.sha256(source.read_bytes()).hexdigest()
        if after != before or source_bytes_after != source_bytes_before:
            raise RuntimeError("SOURCE_IMAGE_MUTATED")
        report = {
            "submission_id": SUBMISSION_ID,
            "question_id": QUESTION_ID,
            "source_sha256_before": before,
            "source_sha256_after": after,
            "source_bytes_sha256_before": source_bytes_before,
            "source_bytes_sha256_after": source_bytes_after,
            "run_id": run.id,
            "run_status": run.status,
            "run_selected": run.selected,
            "output": output,
            "model_calls": calls,
            "events": len(events),
            "runtime_statuses": manager.statuses(),
            "grading_job_created": 0,
            "ornith_grading_calls": 0,
        }
        (AUDIT_DIR / "result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
