# J.UI.12b-fix6 — Split Review Reliability & Analysis Merge Preservation

## Result

READY_FOR_PRODUCTION_VALIDATION. Deployed Sample Q5 acceptance has not been performed. Final publication (J.UI.12c), grading revision binding and Question drag-and-drop ordering are outside this change. **Question drag-and-drop ordering: deferred to future phase.**

## Audit and causes

- AI split used the shared busy flag but kept a static button label and had no immediately acquired in-flight guard. It offered no visible progress or clear retry guidance.
- AI range proposals treated every range as a child. There was no teacher-controlled parent/child/exclude role. Common introductory text therefore became a child. Range labels also used boundary offsets instead of sequential indexes.
- Numbered splitting could recognize a selected child's own leading ordinal as a new wrapper. Apply did not reject that repeated source/body. Existing children were not checked before creating more nodes.
- Authoring projected `is_gradable` from direct score semantics. Newly split leaf nodes have unset points, so native Answer/Rubric mapping excluded them. The manual assignment selector had the same restriction. Native results could exist but remain unassigned and invisible for the selected Question.
- The Answer analysis endpoint already copied the current working snapshot. The rollback path was generic saved-source import: it rebuilt a projection from formal/latest legacy Question review and replaced the working copy, restoring the pre-authoring-split tree.
- Sequential analysis replaced the Answer domain with the latest material's entries. Compact Answer/Rubric projections were not refreshed immediately, and results from the previous material were lost. A generic success message did not expose zero assignments.

## Split implementation

The existing source-preserving split proposal/apply helpers remain authoritative. Each review block now has an editable role: 親本文に残す / 小問にする / 除外. Numbered common context is a parent block; AI range-only proposals default the first context block to parent for review. Teachers can change the roles before explicit 分割を適用. Explicit exclusion removes that block from both parent and children; excluded formula/figure decisions remain represented. No proposal is automatically applied.

Split controls are in 本文編集. Settings retain points, hierarchy/reparent and ordering. AI runs show a spinner and 分割案を作成中…, disable the action and acquire a synchronous request guard. Failures retain text and enable retry. Unsaved new nodes require explicit Save before a server-backed AI request; no hidden autosave is introduced.

Proposals bind to the selected stable key. Apply validates everything before returning one parent/children update. Duplicate protection compares selected wrapper context, body and source slices/element IDs/region anchors with existing children, rather than only comparing labels. A repeated `(2)` wrapper cannot become `(2) > (2)`; intentional `1.`/`2.` grandchildren remain supported. Formula anchors, text slices and figure decisions use the existing engine. Textareas keep the existing stable DOM/local-buffer lifecycle.

## Analysis merge and assignment

Answer and Rubric use the existing native analysis pipeline against canonical current authoring nodes. Included leaf identity is independent of whether points have been assigned. Existing stable/formal aliases and native source geometry/numbering mapping resolve candidates; ambiguous/unmapped results stay unassigned, never attached to an arbitrary leaf.

`merge_answer_analysis` modifies only the Answer domain and compact Answer/Rubric projections. Nodes remain byte-for-byte equal: stable keys, parent keys, order, points and teacher body edits. Different materials accumulate entries. Explicit same-material reanalysis supersedes that material's entries while the previous snapshot remains in analysis backup.

Each candidate keeps an immutable native source draft reference. A compact source registry binds retained candidates to their original Test/material/SHA/artifacts; no raw model response or image bytes are embedded. Source tools select that candidate's own PDF/IR and artifact store, so importing Rubric from another PDF does not redirect old Answer diagrams/OCR to the new PDF. Foreign source references and replaced sources remain rejected. Diagram context and replacement validation cover retained source bindings too.

Saved-source import preserves the working tree when the Question source revision token has not changed. A genuinely changed Question source remains subject to the existing explicit reconciliation/backup flow; there is no silent general merge of conflicting Question reviews.

Analysis reports assigned/unresolved counts. Zero assignments produce an actionable error and display the retained unassigned candidates. Manual assignment updates both target identity and inclusion/mapping state, and updates the compact projections at Save. Answer/Rubric sections are enabled after analysis. A pending split proposal blocks source analysis until Apply/Cancel, preserving the proposal.

## Revision, concurrency and inference

Existing edit-version CAS, native analysis transaction and `analysis_backup` preserve the old working revision. Editing/Save actions are disabled during analysis; stale responses are guarded. Save/import conflict tests retain expected-revision enforcement. These operations do not create formal Questions/ModelAnswers or approved Rubrics.

Only explicit AI split, analysis, OCR, diagram discovery and assisted Rubric actions invoke models. Reviewing/applying a split, assigning an unresolved result, switching views/materials, merging domain snapshots, Save and resume do not invoke models. No grading jobs are launched.

## Verification

