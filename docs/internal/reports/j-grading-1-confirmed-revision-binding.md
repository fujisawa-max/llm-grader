# J.GRADING.1 — Confirmed Revision Binding

## Result

**READY_FOR_PRODUCTION_VALIDATION.** After J.GRADING.0 and J.GRADING.0a made the confirmed Web snapshot a complete executable grading contract, this phase binds new Web Submissions and all derived grading jobs to that contract. The full backend suite and focused revision-binding suite pass. No migration is needed; Alembic remains at `0018_revision_lineage`.

No production grading or model inference was run. The revision-binding tests use disposable local databases, isolated files, and a synthetic grader. No production data, deployment, commit, or push was involved. This report retains the initial PARTIAL investigation below as historical context, then records the resumed implementation and final validation in detail.

## Historical initial PARTIAL diagnosis

The following sections preserve the original stop-condition report from before the J.GRADING.0/0a authority decision and implementation. Statements such as “After architecture unchanged” and “Required decision before resuming” describe that earlier point in time; they are superseded by the completed implementation and validation section at the end of this report.

## Baseline

- HEAD: `78a9a914f532d7b0530d0d9d73fd133add5d67c4`.
- Initial `git status --short`: empty.
- Current migration head: `0018_revision_lineage`.
- Submission and GradingJob **already** have nullable `confirmed_authoring_revision_id` FKs, added by migration `0017_confirmed_revision` (file `0017_confirmed_authoring_revision.py`). Adding duplicate revision columns is not the solution.
- Existing FK membership does not itself enforce same-Test membership, binding immutability or full grading-package consistency. No new migration/version was created.

## Before architecture / entry-point map

| Stage | Entry points / inspected modules | Existing behavior / mutable dependency |
|---|---|---|
| Submission API | `api/domain.py`, POST `/tests/{tid}/submissions` | Direct JSON submission delegates to `DomainService.submission`; multi-page registration delegates to `source_registration.register_submission` |
| Image/source import | `student_submission_import.StudentSubmissionImportService` | Stable source identity and retry lookup; new source Submission delegates to the same DomainService; retry returns existing Submission |
| Binding today | `domain.py:117` | Copies `Test.active_confirmed_revision_id`, or null. Does not require an active confirmed revision for all formal/legacy Tests; no Test row lock/refresh at binding; no enforced immutable binding |
| OCR/extraction | `student_answer.py`, `api/student_answers.py` | Reads current `TestQuestion` and assets for target and context. Source image and extraction artifacts have hashes; confirmed revision is not the effective Question lookup |
| Reconstruction | `StudentAnswerReconstructionInputBuilder`, extraction/reconstruction services, `reconstruction_artifacts.py` | Current Question hierarchy/context is used; stored reconstruction input/output hashes protect particular artifacts, not a whole-Test revision definition |
| Readiness / assembler | `grading_context.py`, `grading_mapping.GradingInputAssembler` | Current Questions, corrections, current ModelAnswers and approved RubricVersion; Test-level readiness; does not select the Submission's immutable revision |
| Selected-answer grading | `api/domain.py`, POST `/tests/{tid}/grading-jobs`, `grading_execution.create_execution_job` | Creates a sealed bundle/model settings snapshot, but assembler reads current formal content; this job creation path does not populate the existing confirmed-revision column |
| Legacy domain grading | Same Test job endpoint, `DomainGradingJobAdapter.create_legacy_job` | Copies a common Submission revision pin and rejects mixed pins, but prepares current formal inputs plus filesystem assignment grading levels. ID propagation alone is not revision safety |
| Standalone CLI/filesystem jobs | `api/app.py`, POST `/api/v1/jobs`, `JobRepository.create_job`, orchestration | Can create jobs without a Test/DB Submission link. These require an explicit legacy boundary; cannot be silently associated with latest Test edition |
| Worker / retry | `db/worker.py`, `grading_execution.py`, `grading_inputs.py` | Selected jobs verify sealed package hashes and use frozen inputs; legacy jobs use StageRequest/domain overlays and assignment contracts. This protects a prepared job, not earlier/later OCR, new requests or review lookups |
| Teacher review | `grading_review.py`, `api/grading_review.py`, `teacher_grading.py` | Historical result artifacts are retained, but display/context/model answer/rubric/max totals are loaded from current rows. Teacher decisions also require the referenced RubricVersion to remain approved |
| Finalize / publication | `grading_actions.py`, grading-review endpoints | Uses current review detail/current Test total when validating and persisting finalization; finalized events are append-only/idempotent. Current authoring guard prevents unsafe reprojection |

Existing relationships include Test/Question IDs, RubricVersion IDs, source material IDs, extraction/reconstruction IDs and artifact/context/bundle hashes. They are useful audit evidence, but none substitutes for an immutable whole-Test effective definition. Grading UI currently has no consistently server-supplied `第N版` identity for every path; revision label computation must be shared with authoring history in the future.

