"""Fixed one-shot entrypoint. No connection or execution without explicit subcommand."""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url
from scoring.validation_staging import ReadOnlySource, export_validation_data, stage_validation_data
from tests.run_staged_synthetic_acceptance import run_acceptance


def validate_socket_url(raw):
    url = make_url(raw)
    if (url.drivername != "postgresql+psycopg" or url.host or url.port
            or dict(url.query) != {"host": "/source/postgres"}):
        raise ValueError("VALIDATION_UNIX_SOCKET_URL_REQUIRED")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["help", "export", "import", "acceptance"])
    parser.add_argument("--approved-export", action="store_true")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.operation == "help":
        parser.print_help()
        return
    policy = json.loads(Path("/inputs/allowlist.json").read_text())
    if args.operation == "export":
        if not args.approved_export:
            raise ValueError("VALIDATION_OPERATOR_APPROVAL_REQUIRED")
        raw = Path("/run/secrets/readonly_database_url").read_text().strip()
        # Unix socket only: even DNS/TCP attempts are forbidden in export mode.
        validate_socket_url(raw)
        os.environ["GRADING_VALIDATION_READONLY_DATABASE_URL"] = raw
        with ReadOnlySource.postgres(raw) as source:
            manifest = export_validation_data(source, policy,
                source_environment="same-host-dedicated-validation",
                artifact_roots={key: Path("/source") / key for key in
                                ("question_import", "answer_import")},
                output_root=Path("/work/export"))
        print(json.dumps({"manifest_sha256": manifest["manifest_sha256"]}))
    else:
        if Path("/source").exists() or Path("/run/secrets/readonly_database_url").exists():
            raise ValueError("VALIDATION_SOURCE_RESOURCE_EXPOSED")
        if any("DATABASE_URL" in key or "RUNTIME_MANAGER" in key for key in os.environ):
            raise ValueError("VALIDATION_SOURCE_ENVIRONMENT_EXPOSED")
        if args.operation == "import":
            stage_validation_data(Path("/work/export"), Path("/work/stage"), policy,
                protected_roots=[Path("/source"), Path("/app"), Path("/inputs")],
                expected_manifest_sha256=args.manifest_sha256)
        else:
            run_acceptance(Path("/work/stage"), policy,
                           expected_manifest_sha256=args.manifest_sha256)
        print(json.dumps({"status": args.operation.upper()}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Driver exceptions and URLs never escape to container logs.
        import re
        safe = str(exc) if re.fullmatch(r"(?:STAGING|VALIDATION)_[A-Z_]+", str(exc)) else "VALIDATION_FAILED"
        raise SystemExit(safe)
