# J.GRADING.1c — Production Data Staging for Isolated Synthetic Acceptance

Status: **READY_FOR_PRODUCTION_VALIDATION**. Export/import/staging, enforced read-only local-source verification, isolated Job → Worker → Review → Finalize, focused/full regression, static checks, and the operator runbook are complete. Production data access/execution has not been attempted. J.GRADING.1c is not COMPLETE; J.GRADING.1 remains PARTIAL for its outstanding deployed/runtime acceptance.

## Export choice and existing architecture audit

| Option | Existing capability | Decision |
|---|---|---|
| Authenticated read-only API | Authoring history/confirmed routes provide immutable snapshots, the preview provides executable policy/hash, and crop routes expose selected diagram bytes. | Useful for operator baseline and ownership checks. There is no complete supported API contract for exact saved authoring FK records, linked RubricVersion handles, original submission material closure, and all byte references. Do not infer missing records from DTOs. |
| Read-only PostgreSQL transaction | Exact current schema rows can be selected by explicit IDs and Test ownership while preserving snapshot hashes/relational identities. | Selected for the operator-invoked exporter. Requires an existing read-only DB role plus an enforced read-only transaction. |
| New HTTP export service | Would require a new production auth/audit/file-delivery surface. | Not added. The implementation is a private operational CLI/service module; no production route, queue, or Worker behavior changes. |

Audited `tests/synthetic_validation.py`, revision grading/execution/definition, DB models/repository/Worker, authoring immutability, review/finalization, registration/artifact handling, the authoring/preview APIs, and `docs/admin/production-runbook.md`. The ordinary Worker claims by ID and recovers stale Jobs across its DB. This remains unchanged; a physically separate validation DB is mandatory. Review reads frozen revision policy, and Finalize writes an append-only event without publishing.

The CLI export path accepts PostgreSQL only and takes its credential from `GRADING_VALIDATION_READONLY_DATABASE_URL`, never a command-line credential. It checks effective writes for the current role and SET ROLE memberships, ownership/privileged role attributes, table writes, sequence advancement, schema/database creation/TEMP, and executable application volatile/security-definer functions. It rejects write-capable credentials before reading Test data, opens `REPEATABLE READ` / `READ ONLY`, attests the actual setting, and rolls back on exit. It never creates users/roles/grants. CLI failures emit fixed codes rather than driver exceptions/URLs/paths/content.

The independent local source fixture opens SQLite with physical `mode=ro` plus `query_only=ON` and an explicit read transaction. An actual attempted UPDATE is denied. The PostgreSQL permission-rejection path has a controlled driver unit test; a live PostgreSQL server was unavailable locally. The PostgreSQL catalog/role preflight and actual production credential/OS mount permissions remain operator acceptance checks. No production connection was used to fill that gap.

## Explicit scope and dependency closure

There is no default Test or all-Test export. The operator supplies exact Test, owning teacher, two revision IDs, two Submission IDs/pins, Question IDs, and expected A/B Question/Answer/score-level values. Each same-Test table query includes Test scope; student queries include Offering scope. The exporter verifies the owning active teacher and rejects missing, foreign, ambiguous, extra-edition, or incomplete identities. This tool supports the requested two-edition/two-submission/single-executable-Question acceptance, not general bundle export/import.

| Records | Why required / boundary |
|---|---|
| Course, CourseOffering, Test | Ownership and relational closure; active B preserved. |
| Minimal User rows | Owner and existing created/confirmed/approved actor FK closure. IDs/timestamps and audit actor FKs retained; no production passwords, emails, or sessions selected. Staging owner is a local teacher; other audit actors inactive. |
| TestQuestion rows for frozen IDs | Relational handles required by Job/review/FKs. Current body/content is not grading authority. No extra Question is fetched to repair a missing identity. |
| ConfirmedAuthoringRevision A/B | Exact snapshot, canonical SHA, revision/edit version, and original confirmation actor FK. |
| Exact referenced TestAuthoringRevision rows | Required FK and parent lineage; saved snapshot/hash must equal the confirmed snapshot. No latest draft is substituted. |
| Linked RubricVersion rows | Existing legacy compatibility Job FK selected by `generation_metadata.authoring_revision_id`. The real existing row is copied; no dummy policy is manufactured. Its mutable rubric JSON does not supply executable grading semantics. |
| Student, StudentSubmission S1/S2 | Student/Offering identity and immutable A/B pins. Student labels become staging pseudonyms; IDs remain unchanged. |
| TestMaterial closure | Snapshot source materials; registered Submission manifests; their SHA-bound original PDF/image material IDs; associated immutable bytes. Cross-Test materials are rejected. |