## Proven stop-condition evidence

Two disposable local SQLite fixtures were used through existing services. Probe scripts/results are outside the repository. No existing fixture PDFs or service files were changed.

### 1. External discrete scoring levels are not frozen in authoring

Using the existing `tests.mapping_fixture` and `GradingInputAssembler`/`prepare_inputs` contracts:

1. Capture `canonical_hash(test_authoring.projection(...))`.
2. Prepare inputs with valid assignment criterion levels `[0, 10]`.
3. Change only the external assignment rubric to valid levels `[0, 5, 10]` with distinct partial-credit conditions.
4. Prepare inputs again.

Observed:

- Both preparations accepted.
- Authoring snapshot hash unchanged.
- Effective `rubric_data.criteria[*].levels` and allowed scores changed.
- Database Question, Answer and approved Rubric content unchanged.
- Grading jobs created: **0**.

`grading_inputs.prepare_inputs` compares approved criterion IDs/points/descriptions, max score and sum aggregation, but then copies the external `rubric_data`, including levels/conditions. Those levels affect allowed scores and model grading requests. They cannot be reconstructed from a criterion description/max points alone.

The current immutable snapshot could retain levels **if** already present inside criterion JSON. It does not require or populate them for normal authoring, and the legacy path does not require full equality of external levels to those embedded values. The counterexample concerns a supported path, not a claim that every confirmed revision lacks levels.

### 2. Successful confirmation does not imply complete executable grading policy

Using a fresh authoring fixture with complete Question, Answer and criterion points:

- Final Review `can_confirm=true`.
- Confirm returned **200**.
- Saved snapshot exactly equals confirmed snapshot.
- Confirmed criteria have no levels.
- `grading_execution.execution_rubric` rejects the derived rubric with **`不正な配点・許容点数`**.
- `teacher_grading._criterion_definitions` similarly requires nonempty levels (`TEACHER_GRADING_LEVELS_MISSING`).

Inventing all-or-nothing levels or generating partial-credit rules would alter grading policy and violates this phase's constraints. Selecting a current external assignment later would violate the immutable-basis invariant.

### 3. Other adapter/inventory gaps

- Changing only `TestQuestion.title` leaves authoring projection hash unchanged but changes EffectiveQuestionContextBuilder's context hash. This is a context/audit completeness gap; it is **not** asserted to change the current prompt text, which primarily consumes `effective_text`.
- Current authoring formal projection writes `content={'items': ...}` without `schema_version='test-question-content.v1'`. The existing effective-context builder rejects the confirmed projection with **`UNSUPPORTED_CONTENT_SCHEMA`**, reproduced locally. A revision-aware adapter needs a deliberate deterministic content conversion; changing global formal rows is not a safe shortcut.
- Legacy visual grading reads `rubric_json.teacher_review.reference_assets`. Authoring projection captures criteria and generation metadata, not necessarily that complete Rubric JSON envelope. New authoring diagram records do preserve important crop/source identities, so a frozen adapter can potentially use them, but equivalence to every legacy reference contract cannot be assumed.
- Correction-history rows and some asset attributes are read from DB outside the captured Question metadata. Each needs a frozen value or explicit non-semantic provenance treatment.

The **decisive stop reason is missing authoritative grading levels/conditions**; the content-schema and metadata findings identify additional work for the adapter, not permission to silently alter scoring semantics.

## After architecture

Unchanged. Existing nullable pins remain as they were, assemblers still use current formal rows, and `AUTHORING_HISTORICAL_GRADING_BASIS_UNSUPPORTED` plus readiness publication guards remain enforced. No unsafe interim release is proposed.

## Required decision before resuming

Define where the teacher-approved executable rubric levels/conditions and required visual reference metadata become part of the immutable confirmed definition. Possibilities to evaluate explicitly:

- Preserve/import an existing approved executable rubric/assignment policy into future authoring snapshots **before confirmation**, with exact criterion/score/reference validation and teacher review.
- Require levels already embedded in the confirmed criterion JSON and fail closed for incomplete confirmed revisions; specify how a teacher creates a complete new revision.

Do not synthesize missing score rules, attach current external levels at grading time, or rewrite old immutable snapshots. The choice determines migration/compatibility and normal authoring usability; it was not inferred in this run.

## Implementation design once definition completeness is resolved

