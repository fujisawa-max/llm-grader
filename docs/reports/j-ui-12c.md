# J.UI.12c — Test-wide Final Review and Atomic Confirmation

## Result

**fix2: LOCAL_COMPLETE / READY_FOR_PRODUCTION_VALIDATION. Overall 12c: production acceptance pending.** Local fix2 integrity/selector implementation and full automated validation pass; operator deployment and fresh production revalidation are required. No production changes were made in fix2.

**Historical production fix1 finding (2026-10-11):** Final Review UX, blocker correction, unsaved protection, CAS, and a diagram-free confirmation passed on dedicated production records. Real Sample Q5 was built, reviewed and confirmed, but its confirmed snapshot differs from the saved snapshot in diagram revision metadata and its stored hash does not match the confirmed payload. This is a data-integrity blocker; 12c is not COMPLETE and 12d was not started. Earlier local implementation/deployment findings below are historical; the latest acceptance subsection supersedes them.

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

## fix1 production recheck — 2026-10-11

After the operator reported deployment, an authenticated production recheck succeeded (login API HTTP 200; authoring page bundle HTTP 200). The served authoring bundle still contains the previous `確定済み — revision` wording and does not contain the fix1 `authoring-final-unsaved`, `authoring-final-table`, or `テスト内容は確定済みです。` signatures. The checked local HEAD is `9c961d0` (`Improve final review issue guidance and confirmation UX`). Production fix1 frontend deployment could therefore not be verified, and acceptance was stopped before creating or editing business records. One browser login also succeeded; other browser login probes timed out, so browser acceptance itself is not reported as passing.

No accessible dedicated 12c validation Test was found under the configured Teacher account. No Test/Course/Offering, existing Q5, grades, submissions, or runtime configuration was changed during this recheck. No grading or inference request was initiated. Credentials were read from environment variables only; no values, session cookies, authentication tokens, screenshots, or HAR were recorded. Follow-on 12d work remains gated. Production acceptance must resume after the fix1 frontend build is actually served; this recheck does not establish COMPLETE.

## fix1 resumed production acceptance — 2026-10-11

### Deployment and dedicated records

Authenticated probes now find the fix1 `authoring-final-unsaved` signature and no old `確定済み — revision` text. The operator deployed the application; Codex did not deploy, migrate, stamp, commit or push. Local baseline HEAD is `9c961d0` (`Improve final review issue guidance and confirmation UX`). Initial status on resumption contained only the prior report edit.

Created one dedicated validation Course/Offering and these Tests, under the configured Teacher account:

- `Codex Validation - J.UI.12c-fix1 2026-10-11T13-59-35-830Z` — confirmed, simple hierarchical correction/confirmation fixture.
- `Codex Validation - J.UI.12c Sample Q5 2026-10-11T14-02-08-019Z` — actual PDF workflow; confirmed but subject to the integrity finding below.

No existing Q5, unrelated Test/Course/Offering, user, submission, grade, or runtime configuration was changed. Dedicated validation records were left for inspection.

### UX and normal confirmation evidence

Production Chromium checked the per-question `要修正 1件` tab, opening leftward, current/expected rubric totals (8 versus 10), Escape/focus return, and exact equality of main editor width/height, document height and scroll position before/after opening and closing. The Final Review hierarchy is left aligned; child indentation is greater than parent while the next major Question returns to parent alignment. The correction action selects the correct Question and highlights its rubric points input.

Changing 8 to 10 removes the issue. Entering Final Review with that unsaved change displays the explicit warning and disables Confirm; normal Save clears the warning and recomputes readiness to zero issues. A subsequent separate saved edit makes an older confirmation request fail with 409 and creates no confirmed revision.

The simple dedicated Test then confirmed successfully. Its confirmed snapshot equals the saved snapshot exactly, repeated confirmation returns the same revision, reload and navigation back to Test/Authoring retain confirmed state. Browser request observation recorded no analysis/diagram/grading request during Confirm. The authoritative archive-impact endpoint reports zero submissions and zero grading jobs. An attempted GET to `/tests/{id}/grading-jobs` returned 405 (this route only accepts POST); this was a diagnostic endpoint mistake, not a grading action, and was replaced with `/archive-impact`.