ModelAnswer rows are unnecessary: primary/alternatives and provenance come from the confirmed grading definition. TestQuestionAsset rows and mutable correction/review rows are also unnecessary for pinned execution: required accepted asset/correction metadata is already frozen. No existing Job/JobItem, reconstruction, extraction, teacher decision, auth session, publication, or event history is exported. Only dedicated Test Job/event counts are read for the baseline.

## Manifest, artifacts, and immutable verification

`isolated-grading-export.v1` contains the tool/source label/timestamp, explicit allowlist, active revision, lineage and snapshot SHA, supported grading schema/interpreter, Submission pins, per-record identities/canonical hashes, full record hash, artifact namespace/relative reference/identity/SHA/size/media type, material dependencies, transformations, baseline counts, and canonical manifest SHA. It contains no DB URL, credentials, or source absolute filesystem paths. Exact immutable snapshots remain unmodified in the private data payload; original source-path evidence already present inside a snapshot cannot be rewritten without changing its hash.

Actual rows and bytes are checked in addition to the manifest. Import requires the trusted manifest SHA recorded separately at export, so a bundle cannot be silently resealed during transfer. Record schema/inventory/FK checks reject extra or missing rows. Required artifact closure is derived again from stored snapshots and actual registration JSON, not accepted from an arbitrary file list.

Registration-only JSON is supported together with original `source_material_ids` / `source_sha256s` and each referenced page image. The JSON, original source PDF/images, and rendered page bytes are all preserved and hash-checked. Unsupported mapped-answer JSON is rejected rather than rewritten or supplemented. Accepted frozen visual references retain namespace-relative identity, SHA, geometry/page data, and source provenance. Shared reference bytes are copied without changing the confirmed definition. Per-file and aggregate size limits fail closed (100 MiB per artifact; 512 MiB per export).

Source reads use component-wise `O_NOFOLLOW`; absolute/traversing relative refs and symlink escapes are rejected. Only explicitly mounted roots and allowlisted material metadata are resolved. Output/staging roots must be new, absolute, non-symlink paths disjoint from source/protected/export roots. Files/directories are private (0600/0700). No existing directory is overwritten or recursively deleted.

## Transactional staging and synthetic input

Import verifies the complete package before creating a stage, copies and rechecks bytes, and creates a new `validation.sqlite` using current application metadata. Record insertion uses one transaction with FK enforcement and deferred cycle checks. An injected insert failure rolls back every row. `INCOMPLETE.json` prevents use after failure; `READY.json` is written only after DB/artifact checks. The execution runner independently compares actual staged DB records and FK integrity with the sealed export/receipt before use.

Manifest transformations are limited to environment storage refs/filenames, staging user authentication/display settings, and student display identifiers. Confirmed/saved snapshots, source IDs, actor FKs, Question identities, Submission pins, policy, source/crop geometry, and artifact bytes/hashes are not transformed. No production config is loaded for execution, and no source DB credential is needed by the import/runner.

The existing J1b helper supplies the two specified synthetic answer strings only in the staging environment to J1a's in-memory assembler. They are excluded from export and never saved to production or `StudentAnswerReconstruction`. They appear only in isolated validation Job bundles/result provenance. No new grading policy or synthetic criterion is created.

## Local Job → Worker → Review → Finalize result

The test creates A/S1, then B/S2 through the real authoring/submission APIs, deliberately changes mutable Question/Answer/Rubric projections in the disposable source DB, exports/imports the real closure, and runs the existing synthetic harness against the staged DB. Both Jobs are created while B is active.

| Target | Frozen revision | Question / ModelAnswer | Levels | Score / max | Review / Finalize |
|---|---|---|---|---|---|
| S1 | A / 第1版 | Edition A question / Edition A answer | `[0,10]` | 10 / 10 | Correct A content/label, finalized |
| S2 | B / 第2版 | Edition B question / Edition B answer | `[0,5,10]` | 5 / 10 | Correct B content/label, finalized |

