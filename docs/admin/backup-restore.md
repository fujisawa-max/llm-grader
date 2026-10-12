# Backup, verification, and restore

Backups are immutable operational artifacts. A DB dump and artifact manifest
must share one timestamped backup-set identifier.

## Create a backup set

```bash
set -euo pipefail
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SET="/srv/backups/llm-grader/$STAMP"
mkdir -p "$SET"
pg_dump --format=custom --file "$SET/database.dump" "$DATABASE_URL"
PYTHONPATH=/opt/llm-scoring .venv/bin/python scripts/build_backup_manifest.py \
  /srv/llm-grader/artifacts --output "$SET/artifacts.manifest.json"
printf '%s\n' "$STAMP" > "$SET/backup-set.txt"
```

Do not include `DATABASE_URL` or other secrets in shell history, logs, or this
document. Copy the artifact tree using the approved storage tool; do not
delete or rewrite live artifacts.

## Verify without changing production

```bash
PYTHONPATH=/opt/llm-scoring .venv/bin/python scripts/backup_verify.py \
  /srv/llm-grader/artifacts "$SET/artifacts.manifest.json" \
  --db-backup "$SET/database.dump"
```

The verifier checks manifest SHA, missing/mismatched/extra artifacts, and uses
`pg_restore --list` when available. A restore dry-run uses a new temporary
PostgreSQL instance and a temporary artifact root; it must never target the
production database. Verify that every referenced artifact exists and that each
SHA matches before starting the API.

## Restore sequence

1. Stop frontend, worker, and backend; keep OpenWebUI and borrowed runtimes
   untouched.
2. Restore the dump into a new temporary validation database.
3. Restore the matching artifact backup into a temporary artifact root.
4. Run `backup_verify.py` and DB/artifact consistency checks.
5. Start API, worker, and frontend against the temporary environment.
6. Run a read-only teacher audit and health checks.
7. Resume grading only after an explicit operational approval.

Production restore is deliberately not performed by this project workflow.
