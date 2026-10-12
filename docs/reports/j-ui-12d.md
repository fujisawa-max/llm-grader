# J.UI.12d — Confirmed Revision Management & Revised Draft Foundation

## Result

**READY_FOR_PRODUCTION_VALIDATION**. Local implementation and all required automated validation passed. Production deployment and acceptance are deliberately not performed. J.UI.12c, J.UI.12e and J.UI.12e-fix1 remain COMPLETE. No commit or push.

## Baseline

- HEAD: `8f479c1a8e6ac10896982d4db6206c911ac985b8`.
- Initial `git status --short`: empty (clean).
- Existing models: mutable `TestAuthoringRevision`, immutable `ConfirmedAuthoringRevision`, and `Test.active_confirmed_revision_id`.
- Previously the draft creation endpoint cloned the latest working snapshot, did not identify its parent confirmed revision, and reset its edit version to 1. This could invalidate inherited diagram/review revision metadata.

## Architecture and lineage

- Add nullable `TestAuthoringRevision.parent_confirmed_revision_id`, referencing an existing immutable confirmed revision. Confirmed lineage is obtained through its immutable producing working revision identity. Historical snapshots are never rewritten.
- Explicit fork accepts a selected confirmed revision belonging to the same owned Test; omitted selection uses the active confirmed basis for backwards compatibility.
- Fork verifies the parent's canonical payload/hash and deep-copies its exact snapshot. It does not normalize or re-attest the payload, change diagram revisions, duplicate source files, or invoke inference.
- New editable draft gets an edit version greater than all previous working edit versions. This is concurrency metadata only; diagram content remains unchanged. Saves from discarded/replaced drafts therefore fail CAS.
- Confirmation continues using the existing transaction, exact saved snapshot, non-mutating validation, CAS and idempotency. Only successful confirmation changes the active confirmed pin. The old immutable revision remains inspectable.
- Source/material IDs, role separation, SHA/artifact references, source review acknowledgements, classifications, crop geometry and manual/reuse provenance are preserved by exact copy.

## Numbering, history and read-only inspection

- Teacher labels are `第1版`, `第2版`, etc., derived deterministically by ranking confirmed working revision numbers (then ID). Every new fork receives a higher working revision number; clock corrections cannot renumber existing editions. Timestamps are display metadata only. Working analysis-backup numbers do not appear as edition labels. Existing confirmed rows need no payload or metadata rewrite.
- `版の履歴` opens the shared accessible `AuthoringDialog`. It shows confirmer/time, current active edition, historical editions, existing draft and parent edition.
- Selecting an edition shows its Question hierarchy/body/scores, ModelAnswers/alternatives, accepted diagrams, Rubric descriptions/points and expandable provenance. No inputs or Save controls are rendered for the historical content.
- Historical diagram URLs resolve records and crop identities from the owned immutable snapshot, with an explicit node/entry owner; they read only existing crops from the selected confirmed record and verify the binary SHA inside the owned source artifact directory. They do not use the newest working draft, rediscover geometry or regenerate crops. Retired logical bindings remain inspectable historically, while current draft/reuse source validation stays unchanged; tampered crop bytes are rejected.
- `修正版を作成` is available only without an existing editable draft. An existing draft is shown rather than overwritten. Repeating the same fork resumes the existing draft; requesting a different parent returns a clear conflict.
- `修正版を破棄` requires explicit teacher confirmation, matching working identity/version/hash, and a revised-draft parent. It marks the working draft discarded, preserves its audit event and all confirmed revisions/artifacts, and returns to the confirmed workspace.

## Grading/history safety

Safe draft preparation is allowed with submission history. Existing readiness and confirmation guards continue blocking unsafe activation/reprojection for Tests with submissions/grading history. No submission, job or result references are rebound. This phase does not solve the known mutable-formal grading assembler limitation.

## Migration and compatibility

