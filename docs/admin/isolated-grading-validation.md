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
any build/run, and does not connect during config/build. Docker Compose v2 or later
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

## Stage A — Docker runtime validation without production resources

**Stage A passed on the server on 2026-10-14** (Engine 29.8.1, Compose v5.5.1).
See the actual-server follow-up in
`docs/internal/reports/j-grading-1d-containerized-acceptance.md` for evidence.
These commands prepare only empty
local fixtures, build the image, import Python modules and start help. They
must not run `export`, `import`, `acceptance`, `up`, a synthetic Job, or access
production PostgreSQL. Stage B is a separate approved procedure.

Run this block in Bash as a **nonroot deployment user** with local Docker
access. Substitute the repository location if different. Each failed command
stops; retain its evidence and investigate before proceeding. Do not use sudo
with inherited environment or load production `.env`.

### A–C. Repository and local Docker prerequisites

```bash
set -euo pipefail
cd /opt/llm-scoring
git status --short
test -z "$(git status --porcelain)"   # stop if dirty; do not stash/reset
# Operator must first publish the validation files; Codex does not commit/push.
git pull --ff-only
git status --short
test -z "$(git status --porcelain)"
git rev-parse HEAD
test "$(id -u)" -ne 0
test "$(id -g)" -ne 0

# Use the local daemon only. The Python launcher strips Docker env overrides;
# therefore its active stored context must also point to this same local socket.
docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}'
test "$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_ENV_FILES
unset GRADING_VALIDATION_READONLY_DATABASE_URL LLM_GRADER_DATABASE_URL

docker version
docker compose version
# Read-only inspection: if the existing app already uses this project name, STOP.
docker ps -a --filter label=com.docker.compose.project=llm-grading-validation --format '{{.ID}} {{.Names}}'
# Inspect any existing containers; do not remove/reuse them automatically.
test -z "$(docker ps -aq --filter label=com.docker.compose.project=llm-grading-validation)"
```

If the context is remote/rootless or local daemon is inaccessible, stop and
have the operator establish an approved local context; do not change the
application's Compose/Worker. The project collision test deliberately rejects
leftovers too. The server must have the validation files in its published
checkout before the pull/build; otherwise stop rather than claim deployment.

### D–E. Empty private mounts, config and build

```bash
umask 077
VALIDATION_STAGE_A_ROOT=$(mktemp -d /tmp/grading-validation-stage-a.XXXXXXXX)
export VALIDATION_UID="$(id -u)" VALIDATION_GID="$(id -g)"
mkdir -m 700 "$VALIDATION_STAGE_A_ROOT/work" "$VALIDATION_STAGE_A_ROOT/inputs" \
  "$VALIDATION_STAGE_A_ROOT/empty-question" "$VALIDATION_STAGE_A_ROOT/empty-answer" \
  "$VALIDATION_STAGE_A_ROOT/empty-socket" "$VALIDATION_STAGE_A_ROOT/evidence"
export VALIDATION_WORK_ROOT="$VALIDATION_STAGE_A_ROOT/work"
export VALIDATION_ALLOWLIST="$VALIDATION_STAGE_A_ROOT/inputs/allowlist.json"
export VALIDATION_QUESTION_ROOT="$VALIDATION_STAGE_A_ROOT/empty-question"
export VALIDATION_ANSWER_ROOT="$VALIDATION_STAGE_A_ROOT/empty-answer"
export VALIDATION_PG_SOCKET_ROOT="$VALIDATION_STAGE_A_ROOT/empty-socket"
export VALIDATION_READONLY_URL_FILE="$VALIDATION_STAGE_A_ROOT/inputs/empty-readonly-url"
printf '{}\n' > "$VALIDATION_ALLOWLIST"
: > "$VALIDATION_READONLY_URL_FILE"   # EMPTY: no DB credential, not a usable export
chmod 600 "$VALIDATION_ALLOWLIST" "$VALIDATION_READONLY_URL_FILE"

# Fixed explicit config; never merge the normal application Compose.
stage_a_compose() {
  env -i PATH="$PATH" HOME="$HOME" \
    VALIDATION_UID="$VALIDATION_UID" VALIDATION_GID="$VALIDATION_GID" \
    VALIDATION_WORK_ROOT="$VALIDATION_WORK_ROOT" VALIDATION_ALLOWLIST="$VALIDATION_ALLOWLIST" \
    VALIDATION_QUESTION_ROOT="$VALIDATION_QUESTION_ROOT" VALIDATION_ANSWER_ROOT="$VALIDATION_ANSWER_ROOT" \
    VALIDATION_PG_SOCKET_ROOT="$VALIDATION_PG_SOCKET_ROOT" VALIDATION_READONLY_URL_FILE="$VALIDATION_READONLY_URL_FILE" \
    docker compose --env-file /dev/null --project-directory "$PWD" \
    --project-name llm-grading-validation -f "$PWD/compose.validation.yaml" \
    --profile export --profile acceptance "$@"
}
# Capture both command and tee exit codes; failure stops subsequent execution.
stage_a_logged() {
  local label="$1"; shift
  local -a codes
  set +e
  "$@" 2>&1 | tee "$VALIDATION_STAGE_A_ROOT/evidence/$label.log"
  codes=("${PIPESTATUS[@]}")
  set -e
  printf '%s command_exit=%s log_exit=%s\n' "$label" "${codes[0]}" "${codes[1]}" \
    | tee "$VALIDATION_STAGE_A_ROOT/evidence/$label.exit"
  test "${codes[0]}" -eq 0 && test "${codes[1]}" -eq 0
}

stage_a_logged config-check python scripts/validation-compose.py config
stage_a_compose config --format json > "$VALIDATION_STAGE_A_ROOT/evidence/compose.json"
stage_a_logged build python scripts/validation-compose.py build
docker image inspect llm-grading-validation:1d --format '{{.Id}} {{json .Config.Entrypoint}} {{json .Config.Cmd}}' \
  > "$VALIDATION_STAGE_A_ROOT/evidence/image.txt"
```