### Real Sample Q5 correction and diagram evidence

Uploaded the actual `sampleQ5.pdf`, analyzed Questions, split Q3 into three children in the existing dialog, saved, uploaded actual `sampleQ5_modelAnswer.pdf`, and analyzed Answers. Automatic and manual PDF crop acceptance, saved two-origin reuse from Q3(3), and reload/Back/Resume passed. Server diagnostics returned `candidate_count=2`; both origin entries retained automatic `classified_as_non_answer` history but effective disposition became `include` after teacher diagram acceptance. Q3(3) reused both diagrams. Rubric analysis used the same physical model-answer PDF as a separate role.

Initial real-data readiness had 24 blockers. The PDF's actual score structure was used: Q1 30; Q2(1) 10; Q2(2) 30; Q3 children 10/8/12. Through the normal UI, mixed/wrong-target rubric rows were explicitly marked target-excluded, retained in source entries, and manually authored rubric conditions were added from the PDF (including formula/value subpoints and A/B placement/class subpoints). Classifications were explicitly teacher-confirmed, duplicate/unneeded unassigned candidates explicitly ignored, and PDF geometry warnings acknowledged with teacher notes. No automatic promotion, reassignment, point redistribution, or blocker-rule change occurred. The final server review had zero blockers and allowed confirmation.

### Integrity blocker discovered after real-data confirmation

The actual-PDF Confirm request succeeded, but exact snapshot comparison failed. Read-only follow-up found eight differences, all `diagram_records[*].revision`: saved value **14**, confirmed value **15**. Four records occur in `domains.answer.entries`; their projected copies occur in `answers`. Text, criteria, scores, source/crop artifact references and geometry did not differ in the recursive comparison.

- Recomputing `canonical_hash(working.snapshot)` matches the working payload's hash.
- Recomputing `canonical_hash(confirmed.snapshot)` **does not** match the confirmed record's stored `snapshot_sha256`.
- The stored confirmed hash equals the saved working hash, despite the confirmed payload having changed.

Exact failure point: `confirm()` checks the saved snapshot hash, then calls `AuthoringAnswers(..., row.snapshot).validate()`. That method is designed for Save and assigns validated diagram records using `self.row.edit_version + 1` (`src/scoring/authoring_answers.py`, line 161). It mutates the supplied snapshot, including projected Answer copies. Confirm subsequently captures that changed snapshot while retaining the pre-validation expected hash (`src/scoring/api/test_authoring.py`, confirmation block). Diagram-free coverage does not detect this.

No safety filters were bypassed and no repair of an immutable production record was attempted. Further production mutation/confirmation stopped at this data-integrity uncertainty. Sample Q5 idempotency/reload after this finding are not claimed as completed; the simpler Test proved those paths. A dedicated follow-up must make confirmation validation non-mutating, retain the exact saved payload, add accepted-diagram exact-hash regression coverage, and determine safe handling of the dedicated affected confirmed record. Existing production confirmed revisions were not inspected for impact.

### Automated revalidation and fixture corrections

The original focused issue-overlay test failed because its API fixture changed node bodies while leaving `question_text_buffers` empty; legitimate source blockers therefore made the expected one-item tab a two-item tab. The fixture now aligns buffers with the teacher-authored bodies. Focused Final Review/confirmation: **2 passed**, production Next build passed, grading jobs 0.

Full backend: **970 passed, 2 skipped, 23 warnings, 216.53 seconds**. Full browser initial run: **63 passed, 3 failed** because existing tests looked for the old composite navigation button names and old `テスト全体確認` heading after entering Final Review. Those locators now use the corresponding actionable issue card/button and distinct `最終確認` heading; navigation/focus assertions remain. The affected focused browser run: **4 passed**, grading jobs 0. Final full browser revalidation is recorded below after completion.

