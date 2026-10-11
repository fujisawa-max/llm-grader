# J.UI.12e — Authoring Correction UX Polish

## Result

**READY_FOR_PRODUCTION_VALIDATION** — local implementation and final regression passed. Operator deployment and deployed UX acceptance remain. No deployment or production mutation is performed by this phase. J.UI.12c remains COMPLETE; J.UI.12d and Undo/Redo are not started.

## Baseline

- HEAD: `38c9c0300f212968289e8cf8315ba610d55fa752`.
- Initial status: ` M docs/reports/j-ui-12c.md` only. This is the preceding phase's production-acceptance report update and remains intact. No 12e history is appended there.
- No migration, DB reset, grading job, or formal publication is added.

## Correction navigation

Previously, centering a control in a tall criterion/candidate could leave its meaningful text above the visible viewport. Navigation now captures the content card before narrowing to the focused control. A shared scroll helper reveals the card, accounts for the sticky selector/header, and leaves a small contextual margin below it. Control focus uses `preventScroll`; the existing transient highlight remains.

- Rubric points navigation reveals the criterion card rather than only its number input.
- Classification navigation opens the classification details and reveals its content.
- Unassigned mapping navigation reveals/highlights the exact candidate and focuses its assignment selector.
- Recovery navigation opens the existing panel and reveals the identified candidate, including its internal scroll container.
- Explicit classification/grouping confirmation restores the local content position after the action changes the card.
- No editor columns or overlay geometry change. Default textarea sizing remains unchanged; the existing 132px minimum already supplies a moderate density.

## Manual classification confirmation

`manualClassificationPatch` applies the existing `teacher_reviewed` classification status only when a meaningful routing/category change occurs: disposition, target Question, primary/alternative answer kind, or segment category. Choosing the already-current value is not a new decision. Text, punctuation, criterion prose, and point edits do not pass through this helper and do not implicitly confirm classification. Existing explicit confirmation controls remain.

Teacher metadata records `teacher_confirmed`, `confirmation_origin: manual_edit`, and the changed field names. The first original classification and routing state are retained as `classification_original` and `classification_routing_original`, including original segment/source/confidence information. Subsequent edits retain that original evidence. Explicit ignored disposition remains recorded and does not weaken fix15e or saved-diagram reuse filtering.

The Rubric adapter now round-trips existing `mapping_state` and `teacher_correction` rather than replacing/dropping them. Answer/Rubric collections and source bindings remain separate.

## Unassigned processing queue

Unresolved candidates now show their source text and resolution controls without needing to discover the body-edit switch:

> この候補を対応する設問へ割り当てるか、不要な候補として除外してください。

- `対応する設問` assigns the candidate to a gradable Question, sets included/manual-mapped state, and records the explicit teacher routing decision.
- `不要として除外` sets ignored disposition. The candidate, source draft, source segments, and history remain stored. The excluded card explains that the source/candidate is retained.
- Existing recovery promotion/ignore controls remain; no recovery auto-promotion is introduced.
- Aggregate correction actions support both unassigned Answer and Rubric candidates. They focus the specific candidate rather than a generic view.

The same existing readiness source continues to drive the issue tab, per-Question `*`, and Final Review blockers. Resolved classification issues disappear in the working client state; assignment/exclusion removes the corresponding blocker after Save. Unsaved changes remain a separate state and continue to block Confirm.

## Regression discovered and repaired

The first full browser run found a Save 409 in the existing unmatched-analysis assignment scenario. Its automatic classification was `fallback` with uncertain segments and an empty recovery collection. Marking the teacher's routing decision `teacher_reviewed` caused the compatibility adapter to derive new recovery rows from those segments, which the immutable recovery-source guard correctly rejected.

The adapter now synthesizes recovery only for legacy mixed snapshots, not for already-separated drafts with an authoritative recovery collection. For legacy rows derived on read, Save seeds that evidence from the saved original before adapting the new teacher decision. This preserves the original automatic status/target and retains the immutable-source checks. No blocker or source safety rule is relaxed.

Two backend regressions prove successful confirmation/assignment without new fallback recovery, preservation of legacy evidence, unchanged input snapshot, and rejection of recovery text tampering/removal. The existing unmatched-analysis browser regression then passes.

## Validation