- Reuse the existing Submission pin. Bind at first durable Submission creation, taking the same Test row lock/refresh boundary used by confirmation; validate same-Test confirmed ownership/hash. Refuse absent confirmed basis with a structured Japanese-guided error. Existing importer retries return the original immutable binding.
- Enforce immutable Submission and job pins in services/DB where practical; derive jobs from Submission, never active Test. Explicitly separate standalone legacy CLI jobs rather than manufacturing a pin.
- Build one immutable revision definition adapter: Questions/ancestors/scores, Answers/alternatives, complete executable Rubric, diagrams and provenance exclusively from the pinned revision. Never combine it with current approved Rubric/current formal Question content.
- Preserve frozen canonical Question identities and resolve relational IDs without relying on a newer projection's labels/gradation state. Include newly created Question ID/provenance mapping requirements in the adapter contract.
- Route extraction, reconstruction, assembler/preflight, visual assets, teacher review/decision, finalization/export through the same bound definition. Keep model/runtime selection and prompts unchanged.
- Seal job inputs with the same pin/hash; check job/Submission consistency on worker/retry/review/finalize. Scope mixed-edition Test overviews/totals per Submission instead of newest Test totals.
- Supply server-derived edition labels using the existing stable authoring-history numbering; show `採点対象: 第1版` etc.
- Relax activation guard only for histories proved revision-safe end-to-end; retain fail-closed protection for unresolved legacy history. Test A under edition 1 / B under edition 2 using deliberately different content, scores, rubric/diagrams and finalized-result preservation.

## Historical compatibility / backfill

No production rows were inspected or backfilled; no assertion that existing production history is all safely mappable is made. Existing fixtures demonstrate genuine pre-confirmation/unbound Submissions. Timestamp proximity or a single currently active revision is not proof of matching historical policy.

A future deterministic helper must compare the **complete effective definition**, including executable levels/conditions/reference hashes, against sealed job/reconstruction evidence. Backfill only an exact, unique same-Test match with audit evidence and idempotency. No confirmed revision at the time, missing evidence, or ambiguous matches remain explicitly legacy/unbound. Preserve historical sealed result read access; fail closed on operations needing revision guarantees. Do not remove current activation protection for such history.

## Validation / migrations / model calls

- Local counterexamples: two disposable fixtures; exact-confirmation equality and policy/context gap assertions passed. **0 grading jobs** created by these probes; **0 real model calls**.
- Existing grading mapping/context/execution/review tests: **59 passed, 3 existing warnings**. These use existing isolated/mocked job fixtures; they are not new revision-binding regressions and do not prove the unimplemented feature.
- Full backend/Chromium, new binding E2E, TS/ESLint/Ruff/build and migration upgrades were not run: product implementation stopped before changes, so reporting those as feature validation would be misleading.
- `git diff --check`: passed.
- Migration remains **0018_revision_lineage**. No new Alembic file, DB operation, reset/stamp, configuration/dependency change or production deployment.
- A future additive migration may be needed for membership/immutability constraints and a complete immutable grading-definition envelope; its shape is unresolved. Existing pins do not justify a speculative duplicate-column migration.

## Files inspected

`docs/auto-grading-system-spec-v4.md`; `db/models.py`, `db/repository.py`, `db/worker.py`; `domain.py`, `source_registration.py`, `student_submission_import.py`; `api/app.py`, `api/domain.py`, `api/student_answers.py`, `api/grading_review.py`; `student_answer.py`, `reconstruction_artifacts.py`; `grading_context.py`, `grading_mapping.py`, `grading_inputs.py`, `grading_execution.py`, `grading_visual.py`, `grading_review.py`, `grading_actions.py`, `teacher_grading.py`, `domain_adapter.py`; `test_authoring.py`, `authoring_confirmation.py`, `authoring_sources.py`; migrations 0017/0018; existing grading/authoring fixtures/tests; grading workspace/API types. Source paths are under `src/scoring/` unless indicated otherwise.

## Files changed / exact git status

Only this internal report is added. No source/test/migration changes, commit or push.

```text
?? docs/internal/reports/j-grading-1-confirmed-revision-binding.md
```

## Resumed implementation and architecture

J.GRADING.0/0a resolved the completeness boundary: newly confirmed Web revisions now carry `domains.grading_definition`, with `authority=web_authoring`, `schema_version=web-grading-definition.v1`, a supported interpreter version, complete executable levels, and content-bound visual references. J.GRADING.1 consumes that frozen definition. It does not combine it with current formal rows, `RubricVersion.rubric_json`, or external assignment files.

No columns were added. The existing nullable `StudentSubmission.confirmed_authoring_revision_id` and `GradingJob.confirmed_authoring_revision_id` fields are used. SQLAlchemy flush validation rejects later changes to either pin with `CONFIRMED_AUTHORING_REVISION_BINDING_IMMUTABLE`.

### Binding and pipeline

