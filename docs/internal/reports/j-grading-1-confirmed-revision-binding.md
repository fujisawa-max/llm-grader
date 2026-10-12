# J.GRADING.1 — Confirmed Revision Binding

## Result

**PARTIAL — stopped at the specified information-integrity boundary before product implementation.** Current confirmed snapshots do not necessarily contain the discrete scoring levels required by supported grading paths. A local counterexample proves that identical authoring snapshots can produce different effective grading policies through an external assignment. Inferring missing levels would change scoring policy, which this phase forbids.

No binding-only patch, migration, automatic backfill or activation-guard relaxation was made. No production connection, model execution, deployment, commit or push. Existing completed authoring phases remain COMPLETE; their authoring snapshot integrity was not changed. This is a grading-definition completeness dependency, not a claim that their immutable snapshots mutated.

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
