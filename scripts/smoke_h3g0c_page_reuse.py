"""One-page H.3-G.0c smoke: compact Ricoh once, persist, load twice."""
import hashlib
import json
import sys
import time
from pathlib import Path

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.page_extraction import PageExtractionArtifactStore
from scoring.pdf_native import sha256_file
from scoring.student_answer_runtime import RuntimeStudentAnswerStages
sys.path.insert(0, str(Path(__file__).parent))
from run_h3g_batch import MANIFEST, manager_setup


def main():
    root = Path("/opt/llm-scoring")
    _, factory = create_session_factory("postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    row = next(x for x in MANIFEST if x["sample_identity"] == "s1" and x["test_id"] == "70a63c23-f1b1-46b7-852c-046148b6f451")
    with factory() as session:
        submission = session.get(m.StudentSubmission, row["submission_id"])
        source = Path(session.get(m.TestMaterial, submission.material_id).storage_ref)
    before = sha256_file(source)
    manager, config = manager_setup()
    started = time.monotonic()
    stages = RuntimeStudentAnswerStages(manager, config, runtime_ids={"ricoh": "ocr"})
    _, compact = stages.ricoh_page_compact(source)
    elapsed = time.monotonic() - started
    response = stages.last_raw
    response_sha = hashlib.sha256(json.dumps(response, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    artifact = PageExtractionArtifactStore(root / "artifacts/student-answer").save(
        row["submission_id"], before, compact["regions"], response_sha=response_sha,
        model_version=config["models"]["ocr"]["model_id"], prompt_version="ricoh-compact-v2",
    )
    reused = PageExtractionArtifactStore(root / "artifacts/student-answer").load(
        row["submission_id"], before
    )
    manager.stop("ocr")
    result = {
        "submission_id": row["submission_id"], "source_sha256": before,
        "source_sha_after": sha256_file(source), "elapsed_seconds": elapsed,
        "regions": len(compact["regions"]), "warnings": compact["warnings"],
        "artifact": artifact, "reuse_same_artifact": reused["artifact_id"] == artifact["artifact_id"],
        "ricoh_calls": 1,
    }
    out = root / "artifacts/h3g0c"
    out.mkdir(parents=True, exist_ok=True)
    (out / "smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
