# J.UI.12b-HARDEN-2 — Overnight Authoring Reliability Audit & Repair

## Result
**READY_FOR_PRODUCTION_VALIDATION.** The final broad browser suite and targeted critical run pass. No production deployment or production data was accessed; deployed acceptance remains required.

## Baseline
- Commit: `db5b24c3eb4153e8fdbff9f4e67151504c5ed1f0`
- Initial working tree: clean (`git status --short` empty).
- Migrations: 17 Alembic version files. No migration planned.
- Inventory at baseline: 65 frontend E2E files; 69 backend test files.
- Last committed proposal-dialog phase reported 920 backend passed / 1 skipped; normal browser 60 passed; critical browser 11 passed. These are baseline evidence, not current final-phase verification.
- Existing development harness uses real FastAPI, disposable Postgres, Next production build, Chromium, RuntimeManager and managed stubs.

## Audit observations so far
- Answer diagram reuse has an existing real-browser regression test that accepts Q3(1), analyzes a same-PDF Rubric binding, then reuses the accepted artifact in Q3(2), verifies the crop and confirms no additional RuntimeManager calls. Baseline critical run passed this scenario. Recheck after final code.
- `source_projection` chooses the globally newest `ModelAnswerImportDraft`; that is unsuitable as the authoritative source for a Question analysis. The explicit Question path used that whole projection as the next authoring revision, so it could replace the saved Answer/Rubric domains with whichever one import happened to be newest.
- `merge_answer_analysis` counted every geometry-created entry as a Rubric candidate. A Rubric source could therefore report candidate entries even when no segment was classified as a criterion/recoverable uncertain item. Also, the projection could replace an existing criterion list with an empty list when fresh classification had no usable groups.
- Existing source-backed classification segments include their category and exact extracted text, so `rubric`/`uncertain` segments can be offered for explicit teacher recovery without generating or rewriting prose. Recovery uses normal criteria with unresolved points/grouping flags and preserved segment identity.
- Current analysis feedback had a generic disabled button and generic “selected material” status line. Converting the line to an accessible compact strip with a role-specific label.
- There is one persisted editable authoring revision containing Question, Answer, and Rubric domains, alongside separate source/import drafts and role-bound analysis markers. Global latest-import selection is not a safe domain authority; merges must stay role- and source-bound.

## Fixes and regression coverage
See the completed sections below; append each defect only after its focused test reproduces and passes.

## Reproduced defects and fixes

### Defect 1 — Question analysis projected a globally latest Answer import
- **Symptom/reproduction:** analyze a Question sheet after Answer and Rubric imports had been saved. The source projection could choose whichever `ModelAnswerImportDraft` was globally newest and use its entire projection as the new authoring revision, replacing current Answer/Rubric candidate-domain state.
- **Root cause:** explicit Question analysis reused `source_projection()` as a full snapshot replacement. That projection is appropriate for initial/source-backed projection but not for updating one role in an existing editable revision.
- **Fix:** `merge_question_analysis(current, analyzed)` makes the current authoring snapshot authoritative for Answer/Rubric, replacing only Question nodes, Question source metadata/tokens and Question diagnostics. Candidate targets removed by a new tree are retained as unresolved rather than discarded.
- **Regression:** backend snapshot test plus production-like browser comparison around Question analysis checks Answer entries, Answer sources/material, tokens, answers and rubrics. Browser run pending latest rerun.

### Defect 2 — Rubric analysis counted geometry rows, not criteria
- **Symptom/reproduction:** a Rubric-role analysis could produce geometry entries containing only Question/noise segments and report candidates even though there were no criteria. Fresh empty rubric projections could also replace existing criteria with an empty list.
- **Root cause:** candidate counts used geometry entry count; the role merge could project an empty rubric list.
- **Fix:** Rubric result counts only `rubric`/`uncertain` extracted segments and their Question mapping. Zero candidates report `no_candidates`; uncertain/unassigned segments stay in the source-bound domain for explicit recovery; empty projections no longer erase prior criteria. The page directs teachers to manual add for true zero-result cases.
- **Regression:** partial/uncertain and zero/noise backend tests. Browser scenario exercises explicit promotion of a retained uncertain segment to a rubric criterion, assignment, points confirmation, save/resume and unchanged runtime-call counts.