- Backend regression: **373 passed**, 5 existing warnings. Focused authoring suites: **54 passed** (a subset of the 373, not an additional count). Five new backend cases cover post-split unscored mapping/tree preservation, cross-material merge/unresolved results, legacy-import preservation, forged source bindings and retained original-material diagram preview/Save.
- Final default production-like Playwright harness: **50 passed** = 37 browser scenarios + 13 LaTeX/error-mapping helper cases.
- Additional truncated-Ricoh diagram/OCR/split harness: **30 passed** = 9 browser scenarios + 21 split helper cases. Four browser scenarios overlap the default run; together these cover **42 distinct browser scenarios and 34 helper cases**. Three new browser scenarios specifically exercise split progress/review, role choices/wrapper rejection/retry/grandchildren, sequential Answer/Rubric merge, and zero-assignment manual resolution.
- TypeScript `npx tsc --noEmit`: passed.
- ESLint: **0 errors, 19 existing warnings**, no new errors.
- Ruff on changed Python/service tests: passed.
- Production Next build: passed in the isolated browser harnesses. Existing CSS autoprefixer/ESLint warnings remain.
- `git diff --check`: passed.
- Grading-job count: **0** in every successful isolated harness; no production grading job was launched.
- An initial new manual-assignment browser test timed out while targeting preview-hidden controls. The corrected test enters body edit. A subsequent run exposed the select label including its option text; an explicit `aria-label` now makes the target stable. The final whole suite passes, including manual assignment and Save.

Reproduction: `python -m tests.run_runtime_browser_e2e --insecure-origin` for the default suite. The additional harness uses `LLM_GRADER_STUB_DIAGRAM_RESPONSE_MODE=truncated` with `authoring-diagram-reuse-real`, `authoring-math-real`, `diagram-review-override-real`, `diagram-review-reuse-real`, `authoring-preview-materials-real`, `authoring-entry-layout-real`, `authoring-source-backed-real` and `question-split` specs.

Browser fixtures use disposable Tests, real authorized API paths, production Next builds and RuntimeManager-managed stubs, not production Q5 data.

Coverage includes AI delay/loading/double-click guard, failure/retry, parent/child/exclude review, repeated wrapper rejection, intentional grandchildren, sequential source-backed Question→split/edit→Answer→Rubric analysis, unassigned-result manual assignment, Save/reload, unchanged formal data, caret/IME/preview, source math OCR, teacher-confirmed diagrams and confirmed reuse, material navigation/replacement, legacy reviews and archive.

## Production acceptance still required

Run real Sample Q5: generate/review split with progress; confirm no duplicate wrapper hierarchy; edit/save split children; analyze Answer then Rubric; verify imported content and exact tree preservation; verify unresolved assignment guidance, OCR/diagram/reuse, and reload. No production deployment or production data mutation was performed by this task.

## Changed files and scope

- UI/state: `frontend/app/tests/[testId]/authoring/page.tsx`, `frontend/components/reviews/AuthoringCandidates.tsx`, `frontend/app/globals.css`.
- Shared split/helpers/types: `frontend/lib/questionSplit.ts`, `frontend/lib/questionSplitApply.ts`, `frontend/lib/api/testAuthoring.ts`.
- Backend adapters/API/preflight: `src/scoring/authoring_sources.py`, `src/scoring/authoring_answers.py`, `src/scoring/api/test_authoring.py`, `src/scoring/test_authoring.py`.
- Service tests: `tests/test_authoring_diagrams.py`, `tests/run_runtime_browser_e2e.py`, `frontend/e2e/authoring-split-merge-real.spec.ts`, `frontend/e2e/question-split.spec.ts`, `frontend/e2e/authoring-analysis-access-real.spec.ts`, `frontend/e2e/authoring-math-real.spec.ts`, `frontend/e2e/authoring-preview-materials-real.spec.ts`.
- This report.

No schema migration, parallel extraction engine, model/runtime setting change, publication, grading input change, or production data operation. All changed/new files are service source, tests or service documentation. No commit/push performed; changes remain unstaged.

## Checklist

- [x] AI spinner/running label, immediate request guard, retry guidance; split in body mode.
- [x] Parent/child/exclude teacher review; atomic apply; existing source/formula engine retained.
- [x] Existing child/source awareness; repeated wrapper rejected; intentional grandchildren supported.
- [x] Current tree authoritative for Answer/Rubric; domain merge and visible projections.
- [x] Unassigned results/counts retained; explicit manual assignment, including unscored leaf nodes.
- [x] Previous draft/analysis backup and optimistic concurrency retained.
- [x] Same-Test source registry and per-entry artifact context; foreign source rejected.
- [x] Formal entities unchanged; no jobs started.
- [x] Backend, browser E2E, TypeScript, ESLint, Ruff, production build and diff validation.
- [ ] Real deployed Sample Q5 production acceptance (pending).
- [x] Drag-and-drop explicitly deferred; final publication intentionally out of scope.

## Final Git/remaining work

Git status: 16 modified tracked files and 2 new service files (this report and the split/merge browser spec), all unstaged. No commit or push. The implementation/test checklist is complete; deployed production acceptance is pending. Existing production Q5/results were not accessed or altered. No known implementation/test defect remains from this phase.
