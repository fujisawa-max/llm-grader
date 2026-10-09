# J.UI.12c — Test-wide Final Review and Atomic Confirmation

## Result

**READY_FOR_PRODUCTION_VALIDATION.** The local implementation, backend suite, production-like Chromium suite, migration checks, and static/build checks pass. Production acceptance was not run because the production server is serving the pre-12c UI/API and this workspace has no established deployment channel. The 12d gate therefore did not pass; no 12d implementation was started.

## Baseline

- Initial HEAD: `4d21c122bd83e7b4b85450153a35a4504941f4f9`.
- Initial worktree: clean; fix15e was already part of the baseline.
- Existing migration count: 17 tracked files. This phase adds `0017_confirmed_authoring_revision.py` (18 files total).
- Existing baseline suite counts recorded in the fix15e report: backend 963 passed / 1 skipped; browser 64 passed.
- Authoring state before this phase was a mutable `TestAuthoringRevision` snapshot plus separately mutable formal Question, ModelAnswer, and Rubric rows. Publication was deliberately disabled; grading inputs read the formal rows and had no whole-Test revision pin.

## Confirmation architecture

`TestAuthoringRevision` remains the saved working revision. A successful confirmation creates an immutable `ConfirmedAuthoringRevision` containing the exact normalized saved snapshot, stable revision/edit-version identity, SHA-256, confirmer, and timestamp. `Test.active_confirmed_revision_id` identifies the active basis. Confirmation projects Question, ModelAnswer, and approved Rubric rows deterministically from that snapshot inside the same database transaction, then changes the working revision state to confirmed and records a DomainEvent. No model, OCR, classifier, diagram, or grading call is part of this path.

The additive migration adds the confirmed-revision table and nullable references from Test, StudentSubmission, and GradingJob. Existing submissions/jobs retain null references and are not rewritten. Fresh and existing SQLite migration paths, including downgrade, are covered. No database reset or production migration was run.

## Readiness and concurrency

Final Review shows the saved revision/edit version, the full Question tree, gradable scores and Test total, per-Question Answer/Rubric/diagram/source readiness, and blockers. Unsaved client changes add a blocker and disable confirmation. The explicit confirmation dialog names the Test/revision and requires a second explicit action. Existing preflight blockers remain distinct from the informational source warnings; source warnings that indicate unresolved provenance remain blocking under current product semantics.

The server independently verifies ownership, expected revision ID/edit version/snapshot hash, current baseline, source materials and provenance, Question/Answer validity, and preflight blockers. It locks the Test row and performs compare-and-set on the authoring revision. Stale review returns conflict; duplicate confirmation of the same exact revision returns the same confirmed record. An injected failure after formal projection rolls the entire transaction back, including formal rows, confirmed revision, active pointer, and revision state.

A session guard makes confirmed revision records and projected Question/Answer/Rubric/Test content read-only through ORM mutations. A newly created StudentSubmission captures the active confirmed revision ID; GradingJob and its input manifest capture the submission revision ID and reject mixed-revision batches. Legacy submissions/jobs remain unbound. Since the existing grading assembler still reads mutable formal rows rather than versioned projections, confirmation is blocked on Tests that already have submission or grading history. This is fail-safe compatibility behavior; historical job inputs are not migrated or rewritten. Supporting another confirmed basis on a Test with existing grading history requires the later grading-pipeline revision-binding work and was not attempted here.

## Validation results

- Focused backend/correction/authoring set: 73 passed, 1 warning.
- Full backend: 968 passed, 1 skipped, 23 warnings, 217 seconds.
- Confirmation backend cases cover exact snapshot projection, immutable state, idempotency, stale-review conflict, rollback after injected failure, score blockers, migration safety, and submission/job revision pins.
- Full production-like Chromium: 65 passed, including Final Review confirmation, Sample Q5 split/diagram discovery and reuse, Save/resume, stale-tab, OCR, Rubric, source-backed authoring, and diagram regression groups. An initial run overlapped the full backend workload and timed out the Sample Q5 diagram request; that exact test passed in isolation (25 seconds), then the full browser run passed after backend execution had ended.
- Confirmation E2E creates a disposable Test, checks that unsaved edits block confirmation, saves and confirms the saved snapshot, verifies snapshot/hash identity and formal projections, repeats confirmation to prove idempotency, reloads the confirmed state, and compares RuntimeManager call counts before/after confirmation (unchanged).
- TypeScript: passed. Targeted ESLint: passed with no new errors. Ruff: passed. Next production build: passed; existing project CSS/autoprefixer and lint warnings remain. `git diff --check`: passed before the final E2E assertion; rerun at close.
- Browser harness reported grading jobs = 0. No formal grading was launched.

## Production acceptance and safety

A read-only production probe authenticated with the supplied environment configuration and inspected the existing dedicated fix15e validation Test plus served frontend assets. Production still reports publication unavailable and does not contain the 12c Final Review/confirmed endpoint assets. The repository runbook describes operator-managed backup, deployment, migration, and worker procedures, but this environment has no established deployment workflow or deployment-host access. No deployment was attempted and no validation Course, Offering, or Test was created. Existing Sample Q5, other production Tests, grades, submissions, users, runtime configuration, and formal data were not changed. Production inference/grading jobs = 0.

The teacher credentials were read only from environment variables. Values were not printed, included in source/report text, screenshots, HAR, or test artifacts. The final changed-file scan checked all three configured values and found no credential literal.

## J.UI.12d gate

The gate requires deployed 12c plus successful production acceptance. Neither is available, so 12d was not started. No `j-ui-12d.md` report is created.

## Files changed

- `src/scoring/db/models.py`, `src/scoring/db/database.py`: confirmed revision model and immutable-state guard registration.
- `migrations/versions/0017_confirmed_authoring_revision.py`: additive schema and references.
- `src/scoring/authoring_confirmation.py`: deterministic formal projection and mutation guard.
- `src/scoring/api/test_authoring.py`, `src/scoring/test_authoring.py`: Test-wide readiness and atomic confirm/review/read APIs.
- `src/scoring/domain.py`, `src/scoring/domain_adapter.py`: submission/job revision binding.
- `src/scoring/api/domain.py`, `src/scoring/api/model_answer_imports.py`, `src/scoring/question_import.py`: confirmed-state mutation protection.
- `frontend/app/tests/[testId]/authoring/page.tsx`, `frontend/lib/api/testAuthoring.ts`: Final Review and explicit confirmation UI/API.
- `frontend/e2e/authoring-final-confirmation-real.spec.ts`, `frontend/e2e/test-authoring-foundation-real.spec.ts`, `tests/run_runtime_browser_e2e.py`: browser coverage and suite registration.
- `tests/test_test_authoring.py`: confirmation/readiness/atomicity/migration/pinning tests.
- `docs/reports/j-ui-12c.md`: this report.

## Remaining issues

- Production deployment and dedicated Sample Q5 production acceptance remain outstanding; do not claim COMPLETE.
- Grading history created before a confirmed revision has no revision reference. Tests with existing submission/job history are therefore blocked from this confirmation projection until the grading pipeline can safely consume immutable revision projections.
- J.UI.12d revision history/new-draft foundation, J.UI.12c publication UI polish beyond this scope, and drag-and-drop remain deferred.