### Defect 3 — Answer reanalysis could drop Rubric edits stored on source candidates
- **Symptom/reproduction:** reanalyze the same Answer PDF after a teacher edited criteria attached to its candidate. Native extraction creates fresh candidate UUIDs, so the previous candidate was removed from the active answer-domain entry list even though the top-level Rubric map could remain unchanged.
- **Root cause:** role merge retained old same-material entries only for accepted diagrams; Rubric edits/history are nested on source-bound entries and were not independently retained.
- **Fix:** preserve Rubric edits, consolidation data and operation history on matching IDs. If extraction changes entry IDs, preserve prior teacher-reviewed/rubric-edited entries under their original source identity as Rubric-only entries, while current Answer text comes from the new analysis. Those entries are hidden from the Answer section and remain editable under Rubric.
- **Regression:** unit test verifies fresh candidate ID replacement retains criterion IDs/text/points/history/source draft and updates the Answer projection only. Browser same-role reanalysis isolation remains part of the production-like scenario.

### Defect 4 — A replacement in one role blocked diagram actions for all role sources
- **Symptom/reproduction:** analyze Answer and then Rubric, replace only the Rubric binding, and request reuse for an already accepted Answer diagram. The authoring endpoint rejected the request because a single domain-level replacement check saw any replaced source in the combined Answer/Rubric snapshot.
- **Root cause:** `answer_context()` rejected all entry operations based on aggregate `replacement_problems()`. In the frontend, `answerStale` checked only the single most recently analyzed material, while `AuthoringCandidates` used that single draft ID for all entry operations.
- **Fix:** resolve replacement state after `AuthoringAnswers.entry()` binds the requested entry to its `source_draft_id`; preserve the established 409 for the entry whose own source was replaced. The frontend computes replaced source draft IDs from the material registry and marks only entries bound to those sources stale. OCR uses each entry’s source draft ID. The unrelated role remains usable.
- **Regression:** expanded sibling diagram test performs Rubric analysis, replaces only the Rubric binding, then verifies the accepted Answer diagram is still discoverable without inference; the preexisting Answer-replacement test still expects 409 for its stale entry. Production-like browser replacement checks the page remains free of uncaught/console errors.

## Current verification checkpoint
- Focused backend after the final source-merge fixes: `tests/test_authoring_diagrams.py tests/test_authoring_sources.py tests/test_shared_source_bindings.py`: **39 passed**, one existing Starlette deprecation warning.
- Targeted role-isolation/recovery real-browser spec: **1 passed** under production Next build + real FastAPI + disposable DB + RuntimeManager managed stub; harness reported grading jobs **0**. It checked role-specific progress, Answer/Rubric reanalysis independence, Question reanalysis preservation, shared PDF role binding, recovery promotion with no additional model calls, replacement separation, Save/Back/resume and no browser console/page errors.
- Expanded diagram backend test: Answer sibling reuse remains available after Rubric analysis and Rubric-only replacement; a genuinely replaced Answer source still rejects its diagram operation with 409.
- A first browser attempt was stopped after a test fixture selected the material dropdown rather than the Question selector. The trace identified the wrong selector; corrected rerun passed. No product defect was attributed to that attempt.
- Full backend suite after final backend changes: **925 passed, 1 skipped, 21 existing collection/deprecation warnings in 200.86s**.
- Critical truncated-response authoring group: **10 passed** under production Next build + disposable PostgreSQL + FastAPI + RuntimeManager managed stubs; grading jobs **0**.
- Analysis/access browser spec: **2 passed**, including fresh Sample Q5-like workflows in both Question→Answer→Rubric and Question→Rubric→Answer order. It compares the teacher-edited Question tree, per-role source identity/SHA and source-bound entries, Answer/Rubric projections, reload and Back/resume. Formal entity endpoints remained empty; grading jobs **0**.
- Static checks after the final product change: Ruff passed; TypeScript passed; ESLint **0 errors / 19 existing warnings**; `git diff --check` passed. The last UI-only recovery guidance change is included in the post-fix production Next build/full browser run; final diff check follows it.
- Full normal production-like browser suite first ran **60 passed / 1 failed**. The lone failure was the stale recovery expectation documented as Defect 7. After the behavior was fixed and its regression assertion updated, the post-fix suite passed **61/61** after a fresh Next production build; the harness reported grading jobs **0**.
- The Rubric recovery visibility filter excludes `fallback`-only uncertain text; backend zero-result regression includes this case. The Q5-like browser run saw no auto-registered Rubric criteria for its source, surfaced a truthful zero-candidate/manual-add warning, and exercised a separately retained reviewed candidate through explicit promotion.
- First attempts at the expanded browser scenario found test-side synchronization/fixture errors (old replaced source used for a synthetic recovery candidate; Question tree expected before teacher edit; answer-endpoint waiter used for Question analysis). Corrected these without weakening assertions. Direct HTTP response synchronization plus both-order workflow now passes.

