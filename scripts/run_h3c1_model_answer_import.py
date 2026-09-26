#!/usr/bin/env python3
"""Run the H.3-C.1 source-first import without confirming answers or rubrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring.db.database import create_session_factory
from scoring.model_answer_import import ARTIFACT_ROOT, import_all


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    parser.add_argument("--artifact-root", default=str(ARTIFACT_ROOT))
    args = parser.parse_args()
    _, factory = create_session_factory(args.database_url)
    root = Path(args.artifact_root)
    with factory() as session:
        report = import_all(session, root)
    report_path = root / "completion-preflight.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
