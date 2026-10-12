# J.UI.12e — Authoring Correction UX Polish

## Result

**COMPLETE** — local regression passed and production correction-UX acceptance passed on 2026-10-11 after operator deployment. Dedicated validation records only were modified. J.UI.12c remains COMPLETE; J.UI.12d and Undo/Redo are not started.

## Baseline

- HEAD: `38c9c0300f212968289e8cf8315ba610d55fa752`.
- Initial status: ` M docs/internal/reports/j-ui-12c.md` only. This is the preceding phase's production-acceptance report update and remains intact. No 12e history is appended there.
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

The local implementation stopped before deployment. The operator subsequently deployed 12e and explicitly requested production acceptance. Its results are recorded below; J.UI.12c remains COMPLETE.

## Production acceptance — 2026-10-11

- Acceptance checkout HEAD: `336b3f0dc998a88831c01c30330b7fe777ad23f3`; working tree was clean at acceptance start.
- Teacher browser login and authenticated API access passed. Deployed 12e was demonstrated by its new issue guidance, processing controls, manual-edit confirmation metadata and content-first navigation, rather than assumed from the local checkout.
- Dedicated Course/Offering: `Codex Validation - J.UI.12e 2026-10-11T17-07-51-561Z`.
- Dedicated Test: `Codex Validation - J.UI.12e 2026-10-11T17-07-51-561Z - Source candidates`. It remains as an editable validation draft for inspection; no Confirm/publication was performed.
- Uploaded the actual `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf` as Answer and Rubric sources and ran explicit source analysis. Native Answer extraction produced one unassigned source-backed candidate with classification `fallback`. Native Rubric extraction produced no useful candidates and no recovery rows. No extracted Rubric data was fabricated.

### Correction navigation and confirmation

- Final Review's native unassigned-Answer action selected the unassigned queue, highlighted the exact candidate, focused `対応する設問`, and displayed the concrete assignment/exclusion guidance. The candidate text was visible below the sticky selector.
- A controlled classification-review state was then exercised on the same dedicated source candidate using its permitted teacher-editable segment categories and normal authenticated authoring Save. Server canonicalization produced `needs_teacher_review`. This was a controlled teacher-edit case, not a claim that native inference produced that status; the original native automatic `fallback` classification remained in teacher history.
- The selected Question showed `*` and `要修正 1件`. Opening the issue overlay preserved editor width and window scroll position. Its correction action opened/highlighted classification content in the visible viewport.
- Editing answer prose and saving left `needs_teacher_review` and its issue intact. Changing answer kind and returning it to the intended primary kind changed status to `teacher_reviewed`, recorded `confirmation_origin: manual_edit`, and retained the original automatic classification exactly.
- The issue tab and selected dropdown `*` disappeared immediately while Save remained dirty. Final Review showed the unsaved warning and disabled Confirm. Save then cleared the unsaved state without analysis.
- A five-criterion teacher-authored Rubric exercised a low-page criterion's `修正箇所へ` and `この採点基準を確認`. The criterion textarea, not only its button, was visible below sticky controls both before and after confirmation. Highlight remained functional, and its issue disappeared after the explicit confirmation.
- Chromium viewport: 1600×900. Sticky selector bottom: y=232px; classification content began at y=280.78px, unassigned candidate text at y=298.88px, and the Rubric textarea at y=309.72px with height=132px. The meaningful content was inside the viewport below the sticky controls.

### Unassigned processing and persistence

- Native PDF-derived Answer candidate: assignment set included/manual-mapped state and teacher-reviewed classification; its unassigned blocker disappeared. Its source, source draft and original automatic classification were unchanged. Returning it to the unassigned queue and choosing `不要として除外` set ignored disposition, retained the source-backed candidate, and removed its blocker.
- Since native Rubric extraction returned zero candidates, two clearly teacher-authored non-scoring Rubric candidates were created in this dedicated draft through normal authoring Save to exercise the same unassigned UI. One was assigned and the other explicitly excluded. Both retained their teacher-manual source/history and manual confirmation metadata; their corresponding blockers disappeared. This production case does not assert native source-derived Rubric extraction; that path remains covered by the local source-backed browser regressions.
- A teacher-created primary answer kept the final dedicated draft valid after the native candidate's deliberate exclusion. Five 20-point criteria plus the non-scoring assigned candidate retained the Test's 100-point total.
- Final server readiness blockers: **0**. Reload, Back and resume preserved assignment/exclusion decisions, confirmed criterion handling, source/provenance and clear issue markers.

### Safety and verification limits

- Dedicated Test grading jobs: **0**; observed grading-start requests: **0**.
- Correction/Save/navigation phases issued **0** analysis/OCR/split/normalization requests. Initial explicit Answer/Rubric analysis was separate and expected. Runtime-wide inference logs were not accessed with the Teacher account; exact no-inference call counts remain proven by local RuntimeManager regressions.
- No JavaScript page exceptions or unexpected HTTP errors occurred in the completed final UI acceptance segment. Earlier automation setup attempts needed the selected target/edit state synchronized; an API-only Rubric fixture update initially omitted its matching flattened projection and was rejected with 409. The setup was corrected to submit matching normal authoring representations; no product change, retry delay or safety relaxation was needed.
- No existing Tests, confirmed revisions, grades, submissions, users or runtime configuration were modified. No deployment, migration, DB reset or unrelated cleanup was performed by the agent. Validation records were left for inspection.
- Credentials were read only from environment variables. No screenshots, HAR, browser traces, cookies or authentication tokens were saved. The changed report and local acceptance scripts/results/logs were checked for literal credential values without printing those values.
- Production correction UX acceptance passed; there is no remaining 12e acceptance blocker. Parent/child marker ownership, diagrams, role isolation, CAS/idempotency and confirmed snapshot integrity remain backed by the already-passing 72-case full local browser and 981-case backend regression; this phase did not reconfirm or rewrite an existing production revision.

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
- `docs/internal/reports/j-ui-12e.md`: standalone phase report.
- `docs/internal/reports/j-ui-12c.md`: inherited baseline change only; not changed by 12e.

## Local implementation final git status (historical)

```text
 M docs/internal/reports/j-ui-12c.md
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
?? docs/internal/reports/j-ui-12e.md
?? frontend/e2e/authoring-correction-ux-real.spec.ts
?? frontend/lib/authoringClassification.ts
```

The 12c report change is inherited from the initial baseline. No files staged, committed or pushed.

## Production acceptance final git status

Only this standalone phase report changed during production acceptance:

```text
 M docs/internal/reports/j-ui-12e.md
```

No parent report or J.UI.12c report was edited. No commit or push was performed.