### Defect 5 — Classifier fallback text was too permissive for Rubric recovery
- **Symptom/reproduction:** fallback classification can represent an entire raw extraction as one `uncertain` segment. The first recovery filter would have offered it as a criterion despite no semantic classification.
- **Fix:** `rubric` segments remain recoverable; `uncertain` segments are recoverable only for actual `classified`, `needs_teacher_review`, or `teacher_reviewed` states. Fallback-only uncertain text produces the truthful zero-candidate/manual-add state. No criteria are synthesized.
- **Regression:** zero-result backend test includes a fallback uncertain block and verifies no candidates plus preservation of previous criteria. The explicit recovery browser fixture uses a `needs_teacher_review` segment and verifies exact-source promotion.

### Defect 6 — Teacher Answer corrections could disappear on fallback reanalysis
- **Symptom/reproduction:** edit an Answer candidate, then reanalyze the same source when the classifier returns native/fallback output with fresh candidate IDs. The previous merge only retained entries with diagram or Rubric work, so the teacher answer could be removed.
- **Root cause:** native reanalysis generates new IDs and fallback output is not a replacement for meaningful teacher-owned Answer content. The merge previously treated it as such when IDs did not match.
- **Fix:** preserve source-bound teacher corrections and explicitly teacher-reviewed Answer segments. Matching entries restore teacher text/classification when new output is fallback; changed-ID teacher-answer entries remain under their original source identity. API returns `fallback_count`; UI surfaces a warning.
- **Regression:** backend test forces fallback classification with a new ID and asserts teacher answer text/source ownership/fallback count.

### Defect 7 — Unassigned fallback candidates were retained but not brought into view
- **Symptom/reproduction:** analyze a source whose extracted entries cannot be assigned and whose classifier falls back. The first broad browser rerun showed the previous “could not map” alert did not appear; the new fallback warning was shown while the view remained on the Question target.
- **Root cause:** completion prioritized `fallback_count` over zero assigned entries and did not select the retained unassigned-candidate target.
- **Fix:** when fallback candidates remain unassigned, completion switches to that target and explicitly tells the teacher to review and assign them. It does not invent or auto-assign content.
- **Regression:** browser assertion checks the actionable message and selected `unassigned` target, then manually assigns/saves the retained candidate and verifies no extra model calls. Focused browser scenario: **3 passed**.

## Full backend checkpoint notes
- First full run: 922 passed / 1 skipped, with 2 failures. One fixture omitted the classifier status while representing a recoverable uncertain segment; the other exposed a real accepted-diagram preservation regression where stale classifier output was retained.
- Fixed the fixture status to reflect a genuine review-state result. Updated the preservation logic so accepted diagrams retain their verified assignment while old classifier/Rubric payload is cleared unless teacher-owned Rubric edits/history exist. Focused rerun: 3 passed. Full backend suite restarted after this change.
- Final full backend run: **925 passed, 1 skipped**. No backend test failure remains.

## Domain isolation and source ownership results
- **Question analysis:** the before/after browser snapshots compare stable keys, parent links, ordering, edited text and points, plus Answer entries/domain sources and Rubric criteria/history. Both `Question → Answer → Rubric` and `Question → Rubric → Answer` complete on fresh disposable Sample-Q5-like Tests; only Question analysis changes the Question projection.
- **Answer analysis/reanalysis:** merge tests preserve Question nodes and Rubric criteria/history; fresh candidate identity does not delete teacher-owned Answer text, accepted diagram assignments, or Rubric edits. Answer source registry and SHA remain bound to the Answer material.
- **Rubric analysis/reanalysis:** the other analysis order shows Question tree and Answer source-bound entries/diagrams unchanged. Rubric candidates remain linked to the material that produced them; no role context is inferred from globally newest import.
- The authoring working copy is one revision with three domains. Native import drafts remain separate and can have distinct IDs per source/material. The prior bug was using a global projection/recent source as if it owned the whole authoring state.

## Diagram reuse and Rubric recovery findings
- The reuse regression was consistent with cross-role source context leaking through the combined Answer/Rubric domain: actions used aggregate replacement state and a single latest source ID, even when the requested Answer candidate belonged to an older, still-valid Answer source. A Rubric source registration/replacement could consequently make a valid Answer candidate appear stale or lose its compatible source context.
- Reuse now resolves the requested candidate first, then checks the replacement state for that candidate's own source draft. Frontend stale/OCR/review operations likewise use each candidate's source ID. Reuse remains limited by the existing same-Test, same-major, accepted-artifact scope; it was not widened to arbitrary Test-wide artifacts.
- Critical truncated-Ricoh browser coverage verifies accepted Q3(1) diagram → Rubric analysis → Q3(2) reuse, same crop identity, saved/reloaded assignment, and unchanged RuntimeManager call counts. Backend coverage additionally replaces the Rubric binding while confirming Answer reuse remains valid; replacing an Answer's own source still produces the existing 409.
- Rubric extraction lifecycle is: extracted segments → normalized/classified category → question mapping → role-scoped projection → teacher promotion. Previously, geometry entries inflated the candidate count and empty fresh projections could erase prior criteria; fallback-only uncertain raw text could also look recoverable. Now true criterion segments and semantically reviewed uncertain segments are retained; fallback-only/noise is excluded from promotion and the UI offers manual add when the result is truly empty. A mapped criterion promotion preserves segment provenance and remains a normal unresolved-points Rubric item for teacher review.
- No schema migration was needed. The retained candidate lives in the existing source-bound authoring entry JSON; rubric promotion records its origin segment. This avoids a separate candidate table and keeps source/material identity available through save/resume.