| Stage | Implemented behavior |
|---|---|
| New Web Submission | `POST /tests/{id}/submissions` uses `active_revision_for_submission`, which locks/refreshes the Test row, reads its active revision at that transaction boundary, verifies same-Test ownership, canonical snapshot hash, Web authority/interpreter, completeness, and frozen asset bytes, then stores the revision ID on creation. Missing or invalid definitions fail closed with stable error codes and teacher-facing Japanese guidance. |
| Registration retry | `source_registration.register_submission` checks the existing source/student identity first. An idempotent retry returns the original Submission and pin even if another edition is now active. A genuinely new registration takes the current verified active revision. |
| OCR and reconstruction | OCR/extraction still creates student-specific content. Reconstruction context and Question hierarchy are taken from the Submission’s revision definition. Registered page manifests and files are identity/hash checked; multi-page selection must identify a page explicitly. A later active edition or mutated formal Question content does not change the reconstruction context. Unsafe identity mapping fails closed. |
| GradingJob creation | The Web `/tests/{id}/grading-jobs` route selects `create_revision_execution_job`. That service locks and reloads the Submission, requires its pin, validates that revision and builds the bundle from the pinned snapshot. `job.confirmed_authoring_revision_id` is copied from the Submission. It never reads `Test.active_confirmed_revision_id` to choose a job edition. Delayed jobs and retries therefore retain the Submission’s original edition. |
| Job execution | The worker checks Submission/Job/revision IDs, snapshot and bundle hashes, item metadata, executable completeness, and the expected frozen package before invoking the grader. Rehashed-but-mutated bundles are also rejected by recomputing their contents from the confirmed snapshot. |
| Teacher review and finalize | Review verifies the persisted job contract and projects Question, answer, rubric levels, maximum score, and edition label from the bound revision/job. It does not display newer mutable Question/Answer/Rubric content as the grading basis. Per-Submission totals use that revision’s frozen maximums; mixed-edition Test overviews do not pretend to have one shared total. Finalization validates the same contract and reports the edition label. |

The immutable adapter is `src/scoring/revision_grading.py`. It projects Question context and hierarchy, stable authoring identity, accepted ModelAnswer and alternatives, Rubric criterion IDs and levels/conditions, derived criterion maxima, source provenance, and visual references from `domains.grading_definition`. J.GRADING.0 confirmation compilation now freezes each formal Question row ID as an identity handle in the grading definition. New revisions resolve that handle without querying current Question rows. Older immutable snapshots that predate the handle use a unique stable-key compatibility lookup; ambiguity or a missing row fails closed. Neither path reads mutable Question text, score, answer, hierarchy order, or grading policy.

Criterion maxima come from `max(level.score)`, not the mutable compatibility `points` projection. Visual references are loaded through the frozen immutable artifact reference and SHA validation. A missing root, missing object, or mismatched bytes fails closed; a newer current diagram is never substituted. The existing `GradingJob.rubric_version_id` remains a compatibility/audit FK. To populate it, the assembler selects only the linked `RubricVersion.id` and `generation_metadata` matching this authoring revision; it never loads `rubric_json` or uses that row to construct scoring inputs. Revision-bound teacher review and decisions likewise validate the pinned bundle and do not load current Rubric state.

The Web/legacy boundary remains explicit. Web grading jobs are routed through the revision-bound factory. The former mutable Web execution factory remains guarded with `WEB_GRADING_REVISION_BINDING_REQUIRED` so it cannot bypass the new route. Standalone CLI/filesystem grading remains its existing explicit legacy path; it does not supply Web grading policy.

### Errors and compatibility

The new Submission/API and grading-job/API paths return structured 409 errors for absent pins, cross-Test revision IDs, unsupported authority/interpreter, legacy-incomplete revisions, bad snapshot hashes, incomplete definitions, and invalid/changed immutable assets. The user-facing Submission guidance is: `採点を開始する前に、問題・模範解答・採点基準を最終確認して確定してください。`

Existing historical null-pin records are not backfilled or attached to the newest revision. They remain identifiable/readable through existing paths where safe, but they cannot enter revision-required Web grading. `revision_safe_grading_history()` checks every existing Submission and job against its revision and frozen bundle. The authoring activation guard is relaxed only when all existing history passes that check; any null pin, legacy job, invalid snapshot/asset, missing Submission relationship, or content mismatch keeps the blocker in place. No historical score or result is regraded or rewritten.

New grading responses expose `confirmed_authoring_revision_id` and the server-derived edition label (`第1版`, `第2版`, …). The ordering uses the same confirmed revision lineage as authoring history.

### A/B isolation and API/service regressions

The focused integration flow confirms edition A, creates S1 and a job, confirms edition B with different Question/ModelAnswer text and Rubric levels (`[0, 10]` versus `[0, 5, 10]`), then creates S2. It verifies:

