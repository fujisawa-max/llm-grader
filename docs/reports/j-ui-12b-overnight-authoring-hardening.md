# J.UI.12b-HARDEN-1 — Overnight Unified Authoring Hardening

## Result

READY_FOR_PRODUCTION_VALIDATION. Automated hardening and regression checks are complete. Deployed/production acceptance was intentionally not run; production systems remain untouched.

## Baseline

- HEAD: `99d925661590b76ef0a15354f009ec4b57544d5d`
- Initial `git status --short`: clean
- Architecture spec: `docs/auto-grading-system-spec-v4.md` reviewed
- Production database, deployed Sample Q5, formal production data and grading jobs: not accessed

## Scenario progress

- [x] Baseline / safety recorded
- [x] Save/reload/Back/resume ten-cycle endurance
- [x] Dirty → Save → analysis readiness repeated five cycles
- [x] Split role permutations and persistence (including duplicate-wrapper guard and intentional grandchild)
- [x] Question → Answer → Rubric workflow across independent fixtures (repeated in isolated split/merge and critical-run fixtures)
- [x] Unresolved mapping/manual assignment
- [x] Reanalysis and cross-material accumulation
- [x] Replacement/stale source
- [x] Source warning and external review conflict/import
- [x] Multi-tab stale save
- [x] Save response racing a newer local edit
- [x] OCR/diagram/Rubric persistence after resume (browser regression coverage)
- [x] Broad backend + browser regressions and two consecutive critical runs

## Defects found

### Defect 1 — Pending split proposal did not explain why material analysis was unavailable
- **Symptom:** With a split proposal open, the selected material's analysis action was disabled, but the proposal itself did not state that analysis must wait until the proposal is applied or canceled.
- **Reproduction:** Save Question text, generate an AI split proposal, select an Answer source. The Analyze button is disabled because the split suggestion updates the local source-backed Question state; the only prior message was generic save guidance, which did not explain the pending proposal constraint.
- **Root cause:** The analysis handler guarded `splitProposal`, but the guard text only appeared after a click; readiness disabled the button first, so the guarded handler was unreachable. The proposal UI had no equivalent visible status.
- **Fix:** Added an explicit status next to the pending proposal: analysis can resume after applying or canceling it, and the proposal remains retained. The regression now asserts the action stays disabled, guidance is visible, and the persisted revision is unchanged.
- **Regression:** Focused split/merge browser scenario passed 3/3 after the correction. Neighboring endurance/readiness/stale-save and split/merge/material flows are now in the required post-fix repeated critical run.

### Defect 2 — Save's edit-epoch protection could not be exercised through the UI
- **Symptom:** During a delayed Save, the Question textarea was disabled until the response, making it impossible to continue editing while the request was in flight.
- **Reproduction:** Start Save with a controlled API-route delay, then attempt to change the Question body before releasing the response. The editor was disabled even though Save already captures a snapshot and tracks `editEpoch`.
- **Root cause:** The Unified Workspace passed `saving` as `NodeEditor.readonly`, disabling the whole editor and preventing the existing edit-epoch merge path from being reachable through normal interaction.
- **Fix:** Keep the Question editor writable during Save (analysis/read-only states still disable it). The existing save response path preserves the newer local buffer, advances the persisted revision baseline, and leaves the page dirty for the next Save.
- **Regression:** First delayed-response attempt confirmed the local text remained, and correctly showed “送信した内容は保存しました。その後の変更は未保存です。” instead of claiming the whole editor was saved. The test initially expected the generic success banner; corrected it to assert the precise partial-save status, no generic success, dirty state, persisted first snapshot and successful second Save. Focused endurance passed 4/4 and the critical matrix passed 22/22 twice consecutively afterward.

The first mixed repeated browser matrix also exposed harness contamination rather than confirmed product defects: repeated fixed-ID fixtures changed one another's initial state, a repeated Test-list test reused names, and a source OCR test assumed a seed text that was not present in its current fixture. Those cases are being rerun in separate disposable harnesses; the Test-list fixture now uses a unique run suffix. No assertions were weakened.

## Final verification

- After the last product code change, the critical overnight matrix passed **22/22 cases twice consecutively**. It includes Save/reload/Back/resume endurance, readiness, split persistence, sequential Answer/Rubric merge, source warning, replacement, stale-tab conflict and an in-flight edit.
- `pytest -q tests`: **913 passed, 1 skipped, 13 warnings**.
- Production-like browser suite: **56/56 passed**. Additional post-suite targeted coverage passed for saved-review import (**1/1**), replacement/reanalysis (**2/2**) and truncated-Ricoh teacher confirmation/reuse (**4/4 across two clean harnesses**).
- `npm run typecheck`: passed.
- `npm run lint`: 0 errors, 19 warnings in existing unrelated files.
- `ruff check src tests`: passed.
- Production `next build`: passed through the isolated browser runner after the final product code change.
- `git diff --check`: passed.
- Browser harness checked grading jobs at start and end: **0**. No formal publishing was performed.
- Remaining operational limitation: real deployed acceptance is not performed by design. Question drag-and-drop ordering and J.UI.12c publication remain explicitly deferred.
- Working tree contains only uncommitted hardening code, regression/harness updates and this report. No commit, push or deployment has occurred.

## Progress update — endurance harness

- Added `frontend/e2e/authoring-endurance-real.spec.ts`: deterministic 10-cycle Save/reload/Back/resume with a stable Question key, parent, points and exact text checks; plus five dirty → Save → reanalysis readiness cycles and no-auto-analysis call-count checks.
- Registered it in the normal isolated browser suite.
- First attempt stopped in the harness because it queried “点数”; the existing settings field is labeled “配点”. This was a test locator error, not a product defect. Corrected the locator and rerunning the scenario.
- Broad backend suite and isolated endurance browser harness are running. Initial backend progress showed failures; final tracebacks are needed before classifying them.

