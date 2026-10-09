# J.UI.12b-fix12 — Save-to-Analyze, Material Management & Strict Role Isolation

## Result
READY_FOR_PRODUCTION_VALIDATION. Automated development-machine validation passed; deployed acceptance was intentionally not performed.

## Baseline
- HEAD: `b1eed08b17a819f35efe8a4c399eafd7b788ec84` (`Harden authoring domain isolation and source recovery`). HARDEN-2 is committed at HEAD.
- Initial working tree: clean.
- Migrations: 17 version files; no change planned at baseline.
- Current inventory: 62 frontend E2E spec files, 69 backend test files. Last committed full backend run: 925 passed / 1 skipped; normal production-like browser suite: 61 passed; critical truncated-Ricoh group: 10 passed. These are the pre-fix12 baseline counts.
- Production-like harness: FastAPI, disposable PostgreSQL, Next production build, Chromium/Playwright, RuntimeManager and managed stubs.

## Pre-fix12 audit notes
- Save is currently disabled when `dirty === false`; a saved/clean appearance and accessible saved status are not exposed on the action itself.
- Upload and existing-file reuse register the binding, mark the authoring revision dirty and return to PDF view. There is no post-registration Save→analysis choice dialog.
- Material management supports selection and replacement but no binding delete or role change. The API has upload/reuse/list/file routes only.
- Add defaults to the last selected `role` state (`question_sheet` initially), not the next missing role.
- Answer text preview lacked the same bordered frame as Question text; its diagram preview can remain outside the text frame.
- `analysisProgress` is set role-specifically but currently renders in the page header area, not near the right editor target/section.
- The existing source registry distinguishes material IDs, roles, SHA and source draft IDs. HARDEN-2 introduced merge protections and per-entry source lookup; strict isolation must be re-verified with same-artifact role bindings and teacher edits.

## Reproduction and implementation log

### Defect 1 — Answer analysis could project rubric-classified segments into Rubric
- Symptom/reproduction: a focused regression passes an Answer-role import with an explicitly rubric-classified segment and group through `merge_answer_analysis`; before the fix, it populated `snapshot.rubrics` when that field had no prior state.
- Root cause: the merge condition let any non-Answer-role or missing Rubric projection write the Rubric domain, and resume projection similarly used the globally latest Answer-import draft regardless of its binding role.
- Fix: role is passed explicitly from the selected material; only `rubric_source` may update the Rubric projection. Source resume now selects latest draft per Answer/Rubric binding role, combines source-bound candidates while projecting only role-owned domain state, and stores material role/source identity per binding. Source tokens now separate Answer and Rubric revisions.
- Regression: `test_answer_analysis_never_projects_rubric_segments_into_rubric_domain` and `test_resume_projects_latest_answer_and_rubric_imports_into_separate_domains`.

### Defect 2 — Material registration had no Save→analysis path and management could not correct bindings
- Symptom: a newly registered source marked the working revision dirty, disabling analysis, with no adjacent next-step action. Material edit had no delete or role correction action.
- Root cause: registration and authoring save were independent UI operations, while the material API only exposed immutable upload/reuse/list/file operations.
- Fix: added a shared Save→role-specific analysis confirmation dialog; “いいえ” keeps the binding unsaved and does no analysis. Saved/dirty Save button states remain enabled when clean; clean Save is local no-op. Material role change creates a new binding over the same bytes/SHA and tombstones the old role binding; delete tombstones only that binding. Artifact bytes remain untouched. No schema migration.
- Regression: browser coverage for registration yes/no and backend coverage for shared-source delete/role-change/duplicate behavior.

### Defect 3 — Rubric-role candidates could render as Answer editor rows
- Symptom/root cause: source candidates share a backing collection for authoring, and the UI previously rendered both Answer and Rubric controls on every row, regardless of binding role.
- Fix: role-aware row ownership hides Answer controls for Rubric-source candidates, keeps rubric-like Answer segments available for explicit teacher recovery, and keeps manual Answer/Rubric add controls in their owning section. Empty Rubric candidates still show a preview/edit mode wrapper.
- Regression: rubric reliability and role-isolation browser tests.

### Defect 4 — Analysis progress was easy to miss
- Root cause: the role-specific status was rendered above the workspace rather than adjacent to the right editor target controls.
- Fix: moved the status strip directly beneath the selector and strengthened its color, border, spinner and label while retaining indeterminate progress.
- Regression: registration YES browser flow waits for the role-specific Question progress status.