- S1 and its early job remain pinned to A; S2 and its job pin B.
- A delayed S1 job created after B activation still uses A.
- Retrying S1 creation returns S1’s original ID and A pin.
- After deliberate drift in current formal Question, ModelAnswer, and Rubric rows, A and B bundles still contain their own immutable text and levels, and the synthetic grader receives those same inputs.
- A SQL guard around the real delayed-job API/assembler rejects reads of current `test_questions` and `model_answers` tables and of Rubric policy columns (`rubric_json` / `rubric_text`). The only Rubric table read is the linked ID and `generation_metadata` needed to populate the legacy FK; this metadata does not contribute scoring content.
- A student reconstruction run after B activation still uses A’s frozen Question context.
- Review displays `第1版`/`第2版` and the corresponding frozen Question, answer, and levels. Finalizing A after B activation preserves A’s label and 10-point total.
- ORM attempts to change an existing Submission or Job pin fail.
- A frozen visual-reference test proves the two revision packages retain their own SHA and geometry.
- Missing active revision, invalid snapshot hash, missing/incomplete definition, and cross-Test revision are rejected. A fully rehashed bundle that disagrees with the pinned snapshot is rejected by the worker and is not considered safe history.

The integration suite uses the actual FastAPI submission/job/review/finalize APIs plus the worker and assembler, not a detached helper-only path. The local TestClient fixture and files are disposable. No production job was created.

### Activation, retry, and historical policy

The old activation safety check is now conditional rather than removed globally. A Test with fully pinned and verified history can activate a later edition for future Submissions; old Submissions/jobs remain pinned. The regression covers A history followed by B confirmation and activation. If any history is legacy or unverifiable, the existing fail-closed activation issue remains.

No automatic association/backfill is attempted for historical null-pin rows. Their former active revision cannot be inferred safely from current state or timestamp proximity. Explicit legacy workflows continue to use their existing contracts.

## Final validation

- Focused backend integration/regression group: **143 passed, 3 warnings**. It covered revision binding, grading-definition verification, Submission/Job API flows, reconstruction, grading review/finalize, legacy execution boundaries, and authoring activation/history checks.
- Full backend suite: **1,056 passed, 2 skipped, 23 warnings** in **261.79 seconds** on the final code.
- `ruff check` over every changed Python source and test: **passed**.
- `python -m compileall -q src/scoring`: **passed**.
- `git diff --check`: **passed**.
- Alembic head: **`0018_revision_lineage`**. No migration was added.
- Frontend files were not changed, so TypeScript, ESLint, Next build, and Chromium were not applicable to this backend-only change.
- Grading: the focused A/A/B integration uses **3 synthetic grader client requests**. Real model calls: **0**. Production grading jobs: **0**. OCR/classifier/model services are not invoked by the binding tests; extraction/reconstruction dependencies are controlled stubs.

## Files changed in this implementation

Modified source files:

```text
src/scoring/api/app.py
src/scoring/api/domain.py
src/scoring/api/student_answers.py
src/scoring/api/test_authoring.py
src/scoring/authoring_confirmation.py
src/scoring/db/worker.py
src/scoring/domain.py
src/scoring/grading_actions.py
src/scoring/grading_definition.py
src/scoring/grading_execution.py
src/scoring/grading_review.py
src/scoring/source_registration.py
src/scoring/student_answer.py
src/scoring/teacher_grading.py
src/scoring/revision_grading.py
```

Modified/new tests:

```text
tests/test_grading_definition.py
tests/test_grading_execution.py
tests/test_teacher_preparation.py
tests/test_test_authoring.py
tests/test_revision_grading.py
```

No production or local Codex-only files were added. No frontend or migration file changed.

## Exact git status after implementation

```text
 M docs/internal/reports/j-grading-1-confirmed-revision-binding.md
 M src/scoring/api/app.py
 M src/scoring/api/domain.py
 M src/scoring/api/student_answers.py
 M src/scoring/api/test_authoring.py
 M src/scoring/authoring_confirmation.py
 M src/scoring/db/worker.py
 M src/scoring/domain.py
 M src/scoring/grading_actions.py
 M src/scoring/grading_definition.py
 M src/scoring/grading_execution.py
 M src/scoring/grading_review.py
 M src/scoring/source_registration.py
 M src/scoring/student_answer.py
 M src/scoring/teacher_grading.py
 M tests/test_grading_definition.py
 M tests/test_grading_execution.py
 M tests/test_teacher_preparation.py
 M tests/test_test_authoring.py
?? src/scoring/revision_grading.py
?? tests/test_revision_grading.py
```

No commit or push was made. Production acceptance remains outstanding.

## Production Acceptance — 2026-10-13

**Result: PARTIAL.** Production API acceptance verified confirmed-revision creation, exact revision fork, and the Submission binding invariant. Delayed Job creation, actual assembled grading packages, teacher review, and finalization remain unverified because the production worker's grading mode could not be proven synthetic. No grading Job was created and no inference was invoked.

### Deployment and service access