- Additive migration: `0018_revision_lineage` (ID below PostgreSQL's 32-character limit), after `0017_confirmed_revision`.
- Nullable FK only; no snapshot updates, DB reset or backfill of guessed lineage.
- Existing pre-12d confirmed revisions remain readable; unavailable historical lineage is shown as absent.
- Upgrade handles both old schemas and the fresh-install convention where initial metadata already contains current columns. SQLite fresh upgrade/downgrade/upgrade and retained-row migration tests pass.
- Downgrade removes the new lineage metadata only; operators should back up before downgrade because parent links would be lost. Source/confirmed snapshot content is not rewritten.
- Actual PostgreSQL deployment/migration must follow the operator's established backup/runbook process; no production migration was run here.

## Verification

Final validation completed against the final product code:

- Full backend: **996 passed, 2 skipped, 23 existing warnings**.
- Full normal production-like Chromium: **73 passed**; **grading jobs 0**. This includes the new revision-history scenario and existing Final Review, correction UX, source-backed, role-isolation, diagram/manual/reuse, OCR, Save/resume and stale-tab groups.
- Production Next build: passed as part of the final normal browser harness.

Focused/static results:

- Authoring/confirmation/diagrams backend: **92 passed**, 1 existing warning.
- Additional final historical-artifact/diagram checks: **32 passed**, 1 existing warning.
- Final focused actual Sample Q5 revision + keyboard discovery/crop/reuse + legacy Rubric split regression, fresh disposable Chromium harness: **3 passed**, grading jobs **0**.
- Actual Sample Q5 revision scenario: **3 consecutive independent fresh Tests passed** in stress execution.
- TypeScript passed; ESLint **0 errors / 19 existing warnings**; Ruff passed; production Next build passed (existing CSS/browser-image/hook warnings only); `git diff --check` passed.

Second confirmation also recomputes raw API canonical hashes of saved/confirmed payloads, and re-sending the first edition's confirmation after the second edition is active returns the original edition without moving the active basis backwards.

### Broader regression finding

A legacy Rubric screen deferred textarea autofocus could run after the teacher/test selected a score input, diverting a digit into criterion prose. The browser trace and saved payload showed `Accepted duplicate criterion.3`. The same deferred-focus race was also traced in the shared preview-to-editor transition: focus explicitly moved to the diagram-discovery button could be stolen by pending textarea autofocus, preventing keyboard Enter from starting discovery. Narrow focus-at-request guards now skip deferred focus when a newer control selection exists, including score inputs and action buttons; no Rubric semantics or layout changed. The existing regression now asserts all score values and both criterion texts before Save as well as after reclassification.

The mixed `--repeat-each 3` stress attempt used the legacy spec's shared seeded Test, so its second/third executions correctly accumulated Rubric versions 4/6 and failed the fixed version-2 assertion. Those assertions were not weakened. Fresh disposable normal-harness execution passed both scenarios; only the fresh-Test revision scenario's three stress passes are counted above.

Focused backend coverage includes exact fork/hash, clean initial readiness, parent immutability, second confirmation, active pin transition, deterministic history, duplicate/different-parent handling, discard and stale saves, rollback preserving prior active basis, historical submission activation block, and automatic/manual/reused/multiple diagram preservation and historical previews.

Actual Sample Q5 Chromium scenario uses `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`: Q3 split, automatic/manual/reused diagrams, initial confirmation, read-only 第1版, exact fork and raw canonical hash equality, teacher description edit, Save, 第2版 confirmation, independent old/new views, reload/Back/resume and zero additional model calls for revision operations.

## Future Undo/Redo

Confirmed revisions remain immutable anchors. A future working-history journal can store operation boundaries or immutable working snapshots keyed by working revision/edit version, covering text/score edits, Question split/merge/reparent, Rubric split/merge, candidate assign/exclude and diagram accept/reuse/manual crop. Undo/redo should only move/reapply working-state operations; it must never mutate confirmed history or retroactively change a grading pin. Discarded working rows are retained but are not yet a general undo engine.

## Operator handoff

Deploy frontend, backend and additive migration together using the established backup/deployment workflow. Preserve the production environment files and artifact directories; do not reset the database. Then use a **new dedicated validation Test**: confirm 第1版 with actual Sample Q5 diagrams, create exact revised draft, edit/Save, verify active basis still 第1版, confirm 第2版, inspect both editions and reload/resume. Verify inherited diagrams/source review remain valid; verify historical submission/grading activation guard remains enforced. No production Test was accessed or changed during this phase.

## Files changed

- `src/scoring/db/models.py`: working parent confirmed FK.
- `src/scoring/authoring_revision_artifacts.py`: read-only historical crop attestation, ownership/path containment and binary hash checks.
- `migrations/versions/0018_revision_lineage.py`: additive, compatible lineage migration.
- `src/scoring/test_authoring.py`: explicit attested snapshot fork, parent link, monotonic edit version, duplicate-draft guard.
- `src/scoring/api/test_authoring.py`: history/read-only edition/crop endpoints, fork selection and discard CAS.
- `frontend/lib/api/testAuthoring.ts`: revision metadata and history/fork/discard API types.
- `frontend/components/reviews/AuthoringRevisionHistory.tsx`: history and immutable content inspection.
- `frontend/app/tests/[testId]/authoring/page.tsx`: revision entry point/state header, explicit displayed-parent fork, discard integration and safe target restoration.
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`: narrowly guard deferred Rubric focus against newer field selection.
- `frontend/e2e/rubric-split-real-isolated.spec.ts`: strengthen content/score preservation assertions for the diagnosed focus race.
- `frontend/components/reviews/AuthoringPreviewEditor.tsx`: preserve newer explicit focus during deferred editor autofocus.
- `frontend/e2e/authoring-sample-q5-diagram-real.spec.ts`: explicitly attest keyboard focus before discovery Enter.
- `tests/test_test_authoring.py`: revision lifecycle, conflicts, rollback, migration and historical safety.
- `tests/test_authoring_diagrams.py`: exact fork, historical automatic/manual/reused diagram previews, retired binding and tampered crop negatives.
- `tests/run_runtime_browser_e2e.py`: include the revision lifecycle scenario in the normal production-like suite.
- `frontend/e2e/authoring-revision-history-real.spec.ts`: actual-PDF edition lifecycle regression.
- `docs/reports/j-ui-12d.md`: separate implementation/validation/handoff report.

## Remaining issues / safety

- Operator deployment and a new dedicated production validation Test are required before COMPLETE.
- Actual PostgreSQL migration execution was not available locally; standard additive ALTER/FK migration and migration identifier constraints were reviewed, and SQLite fresh/upgrade/downgrade/upgrade paths passed. Follow the production runbook and backups.
- Historical grading activation remains deliberately blocked; full immutable grading-input assembly is future work.
- General Undo/Redo, visual revision diffs and parallel branch management remain deferred.
- No production connection or mutation occurred. All browser/domain validation used disposable local records/artifacts; no student grading was launched. Fork/history/Save/Confirm introduced no additional model calls.
- No production credential values were printed or written. Added-content password-literal audit found 0 matches. No credential/config/auth/local-helper file is in the change list.

## Git status

Exact final status (all changes unstaged, no commit/push):

```text
 M frontend/app/model-answer-import-reviews/[draftId]/page.tsx
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringPreviewEditor.tsx
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/rubric-split-real-isolated.spec.ts
 M frontend/lib/api/testAuthoring.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/db/models.py
 M src/scoring/test_authoring.py
 M tests/run_runtime_browser_e2e.py
 M tests/test_authoring_diagrams.py
 M tests/test_test_authoring.py
?? docs/reports/j-ui-12d.md
?? frontend/components/reviews/AuthoringRevisionHistory.tsx
?? frontend/e2e/authoring-revision-history-real.spec.ts
?? migrations/versions/0018_revision_lineage.py
?? src/scoring/authoring_revision_artifacts.py
```

Tracked diff summary (new service files listed above are additional):

```text
 .../model-answer-import-reviews/[draftId]/page.tsx |   4 +
 frontend/app/tests/[testId]/authoring/page.tsx     |  17 ++-
 .../components/reviews/AuthoringPreviewEditor.tsx  |   3 +
 .../e2e/authoring-sample-q5-diagram-real.spec.ts   |   2 +-
 frontend/e2e/rubric-split-real-isolated.spec.ts    |   8 +-
 frontend/lib/api/testAuthoring.ts                  |   8 +-
 src/scoring/api/test_authoring.py                  |  91 +++++++++++++-
 src/scoring/db/models.py                           |   1 +
 src/scoring/test_authoring.py                      |  21 +++-
 tests/run_runtime_browser_e2e.py                   |   1 +
 tests/test_authoring_diagrams.py                   |  44 +++++++
 tests/test_test_authoring.py                       | 131 +++++++++++++++++++++
 12 files changed, 313 insertions(+), 18 deletions(-)
```