### Defect 5 — Material role correction used the wrong HTTP method
- Symptom/reproduction: opening 資料の編集, changing a role and pressing 種類を変更 produced no response; the production-like API log returned `405 Method Not Allowed` for `POST /materials/{id}/role`.
- Root cause: request options were assembled as `{method: "PATCH", ...json(...)}`; the shared JSON helper's `POST` method overwrote the intended PATCH.
- Fix: put the explicit PATCH method after the helper options so it is authoritative.
- Regression: the material management browser test verifies PATCH completes, the new binding shares SHA/storage, deletion preserves the shared role, and the API list only exposes active bindings.

### Defect 6 — First manual Rubric criterion was never created
- Symptom/reproduction: on a new Test with no source-backed Answer domain, opening 採点基準 and selecting 基準を追加 left the editor with no criterion textarea; subsequent split/edit actions appeared to do nothing.
- Root cause: the empty-state action appended an empty Rubric candidate with `rubric_edits: []`; the no-source fallback projected only `snapshot.rubrics`, which remained empty, so every rerender returned to the same empty state.
- Fix: the first manual-add action now creates a blank teacher-owned criterion in the Rubric entry. The no-source fallback aggregates all criterion rows back into the authoring rubric snapshot.
- Regression: the Rubric reliability browser flow begins from a fresh Test and checks criterion editing, cursor split, assisted proposal, Undo and Save/resume.

### Material lifecycle semantics
- A material row remains as audit history after deletion; a `DomainEvent(material_binding_deleted)` hides it from active material listing, blocks source reuse/file/analysis by that binding, and preserves immutable shared bytes. Role change uses a separate row with the same storage reference and SHA; prior role analysis is not copied. Active same-SHA destination role collisions return 409.
- Add default selects the first missing role in Question → Answer → Rubric order; when all three exist, it rotates after the current role. It does not submit automatically.

### Diagram source-context audit
- Diagram discovery must use the selected candidate's source draft and material binding, not whichever role was imported most recently.
- The prior Answer context treated the globally latest import as primary. A Rubric import could therefore replace the source context used by Answer diagram discovery/reuse.
- The fix resolves active source drafts by explicit role, tags each candidate with its source draft, filters deleted bindings, and chooses active Answer-role context for Answer diagrams.
- The source-backed browser flow discovers a diagram before any accepted diagram exists, accepts it, analyzes the same PDF through a separate Rubric binding, then confirms Answer diagram discovery still returns the diagram. Existing diagram browser cases cover accepted sibling reuse and excluding unrelated major Questions.

### Save-state accessible status
- The visually hidden `aria-describedby` status and visible dirty-state text previously repeated the same exact phrase, which made browser status locators ambiguous.
- The hidden status now says `保存状態: 未保存の変更があります` or `保存状態: 保存済み`; the visible message remains concise.
- Endurance browser coverage confirms that an edit made during an in-flight Save remains dirty after the older Save response.

### Rubric section ownership in regression coverage
- The source-backed E2E previously added Rubric rows inside a teacher-created Answer candidate. That contradicted strict Answer/Rubric section ownership.
- The browser scenario now edits criteria through the separate Rubric section while retaining cursor split, duplicate, merge, Undo, persistence and issue-navigation coverage.
- The first manual Rubric action creates an actual blank criterion, and the no-source fallback writes all criterion rows back to the authoring Rubric snapshot.

### Early validation observations
- Backend targeted group: 42 passed, with one existing Starlette deprecation warning.
- The first focused browser run exposed outdated assertions for unsupported-material readiness and a missing edit-mode wrapper after role-aware filtering. Both were corrected, and the focused suite passed afterward.
- The dedicated truncated-Ricoh/same-major fixture configuration was not available in this environment. The normal browser diagram review and sibling reuse cases did run and passed; the related source-context regression also passed with the managed fixture.

## Analysis isolation and candidate outcomes
- Question, Answer and Rubric retain role-specific material binding IDs and source revisions. A physical source may be shared, but analysis selection and source projection are role-scoped.
- Answer analysis/reanalysis writes Answer-domain state only. Rubric analysis/reanalysis writes Rubric-domain state only. Question tree is based on the current authoring revision and remains unchanged for Answer/Rubric merges.
- Structured backend tests cover role-local merge/projection, shared source bindings, source replacement, deleted binding behavior and source draft selection. Browser isolation workflows compare the Question tree through both Question→Answer→Rubric and Question→Rubric→Answer orderings.
- The Sample-Q5-like Rubric empty-result fixture returned zero extracted candidates. The UI now makes the empty result explicit and preserves manual criterion creation. Existing rubric-like Answer segments remain available only as explicit teacher recovery candidates; they are not silently moved between domains. No candidate text is fabricated.
- The reported Q3(1) issue was source-context selection after another role had been analyzed: diagram lookup could follow the global latest import, which was Rubric. Answer candidate entries now resolve their own Answer source draft/material. The browser regression verifies first discovery before acceptance and again after analyzing the same bytes through a Rubric binding. Existing diagram review scenarios verify accepted sibling reuse remains major-Question scoped.

