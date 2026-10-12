# J.UI.12b-fix11 — Rubric Terminology, Split Reliability & Section Ownership

## Result
**READY_FOR_PRODUCTION_VALIDATION**. Implementation and automated verification passed. Production acceptance not performed. No production access, deployment, commit or push.

## Baseline / audit
Committed baseline: `b438750a0faed40c41699b61be0ad54d520bde46`; clean working tree at start (fix10 already committed externally).

| Symptom | Root cause | Change |
| --- | --- | --- |
| 観点1観点 | Numbered checkbox label and generic textarea label were adjacent; preview had no criterion heading. | Shared `rubricCriterionLabel` produces 基準N; body label is 本文 and accessible name 基準Nの本文, points 基準Nの配点. Preview uses the same headings. |
| Cursor split unreliable | Cached React onSelect offset could be absent/stale; cache was keyed only by criterion ID. | Read actual textarea selectionStart before disabling it. Track active entry+criterion identity; pointer-down retains the textarea focus; keyboard activation uses its retained selection. Selection ranges split at selectionStart. |
| Cursor/assisted split rejected | Both tools required the full Answer source/diagram context, including a blanket material-replacement guard. Independent Rubric text operations could therefore fail after Answer replacement. | Text splitting retains owned Test authorization, draft state, CAS and canonical target checks; it does not require a current PDF/diagram artifact. Native `reconstruct_split` / classifier remain the engines. |
| Assisted split appeared inactive | Busy state disabled fields but kept the original button label; errors often appeared as generic communication failures. | Per-target spinner, 分割案を作成中…, disabled button, synchronous duplicate-request guard; structured actionable failures. |
| Answer add below Rubric | One trailing shared add action followed all interleaved Answer/Rubric candidate sections. | Add action lives inside the last visible Answer candidate section (or explicit empty Answer section). Rubric-only has no Answer add control. Empty Rubric state has its own 採点基準を追加 action. |

## Rubric domain semantics
No new split engine or grading semantics. Manual cursor requests use the existing range reconstruction without inference; assisted requests use the existing classifier only after explicit action. Proposals are reviewed before apply/cancel. Invalid boundary/blank fragments reject with a reason. UTF-16 caret positions convert to Unicode code points; inline/display math tokens cannot be split internally.

Existing point policy remains: explicit unambiguous per-part markers supply points; missing/ambiguous allocation yields 0 with points_conflict and requires teacher review. The proposal explains the original points and that points are not automatically redistributed. Existing completion issues track unresolved points. No original points are silently copied to each child.

Applying inserts fresh stable criterion IDs at the original location, records source segment IDs/ranges, original text/points, source SHA and previous operation provenance, and pushes the original rows into the existing bounded history. Undo restores exact previous rows/IDs/points. Existing merge/insert/duplicate/consolidation stay in use. Native browser undo history is not promised across navigation; persisted domain state is.

## Ownership / presentation
Answer-related controls including classification and manual Answer creation stay inside the Answer section. Rubric-only mode exposes criterion editing and no Answer action. Preview/edit buffers and typed readiness are unchanged. The parent working copy remains the authoritative state; terminology/index changes do not alter internal IDs or schema.

## Verification progress
Focused backend tests for source-independent text splitting, auth target validation, stale CAS, invalid fragments and range/points behavior added. Browser/helper coverage added for cursor selection without synthetic select events, invalid boundary, explicit assisted progress/apply/cancel, points, Undo/merge, Save/reload/Back/resume, Unicode/math boundaries and all Answer/Rubric checkbox combinations. Full verification pending.

## Deferred / remaining
Deployed terminology, cursor/assisted split and section ownership acceptance remains required. J.UI.12c publication and Question/Rubric drag-and-drop remain out of scope. Production Q5, grades, runtime/model configuration unchanged.

## Focused verification checkpoint
- Focused backend authoring/shared-source/native rubric split group: **48 passed** (including 3 new authoring text-tool tests).
- Initial preview/material/source-backed/criterion browser group: **5 passed**.
- Expanded source-backed criterion group: **4 passed** (3 new helper/browser cases + existing source-backed authoring).
- The first expanded source-backed fixture incorrectly assumed the normalized description still contained source point markers; normalization deliberately separates points from description. The fixture now performs an explicit teacher edit with two logical conditions and explicit point markers, preserving original native segment ownership. No product assertion was weakened.
- TypeScript passed. Full ESLint: 0 errors, 19 existing warnings. Ruff and diff check passed. Production Next build passed with existing CSS/ESLint warnings.
- Full normal production-like browser and full backend suites are running after final product changes.
- Native source-backed split verifies disjoint contiguous ranges, shared original segment IDs, sum of explicit points =10, stable Question tree, same native material, exact saved criteria after reload and no formal mutation.
- Split/consolidation review panels are now nested in their owning Rubric candidate section and disappear when that section is hidden; proposal state stays local and returns when shown.

## Regression harness race discovered
Full browser run exposed a stale success-Toast wait in the existing Question split/merge scenario. Trace showed the last PUT contained both child nodes; an immediate GET returned the pre-save tree, then the next GET returned the saved split tree. The previous Save Toast was still visible and was mistaken for completion of the latest Save. Added `saveAuthoring` helper that waits for the specific PUT response and cleared dirty state before snapshot assertions; applied it to that scenario. No sleeps, retries or weakened tree assertions were added. Product Save/resume logic was unchanged.

