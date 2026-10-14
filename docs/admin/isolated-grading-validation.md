# Isolated revision grading acceptance — operator runbook

This procedure is **not yet production-executed**. It is for an explicitly
approved export of the dedicated validation Test only. It does not execute the
production Worker, modify PostgreSQL, start RuntimeManager, or exercise real
model quality. Operator approval is required before any production connection.

## Required access and isolation

- Use an existing DBA-provisioned read-only PostgreSQL credential from the
  secret store. This tool never provisions roles or changes grants.
- Effective privileges, including roles reachable with `SET ROLE`, must have
  no INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER, sequence USAGE/UPDATE,
  schema CREATE, database CREATE/TEMP, superuser/role creation/database
  creation/BYPASSRLS, privileged predefined write/maintenance/signal roles,
  or executable application volatile/security-definer
  functions. PostgreSQL commonly grants TEMP/CREATE or function EXECUTE through
  PUBLIC; the DBA must independently review/revoke those effective privileges
  before this tool can accept the role. Grant SELECT only to the required
  dependency tables listed below and the two baseline count tables.
- The exporter additionally opens `REPEATABLE READ`, `READ ONLY`, checks the
  actual transaction setting, and rolls back on every exit. Write-capable
  roles are rejected before reading Test data. Do not use the application or
  database-owner credential even with a read-only transaction setting.
- Mount source artifacts read-only. Supply exact existing `question_import`
  and `answer_import` roots in a private operator JSON file. No network or
  arbitrary path fetch is supported. The file and DB credential stay outside
  Git/export manifests/logs.
- Export and staging must use fresh, explicit absolute paths without `..` or
  symlink components. Keep staging on a separate validation host/private
  volume inaccessible to production Workers, with no production config and no
  network access to grader/OCR/RuntimeManager. The stage uses its own SQLite
  database. Never point a production Worker at it.
- Install the repository's dev dependencies in the isolated validation
  process (`TestClient`/httpx is used to exercise actual teacher APIs). The
  synthetic runner is test support, not an exposed production API.

Read closure: `users` (IDs/role/timestamps only; no credentials), `courses`,
`course_offerings`, `tests`, exact `test_questions`, `test_materials`,
`test_authoring_revisions`, `confirmed_authoring_revisions`, exactly linked
`rubric_versions`, `students`, and `student_submissions`. Only counts are read
from `grading_jobs` and `domain_events`. No Job history, reconstruction,
auth-session, student-identity PDF, or unrelated student record is exported.
ModelAnswer content comes from immutable snapshots; `model_answers` is not
read. RubricVersion rows are copied for their existing FK/linked identity,
not to supply grading policy.

## 1. Allowlist and baseline

Save this allowlist in the operator workspace. All IDs and expected values are
explicit; the tool has no all-Test/default allowlist:

```json
{
  "test_id": "9fdf06c2-6fc2-4d30-a424-1c3db726bf59",
  "teacher_id": "<authenticated owning teacher UUID>",
  "question_ids": ["1b915527-42cc-488d-9554-17f36d08fca3"],
  "revisions": [
    {"id": "9fd3981c-ee1b-4046-8525-a98f687e8b06", "question_text": "Edition A question", "model_answer": "Edition A answer", "levels": [0, 10]},
    {"id": "b9a17f19-b38e-4d8e-8969-2773fa70b0e6", "question_text": "Edition B question", "model_answer": "Edition B answer", "levels": [0, 5, 10]}
  ],
  "submissions": [
    {"id": "fe0f55c4-29e6-401d-a765-6e9153f23643", "revision_id": "9fd3981c-ee1b-4046-8525-a98f687e8b06"},
    {"id": "5f9a6b5d-dd30-482a-99ef-e1be6b9600fb", "revision_id": "b9a17f19-b38e-4d8e-8969-2773fa70b0e6"}
  ]
}
```

Use authenticated read-only APIs to record active B, S1/A and S2/B pins,
dedicated Test events, and `/api/v1/health` job counts before export. Do not
query unrelated unfiltered Job listings. Record unavailable counters/version
information as **unverified**. The source manifest also records Test-scoped
DB counts; repeatable-read comparisons attest export consistency, not the
absence of concurrent changes by other production users.

Source roots JSON is a mapping of the two namespaces to their actual absolute
source directories. Protected-roots JSON is an explicit list of production
artifact/config/data directories and any local source DB paths. These files
contain environment paths and must not be committed or attached to reports.

## 2. Export and integrity

Load `GRADING_VALIDATION_READONLY_DATABASE_URL` from the secret store without
printing it. Never pass a credential on the command line or enable SQL echo.
The following variables identify private operator files/fresh directories;
they do not identify service production configuration.

```bash
python -m scoring.validation_staging export \
  --allowlist "$VALIDATION_ALLOWLIST" \
  --source-roots "$VALIDATION_SOURCE_ROOTS_FILE" \
  --source-environment dedicated-production-validation \
  --root "$VALIDATION_EXPORT_ROOT"
```