- Pre-deploy working tree was clean. Local checkout was `79de4dfa2e6985447c449a9aec6c7de5e505629d` (`Unify authoring card headings and content frames`); the J.GRADING.1 implementation commit `40b7824` is an ancestor. `git pull --ff-only` had reported `Already up to date`.
- This workspace has no `docker` executable and no configured SSH agent/host access. Therefore `python3 scripts/runtime-compose.py`, `docker compose ps`, and service logs could not be run. The production API does not expose a deployment commit/version endpoint, so the commit actually deployed on the host is **unverified**. No deployment was attempted from this workspace.
- Production `/api/v1/health` returned `status=ok`, `database=ok`, and readable/writable artifact storage before and after the acceptance work. The API-reported global counts were `pending=0`, `failed=0`, `review_required=0` at both checks.
- No production database console or container access was available. Production `alembic_version` is **unverified**; the local repository remains at `0018_revision_lineage`, and this phase added no migration.

### Dedicated validation records

The following records were created under the Codex teacher account. The Test was authored using the authenticated Web authoring/revision APIs. Student-answer PDFs contain synthetic fixture text only; they were registered as source materials and were not OCR-processed.

| Record | Name / identity | ID |
|---|---|---|
| Course | `Codex Validation - J.GRADING.1 - 20261013T150822Z` | `4ac082b8-15e3-4ea7-8f4e-6f98ae5cac37` |
| Offering | 2026, `other`, J.GRADING.1 validation | `56ef0c2d-b077-44f6-84e4-09f4de071a4a` |
| Test | `Revision Binding Acceptance - 20261013T150822Z` | `9fdf06c2-6fc2-4d30-a424-1c3db726bf59` |
| Question | Question 1 | `1b915527-42cc-488d-9554-17f36d08fca3` |
| ModelAnswer | Edition A initial answer | `66543a8b-2e3e-4716-b68a-dde483b31650` |
| Approved RubricVersion | Edition A initial rubric | `8181b0b4-7290-4ec6-bf5f-2966cb8dddf9` |
| Synthetic source material A | `j-grading-1-synthetic-A.pdf` | `4e7fb3bf-26ec-4fcc-82bb-818d1d31c21a` |
| S1 registered page-manifest material | Generated from synthetic source A | `29871193-7830-472c-805b-0ec9b47f5a96` |
| Synthetic source material B | `j-grading-1-synthetic-B.pdf` | `c9ebb800-18cd-4a1b-9d56-7e53fd476c54` |
| S2 registered page-manifest material | Generated from synthetic source B | `3147cf52-abfc-4bd0-9325-4eedaacdca75` |
| Student A | `JGRADING1-SYNTHETIC-A` | `34a20f9c-9ce9-474a-8de6-b45b84778e33` |
| Submission S1 | Synthetic validation record A | `fe0f55c4-29e6-401d-a765-6e9153f23643` |
| Student B | `JGRADING1-SYNTHETIC-B` | `01ae84c8-7f5a-42a2-a019-e3791fd3b3bc` |
| Submission S2 | Synthetic validation record B | `5f9a6b5d-dd30-482a-99ef-e1be6b9600fb` |

### Edition and Submission results

| Edition | Confirmed revision ID | Parent | Snapshot SHA-256 | Frozen Question / Answer | Frozen rubric levels |
|---|---|---|---|---|---|
| 第1版 (A) | `9fd3981c-ee1b-4046-8525-a98f687e8b06` | none | `bcfdeebc2917ca97f10fadca6000bf966c9f5e489b8461540b1cdb350a01a0ec` | `Edition A question` / `Edition A answer` | `[0, 10]` |
| 第2版 (B) | `b9a17f19-b38e-4d8e-8969-2773fa70b0e6` | 第1版 A | `7bb5dd91217637cc95cd9c745c0d0ccf479268394c3619b1c36701a54d1a75dd` | `Edition B question` / `Edition B answer` | `[0, 5, 10]` |

Both confirmed snapshots report `schema_version=web-grading-definition.v1`, `authority=web_authoring`, and `complete=true`. The edition A and B rubric levels and text were read back from each immutable confirmed snapshot. A revised draft fork initially matched A's snapshot exactly before the deliberate B edits. After confirming B, the history API still returned A with its original hash and content, and active revision was B.

| Submission | Submission ID | `confirmed_authoring_revision_id` read back |
|---|---|---|
| S1 | `fe0f55c4-29e6-401d-a765-6e9153f23643` | `9fd3981c-ee1b-4046-8525-a98f687e8b06` (A) |
| S2 | `5f9a6b5d-dd30-482a-99ef-e1be6b9600fb` | `b9a17f19-b38e-4d8e-8969-2773fa70b0e6` (B) |

The supported Submission registration request for S1 was retried with the same source/student identity after B became active. It returned the same Submission ID and preserved the A pin. Activating B while S1 remained bound to A succeeded. This confirms the production Submission-side pin and retry behavior for the dedicated Test.

### Unverified execution stages and safety boundary