## Final validation
- Focused backend: **42 passed** (one existing Starlette deprecation warning). Full backend after the final product changes: **928 passed, 1 skipped, 22 warnings**, 200.46 seconds.
- Focused production-like browser run: **17 passed**, including new fix12 material flow coverage. An additional source-backed/role-isolation run: **3 passed**.
- Full normal production-like Chromium suite: first run **60 passed / 1 failed** because the LaTeX runtime test remained at `/login` during its 5-second post-login URL assertion. That spec passed alone (**2/2**), and the complete suite then passed consecutively on rerun: **61/61**, 2.2 minutes. All harness runs reported **0 grading jobs**.
- Diagram/OCR coverage in the full suite included discovery and review, Question and Answer math OCR, source math OCR, sibling/source ownership, and formula provenance. The special truncated-Ricoh configuration was not available through this harness; prior baseline critical suite was 10 passed, and the normal critical cases above passed.
- TypeScript: `npm run typecheck` passed.
- ESLint: passed with 0 errors and 19 existing warnings in unrelated files.
- Ruff: `python -m ruff check src tests` passed.
- Production Next build: passed in the production-like browser runs. Existing CSS autoprefixer warnings for `start` alignment and existing lint warnings remain.
- `git diff --check`: passed.
- No schema migration, production access, deploy, commit, or push. Formal publication is outside this workflow; authoring/formal isolation browser assertions passed. Production Q5 was not accessed or modified.

## Changed files
- `frontend/app/tests/[testId]/authoring/page.tsx`, `frontend/app/globals.css`: Save state, registration Save→analysis handoff, material role/delete flows, missing-role default, and right-pane role progress.
- `frontend/components/reviews/AuthoringCandidates.tsx`, `frontend/lib/api/testAuthoring.ts`: role-owned Answer/Rubric display and editing, answer framing, and per-role analysis result typing.
- `src/scoring/api/domain.py`, `src/scoring/api/test_authoring.py`, `src/scoring/authoring_answers.py`, `src/scoring/authoring_sources.py`, `src/scoring/source_registration.py`: binding lifecycle, deleted-binding filtering, role-scoped imports/projections, and candidate source context.
- `tests/test_authoring_diagrams.py`, `tests/test_shared_source_bindings.py`: isolation, shared-source and diagram-source regressions.
- `frontend/e2e/authoring-fix12-material-flow-real.spec.ts` and the updated authoring E2E specs: registration, role isolation, diagram discovery, save/resume and ownership regression coverage.
- `docs/reports/j-ui-12b-fix12.md`: this report.

## Final Git status
Uncommitted and unpushed, as requested. Modified:
`frontend/app/globals.css`; `frontend/app/tests/[testId]/authoring/page.tsx`; `frontend/components/reviews/AuthoringCandidates.tsx`; `frontend/e2e/authoring-analysis-access-real.spec.ts`; `frontend/e2e/authoring-endurance-real.spec.ts`; `frontend/e2e/authoring-preview-materials-real.spec.ts`; `frontend/e2e/authoring-save-resume-real.spec.ts`; `frontend/e2e/authoring-source-backed-real.spec.ts`; `frontend/e2e/authoring-split-merge-real.spec.ts`; `frontend/e2e/test-authoring-foundation-real.spec.ts`; `frontend/lib/api/testAuthoring.ts`; `src/scoring/api/domain.py`; `src/scoring/api/test_authoring.py`; `src/scoring/authoring_answers.py`; `src/scoring/authoring_sources.py`; `src/scoring/source_registration.py`; `tests/test_authoring_diagrams.py`; `tests/test_shared_source_bindings.py`.
Untracked service files: `docs/reports/j-ui-12b-fix12.md`, `frontend/e2e/authoring-fix12-material-flow-real.spec.ts`.

## Remaining / deferred
- Production acceptance remains: verify the new binding Save→Analyze handoff, shared Answer/Rubric source, material delete/role correction, Q3(1) first diagram discovery and Q3(2) reuse on the deployed environment. No deployment was performed here.
- The dedicated truncated-Ricoh fixture configuration was unavailable in this environment; the normal OCR/diagram browser cases passed.
- J.UI.12c publication, grading/student revision binding, and Question drag-and-drop remain deferred. No grading jobs were created.
