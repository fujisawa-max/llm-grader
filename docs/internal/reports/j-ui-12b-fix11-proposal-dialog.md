# J.UI.12b-fix11-proposal-dialog — Rubric Split Proposal Modal

## Result
**READY_FOR_PRODUCTION_VALIDATION**. Production untouched; no commit/push/deployment.

## Baseline
- HEAD: 65de8b78a0f04832afaebc99d0abd3bfa406d177
- Initial working tree: clean.

## Audit and implementation
The split review panel followed all criterion editors within its owning candidate. Ownership was correct, but a middle criterion's result could appear below the viewport. Cursor and assisted proposals now auto-open the shared AuthoringDialog, extracted from the existing authoring analysis confirmation and using the native modal lifecycle already used for archive confirmation. Analysis confirmation uses the same component.

Native showModal provides background inertness, focus containment and Escape handling. Cleanup restores focus; cursor cancellation explicitly restores the originating split button (pointer handling preserves the textarea caret). Header/footer remain outside an internally scrolling body.

Proposal ownership includes component Test/draft/Question scope, entry ID, stable criterion ID, original local criterion baseline and server revision ID. Apply rechecks active server revision ID/edit_version and local criterion baseline, then uses the unchanged range split/history operation. Final Save still enforces server CAS. No server mutation is performed by proposal generation or local apply. Failure retains the dialog/proposal and allows retry; application is guarded against duplicate execution and dismissal.

Candidates remain read-only because the existing domain proposal represents exact original-text ranges and source anchors. Arbitrary candidate editing would invalidate those ranges. Cancel, edit the original criterion and regenerate is the safe supported path. Original current text and points, proposed text/points, and point-conflict guidance are visible. No automatic redistribution or publication is added.

## Verification
Completed: focused 5, final normal 60, critical 11 browser/helper scenarios; full backend 920 passed / 1 skipped.

## Deferred
J.UI.12c final publication and Question/Rubric drag-and-drop remain deferred. Deployed acceptance is required.

## Accessibility defect reproduced during verification
The first full run passed 59 scenarios but the new keyboard scenario failed: native dialog Tab cycling could move document.activeElement outside the dialog at the end of the sequence. Reused the existing analysis confirmation's first/last-control keyboard cycle in the shared dialog. Added explicit background scroll locking/restoration. The regression asserts five consecutive Tab presses remain inside, Escape cancels, and focus returns to the exact originating cursor-split button. Final focused, normal and critical reruns passed.

Added the real Japanese middle-criterion fixture with three rows, prefix removal, viewport bounds, internally scrolling long text, transient preflight failure/retry and external saved revision conflict. A stale proposal's Apply button is disabled; cancellation remains available.

Focused final-code run: 5 passed, including the real Japanese middle-criterion, keyboard, long content and conflict/retry scenario. Disposable harness reported grading jobs 0. Full final-code browser rerun and critical truncated-response group subsequently passed.

## Domain and interaction findings
- Cursor proposals use the actual active textarea/current buffer and current caret, including teacher-removed prefixes. Invalid start/end/math boundaries retain existing actionable errors and never open an empty dialog.
- Assisted generation retains its existing explicit model call, spinner and double-request guard. Proposal generation changes no Rubric rows; there is no Toast solely for opening/cancelling.
- Apply preserves stable original identity in provenance, generates new independent child criterion IDs and replaces only the targeted criterion with consecutive rows. Display numbering follows current order. Existing bounded operation history permits Undo/merge.
- Cancel/Escape preserve text, points, ordering and history. Background is inert while the modal is open; no second proposal is available. Apply disables both actions and Escape cancellation until completion.
- Existing points conflict semantics remain: ranges with explicit points retain those values; ambiguous splits do not duplicate original points and require teacher confirmation.
- Proposed text/ranges remain read-only. No UUID/source token/full SHA is exposed in normal modal content.
- The previous inline split panel is removed; consolidation review is unchanged.
- Split apply is an in-memory operation after a read-only server preflight. This is not a server transaction lock: an update occurring after that read is still protected by the existing final Save CAS.

