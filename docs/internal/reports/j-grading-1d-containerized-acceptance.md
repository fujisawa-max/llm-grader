# J.GRADING.1d — Containerized isolated grading acceptance

Status: **PARTIAL** (2026-10-14). Container configuration, isolation checks,
operator workflow and local synthetic acceptance are implemented. Docker is
not installed in this workspace, so image build, actual Compose rendering and
container execution remain unverified. These are not counted as passes.
No production export/acceptance was authorized or attempted. J.GRADING.1 is
not declared COMPLETE by synthetic acceptance.

## Deployment audit

Read the v4 architecture specification including Docker/runtime constraints,
`compose.yaml`, `Dockerfile.api`, runtime GPU wrapper, production and J1c
runbooks, exporter and synthetic runner/worker.

The ordinary Compose file has no explicit project name. The runtime wrapper
uses the repository as project directory (normally `llm-scoring`, unless the
operator overrides it). The actual deployed project name/networks/volumes
cannot be inspected without the host Docker daemon and remain unverified.
Declared resources: default network plus `runtime-internal` internal network;
`postgres_data`, `artifacts_data`, `llm_models`, `runtime_manager_state` volumes.
PostgreSQL16 is on the default network and exposes configurable port5432;
application DB URL contains the writable application credential. API mounts
artifact storage, runtime-manager mounts models/state/config. API entrypoint
is uvicorn; migration runs Alembic; runtime image contains llama-server and
GPU overrides are selected by `scripts/runtime-compose.py`. None is reused
or changed by validation.

Baseline/final content hashes of unchanged deployment files:

- `compose.yaml`: `45e46fd3447f2d8944b74dc347d6a6bfd0ba4cbbc7cb41fcacfdf8856fc24cff`
- `Dockerfile.api`: `788da1789f48b563e8a71b8e1639365beed91044345edadfd61eb38e98c45b42`
- `scripts/runtime-compose.py`: `c5041fc15180245e688fbb6607a743e8d66e2ad878ce9a6b57bb1416447c484a`

## Isolation architecture

Independent `llm-grading-validation` project has profile-scoped `export` and
`acceptance` one-shot services. Both default to help without operations.
No application stack override, permanent worker, API listening port or new
migration is introduced. Compose file uses JSON syntax, which is valid YAML,
so tests inspect the actual service definitions without a separate YAML parser.

Both explicitly use `network_mode: none` and `runtime: runc`, even if the host
Docker default runtime is NVIDIA. There are no ports, devices/GPU, privileged
mode, host PID/network, Docker socket or production environment entries. The
image filesystem is read-only, capabilities ALL dropped, no-new-privileges,
nonroot UID/GID and bounded temporary filesystem. A private fresh work root is
the sole writable persistent bind mount.

Export mounts exact question/answer artifact roots and PostgreSQL Unix socket
directory **read-only**, plus allowlist and private read-only credential file.
The entrypoint requires explicit `--approved-export`, validates an exact
Unix-socket-only SQLAlchemy URL, supplies
`GRADING_VALIDATION_READONLY_DATABASE_URL` inside export, then calls the
unchanged J1c `ReadOnlySource.postgres` and `export_validation_data`. No grants
are created and privilege checks are not weakened. A Unix socket may still
send SQL; the original effective-role and read-only transaction checks enforce
DB safety. No TCP/DNS/database-network/model-network path is allowed.

Acceptance has neither credential nor socket/source artifact mounts, and no
DB/runtime environment. It sees only the allowlist and copied export/stage
under `/work`. Import and acceptance directly reuse the J1c functions and
marked synthetic worker, not a parallel grading implementation. Results,
Jobs and Finalize records exist only in its separate SQLite stage. The
in-process authenticated FastAPI TestClient does not open a network listener.

A trusted operator/daemon is required: a root Docker administrator can alter
any container. A provisioned accessible PostgreSQL socket, suitable authentication,
readonly DB role and nonroot artifact permissions are prerequisites. If the
current production stack cannot supply these without changing its deployment,
STOP rather than joining its ordinary network or weakening the role checks.
No actual source socket/DB permission availability was assessed here.

## Image and launcher

`Dockerfile.validation` copies service source plus exactly the two existing
synthetic harness modules and the fixed entrypoint. Its dedicated build-context
allowlist excludes `.env`, configs, credentials, data, weights, logs and local
helpers. Python3.12.13 CPU slim base and top-level dependency versions are pinned;
transitive dependencies and base digest are not fully hash-locked. Image includes
psycopg binary, SQLite, FastAPI/httpx, SQLAlchemy and PyMuPDF, no CUDA/models.
`PYTHONPATH=/app` makes the copied `tests` package importable from the script
entrypoint; a subprocess regression proves the corresponding import behavior.
Actual wheel installation/build remains unverified without Docker.

`validation-compose.py` uses only the dedicated file/project with
`--env-file /dev/null`, strips inherited Compose/DB/runtime variables, validates
rendered JSON, and accepts only fixed build/export/import/acceptance operations.
It rejects added service fields/resources, mount changes, unsafe namespaces,
root UID/GID, source/output overlaps, missing/symlink paths and loose private
permissions. It never prints DB credentials. Defaults cannot run acceptance,
and import/acceptance require a trusted64hex manifest hash. Existing exporter
and staging safeguards remain responsible for exact records/assets/CAS hashes.