Record the printed `manifest_sha256` in a trusted channel as
`VALIDATION_MANIFEST_SHA`. Preserve that value separately from the copied
bundle. Transfer only this private export directory to the isolated validation
host. Unset the source credential there before import/execution.

The exporter verifies same-Test ownership, exactly two allowed editions and
A/B lineage, exact saved/confirmed snapshots and canonical SHA, supported Web
grading schema/interpreter, expected Question/Answer/levels/maxima, S1/A and
S2/B pins, full FK closure, and every required artifact byte hash. Registration
JSON, its original source material IDs/SHA-bound PDF/images, and its referenced
page images are copied without changing bytes or page IDs. `material_dependencies`
binds the registered-answer provenance to the complete original-source closure.
Frozen Question/Answer references retain namespace-relative paths,
geometry, SHA, and provenance. No synthetic answer is present in the export.

`manifest.json` is written last. Missing completion marker, missing dependencies,
unrelated rows/files, unsupported source JSON, unexpected source format, absent
or changed artifact, symlink, path traversal, or policy mismatch aborts. Do
not repair source snapshots or substitute current rows/artifacts to obtain a
pass. Incomplete output is retained only for operator inspection; it is not a
valid export.

## 3. Import into a fresh stage

```bash
python -m scoring.validation_staging import \
  --allowlist "$VALIDATION_ALLOWLIST" \
  --export-root "$VALIDATION_EXPORT_ROOT" \
  --protected-roots "$VALIDATION_PROTECTED_ROOTS_FILE" \
  --expected-manifest-sha256 "$VALIDATION_MANIFEST_SHA" \
  --root "$VALIDATION_STAGE_ROOT"
```

Import verifies the trusted manifest checksum, individual record/artifact
inventory, actual bytes, immutable contracts, and FK closure before creating
the root. Source and destination roots must be disjoint. Existing roots are
never overwritten. Private directories/files use 0700/0600 permissions.

Rows are inserted into `validation.sqlite` in one transaction with SQLite
foreign keys enabled and deferred for the revision/Test cycles. An injected
insert failure rolls back all rows. `READY.json` is written only after all
imports, immutable references, and hashes have been checked; `INCOMPLETE.json`
means the stage must not execute. No database migration is required; application
Alembic head remains `0018_revision_lineage`.

Only storage locations and staging actor/student display/authentication fields
are transformed, as recorded in the manifest. All relational IDs, audit actor
FKs, Submission pins, saved/confirmed snapshots, grading policy, page/crop
bytes, and hashes remain intact. No production password/email/session token is
selected or copied. Non-owner audit users are inactive in staging. The owner
uses an ephemeral local authenticated session only in the isolated API fixture.

## 4. Isolated Job → Worker → Review → Finalize

```bash
python -m tests.run_staged_synthetic_acceptance \
  --allowlist "$VALIDATION_ALLOWLIST" \
  --expected-manifest-sha256 "$VALIDATION_MANIFEST_SHA" \
  --root "$VALIDATION_STAGE_ROOT"
```

The runner revalidates the actual SQLite rows against the export. It supplies
`Synthetic answer for edition A acceptance` and
`Synthetic answer for edition B acceptance` only to the shared in-memory
assembler. Synthetic answers live in validation Job bundles/results only;
no `StudentAnswerReconstruction` is created in any environment.

Both Jobs are created while B is active. Expected results are S1/第1版/A/
`[0,10]`/10 of 10 and S2/第2版/B/`[0,5,10]`/5 of 10. The normal shared Worker
claim/result persistence and real authenticated Review/Finalize routers run
against the staged database. Repeat Job execution and finalization are
idempotent. Grader/OCR/RuntimeManager construction and publication calls are
explicitly forbidden. The runner writes `acceptance.json` with IDs, hashes,
scores, finalization references, and zero real-model/OCR calls.

The synthetic Worker accepts only the exact staged DB and allowlisted marked
Jobs. It refuses to invoke ordinary DB-wide stale recovery if any normal Job
is present. Never run the synthetic worker with production credentials/DB.
An already executed stage is not silently rerun or overwritten; use a fresh
stage for another acceptance.

## 5. Production baseline and cleanup

Recheck the same read-only production APIs after isolated acceptance. Confirm
active B, original pins, dedicated event counts, and health Job counts remain
unchanged. Record concurrent/unobservable changes accurately; do not infer zero
changes from the local result alone. No production Job/reconstruction/result
or queue/model setting should have been touched.

Retain the report/checksums according to the operator's data policy. Cleanup
is a manual, separately approved deletion of the **exact newly created export
and staging directories only**. First confirm their paths have no symlinks,
their manifest/READY receipt match the trusted checksum and dedicated Test,
and they are disjoint from all protected roots. Do not use wildcard cleanup,
delete parent directories, or delete source artifacts/production directories.
Remove private allowlist/path files and source credentials from the validation
host when no longer needed. This tool performs no automatic recursive cleanup.

Successful isolated acceptance proves production-derived data can travel
through the shared pipeline. It does not establish the ordinary production
Worker/runtime/model deployment or actual grading quality. J.GRADING.1's
remaining production runtime items must be assessed separately.