The Compose file is JSON (valid YAML); real `compose config` must succeed and
the launcher must report `VALIDATION_ISOLATION_CONFIG_OK`. All six source
variables above point **only** inside the fresh fixture. Export's declared
mounts are empty placeholders and its service is never started. Acceptance
mounts only `/work` and the dummy allowlist.

Dockerfile-specific `Dockerfile.validation.dockerignore`, adjacent to the
selected Dockerfile, takes precedence over root `.dockerignore` in a supported
Docker build. Keep both files present in the published checkout. Build logs
must show successful context/ignore loading and each explicit COPY. Expected
COPY inputs: requirements, pyproject/README, src, three tests package files
and the one container entrypoint. Image inspection below checks resulting
contents; it cannot prove ignore precedence by itself. If the builder cannot
honor the Dockerfile-specific ignore file, STOP rather than upload a broader
context. Record Docker/Compose/builder versions and the build log.

### F–G. Import smoke and help-only start

```bash
stage_a_logged smoke stage_a_compose run --rm --no-deps --pull never \
  --entrypoint python acceptance -c '
import os
from pathlib import Path
import scoring.validation_staging
import tests.synthetic_validation
import tests.run_staged_synthetic_acceptance
import fastapi, httpx, psycopg, sqlite3, fitz
assert os.environ["PYTHONPATH"] == "/app"
assert not Path("/source").exists()
assert not Path("/run/secrets/readonly_database_url").exists()
assert not Path("/app/.env").exists() and not Path("/app/config").exists()
assert {p.name for p in Path("/app/tests").iterdir()} == {"__init__.py", "synthetic_validation.py", "run_staged_synthetic_acceptance.py"}
assert {p.name for p in Path("/app/scripts").iterdir()} == {"validation-container.py"}
assert not any("DATABASE_URL" in k or "RUNTIME_MANAGER" in k for k in os.environ)
p = Path("/work/stage-a-write-probe")
with p.open("x") as f: f.write("permission probe")
p.unlink()
print("STAGE_A_IMPORT_AND_NONROOT_WRITE_OK")
'

VALIDATION_HELP_NAME="grading-validation-stage-a-$(date -u +%Y%m%d%H%M%S)-$$"
stage_a_logged help stage_a_compose run --no-deps --pull never \
  --name "$VALIDATION_HELP_NAME" acceptance help
# Keep the stopped help container for inspection; no --rm here.
```

