#!/usr/bin/env python3
"""Create or verify a read-only artifact backup manifest for I.5 smoke checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring.recovery import build_artifact_manifest, verify_artifact_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path,
                        help="manifest destination (required when creating a manifest)")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        report = verify_artifact_manifest(args.root, json.loads(args.verify.read_text(encoding="utf-8")))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2
    if args.output is None:
        parser.error("--output is required when creating a manifest")
    manifest = build_artifact_manifest(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(args.output), "files": len(manifest["files"]),
                      "manifest_sha256": manifest["manifest_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
