# J.UI.15 — Compact ModelAnswer editing

Status: **READY_FOR_PRODUCTION_VALIDATION**. Local implementation and required production-like validation passed; no production changes, commit or push.

## Implementation

Previously assigned Answer text, routing controls, alternatives and diagram controls were accessed through a broad Preview/Edit wrapper; editing exposed large textareas and conversion guidance in the workspace. Unified Authoring now opts into compact Answer cards. Primary Answer entries are labeled 模範解答1, 模範解答2, etc.; their existing primary/alternative/ignored state remains explicit. Nested accepted alternatives have individually readable content and Edit actions. Markdown/LaTeX uses the existing renderer with its existing fallback; no content truncation or scoring conversion is introduced.

`CompactModelAnswerText` and `ModelAnswerTextDialog` reuse the native `AuthoringDialog` lifecycle: a four-row resizable textarea, initial focus, Escape/Cancel, focus return and keyboard focus containment. Done applies only working state; global Save remains the durable boundary. Cancel discards dialog text and conversion results. New Answer/alternative creation opens a dialog before adding a working card. IDs are created through the existing UUID helper; accepted entries retain their original IDs. Dialog completion does not send an API Save.

LaTeX normalization uses the same control, engine, context and source-bound API. It operates on the dialog buffer; proposals/guidance stay inside the scrolling dialog. Source-stale normalization remains disabled. Applied normalization metadata for primary and newly created domain entries is staged until Done using the existing `teacher_correction.latex_normalization` fields, including existing region audit fields without image blobs. Cancel does not publish it. Legacy projection-only Answer editing retains its existing plain-text persistence representation.

Normal cards show accepted diagrams. The same canonical `DiagramReview` rendering/callback is reused in compact and legacy branches: manual crop, exact/parent fallback, saved reuse, source ownership, trust checks and acceptance remain independent from text editing. Required diagram review is not hidden. Routing/classification/remove controls use the existing callbacks; uncommon routing actions live under ▶/▼ 解答の操作 with `aria-expanded` synchronized to native disclosure state. Classification review is independently discoverable even when body editing is closed.

Existing accepted-entry exclusion is clearly named この模範解答を対象外にする and stores ignored disposition, retaining the entry/source/history. It is not physical deletion or unassigned candidate exclusion. The existing disposition control restores inclusion. Nested alternatives use the existing manual-alternative override list for editing/removal; original automatic classification evidence remains stored. No text similarity merge, auto-assignment or candidate lifecycle reconciliation is introduced. No-op/edit-revert does not manufacture review approval; unchanged source-domain primary completions and unchanged alternatives do not overwrite entries/overrides; meaningful primary text edits still obtain the server-owned manual-edit text-review receipt on successful Save. Whitespace comparison and classification confirmation remain the existing backend semantics; no generic Answer text-confirmation control was invented.

The J.UI.14a queue is unchanged. Assigning a source candidate exposes that same identity as a compact card; text edits cannot recreate an unassigned duplicate. Question/Rubric semantics, visibility/domain counts, readiness, source warnings, Save CAS and in-flight Save protections are unchanged. Legacy/import-review callers default to the existing noncompact presentation.

## Navigation, review and revisions

Answer text corrections reveal/focus the appropriate Edit action. Classification issues expand their exact classification row and routing disclosure; diagram issues retain their existing exact diagram target. Unassigned issues still navigate to the unified queue. Existing Test/source navigation is retained. All issue state remains server-owned; no client issue suppression was added.

Final Review adds a read-only ModelAnswer disclosure with primary/alternative content and accepted diagrams. History continues to render immutable revision data without edit controls, with numbered entry headings. Fork/Confirm/CAS/readiness APIs are unchanged. Browser validation confirms two editions, verifies exact initial fork equality and verifies the first confirmed edition is byte-for-byte unchanged after editing/confirming the second.

## Validation

Established harness: `python -m tests.run_runtime_browser_e2e`, temporary DB/artifacts, real FastAPI/RuntimeManager, fresh production Next build/server, managed synthetic model stubs only. No production records were accessed or changed in this phase.