- No GradingJob was created. The dedicated Test event list contains no grading-job event. No production OCR, grader, or other model call was made.
- A delayed S1 Job after B activation and an S2 Job were not attempted. Job creation queues work for the production worker; no established production synthetic-grader mode or paused worker was available to guarantee that the queued request could not invoke a real grader. The acceptance instructions require stopping in that situation.
- Consequently, the actual assembled execution bundles, teacher review edition/context, finalization, and score totals were not exercised on production. The immutable A/B definitions above demonstrate the frozen source data, but do not substitute for those runtime checks.
- Existing historical null-pin rows were not inspected or changed. No unrelated production records were modified. The only production data intentionally created were the dedicated Course, Offering, Test, Question, ModelAnswer, approved RubricVersion, two confirmed revisions, two synthetic student/source registrations, and their associated source/material records.

### Exact Git status after this report update

```text
 M docs/internal/reports/j-grading-1-confirmed-revision-binding.md
```

No commit or push was made. Production acceptance remains **PARTIAL** until a deployment commit/Alembic version can be verified on the host and the delayed-job package, review, and safe synthetic finalization checks can run without real inference.

## Safe production package audit — 2026-10-13 continuation

**Decision: PARTIAL; stop before creating any GradingJob.** The production API has no supported prepare-only, paused/manual enqueue, synthetic grader, or package-inspection route that can prove a job will not reach the managed grader. The existing input-preview route is read-only but these two submissions are registration-only and have no reconstructed answer, so it cannot build the execution bundle. This section records the additional production checks and the proposed J.GRADING.1a design; no product code was changed.

### Production API and submission preview checks

- Read-only production OpenAPI returned `200`, with `info.title=llm-grader API` and `info.version=1.0`. It exposes `GET /api/v1/tests/{tid}/submissions/{sid}/questions/{qid}/grading-input-preview` and `POST /api/v1/tests/{tid}/grading-jobs`; the latter accepts an open-ended JSON object and documents no `dry_run`, `prepare_only`, `enqueue`, or synthetic-execution parameter.
- `GET /api/v1/health` returned `status=ok`, `database=ok`, and `jobs.pending=0`, `failed=0`, `review_required=0`.
- `GET /api/v1/version`, `/api/v1/system/version`, `/api/v1/diagnostics`, and `/api/v1/admin/alembic` each returned `404`. OpenAPI has no build SHA extension. Thus production host commit and production Alembic revision remain unverified.
- Using an authenticated Codex session, read-only readiness and preview requests confirmed S1 (`fe0f55c4-29e6-401d-a765-6e9153f23643`) is still pinned to A (`9fd3981c-ee1b-4046-8525-a98f687e8b06`, `第1版`) and S2 (`5f9a6b5d-dd30-482a-99ef-e1be6b9600fb`) to B (`b9a17f19-b38e-4d8e-8969-2773fa70b0e6`, `第2版`). Each readiness response reported one gradable question, zero ready bundles, and one blocked bundle with `ANSWER_RECONSTRUCTION_MISSING`; each corresponding preview returned `409 ANSWER_RECONSTRUCTION_MISSING`.
- The source PDFs were registered only; no OCR or reconstruction was run. Therefore the production API did not produce an actual A or B execution bundle. The confirmed snapshots themselves still prove A's question/answer and `[0,10]` policy and B's question/answer and `[0,5,10]` policy as recorded above, but that is not a substitute for validating the assembled execution package.
- The dedicated Test event list contains only authoring/revision events and no grading-job event. No grading job was created during either acceptance attempt. The authenticated read-only checks used a normal Codex login session; no Course, Test, submission, authoring, or grading records were changed by this continuation.

### Job-to-worker-to-grader safety audit

The production route and local implementation establish this path:

1. `POST /tests/{tid}/grading-jobs` in `src/scoring/api/domain.py` calls `create_revision_execution_job` for Web execution, adds a `job_created` event, commits, then returns. The route has no enqueue-suppression or prepare-only flag. It does not run the worker inline, but the committed Job state is `queued`.
2. `create_revision_execution_job` in `src/scoring/grading_execution.py` invokes `RevisionGradingInputAssembler.execution_preview`, validates the revision-bound bundle, reads the grading runtime configuration, seals the bundle and revision/hash metadata into `GradingJob.metadata_json`, creates the queued Job and JobItem, and flushes them. This sealing happens before inference, but only inside Job creation; there is no existing endpoint that returns that sealed package without creating the Job.
3. `docs/admin/production-runbook.md` requires a separately deployment-managed grading worker and recommends checking its PID. It is not a Compose service in this checkout, and API `/health` does not report worker liveness or a paused state. A committed queued Job therefore cannot be proven safe from worker pickup using the available production API.
4. `JobWorker.run_once` in `src/scoring/db/worker.py` claims a queued Job and transitions it to `preparing`. For revision-bound work, it verifies the Submission/Job contract before constructing `GradingExecutionRunner`.
5. `GradingExecutionRunner.run` in `src/scoring/grading_execution.py` verifies the sealed snapshot and asset hashes, then calls RuntimeManager `status('grader')`, `ensure_running('grader')`, and `health('grader')`, constructs the client, and calls `client.chat(...)`. RuntimeManager may start a managed grader. That path can perform real inference.

