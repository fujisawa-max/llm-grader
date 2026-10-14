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
  volume, or use the strictly isolated same-host Docker procedure below. In
  either case it must be inaccessible to production Workers, with no production config and no
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

## Same-host Docker validation (J.GRADING.1d)

A separate physical machine is preferable, but the pre-production server may
use this explicitly separate project. **No production export or acceptance has
been performed by this change.** This is an operator workflow, not a deployment
replacement. Use `scripts/validation-compose.py`; do not combine these services
with `compose.yaml`, GPU overrides, production networks or `.env`. No `up` is
needed: each invocation is a one-shot `run --rm --no-deps`. Default command is
help only; `up` does not connect or run acceptance.

### Boundaries and prerequisites

- Project is fixed to `llm-grading-validation`; image is CPU Python 3.12.13 with
  pinned top-level dependencies in `requirements.validation.txt`. The dedicated
  Dockerfile-specific context ignore file allows source plus exactly the two
  validation harness modules and entrypoint. No config/secrets/model weights,
  production `.env`, artifacts, or development helpers enter the image.
- Both services use `network_mode: none` and explicitly `runtime: runc`, no ports, no devices/GPU/NVIDIA,
  no privileged mode, no host namespace, no Docker socket, nonroot numeric
  UID/GID, all capabilities dropped, no-new-privileges, read-only image and
  bounded tmpfs. Only private `/work` is persistent/writable.
- **Export is Unix-socket only**, not TCP or a production Docker network.
  An existing PostgreSQL Unix socket directory must be available to a bind
  mount, with peer/password authentication appropriate to the read-only role.
  URL must be exactly `postgresql+psycopg://<role>:<password>@/<database>?host=/source/postgres`
  (percent-encode credentials; no TCP host/port or additional driver parameters).
  Existing sockets inside an inaccessible container are not automatically
  exposed. If no approved socket directory is available, STOP; do not alter
  PostgreSQL configuration/Compose or join its network as a workaround.
- DBA prerequisites and J1c privilege gates above remain unchanged, including
  PUBLIC privileges and reachable roles. A read-only mount does **not** make
  socket SQL read-only; the existing exporter role/transaction gates do that.
- Source mount allowlist: exact question-import root, exact answer-import root,
  socket directory, private allowlist file, private credential file. All are
  read-only. Do not use a host root/ancestor containing unrelated data. The
  wrapper rejects root paths, symlinks, overlapping output/input roots, missing
  files, root UID/GID, and loose private-file/directory permissions.
- Acceptance mounts **only** the private `/work` (export/stage/results) and
  allowlist, with no source artifact mount, credential file or DB environment.
  Network is absent; ordinary workers cannot see its SQLite, which must not be
  published or mounted into the production stack. Review/Finalize uses in-process
  FastAPI TestClient without opening a listening port.
- This is trusted-operator containment, not protection against root/Docker
  administrators who intentionally alter mounts/image/commands. The Docker
  daemon must be local and trusted. Do not use shell tracing or a credential
  on CLI. Do not save `docker inspect` output containing export secrets; the
  URL is read from a file only inside export, never a Compose environment value.

### Prepare and validate without connecting

Create a **new private** operator workspace outside the repository and all
production roots, owned by the nonroot numeric UID/GID that will run the
container. Do not reuse or overwrite an existing export/stage directory.
Prepare the exact allowlist above with owning teacher ID. Keep secret/path
files private and outside Git. Set these nonsecret path variables explicitly:

```bash
export VALIDATION_UID="$(id -u)" VALIDATION_GID="$(id -g)"
export VALIDATION_WORK_ROOT=/srv/grading-validation/run-UNIQUE
export VALIDATION_ALLOWLIST=/srv/grading-validation/operator/allowlist.json
export VALIDATION_QUESTION_ROOT=/actual/question-imports
export VALIDATION_ANSWER_ROOT=/actual/answer-imports
export VALIDATION_PG_SOCKET_ROOT=/actual/postgresql-socket-directory
export VALIDATION_READONLY_URL_FILE=/srv/grading-validation/operator/readonly-url
```

The work directory must already exist mode 0700 and inputs mode 0600, owned
and readable by the selected UID. A root-only Docker user should use a dedicated
nonroot UID/GID rather than set 0. All source files must be readable by that UID;
never change production permissions broadly to obtain access. The credential
file contains only the existing `GRADING_VALIDATION_READONLY_DATABASE_URL`
value, provisioned from the secret store without logging; it is loaded into that
variable inside export only. No credential is inherited from host environment.

```bash
python scripts/validation-compose.py config
python scripts/validation-compose.py build
```

The launcher uses `--env-file /dev/null`, one explicit Compose file/project,
strips production/Compose/DB/runtime variables, validates rendered JSON before
any build/run, and does not connect during config/build. Docker Compose v2
with JSON config output and `run --pull never` is required. Missing Docker,
unsupported syntax, missing paths/permissions or unsafe configuration stops.
Build uses package-registry networking only in Docker's build phase; no source
DB is connected. Pinned top-level versions do not yet constitute a fully
hash-locked transitive supply-chain build; record the built image ID.

Inspect the rendered service configuration privately using the same explicit
`--env-file /dev/null -p llm-grading-validation -f compose.validation.yaml`
flags and profiles. Verify exact mount sources/destinations, readonly flags,
`NetworkMode=none`, no ports/devices, capabilities, user and image entrypoint.
For actual-container inspection, create a default-help acceptance container
with these flags (`compose create acceptance`), inspect its **exact container
ID** using `docker inspect`, then remove only that stopped container. Do not
start export during inspection. No long-running Worker is launched.

### Explicit approved execution

After operator approval, record production API baseline as described above.
Then:

```bash
python scripts/validation-compose.py export --approved-export
# Record printed manifest SHA separately in a trusted channel.
export VALIDATION_MANIFEST_SHA=<recorded-64-hex-sha>
python scripts/validation-compose.py import --manifest-sha256 "$VALIDATION_MANIFEST_SHA"
python scripts/validation-compose.py acceptance --manifest-sha256 "$VALIDATION_MANIFEST_SHA"
```

Export writes `/work/export`; import writes **fresh** `/work/stage`; acceptance
writes `/work/stage/acceptance.json` and validation-only Job/results in its
SQLite. Export container exits and its secret/source mounts disappear before
acceptance runs. The modes use the existing J1c services and identical A/B
worker/review/finalization checks, not an alternative policy assembler.

Read-only role failure reports `STAGING_*` without raw driver credentials.
Fix effective grants through the DBA, not the exporter. Failed socket/network
setup stops rather than falling back to TCP. Existing/incomplete output is
never overwritten or automatically deleted. Investigate its exact path; for
retry use a fresh private work root and new trusted export checksum. Preserve
partial evidence, and never repair immutable records to force acceptance.

After acceptance, recheck **production** API baseline separately. No production
baseline is inferred from staged results. Record actual image ID, Compose
version/config/isolation inspection, A/B hashes/scores and zero real model/OCR
calls. J1d COMPLETE requires that actual-server evidence; J.GRADING.1 ordinary
runtime/model acceptance remains separate.

Cleanup: `run --rm` removes one-shot containers only; default-help inspection
containers can be removed by exact ID. Do not run `down -v` against a production
project or use wildcard recursive cleanup. Apply the preceding manual approved
cleanup policy to the exact private newly created work directory and credentials,
after checking receipts/protected roots. No production volumes are created,
deleted or changed by this Compose file.