Smoke only imports modules and creates/removes one exact permission probe;
it does not create a DB/Job or invoke models. It checks that nonroot can write
`/work`, imports work under read-only rootfs/network-none and `/app` PYTHONPATH,
and packaging includes TestClient/httpx/PostgreSQL/SQLite dependencies. Python
bytecode writing is disabled; `/tmp` is writable bounded tmpfs. Help must show
only the implemented `help/export/import/acceptance` command syntax. No operation
other than help runs. Failed import/build/permission checks are not feature passes.

### H–J. Inspect and enforce actual container isolation

```bash
docker inspect "$VALIDATION_HELP_NAME" > "$VALIDATION_STAGE_A_ROOT/evidence/help-inspect.json"
python - "$VALIDATION_STAGE_A_ROOT/evidence/help-inspect.json" "$VALIDATION_WORK_ROOT" "$VALIDATION_ALLOWLIST" <<'PY'
import json, sys
c, = json.load(open(sys.argv[1]))
h, cfg = c["HostConfig"], c["Config"]
assert c["State"]["Status"] == "exited" and c["State"]["ExitCode"] == 0
assert cfg["Labels"]["com.docker.compose.project"] == "llm-grading-validation"
assert cfg["Entrypoint"] == ["python", "scripts/validation-container.py"]
assert cfg["Cmd"] == ["help"]
assert h["NetworkMode"] == "none" and h["Runtime"] == "runc"
assert not h["Privileged"] and h["ReadonlyRootfs"]
assert h["PidMode"] == "" and h["IpcMode"] != "host"
assert set(h["CapDrop"]) == {"ALL"} and not h.get("CapAdd")
assert "no-new-privileges:true" in h["SecurityOpt"]
assert not h.get("Devices") and not h.get("DeviceRequests")
assert not h.get("PortBindings") and not cfg.get("ExposedPorts")
assert not c["NetworkSettings"].get("Ports")
assert "/tmp" in h["Tmpfs"]
uid, gid = map(int, cfg["User"].split(":"))
assert uid > 0 and gid > 0
assert all(m["Type"] == "bind" or (m["Type"] == "tmpfs" and m["Destination"] == "/tmp") for m in c["Mounts"])
mounts = {m["Destination"]: m for m in c["Mounts"] if m["Type"] == "bind"}
assert set(mounts) == {"/work", "/inputs/allowlist.json"}
for target, source, writable in [("/work", sys.argv[2], True), ("/inputs/allowlist.json", sys.argv[3], False)]:
    m = mounts[target]
    assert m["Type"] == "bind" and m["Source"] == source and m["RW"] == writable
names = sorted(v.split("=", 1)[0] for v in cfg["Env"])
assert not any("DATABASE_URL" in n or "RUNTIME_MANAGER" in n or n.startswith("NVIDIA") for n in names)
print(json.dumps({"exit_code": c["State"]["ExitCode"], "network": h["NetworkMode"],
                  "runtime": h["Runtime"], "privileged": h["Privileged"],
                  "mount_targets": sorted(mounts), "environment_names": names,
                  "status": "STAGE_A_ISOLATION_OK"}, indent=2))
PY
# Confirm work root has no export, stage, SQLite, Job or acceptance files.
test -z "$(find "$VALIDATION_WORK_ROOT" -mindepth 1 -print -quit)"
git status --short
```

Keep evidence private; inspect contains only this no-secret Stage A container,
and the summary prints environment **names**, not values. Record config/build/
smoke/help/isolation exit codes, image ID, git SHA, help output and runtime/mount/
network/capability/port/device assertions. If any assertion fails, stop and retain
logs/container. Do not change DB/production Compose/Worker/GPU/runtime to fix it.
Analyze missing dependencies/COPY/import path/UID/mount or unsupported Docker
syntax and propose the smallest validation-only correction first.

After successful evidence collection, optionally remove **only** the exact
stopped help container with `docker rm "$VALIDATION_HELP_NAME"`. Retain the
private evidence root; no recursive cleanup is part of Stage A. A successful
Stage A verifies Docker packaging/startup/isolation only. J1d remains PARTIAL
until remaining required container/staged-data acceptance is established;
production-derived Stage B still requires separate approval.