## Broad backend checkpoint

- `pytest -q tests`: 905 passed, 1 skipped, 8 failed. Seven failures are unrelated grading/student-input HTTP tests returning 401 under their unauthenticated `TestClient` calls; the authoring change set does not touch the authentication middleware or those endpoints. The eighth is the existing PDF native same-test/same-SHA rejection test; the authoring change set does not touch that endpoint or PDF native implementation. These failures are recorded as baseline suite/environment compatibility issues pending isolated confirmation.
- No grading work was started; the single grading-job test receives 401 before job creation.
- Targeted authoring backend suite from fix7 remains green before this hardening pass; final focused rerun will be done after browser issues are triaged.

### Endurance harness investigation

- Second harness run exposed two more test-only issues before any product Save: the “配点” accessible name matches both the score-mode select and score input, and settings mode must return to preview before entering body edit. Select the spinbutton role and follow the UI’s settings → preview → body-edit transitions.
- The five-cycle analysis assertion was corrected to distinguish native extraction from model inference. It now checks that Save leaves revision and RuntimeManager call counts unchanged, then verifies explicit reanalysis creates the next authoring revision. A Question PDF may be natively reanalyzed with zero chat-completion calls, so requiring an inference log was invalid.
- These harness corrections do not weaken product assertions.
- A further endurance harness issue was that edit mode intentionally returns to preview after reload/resume. The test now re-enters body edit explicitly before editing the next cycle, consistent with the existing preview/edit contract. A clean triple repeat is running.
- First fully exercised endurance attempt completed all ten Save/reload/Back/resume cycles and the five readiness/reanalysis cycles. The only failing assertion treated Next.js speculative route-data requests canceled during intentional Back/reload as network failures; no API errors, 5xx, page errors or console errors were present. The harness now excludes only the expected `net::ERR_ABORTED` for `_rsc` navigation requests and continues to fail on other request failures. Running the full critical spec three times now.

### Baseline suite updates

The initial eight broad-suite failures reproduced independently. Seven were stale HTTP tests that opened the real authenticated app without logging in, causing them to stop at 401 before reaching their intended assertions. Added a test-only helper that creates a disposable teacher credential and authenticates those requests; application auth behavior is unchanged. The eighth test expected duplicate same-Test/same-SHA PDF upload to reject, while the current endpoint deliberately returns the already completed extraction for an idempotent retry. Updated the test to assert same extraction reuse and cross-Test extraction isolation, preserving a strong check rather than relaxing it. Focused rerun is in progress.

## First endurance results

- Endurance suite with three repeats: 6/6 browser cases passed. This represents 30 Save/reload/Back/resume cycles and 15 dirty → Save → explicit reanalysis cycles across independent fixtures. Revision stayed at 1; edit_version advanced 1 per Save; stable key, hierarchy, direct points and exact text survived. Snapshot SHA changed on each changed snapshot. No formal Question/Answer/Rubric was created. Isolated harness grading jobs: 0.
- The same endurance suite plus the new stale-tab scenario passed again in a fresh disposable harness (3/3): 10 additional Save/resume cycles, five readiness cycles, and Tab B's stale Save was explicitly rejected while Tab A's value remained authoritative.
- Split/merge browser run after the pending-proposal messaging fix: 3/3 passed. It covered the guarded pending proposal, parent/child/exclude, duplicate-wrapper rejection, intentional grandchildren, actionable unresolved assignments, and sequential Answer/Rubric import with exact Question tree preservation.
- Same suite's first instrumented run caught only navigation-canceled Next.js RSC prefetch requests. The final observer treats those intentional cancellations as expected and still captures page errors, console errors, non-RSC request failures and 5xx.
- After allowing Question edits during Save, the focused endurance spec passed 4/4, including delayed Save/edit-epoch/second Save. The full critical matrix then passed **22/22 twice consecutively** after the latest product change; both runs included Save/resume endurance, dirty→Save→readiness, stale-tab rejection, in-flight edit preservation, source warning, material replacement, split persistence, Answer/Rubric merge and unresolved mapping.
- Normal production-like browser regression after the final product fix completed **56/56 passed** in 1.9 minutes. It included Question and ModelAnswer math OCR, diagrams and parent/PDF shared assignment, split provenance, Rubric editing/merge/split, continuation/issue navigation, RuntimeManager classification, authoring foundation, Save-in-flight edits and all registered authoring hardening specs. Harness start/end invariant reported zero grading jobs.
- `npm run typecheck`: passed. `ruff check src tests`: passed. `npm run lint`: 0 errors, 19 existing warnings in unrelated files. `git diff --check`: passed at this checkpoint.
- Truncated-Ricoh teacher-confirmation and confirmed-diagram-reuse passed twice in separate fresh harnesses: 4/4 total, with each run confirming zero grading jobs.
- An explicit “保存済みレビューを取り込む” merge/preservation assertion was added after the full suite and passed separately (1/1): it verifies imported Answer data while preserving the exact authoring Question tree/text and formal entities. Its first attempt used an over-complete HTTP fixture payload and received the expected validation 422; the test now uses the endpoint's established update DTO, not weaker product assertions.

## Backend regression update

After correcting the test setup to authenticate fixture users and point the isolated app artifact root at its temporary source tree, the final broad suite passed: **913 passed, 1 skipped, 13 warnings in 189.78s**. The earlier 8 failures were all test harness setup/expectation drift, not product defects. The test corrections do not alter auth or grading behavior; duplicate PDF retry now asserts idempotent same-Test reuse and cross-Test separation.
