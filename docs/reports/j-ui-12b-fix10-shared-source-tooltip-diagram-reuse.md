# J.UI.12b-fix10 — Shared Source Reuse, Tooltip Visibility & Diagram Reuse Regression

## Result
**READY_FOR_PRODUCTION_VALIDATION**. Implementation and automated verification passed. Production acceptance is not performed. No deployment, production database access, commit or push.

## Baseline and audit
Baseline: `3087ce5fa900a6177e51de90ac896b3fcecebdb7`; initial working tree clean.

| Area | Before / root cause | Change |
| --- | --- | --- |
| Shared files | Registration already deduplicates by Test + role + SHA, with SHA-addressed PDF storage. No existing-file binding UI/API was exposed; users had to upload again. | Same-Test reuse endpoint and Add screen selector create a distinct role binding over the existing verified storage reference. |
| Role analysis | Native Answer/Rubric import shares a draft domain; projection rebuilt both domains from all entries. | Preserve source role and project only the selected domain; dedicated Rubric state takes precedence over incidental criteria in Answer sources. |
| Tooltip | Absolute tooltip stayed inside source-pane overflow/stacking contexts and could extend beyond the viewport. z-index alone cannot escape overflow clipping. | Body portal, fixed overlay and viewport-clamped placement, refreshed on resize/scroll. |
| Diagram reuse | A manual Answer defaulted to the latest import draft, which could be Rubric. Reuse is correctly source-scoped, so the earlier Answer diagram disappeared. | Select an Answer source for manual Answer operations, retaining explicit per-candidate provenance. |
| Reuse Save | Browser review returned the original Answer draft ID; new-candidate validation allowed only the latest draft ID. | Allow registered immutable source contexts in the current working copy; native artifact validation remains mandatory. |

No schema migration or SourceFile table was needed. TestMaterial bindings share storage_ref/SHA but retain distinct IDs, roles, authoring analysis markers, revisions and replacement references.

## Material management
The Add pane retains file upload and adds `既存ファイルを再利用`. The existing-file selector shows filename, short SHA and currently registered roles. `${role}として追加` registers the binding, marks the working copy dirty, selects its PDF and emits the existing success notification. No byte upload, artifact copy, extraction or inference occurs through reuse. Same-role/SHA registration is idempotent; UI explains and disables duplicate registration. Same filename with different roles remains visible as separate dropdown options. `PDFに戻る` was removed; the permanent dropdown is the navigation mechanism.

Replacement continues to reference a specific material ID, never a filename/SHA globally. Replacing Answer leaves Rubric on the old shared source and retains the immutable PDF. Same-SHA upload uses existing content-addressed storage and role-specific idempotency.

## Analysis isolation
Answer and Rubric analysis still use the existing native import pipeline and fix8 role-specific confirmation. Answer import/reanalysis preserves Rubric projection; Rubric import/reanalysis preserves Answer projection and current Question tree. Source registry retains each material binding and native draft/artifact/SHA context. No automatic analysis was introduced.

Same-material, same-SHA reanalysis retains accepted diagram assignments on their original source/artifact context while replacing extracted text/criteria. Different-SHA results cannot inherit old verified geometry as current-source state.

## Tooltip
Mouse hover and keyboard focus open the same `role=tooltip`, connected with aria-describedby. Escape/blur/mouse leave dismiss it. Disabled reasons remain typed readiness output; no string-derived readiness logic was added. Ready state removes the tooltip and disabled wrapper tab stop immediately. The overlay does not change control/PDF dimensions.

## Diagram reuse safety
J.UI.10e native discovery/reuse engine remains unchanged: saved accepted valid artifacts, same Test, same source context and same major Question tree. No Test-wide or filename-based scope expansion. Reuse shares crop artifacts but assigns independently to each child; no Ricoh, geometry, rendering or LLM call is added. The regression now exercises Answer acceptance, later Rubric analysis over the same PDF, new sibling manual Answer reuse, Save and reload. Foreign/stale/excluded/missing artifacts remain covered by existing backend safety tests.

## Verification progress
- Initial targeted source/authoring suites: 69 passed.
- Added focused shared-source tests: 3 passed.
- Updated diagram + shared-source targeted group: 21 passed.
- Focused production-like access/save/split browser group: 6 passed (before final source validation correction).
- Truncated-Ricoh/OCR/diagram browser group: initial run exposed the reuse-Save source-token defect; after correction 4 passed, grading jobs 0.
- Final full backend suite: **916 passed, 1 skipped**, 13 existing collection/deprecation warnings.
- Final full production-like browser suite: **56 passed**.
- TypeScript passed; ESLint 0 errors, 19 existing warnings; Ruff passed; production Next build passed with existing CSS/ESLint warnings. Final diff check passed.