TypeScript, targeted ESLint, changed-Python Ruff, production Next builds and diff checks passed. The committed migration ID is `0017_confirmed_revision` (within 32 characters); the earlier disposable PostgreSQL upgrade/downgrade/upgrade check passed 2 tests. No production database migration state was directly inspected through this Teacher-only environment, and no downgrade/reset/stamp was performed.

### Safety and repository

Only explicit Question/Answer/Rubric analysis and explicit diagram discovery invoked normal inference paths. Save, correction, manual crop, reuse and Confirm added no analysis request. Browser-level absence of analysis requests does not replace server-runtime telemetry; no direct production model-call log audit was available. Both dedicated Tests report grading jobs 0 and submissions 0 through archive-impact. Credentials came solely from environment variables; changed-file and production acceptance script/artifact literal scans passed. No production screenshots/HAR/session cookies/tokens were saved.

This continuation changes service E2E fixtures/locators and this report only; it does not alter deployed application logic or the confirmation architecture. No commit/push was performed. J.UI.12d remains gated and unstarted.

### Final local result and exact status

Final full normal production-like Chromium: **66 passed, 2.8 minutes**, grading jobs **0**. Production Next build completed successfully in this harness. This does not clear the independently reproduced production confirmed-diagram hash defect.

Final modified files:

- `docs/reports/j-ui-12c.md`: production UX/correction evidence, dedicated Tests, precise snapshot-integrity blocker and safety limits.
- `frontend/e2e/authoring-final-review-issues-real.spec.ts`: synchronize body-edit fixture buffers so the expected actionable issue count is valid.
- `frontend/e2e/authoring-preview-materials-real.spec.ts`: locate the new actionable score issue card/action; retain exact correction/focus checks.
- `frontend/e2e/authoring-source-backed-real.spec.ts`: locate the new actionable rubric issue card/action; retain target and focus checks.
- `frontend/e2e/test-authoring-foundation-real.spec.ts`: require the distinct Final Review heading after its explicit entry action.

Exact final `git status --short`:

```text
 M docs/reports/j-ui-12c.md
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
```

Result: **PARTIAL**. Fix1's production presentation/correction paths pass, but whole 12c acceptance cannot be COMPLETE until the saved-diagram confirmation mutation/hash defect is repaired and revalidated. No follow-on 12d work.

## J.UI.12c-fix2 — Non-mutating confirmation and Question issue markers (2026-10-11)

### Scope and baseline

Local implementation only; no deployment, production login, migration, or production data mutation in this run. J.UI.12d remains unstarted. HEAD: `9c961d0cbffe9b841418a3b3b85ad078bd7689b3`.

The initial working tree contained intended fix1 acceptance changes in this report and four browser files: `authoring-final-review-issues-real.spec.ts`, `authoring-preview-materials-real.spec.ts`, `authoring-source-backed-real.spec.ts`, and `test-authoring-foundation-real.spec.ts`. Those changes were preserved. No database migration is added.

### Root cause and repair

Confirmation used the Save-oriented `AuthoringAnswers.validate()` on `row.snapshot`. That validator attests diagrams at `row.edit_version + 1` and rebuilds answer projections. Consequently a saved diagram revision could increase during Confirm while the previously supplied hash remained unchanged.

Confirmation now freezes the normalized saved snapshot, verifies its canonical hash against the reviewed identity, and passes separate deep copies to Answer and Question validation. Validator transformations are discarded; their readiness/provenance checks still apply. Formal projection also receives a detached copy. The confirmed payload is copied from the frozen saved snapshot, its hash is recomputed, and working/confirmed hash invariants are checked before transaction completion. Save normalization remains unchanged.

The existing idempotent branch also verifies the persisted confirmed payload/hash. An inconsistent historical payload fails closed without rewriting that immutable record. The previously affected production validation Test remains untouched.

### Integrity and regression evidence