## Automated verification
- Full backend regression: **920 passed, 1 skipped**, 21 collection/deprecation warnings. No Python service/backend semantic change.
- TypeScript: passed.
- ESLint: 0 errors, 19 existing warnings.
- Ruff `src tests`: passed (extra check; no Python changes).
- Production Next build: passed in focused harness; existing CSS autoprefixer warnings.
- `git diff --check`: passed.

## Files changed
- `frontend/components/reviews/AuthoringDialog.tsx` — shared modal lifecycle, focus cycle/restoration, background inertness/scroll lock.
- `frontend/components/reviews/AuthoringCandidates.tsx` — modal proposal presentation and ownership/conflict guards.
- `frontend/app/tests/[testId]/authoring/page.tsx` — uses shared component for existing role-specific analysis confirmation.
- `frontend/app/globals.css` — modal viewport/internal body scroll/footer sizing.
- `frontend/e2e/authoring-rubric-reliability-real.spec.ts` — modal locators and Japanese middle-criterion/keyboard/long/retry/conflict regression.
- `frontend/e2e/authoring-source-backed-real.spec.ts` — modal apply locator.
- This report.

Final production-like normal browser suite: **60 passed**, grading jobs **0**. Includes HARDEN Save/reload/Back/resume endurance, dirty-save readiness, stale-tab Save, edit-during-Save, source-backed Question/Answer/Rubric merge, notifications/issues, source replacement and legacy review. The final normal run includes the new assisted middle-criterion apply/cancel checks; a subsequent critical run also includes cancellation of an unedited source-backed proposal.


Final critical truncated-Ricoh / diagram reuse / OCR / Rubric modal / Save-resume / shared-source analysis group: **11 passed**, grading jobs **0**. This rerun includes unedited source-backed cancellation, teacher-edited source-backed apply/persistence, Japanese middle-criterion cursor and assisted apply/cancel, internal long-content scrolling, keyboard trap/return, retry and stale revision rejection.

## Required checklist
- [x] Single automatically opened dialog; no inline split review.
- [x] `role=dialog` (native dialog), `aria-modal`, labelled title `基準Nの分割案`, original/current criterion and candidate text/points.
- [x] Apply/cancel, Escape cancellation, focus containment/return, background inertness and scroll locking.
- [x] Viewport bounds, long body internal scroll, reachable actions.
- [x] Active textarea/caret, original source-backed and teacher-edited text; invalid boundary guard.
- [x] Assisted running feedback, explicit inference only, no auto-apply, apply/cancel/error/retry.
- [x] Stable target identity, consecutive order, points rules, source provenance, Undo/merge and Save/reload/Back/resume.
- [x] Stale revision preflight rejects without local mutation; existing Save CAS remains authoritative.
- [x] Answer section ownership and `基準` terminology.
- [x] Shared source, tooltip, diagrams/reuse, OCR, notifications/issues and HARDEN critical regression.
- [x] TypeScript / ESLint no new errors / Ruff / production build / diff check.
- [x] Disposable harnesses: grading jobs zero; no authoring publication.
- [ ] Deployed real-machine acceptance (intentionally unperformed).

## Git status
Seven service-related files changed: five tracked modifications plus the new shared component and this report. Nothing staged/committed/pushed. No backend/schema changes.

## Remaining issues / production acceptance
No reproduced product defect remains from this scope. Verify real deployment's three-criterion cursor split, teacher-edited prefix removal, assisted split, immediate dialog visibility near viewport bottom, keyboard navigation and apply/cancel. Proposal text editing is intentionally unsupported to protect source ranges; cancel/edit/regenerate remains available. Session modal state is not persisted across navigation. J.UI.12c and all drag-and-drop remain deferred.