## Invariants and scope
New workflows create no formal Question/ModelAnswer/approved Rubric and no grading jobs. Existing legacy formal-transfer tests may exercise their own disposable fixture APIs; fix10 does not publish. All browser harnesses use disposable databases, real FastAPI/RuntimeManager and managed model stubs. Production/Q5 untouched.

## Remaining / deferred
Real deployed shared-PDF analysis/replacement, tooltip visibility and sibling diagram reuse acceptance remain required. Question drag-and-drop ordering and J.UI.12c publication remain deferred.

## Additional regression finding
The first full normal browser run passed 55/56 but explicit saved-review import crashed rendering: retained diagram-only entries had `semantic_classification={}`, while the existing editor expects a segment array when classification exists. The preservation adapter now records no classification (`null`) rather than an incomplete classification object. A focused regression asserts the compact preserved entry schema, and the existing full source-backed browser test covers actual rendering/import. Same native candidate IDs are merged rather than duplicated when explicitly importing that review again. Full suites restarted after these corrections.

## Changed files
- `src/scoring/source_registration.py`, `src/scoring/api/domain.py`: authenticated same-Test source reuse, immutable source validation and idempotent role bindings.
- `src/scoring/api/test_authoring.py`, `src/scoring/authoring_sources.py`, `src/scoring/authoring_answers.py`: role-specific merge/projection and correct manual Answer source context; accepted artifact retention.
- `frontend/app/tests/[testId]/authoring/page.tsx`: Add-pane reuse flow and removal of PDF-back button.
- `frontend/components/reviews/DisabledActionHint.tsx`, `frontend/app/globals.css`: portal tooltip positioning.
- `tests/test_shared_source_bindings.py`, `tests/test_authoring_diagrams.py`: shared role/artifact, replacement, independent domain merge, retained geometry and reuse-Save regressions.
- `frontend/e2e/authoring-analysis-access-real.spec.ts`, `frontend/e2e/authoring-diagram-reuse-real.spec.ts`, `frontend/e2e/authoringNotifications.ts`: actual shared-source UI, independent reanalysis/replacement, original-source sibling reuse Save/reload/Back/resume, hover/focus viewport assertions.
- This report.

## Git status
12 tracked files modified; report and shared-source test file untracked. All are service source/tests/service-facing report files. No staging, commit or push performed.

## Final normal browser checkpoint
After the last product change, all 56 production-like browser scenarios passed (1.9 minutes). This includes shared-source registration without upload/inference, role-specific analysis and repeated reanalysis, one-role replacement retaining the other source, tooltip hover/focus geometry, notification/issues separation, source-backed import/rendering, Save/resume/readiness, 10-cycle endurance, 5-cycle readiness endurance, stale-tab Save and edit-during-Save. Normal harness confirmed grading jobs 0. No uncaught page/console errors in the updated successful workflows. Explicit stale-save/negative fixtures retain their expected error handling.

## Final critical browser checkpoint
Final truncated-Ricoh/teacher override/OCR/unified sibling reuse group: 4/4 passed (14.5 seconds), grading jobs 0. The reuse scenario now verifies original and reused crop SHA, independent assignments, artifact accessibility, reload and Back/resume after a Rubric source becomes the latest analysis. Runtime call counts do not increase for reuse, Save or navigation. Existing backend `test_model_answer_diagram_reuse.py` covers unrelated major exclusion, excluded/unaccepted/stale/missing artifacts, forged references and foreign draft attestations without relaxing native safety.

## Static validation
TypeScript passed. Full ESLint: 0 errors and 19 pre-existing warnings. Ruff (`src tests`) passed. Production Next build passed; existing autoprefixer/ESLint warnings remain. `git diff --check` passed. No runtime/model configuration change.

## Final result and remaining issues
All implemented fix10 workflows and automated checks pass. No known reproducible defect remains from this validation. Only deployed acceptance remains: same-PDF Answer/Rubric registration and independent analysis/replacement, edge tooltip hover/focus visibility, and saved same-major diagram reuse. No production access, deployment, commit or push occurred. Changes remain in the working tree for review. Formal isolation and zero grading jobs were verified in disposable browser harnesses. Notification history/issues, typed readiness, split/apply/cancel, OCR, advanced Rubric editing and legacy routes remain covered by the passing suites.

Question drag-and-drop ordering: deferred to future phase. Final publication: deferred to J.UI.12c.
