# J.UI.12b-fix15b — Restore Saved Reuse & Compact Crop Editor

## Result
READY_FOR_PRODUCTION_VALIDATION

## Baseline
- HEAD: 89d881a9f189659b69fcc1462b40b055fb4c1e44
- Initial git status: clean.
- Existing framed Save guidance retained.
- No commit, push, deployment or production access.

## Saved reuse investigation / repair
The unchanged real Sample Q5 baseline test passed, including saved automatic/manual sibling reuse. The intermittent deployed disappearance was not reproduced; its exact deployed trigger cannot be claimed as identified.

The frontend audit found that saved reuse belonged to the same effect as discovery/editor resets and had no explicit dependency on saved diagram baseline contents. The repair separates listing into its own effect. It fetches server-attested persisted reuse on target/source/edit-version transitions and on a token built exclusively from saved same-major Answer entries, their source/disposition and accepted diagram records. Cleanup discards obsolete target/baseline responses.

This removes dependence on discovery state/reset operations and makes the saved baseline an explicit refresh input. It is a frontend state-invalidation repair; no backend filter, artifact format or provenance rules were changed. The precise connection to the intermittent deployed symptom still needs deployed acceptance.

## Unsaved versus saved state
- Unsaved guidance: current working accepted records compared with the saved baseline across the same major.
- Saved reuse: server-attested persisted records only, with a separate effect and baseline token.
- Guidance boolean is not a reuse filter or generation input.
- Save clears guidance by synchronizing the baseline, then triggers persisted reuse refresh.
- Existing framed text remains exactly:
  他の小問で図を再利用するには、図を選択した後に保存してください。

Same-major grouping uses the existing canonicalQuestionRoot parent-key traversal. Labels/prefixes/filenames are not used. Existing helper coverage verifies siblings/grandchildren, unrelated majors and fail-closed missing/cyclic ancestry. Backend same-major/source validation remains authoritative.

## Compact crop editor
Before: crop editor and corrected preview were at the bottom of the whole DiagramReview, after source/reuse/manual crop/exploration information.

After: the existing fieldset is rendered inside its matching candidate's local editing unit.
- Desktop: preview left, crop editor right.
- 左 / 上 / 右 / 下 fields stacked vertically.
- Corrected preview replaces the preview in the same unit after explicit update.
- Existing update/apply/cancel actions remain; candidate accept/edit/exclude actions stay nearby.
- Containers narrower than 480px stack preview and editor vertically.
- Source details, reuse, framed guidance, manual PDF fallback and exploration remain below.
No inference, crop API, coordinates, acceptance or Save behavior changed.

## Additional user wording
Teacher-confirmable notice updated exactly to:
> この図が設問に対応する図か自動では確認できませんでした。PDFと図の範囲を確認し、正しければ使用してください。別の範囲をPDFから切り出すこともできます。

Only text and corresponding exact-text test expectations changed; trust/acceptance predicates unchanged.

## Sample Q5 browser verification
Uses the actual PDFs:
- testData/SampleQ/sampleQ5.pdf
- testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf

Checks:
- automatic discovery and parent fallback, correction/accept;
- accept without Save → sibling guidance and no persisted reuse (DOM plus direct real API assertion);
- return to Q3(1), Save there, navigate Q3(2), guidance absent, saved reusable diagram visible and reuse succeeds;
- manual crop has the same absent-before-Save / visible-after-Save behavior;
- local preview and editor geometry at desktop width, vertical fields and narrow stacking;
- corrected preview remains in the selected candidate unit;
- Rubric analysis leaves Answer state unchanged;
- Save/reload/Back/resume and source/artifact provenance retained;
- existing RuntimeManager counters assert no extra inference for correction, Save, reuse and cached display.

Focused modified scenario passed (20.4s).
After final product/text change, main production-like Chromium group: **9 passed (26.4s)**:
3 real API/browser scenarios (Sample Q5, unified diagram reuse, legacy reuse) plus 6 hierarchy/review helper tests.
Real FastAPI, disposable DB, RuntimeManager and managed stubs used; Next production build passed.
Harness confirmed **grading jobs = 0**.

An earlier combined 10-test run had 9 passed and 1 login failure in legacy override, before diagram operations. Trace contained auth/me 401 but no auth/login POST. The override scenario passed isolated before the wording change. The final isolated run after the wording change also passed: **1 passed**, grading jobs 0. Thus all 10 unique requested focused/relevant cases passed against final product code across the main and isolated runs. No sleep, retry setting or weaker assertion was added.

## Static checks
- TypeScript: passed.
- ESLint: 0 errors / 19 pre-existing warnings.
- Next production builds: passed.
- git diff --check: passed.
- Backend/Python unchanged; full backend suite and Ruff not required by this phase.
- Full normal browser suite not run; requested focused and relevant review/reuse scenarios run.

## Files changed
- frontend/components/reviews/DiagramReview.tsx: independent saved-reuse effect, local crop editor and requested notice wording.
- frontend/components/reviews/AuthoringCandidates.tsx: saved same-major baseline refresh token, independent from dirty guidance.
- frontend/app/globals.css: compact responsive preview/editor layout.
- frontend/e2e/authoring-sample-q5-diagram-real.spec.ts: Save-on-origin flow, persisted unsaved exclusion, manual parity and layout assertions.
- frontend/e2e/authoring-diagram-reuse-real.spec.ts: new exact notice text.
- frontend/e2e/diagram-review-reuse-real.spec.ts: new exact notice text.
- frontend/e2e/diagram-review-override-real.spec.ts: new exact notice text.
- docs/reports/j-ui-12b-fix15b.md: this report.

## Remaining acceptance
On the deployed machine repeat automatic and manual Q3(1) accept → unsaved Q3(2) guidance → Save → saved reuse; verify crop editor placement and new notice text.
Exact deployed intermittent trigger remains unconfirmed.
Discovery, manual crop, persistence, provenance and backend reuse semantics unchanged.
J.UI.12c remains deferred.

## Final git status

```text
 M frontend/app/globals.css
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/DiagramReview.tsx
 M frontend/e2e/authoring-diagram-reuse-real.spec.ts
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/diagram-review-override-real.spec.ts
 M frontend/e2e/diagram-review-reuse-real.spec.ts
?? docs/reports/j-ui-12b-fix15b.md

```