The runner reuses J1b Job construction, the shared sealed execution package, actual ordinary JobWorker claim/persistence, and real authenticated Review/Finalize APIs. It checks package hashes, pin/edition/content/score isolation, duplicate Job completion and idempotent finalization, exact imported snapshots before/after, zero reconstruction rows, and unpublished results. RuntimeManager/grader constructors/chat, reconstruction, and publication methods are patched to fail within the isolated validation process only; none is called. `acceptance.json` records IDs/hash/score/finalization evidence without credentials or unrelated student information.

The ordinary Worker pointed at the independent source DB cannot see either synthetic Job ID and returns no work. J1b regression also rejects ordinary/unmarked Jobs in the validation Worker, verifies exact DB identity and Test allowlisting, and avoids global stale recovery when normal work exists. Production isolation additionally requires the separate private host/volume described in the runbook; it is not inferred from a metadata flag.

The local source SQLite file SHA is identical before/after export and complete staged execution; active B and Submission pins remain unchanged, and source Job/reconstruction counts remain zero. Production health/baseline/host identity is **unverified**, because production access is prohibited in this phase.

## Negative/security validation

New tests exercise unauthorized ownership, nonallowlisted Test/Submission/revision IDs, cross-Test revised records, missing FK dependencies, altered snapshot hashes, unsupported schema/levels, wrong pins, extra students/credentials, changed/missing artifacts and original-source PDFs, registration-source lineage, traversal/symlink escapes, unlisted artifacts, synthetic-input export leakage, wrong trusted manifest checksum, existing root collision, source/destination overlap, wrong Worker DB identity, actual read-only source write denial, writable PostgreSQL role rejection, and injected import rollback/not-ready execution. Rehashed invalid records still fail independent structural/semantic checks.

J1a/J1b regressions retain package identity, authorization, sealed asset/hash rejection, ordinary/synthetic Worker separation, null-pin legacy rejection, concurrent claim arbitration, and retry idempotency. No feature test is skipped due infrastructure.

## Validation and migration

- New staging/export/import group: **26 passed**.
- Focused staging + J1a/J1b revision grading + execution + grading-definition group: **80 passed**.
- Full backend suite: **1,089 passed, 2 skipped, 23 warnings**, 292.90 seconds. The skips are existing tests; no new staging feature validation was skipped. Warnings are existing SQLAlchemy model collection warnings and a Starlette deprecation warning.
- Ruff on changed Python: passed. `python -m compileall -q src/scoring tests`: passed.
- `git diff --check` and separate whitespace checks for all untracked new files: passed. Both CLI `--help` smoke checks passed.
- No frontend/API contract changed; no frontend build required.
- No migration. Only a new disposable SQLite schema is created; no production migration, reset, or Alembic stamp. Repository head remains `0018_revision_lineage`.
- Production connections/data retrieval/Jobs/config changes: **0**. Real model/OCR/LLM/RuntimeManager calls: **0**. The J1c execution test creates two local staged synthetic Jobs only.

## Operator runbook and limitations

See [isolated grading validation runbook](../../admin/isolated-grading-validation.md) for DBA-provisioned read-only credentials, exact dedicated production allowlist, baseline checks, secure export/checksum transfer, artifact verification, fresh-root import, isolated execution, authenticated Review/Finalize, post-run production baseline comparison, and strictly limited manual cleanup. Production access/execution requires explicit operator approval and is not automated by this work.

No live PostgreSQL/production ACL or artifact mount was available/used locally. The production permission preflight must pass with the actual read-only role; a write-capable role is not accepted merely because the code issues SELECTs. Source absolute material locations must lie below the explicitly read-only roots; unsupported/missing data stops the process. Operator protected-root inventory and separate host/volume enforcement are required—source paths are deliberately not inferred from a manifest.

Successful later production-derived isolated acceptance will not validate ordinary production Worker startup, queue/runtime wiring, real grading models, or scoring quality. J.GRADING.1 remains **PARTIAL** until its remaining production runtime acceptance items are evaluated separately. J.GRADING.1c is not COMPLETE without approved staging of the real dedicated production records and unchanged production baseline verification.

## Files changed and exact git status

Initial working tree was clean. Only these service implementation/tests/docs were added:

```text
?? docs/admin/isolated-grading-validation.md
?? docs/internal/reports/j-grading-1c-production-validation-staging.md
?? src/scoring/validation_staging.py
?? tests/run_staged_synthetic_acceptance.py
?? tests/test_validation_staging.py
```

No credentials, local DB/artifacts, or operator path files are tracked. No commit, push, deployment, or production action was performed.
