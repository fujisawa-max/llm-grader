#!/usr/bin/env python3
"""Verify an artifact manifest and inspect a PostgreSQL backup without restore."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from scoring.recovery import verify_artifact_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only backup verification")
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--db-backup", type=Path,
                        help="Optional pg_dump custom-format file to inspect with pg_restore --list")
    args = parser.parse_args()

    report = {
        "artifact": verify_artifact_manifest(
            args.artifact_root,
            json.loads(args.manifest.read_text(encoding="utf-8")),
        ),
        "database": {"checked": False, "valid": None},
    }
    if args.db_backup:
        restore_tool = shutil.which("pg_restore")
        if not restore_tool:
            report["database"] = {"checked": False, "valid": None,
                                   "reason": "pg_restore_not_installed"}
        elif not args.db_backup.is_file():
            report["database"] = {"checked": True, "valid": False,
                                   "reason": "backup_file_missing"}
        else:
            result = subprocess.run(
                [restore_tool, "--list", "--exit-on-error", str(args.db_backup)],
                capture_output=True, text=True, check=False,
            )
            report["database"] = {
                "checked": True,
                "valid": result.returncode == 0,
                "entries": len([line for line in result.stdout.splitlines() if line.strip()]),
                "error": result.stderr.strip() or None,
            }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["artifact"]["valid"] and report["database"].get("valid", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
