# Q5 PostgreSQL cutover and rollback

The legacy source is immutable: `/tmp/j1-q5-pilot/pilot.sqlite` and
`/tmp/j1-q5-pilot/artifacts`. Do not delete or edit them.

The import retains every UUID, foreign key, selected reconstruction, job,
criterion score, event and immutable JSON snapshot. Existing jobs are copied,
never executed. Operational `test_materials.storage_ref` and
`grading_job_items.raw_response_path/normalized_result_path` absolute paths are
mapped from the legacy artifact root to `/opt/llm-scoring/data/q5-artifacts`.
Historical absolute paths within immutable snapshots remain historical evidence;
they are not rewritten/rehashed. Relative artifact references are unchanged.

The pilot owner ID `1ab60f19-09c7-4f46-9288-1ab4f0b014de` remains Course owner.
The operator explicitly approved assigning dedicated login credentials to this
same account; no merge with an admin/other teacher is performed.

## Gate and application

`scripts/migrate_q5_sqlite_to_postgres.py` defaults to read-only dry-run.
Supply the DB URL through `DATABASE_URL` (never print it). Arguments:

```
--source /tmp/j1-q5-pilot/pilot.sqlite
--source-root /tmp/j1-q5-pilot/artifacts
--target-root /opt/llm-scoring/data/q5-artifacts
--test-id 196893ba-f57f-41a9-974e-8d51b697d672
--report /protected/report.json
```

Only add `--apply` after staging counts/FKs/browser/results/SHA pass.
Conflicts are reported without overwriting. All inserts are one transaction;
constraint errors roll back the entire import. Retry is a no-op for identical
rows. Subsequent authorized account edits can intentionally produce a User
conflict on a full re-import; do not overwrite those edits to bypass it.

Persistent artifacts are copied first and SHA-verified; originals remain.
Backup-set path and manifests are recorded in the phase report.

## Rollback before cutover

An import exception rolls back all inserted rows. No manual DELETE/re-ID/reset.
Keep existing 3002/8001 authentication validation services unchanged.

## Rollback after successful import/cutover

1. Stop only the new Q5 API/frontend processes identified in the cutover report.
   Never stop OpenWebUI or borrowed/owned model runtimes.
2. Preserve the current grader DB with a new dump before any recovery work.
3. Restore the pre-import custom-format `grader.dump` into a **new** recovery DB
   using `createdb` then `pg_restore --exit-on-error -d <new recovery DB>`.
   Do not reset/drop or restore over the live grader DB.
4. Validate the restored DB's revision, counts and pre-import hashes.
5. Explicitly select the recovery connection in a protected service config;
   preserve the pre-change config, then restart only the affected API/frontend.
6. Confirm login/health and existing records. The legacy Q5 SQLite/artifact
   files and persistent artifact copy remain available, byte-identical.
7. The old SQLite frontend/API cannot be blindly restored using current auth
   code. Restoring legacy serving requires its original deployable code version.

Production PostgreSQL restore is not executed in this phase; only a separate
staging restore is performed. A post-cutover rollback is an explicit operator
operation, not an automatic destructive cleanup.