- Main focused group: **12 passed / 0 skipped / 0 failed**, 1.1 minutes. New compact display/edit/cancel/add/alternative edit/removal, local math apply/cancel, failed Save retention, Save/reload, Final Review and read-only history/two-edition workflow; existing classification, source-backed authoring, material controls/native editing history, source math provenance and confirmation regressions.
- Additional affected group: **8 passed / 0 skipped / 0 failed**, 17.3s. Source candidate assignment into the same compact entry, manual text-review receipt, no-op/edit-revert, peer/source/classification preservation, new-dialog normalization receipt, exclusion; Question compact, Rubric polish/canonical levels, Question source navigation and Save/resume. Includes one pure score-level semantic test.
- J.UI.14a unified queue: **1 passed / 0 skipped / 0 failed**, 2.0s, in a separate fresh fixture so previous assignment/exclusion tests cannot consume its candidates.
- Final latest-code J.UI.15 rerun: **2 passed / 0 skipped / 0 failed**, fresh production build; both new compact and assigned-candidate scenarios pass. An optional skip-build attempt failed at login because its compiled API target belonged to a previous disposable harness; that infrastructure run was not counted as a feature pass.
- Full normal Chromium: **74 passed / 0 skipped / 0 failed**, 4.5 minutes. Fresh production build, disposable real API/Manager fixture; harness verifies grading jobs 0.
- TypeScript: passed. ESLint: 0 errors / 19 pre-existing warnings. Fresh Next production builds: passed. `git diff --check`: passed.
- Backend/API/schema/migration changes: **none**; Ruff and backend regression suites are not required for this UI-only change. Existing server confirmation/readiness/source semantics are exercised through the real API browser tests.

Sample Q5 specifically proves the dialog sends diagram records unchanged; after Save, every field is identical except the existing working CAS revision stamp. `AuthoringAnswers.validate()` calls diagram validation with `row.edit_version + 1`; this pre-existing Save bookkeeping is deliberately retained. Crop SHA, geometry, acceptance, source role/owner, binding and provenance remain exact. Subsequent sibling reuse, manual crop, Save/reload/Back/resume and Answer/Rubric isolation pass. Confirmation's separate non-mutating diagram/snapshot guarantee remains covered by existing confirmation scenarios.

Grading jobs **0**. Real model inference **0**. Ordinary local text editing, queue assignment and classification operations have model-call delta **0**. Explicit LaTeX/analysis/diagram regressions use managed synthetic stubs and are not reported as zero synthetic calls.

The first full run was 72 passed / 2 failed: the three-child Sample Q5 scenarios attempted to use routing controls without opening the new operation disclosure. Their navigation was updated without changing inclusion/provenance assertions; both passed on the full rerun. Initial exploratory runs failed on obsolete Preview/Edit selectors, missing dialog input labels/test helper imports, a confirmation-response race and an overly strict Save diagram-revision assertion; these were corrected while retaining content/provenance/readiness assertions. The optional truncated-Ricoh-only authoring diagram spec was skipped by the normal harness because its specialized fixture/mode is absent; it was not counted as a feature pass. Required J.UI.15 diagram/reuse validation ran against actual Sample Q5 and the normal diagram fixtures. No required J.UI.15 feature validation is skipped.

## Files and handoff

Product changes:
- `frontend/components/reviews/CompactModelAnswerText.tsx`: compact text/alternatives and local dialog.
- `frontend/components/reviews/AuthoringCandidates.tsx`: opt-in compact assigned Answer cards, staged new-entry creation/normalization, canonical routing/exclusion and shared diagram rendering.
- `frontend/app/tests/[testId]/authoring/page.tsx`: compact opt-in/fallback, issue focus/disclosure and read-only Final Review Answer display.
- `frontend/components/reviews/AuthoringRevisionHistory.tsx`: numbered Answer headings; no snapshot mutation.

Tests: `authoringEditMode.ts`; new `compact-model-answer-real.spec.ts` and `compact-model-answer-assignment-real.spec.ts`; adapted authoring correction, diagram-reuse, final-confirmation, math, preview-material, Sample Q5 diagram/three-child reuse, source-backed, split/merge, foundation, Rubric polish/canonical-level scenarios. Their durable content, source, CAS, model-call and readiness assertions remain in place.

This report is separate from earlier phase reports. No backend, migrations, dependencies, runtime/model configuration or production data changed. Operator production acceptance must use a new dedicated Test to verify compact assigned/alternative editing, Cancel/Done/Save lifecycle, queue assignment, source/diagram reuse and historical edition immutability. Deployment is frontend-only; no migration is introduced. Do not launch grading jobs. This is not COMPLETE until operator production acceptance.

## Git status

Before J.UI.15: clean (`git status --short` empty). After final validation (no staging, commit or push):

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/AuthoringRevisionHistory.tsx
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/e2e/authoring-diagram-reuse-real.spec.ts
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-math-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M frontend/e2e/authoringEditMode.ts
 M frontend/e2e/rubric-interaction-polish-real.spec.ts
 M frontend/e2e/rubric-levels-canonical.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
?? docs/internal/reports/j-ui-15-compact-model-answer-editing.md
?? frontend/components/reviews/CompactModelAnswerText.tsx
?? frontend/e2e/compact-model-answer-assignment-real.spec.ts
?? frontend/e2e/compact-model-answer-real.spec.ts
```