Eight parameterized backend cases cover automatic, manual PDF crop, saved reuse, and multiple diagrams, each with normal confirmation and injected mid-projection failure. They assert complete saved/confirmed snapshot equality, persisted canonical hash equality, unchanged working edit version and diagram revisions, successful idempotent confirmation, and complete rollback. Existing diagram-free, CAS, permissions, immutable revision, formal projection, and grading binding tests remain enabled. A separate deliberately corrupted historical fixture proves duplicate confirmation refuses inconsistent data without repair.

The new actual-PDF Chromium scenario uses `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`: fresh Test, Q3 split into three children, automatic diagram acceptance, manual PDF drag crop, two saved sibling origins, reuse of both, Save/reload/Back/resume, then Final Review and Confirm. It compares the entire snapshot recursively and computes canonical hashes from raw API JSON using the backend canonicalizer, preserving JSON numeric representation. Four accepted diagram records include manual and reused provenance; all record revision values must remain identical. Fixture readiness corrections are explicit teacher-owned score/rubric/review decisions, not new product defaults or weakened blockers.

### Question selector

Normal Question options append ` *` when `issuesForQuestion(stable_key)` returns direct-owned unresolved issues. The floating issue tab consumes the same helper and readiness collection. Child issues do not mark their parent; special all-Test/unassigned options are unchanged. Marked options have an accessible label ending in `要修正あり`, while visible selected option text retains the asterisk.

The browser regression checks marked/unmarked parent and child options, selected text, accessibility, correction/Save removing the marker, a new mismatch adding it again, and consistency with the floating tab. Existing overlay no-reflow, navigation/highlight, unsaved Final Review, and hierarchy assertions remain active.

### Changed files

- `src/scoring/api/test_authoring.py`: detached validation/projection and confirmation hash guards.
- `frontend/app/tests/[testId]/authoring/page.tsx`: shared direct-owned issue helper and accessible option markers.
- `tests/test_authoring_diagrams.py`: diagram snapshot exactness and rollback cases.
- `tests/test_test_authoring.py`: diagram-free hash and inconsistent prior-payload refusal.
- `frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts`: actual-PDF diagram confirmation integrity regression.
- `frontend/e2e/authoring-final-review-issues-real.spec.ts`: marker/live-update coverage plus inherited fix1 correction.
- `tests/run_runtime_browser_e2e.py`: default suite includes real-Q5 confirmation and three-child inclusion regressions.
- Three other existing browser files listed in the baseline retain fix1 locator adaptations.
- This report records the local fix2 result separately from production acceptance.

### Production handoff

Operator deployment is required before production acceptance resumes. Use a new dedicated validation Test/fresh isolated revision and repeat actual-Q5 confirmation/hash comparison. Do not rewrite or reuse the affected immutable production record as repaired evidence. This run must stop before deployment; overall 12c cannot be marked COMPLETE from local tests alone.

### Final local validation and status

**LOCAL_COMPLETE / READY_FOR_PRODUCTION_VALIDATION.** Stop before operator deployment.

- Focused backend: 74 passed plus the additional inconsistent-prior regression (1 passed).
- Full backend: **979 passed, 2 skipped, 23 warnings**, 224.36 seconds.
- Focused production-like Chromium: **5 passed**, 46.0 seconds.
- Full normal production-like Chromium: **69 passed**, 3.4 minutes; real FastAPI/RuntimeManager with managed inference stubs. Includes actual Sample Q5 confirmation and native/controlled three-child diagram reuse.
- TypeScript and ESLint: passed; production Next build passed (existing image-optimization warnings only, no new lint errors).
- Ruff (changed Python) and `git diff --check`: passed.
- Browser harness: **grading jobs = 0**. Explicit call-count assertions show no inference on Confirm/Save/reuse.
- Changed-file credential audit: no configured production password literal found. No production authentication, screenshot, token, or credential artifact generated in this phase.
- No migration, commit, push, production deployment, immutable production-record repair, or J.UI.12d work.

Exact final git status:

```text
 M docs/reports/j-ui-12c.md
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
 M src/scoring/api/test_authoring.py
 M tests/run_runtime_browser_e2e.py
 M tests/test_authoring_diagrams.py
 M tests/test_test_authoring.py
?? frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts
```
