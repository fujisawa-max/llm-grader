# J.UI.12b-fix9 — Quiet Analysis Readiness Hint & Split Section Separation

## Result

READY_FOR_PRODUCTION_VALIDATION. Implementation and automated checks passed; deployed acceptance is not performed.

## Baseline / audit

- Baseline HEAD: `3cc71641a1a6bad47bdc684f9d54ab4494be5180`; initial working tree clean.
- The authoring page rendered the typed `unsaved_changes` readiness state as a large inline source-pane notice with a second Save button. The analysis action already used the same typed readiness to remain disabled.
- Split proposals rendered classification and source settings first, then the editable child name last. Blocks had no explicit horizontal separator.

## Implementation

- Removed the unsaved-analysis inline banner. The main Save action remains the single Save entry point.
- Added reusable `DisabledActionHint`: a keyboard-focusable wrapper around disabled analysis controls, an `aria-describedby` connection, and a `role=tooltip` shown on hover or focus. The wrapper leaves the tab order when the action becomes ready.
- `unsaved_changes` uses “未保存の変更があります。この資料を解析する前に保存してください。” Other unavailable states use the existing typed readiness reason. Readiness logic and API state transitions are unchanged.
- Save immediately removes the reason/Tooltip and enables the existing analysis confirmation action. Showing a Tooltip does not save, analyze, notify, or change an Issue.
- Moved each split block's editable name to its top, followed immediately by a shared `authoring-split-divider` horizontal separator; classification and source settings follow. Parent-context, child, and excluded blocks share the same styling. Mapping, classification, apply/cancel and provenance semantics are unchanged.

## Regression coverage

- Updated former banner assertions to verify absence of the banner, exact Tooltip wording, hover visibility, focus visibility and hiding after focus leaves.
- Existing repeated readiness tests still verify disabled actions before Save, immediate enabling after Save, no automatic analysis and retained Save/Back/reload state.
- Split E2E checks all three proposal blocks, divider width, and vertical order: name input → divider → role selector.
- Notification history and Issues remain distinct and use their existing state models.

## Verification

- Normal production-like browser regression: **56/56 passed**. Includes hover/focus Tooltips, immediate Save readiness, modal confirmation, split divider geometry, 10 Save/reload/Back/resume cycles, 5 dirty/Save/readiness cycles, stale Save and in-flight editing, notification/Issues, Answer/Rubric analysis, source-backed editing and legacy routes.
- Additional truncated-Ricoh / authoring diagram reuse / Question and Answer OCR regression: **4/4 passed**.
- TypeScript: passed. ESLint: **0 errors, 19 existing unrelated warnings**. Ruff: passed. `git diff --check`: passed.
- Production Next.js build: passed through both isolated browser harnesses; existing CSS compatibility warnings remain.
- Both harnesses report **grading jobs 0**. No automatic model calls were added by presentation or focus changes.
- Backend tests were not rerun for this frontend-only presentation change; no backend code changed.

## Files changed / git status

- `frontend/components/reviews/DisabledActionHint.tsx` (new shared disabled-control hint)
- `frontend/app/tests/[testId]/authoring/page.tsx` and `frontend/app/globals.css`
- `frontend/e2e/authoringNotifications.ts` and four authoring specs: analysis-access, endurance, save-resume, split-merge
- This report
- Changes remain unstaged/uncommitted; HEAD remains the recorded baseline.

## Safety / remaining

- Frontend-only presentation changes; no backend/schema changes or production access.
- No commit, push, or deployment.
- Production UX acceptance remains required.
- Question drag-and-drop and J.UI.12c final publication remain deferred.