## Analysis progress and failure behavior
- Analysis status is an unobtrusive `role=status` / polite live strip with spinner and explicit role label: 問題, 模範解答, or 採点基準. It appears while the button stays disabled, does not obscure PDF viewing, and is cleared in `finally` on success or failure.
- Empty Rubric output says that no automatic candidates were extracted and directs the teacher to manually add criteria. Fallback results carry a warning/count; unassigned results switch to the unassigned target so retained candidates are discoverable.
- Failure pathways in the backend preserve prior teacher-owned Answer/Rubric data; existing browser failure/OCR retry cases pass. The final suites do not exhaust every possible external model timeout/malformed payload permutation; managed truncated/fallback and runtime-unavailable paths are covered.

## Final browser and safety checkpoint
- Normal production-like Chromium suite after the final UI fix: **61 passed**, **0 failed**. This includes two real-Q5-like analysis-order fixtures, the 10-cycle save/reload/back/resume endurance scenario, five dirty→Save→reanalysis cycles, stale-tab CAS, edit-during-Save, issue navigation, split/undo/proposal dialog, Answer/Rubric UI ownership, OCR, diagram review, and legacy review continuations.
- Focused unmatched/fallback recovery browser suite: **3 passed** after the fix. A prior full-suite run was **60 passed / 1 failed** on the recovery alert/target expectation; the test exposed an actual visibility gap and was strengthened to assert target selection plus manual assignment rather than accepting a generic warning.
- Dedicated truncated-Ricoh diagram/OCR/split browser group after final code changes: **10 passed**, 0 failed; fresh production Next build succeeded and the harness reported grading jobs **0**.
- Formal Question and ModelAnswer API resources remained empty in the disposable fresh-fixture tests. Browser harness reported grading jobs **0** after normal and focused runs. No production resources were accessed.

## Final commands and remaining manual acceptance
- Backend full suite: **925 passed, 1 skipped**; 21 pre-existing collection/deprecation warnings; about 201 seconds.
- TypeScript: passed after all product changes. ESLint: **0 errors, 19 existing repository-wide warnings**. Ruff: passed. `git diff --check`: passed after all changes. Production Next build: passed in both final browser harnesses (existing Autoprefixer/Next lint warnings only).
- No migrations, commit, push, deployment, formal publication, or grading jobs.

Tomorrow's deployed acceptance:
1. Fresh Test: register/analyze Question, edit/split/save, then register/analyze Answer and Rubric; verify all three after Back/resume.
2. Accept a diagram on Problem 3 > (1), then open Problem 3 > (2) and reuse it. Repeat after Rubric analysis and after Save/reload/Back/resume.
3. Analyze a Rubric source with criteria and verify visible criteria; also verify the true empty-result guidance and retained recoverable candidate path.
4. Reanalyze exactly one of Question, Answer, or Rubric and verify the other two domains remain intact.
5. Register one physical PDF as both Answer and Rubric; verify separate bindings and independent analysis/replacement.
6. Save, navigate Back, resume, and verify the same Question tree, Answer entries/diagram decisions, Rubric criteria, source identities, and exact teacher text.

## Final repository state
- HEAD remains `db5b24c3eb4153e8fdbff9f4e67151504c5ed1f0`; no commit, push, or deployment.
- Final modified files: `frontend/app/globals.css`, `frontend/app/tests/[testId]/authoring/page.tsx`, `frontend/components/reviews/AuthoringCandidates.tsx`, `frontend/e2e/authoring-analysis-access-real.spec.ts`, `frontend/e2e/authoring-split-merge-real.spec.ts`, `frontend/lib/api/testAuthoring.ts`, `src/scoring/api/test_authoring.py`, `src/scoring/authoring_sources.py`, `tests/test_authoring_diagrams.py`, `tests/test_authoring_sources.py`; requested local report `docs/reports/j-ui-12b-harden-2.md` is untracked.
- No migration/schema changes. Working tree is intentionally left uncommitted for review.
- Deferred/out of scope: J.UI.12c/12d publication, grading/student revision binding, Question drag-and-drop, and deployed production acceptance.