No production-supported synthetic/managed-stub grader, worker-disabled mode, paused/manual queue mode, or unconsumed prepared Job state was found. Test-only monkeypatches and local fakes do not establish production safety. The existing preview is safe from grading execution, but S1/S2 fail its reconstruction requirement, so it does not return a sealed bundle. Accordingly, delayed S1 Job -> A, S2 Job -> B, actual bundle hashes/contents, teacher review edition/context, result generation, and finalization remain unverified. Job count created in this continuation: **0**. Production grading/OCR/model calls in this continuation: **0**; across this acceptance: **0**.

### J.GRADING.1a design proposal — not implemented

Prefer option A, a revision-bound package-preview service and staff-scoped API, over a `PREPARED` Job state. A new Job state would need to be excluded from every worker claim/recovery path and could accidentally alter established queue semantics. The preview should reuse the same immutable revision verifier and frozen-question-package assembly used by Job creation, but have no dependency on runtime config, RuntimeManager, grader client, Job/JobItem insertion, event insertion, or commit.

Proposed behavior:

- Add a staff/domain-authorized `POST /api/v1/tests/{tid}/submissions/{sid}/grading-package-preview` diagnostic endpoint (or an equivalent internal service exposed through an existing authorized route). It must verify the Submission pin, Test ownership, confirmed snapshot hash, completeness, artifact hashes, stable Question identity, and edition label using the existing revision-bound verifiers.
- For a Submission that already has a valid teacher-accepted reconstruction, consume that reconstruction without modifying it. For this dedicated registration-only fixture, allow an explicitly marked synthetic answer string in the request body so the same revision-bound package can be built in memory without OCR, model calls, or a persisted reconstruction. The synthetic input must be clearly identified in the response and excluded from logs.
- Assemble and validate the same canonical execution bundle used by `create_revision_execution_job`, including its canonical bundle hash, pinned revision ID/hash, stable Question identity, frozen Question and ModelAnswer, rubric criterion IDs/levels/derived maxima, and frozen visual-reference IDs/SHA values. Return only the fields needed for validation; do not return filesystem paths or unrelated student data.
- Guarantee read-only behavior: no GradingJob/JobItem/event/reconstruction writes, no `commit`, and rollback/close the read transaction. Tests should assert job/event/reconstruction row counts remain unchanged and monkeypatch RuntimeManager/client access to fail if touched. The handler should not load grader runtime configuration or expose a path to `GradingExecutionRunner`.
- Exercise the exact service/API using disposable production-like data first. On production, preview S1 and S2 and verify A returns Edition A question/answer and `[0,10]`, B returns Edition B question/answer and `[0,5,10]`, with different bundle hashes and zero job/model/OCR deltas. Review/result/finalization still require a separately authorized synthetic-result mechanism; this preview alone must not mark J.GRADING.1 COMPLETE.

This is a proposal only. No J.GRADING.1a code, endpoint, worker setting, or production configuration was changed or added during this acceptance.

### Exact Git status after this continuation

```text
 M docs/internal/reports/j-grading-1-confirmed-revision-binding.md
```

No commit or push was made. J.GRADING.1 production acceptance remains **PARTIAL**; continue only after a separately implemented and validated safe package-preview mechanism is deployed. The local codebase has not been deployed from this workspace.

## J.GRADING.1a production acceptance follow-up — 2026-10-13

This follow-up supersedes the preceding J.GRADING.1a proposal and its then-current stop condition; that section remains as the historical result before the preview API was implemented and deployed.

The subsequent J.GRADING.1a implementation was deployed by the operator and accepted against the same dedicated Test without creating any new production records. The deployed OpenAPI listed the read-only package-preview route, and authenticated Codex teacher requests returned Edition A for S1 (`[0,10]`, package hash `073346e9a31af6743399bfa531ccdb3cb2f40a44c8eb6cdc01c4eefdec6ec68b`) and Edition B for S2 (`[0,5,10]`, package hash `eec54659f379191cc7065aa7587465621456ac21158a842b9d238af10baffe4e`). Repeated previews reproduced the same hashes; Test events, Submission pins, active revision, reconstruction runs, and health job counters did not change. No Job or model/OCR call was started. See `docs/internal/reports/j-grading-1a-safe-package-preview.md` for the full acceptance data and limitations.

This closes the J.GRADING.1a package-preview acceptance, but does not close J.GRADING.1: production Job execution, teacher review, and finalization remain unverified, so J.GRADING.1 remains **PARTIAL**. Production Git SHA and Alembic version are still unverified.
