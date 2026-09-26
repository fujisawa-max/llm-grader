#!/usr/bin/env python3
"""One production-path Ornith rubric-draft smoke for H.3-C.1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring.model_answer_import import RubricDraftGenerator
from scoring.runtime.manager import RuntimeManager, RuntimeProfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", default="artifacts/h3c1-model-answer")
    args = parser.parse_args()
    root = Path(args.artifact_root)
    manifests = sorted(root.glob("sampleQ1/*/import-manifest.json"))
    if len(manifests) != 1:
        raise SystemExit("sampleQ1 model-answer import manifest is missing or ambiguous")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    entry = next(x for x in manifest["drafts"]
                 if x["question_id"] == "8a2a7955-2347-4c67-8581-f800721ec558")
    profile = RuntimeProfile(
        runtime_id="ornith_rubric_draft", runtime_type="managed",
        model_id="ornith15-35b-q4km",
        model_path="/opt/models/Ornith-1.5-35B-A3B/Q4_K_M/Ornith-1.5-35B-Q4_K_M.gguf",
        server_binary="/opt/llama.cpp/build/bin/llama-server", vision=False,
        context_size=8192, batch_size=512, ubatch_size=512, gpu_layers=999,
        startup_timeout_seconds=180, stop_timeout_seconds=10,
        log_path=str(root / "runtime-ornith-rubric.log"),
    )
    manager = RuntimeManager({profile.runtime_id: profile})
    generator = RubricDraftGenerator(manager)
    result = generator.generate(entry, {"effective_text": "current authoritative question context; teacher review draft only"})
    output = {"schema_version": "model-answer-rubric-smoke.v1", "question_id": entry["question_id"],
              "student_data": False, "grading": False, "generator": result,
              "runtime_audit": generator.audit, "runtime_status": manager.status(profile.runtime_id)}
    path = root / "sampleQ1" / "rubric-draft-smoke.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result.get("status"), "path": str(path),
                      "audit": generator.audit}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