## Operator workflow and limitations

The admin runbook includes build/config checks, nonroot ownership and source
mount prerequisites, private inspection of the exact container, explicit
approved export, separate trusted manifest capture, import, synthetic acceptance,
production API baseline comparison, failed-run handling and exact-path manual
cleanup. No wildcard cleanup/volume deletion is provided. Fresh export/stage
roots cannot be overwritten, and failed output is retained for diagnosis.

Remaining required evidence: actual Docker build and `compose config`; inspect
actual containers/image ID and network/mount/runtime boundaries; execute local
container synthetic acceptance against disposable evidence; only after separate
operator approval export the dedicated server data and run acceptance; compare
actual production baseline. Source access cannot be claimed from static tests.

## Validation

- Final focused configuration + J1c staging tests: **56 passed**, 1 warning.
  Includes actual-definition checks, negative resource exposure, inherited
  environment stripping, socket-only URL rejection, help-only entrypoint,
  original-source artifact closure and isolated Worker→Review→Finalize.
- Full backend: **1119 passed, 2 skipped, 23 warnings**, 293.15s. No failures.
  Docker checks are explicitly unverified, not included as feature passes.
- Standalone isolated Worker→Review→Finalize test from `/tmp` (outside repository
  CWD/config): **1 passed**, demonstrating no working-directory config dependency.
- Ruff on both new scripts and touched/new tests: passed.
- compileall service/tests/new scripts: passed.
- git diff --check plus new-file whitespace checks: passed.
- Docker Compose config/build/container execution: **unverified**, Docker absent.
- Initial focused run:47passed/1failed because a pre-existing negative test
  expected HASH/LINEAGE while the exporter correctly rejected a changed material
  SHA as MATERIAL_ARTIFACT_MISSING. The test now accepts this additional exact
  fail-closed code; no exporter behavior changed. Final focused run passes.
- An interim full run was interrupted while final isolation changes were being
  completed; only the final complete run is used as evidence.

Production Jobs/export/connections: **0**. Real OCR/LLM/grader/runtime calls:
**0**. Existing J1c fixture executes two disposable synthetic Jobs, with real
Review/Finalize routing against SQLite only. No production configuration,
application semantics, migrations, deployment, commit or push changed.

## Files and exact Git status

Initial `git status --short`: empty. New files are service-facing deployment,
operator support and tests requested for this phase, not Codex-only helpers.

Final exact `git status --short`:

```text
 M docs/admin/isolated-grading-validation.md
 M tests/test_validation_staging.py
?? Dockerfile.validation
?? Dockerfile.validation.dockerignore
?? compose.validation.yaml
?? docs/internal/reports/j-grading-1d-containerized-acceptance.md
?? requirements.validation.txt
?? scripts/validation-compose.py
?? scripts/validation-container.py
?? tests/test_validation_compose.py
```

No staging, commit, push or production execution was performed.

## Stage A preparation follow-up — 2026-10-14

Instructions: `/tmp/j.grading.1d-2.md`. Initial working tree was clean. Audited
Dockerfile/context ignore/COPY inputs, `/app` PYTHONPATH, dependencies, CLI
argument dispatch, fixed project, network-none/runc, nonroot security and
mount boundaries. No implementation correction was required. The earlier
runbook assumed real source paths even for config/build; Stage A now gives
an exact no-production-resource sequence using fresh empty private fixtures.

Added ordered server commands for clean git status / operator `git pull --ff-only`,
local Docker/Compose version and project collision checks, rendered config,
image build/ID, import and nonroot-write smoke, help-only start, actual stopped
container inspection/assertions and private exit/log evidence. Only acceptance
service smoke/help starts; the export service has dummy paths but never starts.
No source credential/socket/artifact is supplied, no synthetic Job is created,
and no production Compose/Worker/model/OpenWebUI changes are made.

The smoke checks required imports, exact image helper files, absent production
config/secret paths and `/work` permissions. The actual-container checklist
checks network-none, runc, nonroot UID/GID, readonly rootfs, cap-drop,
no-new-privileges, no ports/GPU/devices/host namespaces, exact two private bind
mounts and environment names without printing secret values. Image build logs
and builder versions remain required to establish Dockerfile-specific ignore
application; image file inspection alone is not claimed as proof.

Local verification: **30 focused tests passed**, 1 warning; all Stage A Bash
blocks pass `bash -n`; all explicit Docker COPY inputs exist; `git diff --check`
passes. Only documentation changed, so backend behavior/full-suite evidence
above remains applicable. Actual Docker config/build/container execution and
server results are **unverified** because Docker is unavailable here. No
production connection, export, synthetic Job, model call, deployment, commit or
push occurred. J.GRADING.1d remains **PARTIAL**; Stage B remains separate.

Exact follow-up `git status --short`:

```text
 M docs/admin/isolated-grading-validation.md
 M docs/internal/reports/j-grading-1d-containerized-acceptance.md
```
