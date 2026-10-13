# J.UI.13 — Compact Rubric Editing UX

Status: READY_FOR_PRODUCTION_VALIDATION.

## Changes

Rubric criteria now render in the normal authoring view as readable criterion text with a local edit action. Score levels are collapsed by default and summarize level count/scores plus the derived `最高点`. Expanded levels use a compact table with readable conditions and per-row edit actions. Criterion text and score/condition pairs are changed in focused dialogs; dialog completion updates only the in-memory working draft, while the existing global Save remains the persistence boundary. Cancel leaves the draft unchanged. The required zero-point level cannot be deleted through the ordinary dialog.

The score-level display sorts a copy for readability and does not reorder stored policy. Existing criterion grouping, split/merge, undo, exclusion, and source operations remain available under compact operation disclosures. No Question/Answer layout or scoring semantics changed. Rubric issue navigation opens the score-level disclosure and targets its summary or row edit control. Shared dialog focus now enters the dialog and returns to the initiating control on close.

Teacher-facing maximum terminology is consistently `最高点`; the legacy compatibility field remains internal and derived from score levels. Final Review and historical views retain their read-only policy presentation.

## Validation

- Disposable production-like browser harness: `python -m tests.run_runtime_browser_e2e`, using a fresh temporary SQLite database, real FastAPI, RuntimeManager, managed synthetic model stub, and production Next build/server. The earlier stale-build/`--skip-build` attempt was discarded and is not counted.
- Focused J.UI.13 browser run: 3 passed. It covered compact criterion display, score-level summary collapsed by default, expanded table, criterion and score-level dialogs, add/delete, zero-level protection, local dirty state, Save/reload, score-level issue navigation, Final Review, and history/read-only policy display. No test was skipped.
- Focused authoring regression group: 20 passed, 0 skipped, 0 failed. This included issue-overlay/final confirmation, source-backed authoring, Sample Q5 diagram confirmation/reuse, Rubric split/merge, recovery candidates, and whole-Test Save/resume.
- Full production-like Chromium suite: 74 passed, 0 skipped, 0 failed (4.4 minutes). All selected tests ran with the normal API fixture; no infrastructure failure was counted as a feature pass.
- The existing Rubric browser regressions were updated to use the compact criterion cards, local dialogs, and score-level disclosure. Assertions for split/merge, source provenance, stale-save conflict, and recovery ownership remain active.
- TypeScript: passed. ESLint: 0 errors, 19 existing warnings in unrelated files. Next production build: passed with existing Autoprefixer and lint warnings. `git diff --check`: passed.
- Grading jobs: 0, verified by the harness after the full suite. Real model calls: 0; tests used only the local managed synthetic stub where analysis flows required it.

## Production handoff

Local validation is complete. Deploy the already-implemented J.UI.13 changes through the established production process, then perform production acceptance on a dedicated disposable Test. No production deployment or production data changes were made during this validation run.

## Files changed

- `frontend/components/reviews/AuthoringCandidates.tsx`
- `frontend/components/reviews/AuthoringDialog.tsx`
- `frontend/components/reviews/ExecutableRubricLevels.tsx`
- `frontend/app/tests/[testId]/authoring/page.tsx`
- `frontend/app/globals.css`
- `frontend/e2e/rubric-levels-canonical.spec.ts`
- `frontend/e2e/authoring-correction-ux-real.spec.ts`
- `frontend/e2e/authoring-final-confirmation-real.spec.ts`
- `frontend/e2e/authoring-final-review-issues-real.spec.ts`
- `frontend/e2e/authoring-preview-materials-real.spec.ts`
- `frontend/e2e/authoring-rubric-reliability-real.spec.ts`
- `frontend/e2e/authoring-source-backed-real.spec.ts`
- `frontend/e2e/authoring-split-merge-real.spec.ts`
- `frontend/e2e/test-authoring-foundation-real.spec.ts`
- `docs/internal/reports/j-ui-13-compact-rubric-editing.md`

## Exact git status

```text
 M frontend/app/globals.css
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/AuthoringDialog.tsx
 M frontend/components/reviews/ExecutableRubricLevels.tsx
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M frontend/e2e/rubric-levels-canonical.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
?? docs/internal/reports/j-ui-13-compact-rubric-editing.md
```
