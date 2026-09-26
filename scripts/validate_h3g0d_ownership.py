"""Read-only ownership audit for the existing H.3-G.0c page artifact."""
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.page_extraction import PageExtractionArtifactStore
from scoring.region_ownership import classify_regions


TEST = "70a63c23-f1b1-46b7-852c-046148b6f451"
SUBMISSION = "fcf9d128-4dbb-4aee-b49b-1c715fdcfd16"
SHA = "aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba"


def main():
    _, factory = create_session_factory("postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    with factory() as session:
        questions = list(session.scalars(select(m.TestQuestion).where(
            m.TestQuestion.test_id == TEST, m.TestQuestion.is_gradable.is_(True))))
    qtexts = {}
    for q in questions:
        bits = str(q.question_number).split(".")
        ref = f"問題{bits[0]}" if len(bits) == 1 else f"問題{bits[0]} ({bits[1]})"
        qtexts[ref] = q.question_text or ""
    store = PageExtractionArtifactStore(Path("artifacts/student-answer"))
    artifact = store.load(SUBMISSION, SHA)
    regions = classify_regions(artifact["regions"], qtexts)
    store.save_ownership(SUBMISSION, SHA, regions)
    counts = {x: sum(r["ownership"] == x for r in regions)
              for x in ("STUDENT_HANDWRITING", "PRINTED_QUESTION", "MIXED", "UNKNOWN")}
    routing = []
    for ref in sorted({r["question_ref"] for r in regions}):
        own = [r for r in regions if r["question_ref"] == ref]
        students = sum(r["ownership"] == "STUDENT_HANDWRITING" for r in own)
        printed = sum(r["ownership"] == "PRINTED_QUESTION" for r in own)
        uncertain = sum(r["ownership"] in {"MIXED", "UNKNOWN"} for r in own)
        routing.append({"question_ref": ref, "student_regions": students,
                        "printed_regions": printed, "mixed_unknown": uncertain,
                        "routing_status": "READY" if students and not uncertain else
                        "REVIEW_REQUIRED" if uncertain else "BLOCKED"})
    result = {"artifact_id": artifact["artifact_id"], "submission_id": SUBMISSION,
              "source_sha256": SHA, "total_regions": len(regions), "counts": counts,
              "regions": regions, "routing": routing,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "student_answer_printed_routed": 0, "reconstruction_created": 0,
              "grading_jobs": 0, "ornith_grading": 0}
    out = Path("artifacts/h3g0d")
    out.mkdir(parents=True, exist_ok=True)
    (out / "ownership.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