## Broad verification checkpoint
Final full normal production-like browser suite: **59 passed** (2.0 minutes), grading jobs **0**. Includes 10 Save/reload/Back/resume cycles, 5 readiness cycles, stale-tab protection, edit-during-Save, shared source add/reanalysis/replacement, notification/issues, current Question tree preservation, caret/IME, split review, source warnings, legacy Rubric engines and diagram discovery. The stale-Toast test race was corrected and old foundation locators were updated to the new accessible terminology.

Full backend suite first run: 919 passed, 1 skipped. Added a fourth focused test for saved unassigned criterion splitting before assignment, preserving legacy capability without bypassing foreign-target checks; final full backend rerun pending. Final source authorization check does not alter owned assigned-target behavior verified in the full browser run.

Assisted failure/retry is explicitly tested with the managed stub returning 503: inline actionable message appears, current text stays intact, button becomes available, and a later explicit retry produces a proposal. Expected synthetic 503 resource logging is distinguished from unexpected console errors.

## Critical regression checkpoint
Final managed truncated-Ricoh/diagram reuse/teacher override/Question and Answer OCR/save-resume/shared-source analysis/new Rubric group: **10 passed**, grading jobs **0**. Production Next build passed. Includes corrected accepted diagram reuse after Rubric analysis with independent assignments, source warning separation, typed disabled tooltip readiness and role-independent source reanalysis/replacement. No inference on cursor split, Undo, merge, toggles or navigation; explicit assisted split alone calls the existing model path.

## Files changed
- `frontend/components/reviews/AuthoringCandidates.tsx`: terminology, actual active cursor reads, split progress/errors, provenance, and owned Answer/Rubric action and proposal sections.
- `frontend/lib/rubricEditing.ts`: shared criterion naming and Unicode/math-safe split boundary validation.
- `src/scoring/api/test_authoring.py`: authorized text split independent of PDF/diagram validity, owned target/CAS validation, explicit error messages and unassigned saved-candidate support.
- `frontend/e2e/authoring-rubric-reliability-real.spec.ts`: new helper + manual/assisted/points/Undo/persistence/source-backed scenarios.
- `tests/test_authoring_rubric_split.py`: four focused API tests.
- `frontend/e2e/authoring-source-backed-real.spec.ts`: accessible labels and four Answer/Rubric visibility combinations.
- `frontend/e2e/authoring-preview-materials-real.spec.ts`, `frontend/e2e/test-authoring-foundation-real.spec.ts`: updated unified criterion locators.
- `frontend/e2e/authoring-split-merge-real.spec.ts`, `frontend/e2e/authoringNotifications.ts`: updated names and race-free Save verification helper.
- `tests/run_runtime_browser_e2e.py`: new Rubric cases included in the normal production-like suite.
- This report.

All tests use disposable fixtures/databases, real FastAPI/RuntimeManager and managed stubs. Formal-state snapshots are asserted unchanged in the new browser cases; no authoring action publishes or launches grading. Existing legacy formal-transfer tests use only their own disposable fixture APIs.

## Final verification
| Check | Result |
| --- | --- |
| Full backend after final API change | **920 passed, 1 skipped**, 13 existing collection/deprecation warnings |
| Focused new API tests | 4 tests (included in full backend pass) |
| New local helper coverage | 1 semantic helper scenario, Unicode and inline/display math boundaries |
| Full normal production-like browser | **59 passed** |
| Final critical diagram/OCR/save/shared-source/Rubric browser group | **10 passed** |
| Final Rubric-only rerun with start/end/wrong-active-criterion assertions | **3 passed** |
| TypeScript | Passed |
| Full ESLint | 0 errors, 19 existing warnings |
| Ruff (`src tests`) | Passed |
| Production Next build | Passed (existing CSS/ESLint warnings) |
| git diff --check | Passed |
| Browser harness grading jobs | **0** |

The final Rubric rerun covers current caret with selectionStart semantics, first/end/blank/math invalid boundaries, wrong-active-criterion rejection, assisted running/spinner/cancel/apply/failure/retry, points/ordering/Undo/merge, current preview names, exact criteria/IDs/history through Save/reload/Back/resume and native source/range retention. Proposals remain range-based previews; teachers can cancel, edit criterion text and request again rather than editing source ranges inconsistently. No new split engine, point redistribution, schema migration, notification issue conflation or formal publication was introduced.

## Final git status
9 tracked service/test files modified and 3 untracked service-related files (new API tests, new browser spec and this report). Nothing staged; no commit or push. Production/Q5/grades untouched. No runtime/model configuration changes.

## Remaining / production acceptance
No known reproducible defect remains from this validation. Only real deployment UX acceptance remains: terminology, cursor/assisted split, points/Undo and Answer/Rubric simultaneous and single-section ownership. This phase is not COMPLETE.

Question drag-and-drop ordering: **deferred to future phase**. Rubric drag-and-drop not implemented. Final publication: **deferred to J.UI.12c**.