- New browser coverage: classification semantic edits vs prose edits; automatic provenance persistence; Answer/Rubric assignment and exclusion; exact candidate focus, visible guidance and source retention; classification/grouping navigation geometry and highlight; issue counts/markers/readiness; reload; no extra inference.
- Existing fix1 browser coverage now also asserts that the criterion textarea is below the sticky selector and inside the viewport. No-reflow overlay, hierarchy, markers and blocker corrections remain covered.
- Focused browser: 8 passed after the repair (new correction UX, fix1 issues, existing split/merge/unmatched assignment).
- Initial focused backend: 124 passed, 1 warning. Post-repair focused backend: 59 passed, 1 warning.
- Final full production-like Chromium suite: **72 passed (3.5 minutes)**; grading jobs = **0**. Includes actual Sample Q5 auto/manual/reused-diagram confirmation, fix15e inclusion/ignored negative, role isolation, source-backed editing, Rubric, Save/resume, stale tabs, Final Review, CAS/idempotency, and the new correction tests.
- Final full backend after the last product change: **981 passed, 2 skipped, 23 warnings in 227.32 seconds**. Includes confirmation atomicity/rollback, immutable snapshot/hash integrity, CAS/idempotency, authoring/readiness/classification, source isolation and diagram regressions.
- TypeScript passed; ESLint 0 errors / 19 existing warnings; Ruff passed on all changed Python files; production Next build passed as part of the final browser harness; `git diff --check` passed. No new lint errors.
- Earlier full browser run: 71 passed / 1 failed; the failure above was diagnosed and repaired, with no retry/sleep/assertion weakening.
- Intermediate full backend before the final adapter repair: 979 passed, 2 skipped, 23 warnings.
- Validation uses the real FastAPI/RuntimeManager path, disposable databases and managed deterministic model stubs, production Next build and Chromium. Existing actual Sample Q5 diagram/confirmation cases are included in the full normal browser suite.
- Early `--skip-build` attempts failed login because the prior Next build had baked in a different disposable API port. Rebuilding for each fresh harness resolved that environmental failure.

## Safety and production acceptance

Focused browser call-count assertions show no model-call increase from routing changes, assignment/exclusion, Save, readiness refresh or reload. The browser harness asserts grading jobs = 0. Confirmation transaction, snapshot/hash integrity, CAS/idempotency and immutable-revision architecture are unchanged and included in broader regression.

No production connection, deployment, credentials, migration or existing production data modification is required/performed in this phase. After operator deployment, verify content-visible correction navigation, routing edits resolving classification issues, and assignment/exclusion resolving unassigned blockers on an isolated draft. J.UI.12c remains COMPLETE.

## Future Undo/Redo note

Future J.UI.12d/revision-management design should consider undo of unsaved operations and one-step/multi-step undo/redo for Question split/merge/reparent, Rubric split/merge, diagram accept/reuse/manual crop, candidate assign/exclude, and saved working revision history. No Undo/Redo implementation is included here.

## Files changed

- `frontend/lib/reviewIssues.ts`: content-first sticky-aware scroll helper; existing review navigation reuse.
- `frontend/app/tests/[testId]/authoring/page.tsx`: precise correction targets, recovery IDs, Rubric unassigned navigation and metadata round-trip.
- `frontend/components/reviews/AuthoringCandidates.tsx`: classification-routing confirmation, visible unassigned processing controls and local confirmation scrolling.
- `frontend/lib/authoringClassification.ts`: focused teacher-confirmation/provenance helper.
- `frontend/lib/api/testAuthoring.ts`: existing Rubric metadata type support.
- `frontend/app/globals.css`: bounded processing-queue styling; no overlay/editor layout change.
- `src/scoring/authoring_issue_guidance.py`: actionable assignment/exclusion/classification wording.
- `src/scoring/authoring_sources.py`: avoid regenerating authoritative recovery from current teacher decisions.
- `src/scoring/test_authoring.py`: preserve saved legacy recovery evidence during Save compatibility adaptation.
- `tests/test_test_authoring.py`: fallback/legacy recovery safety regressions.
- `tests/run_runtime_browser_e2e.py`: disposable realistic source-backed correction fixtures and new default suite entry.
- `frontend/e2e/authoring-correction-ux-real.spec.ts`: three focused production-like correction tests.
- `frontend/e2e/authoring-final-review-issues-real.spec.ts`: viewport geometry assertion for criterion content.
- `docs/reports/j-ui-12e.md`: standalone phase report.
- `docs/reports/j-ui-12c.md`: inherited baseline change only; not changed by 12e.

## Final git status

```text
 M docs/reports/j-ui-12c.md
 M frontend/app/globals.css
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/lib/api/testAuthoring.ts
 M frontend/lib/reviewIssues.ts
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/authoring_sources.py
 M src/scoring/test_authoring.py
 M tests/run_runtime_browser_e2e.py
 M tests/test_test_authoring.py
?? docs/reports/j-ui-12e.md
?? frontend/e2e/authoring-correction-ux-real.spec.ts
?? frontend/lib/authoringClassification.ts
```

The 12c report change is inherited from the initial baseline. No files staged, committed or pushed.
