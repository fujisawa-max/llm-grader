# J.UI.12b-fix3 — Authoring Analysis Entry & Universal Test Editing Access

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Deployed acceptance has not been performed.

## Audit and causes

The source pane was already vertically stacked after fix1. However, the material dropdown used a vertical label, and fix2 placed Add/Replace/List on a separate actions row. This consumed extra height above the PDF. Explicit native analysis was only available in the collapsed right-hand 試験資料 panel, with separate domain buttons; selecting an unanalysed material did not reveal its own analysis action.

The offering Test table already linked every Test to authoring, but its plain 編集 link was visually secondary and did not distinguish confirmed state. This phase strengthens that existing universal entry rather than claiming the route did not exist. Home already selected one recent/active Test per Course and Test detail already offered authoring as the primary editing destination; both remain unchanged.

## Source controls and materials

The left source controls now form a compact flex row: 利用資料, dropdown, 解析/再解析, 差換え, separator, 一覧. The dropdown grows into available space and has a readable minimum width. The actions stay together; narrow widths can wrap into two rows. The existing shared sticky source pane, PDF toolbar, and PDF body remain vertically stacked, with PDF width using the pane and body filling the remaining viewport height.

Standalone Add moved into 一覧. This opens the existing right-hand materials panel, preserving PDF space. It shows role, filename, source SHA, active/replaced status and current selection; it provides 資料を追加, 選択 and per-material 差換え. Upload and replacement only register files and update local references. They preserve current Question, section visibility and unsaved edits. The old immutable material remains available; replacement provenance/stale validation from fix2 remains in force. No automatic analysis follows upload or replacement.

## Explicit analysis and persistence

The selected material determines the existing pipeline: question_sheet uses Question material extraction -> draft -> review -> authoring source import; model_answer_source and rubric_source use the existing ModelAnswer/Rubric native import service. Supplementary material has a disabled analysis action with a visible explanation. Unsaved edits require Save first; read-only, missing-material and busy conditions have explicit reasons.

Only an explicit click followed by confirmation starts analysis. Progress is visible, the action disables while busy, success updates the draft and the label becomes 再解析. Failure leaves the saved working copy intact and gives retry guidance. Question selection is retained when its stable key exists in the resulting copy; otherwise a safe first Question is selected. Section visibility and edit modes remain intact.

The confirmation explains that a new analysis result will create a new draft and retain the previous saved copy. The new UI passes preserve_previous=true to the existing analysis/import endpoints. Their shared write boundary atomically marks the prior TestAuthoringRevision as analysis_backup and inserts the next draft revision using the same existing table. The old snapshot remains unchanged. Optimistic edit_version increases across this transition; stale saves are rejected. No new table or migration is required. Existing API callers retain their prior default behavior.

Question source import additionally verifies that the selected TestMaterial belongs to the current Test, has the Question role, and matches the source SHA of the imported review. A different latest review cannot silently be marked as analysis of the selected material. Protected analysis_materials references retain material ID/SHA so previously analysed sources still show 再解析 after material switches/reload. Replacement references are carried into the new snapshot. Question analysis continues to compose the latest saved native reviews; this is stated in its confirmation and the prior saved copy is preserved. Formal entities are not published or frozen.

## Editing entries

Every offering Test row now has a button-styled authoring link. A read-only status query selects 編集 for editable state or 表示 for confirmed state; the route itself enforces existing lifecycle and authorization. The link always addresses that row's Test. Archive controls and Test detail links remain available. Home still shows one Test shortcut per Course. Test detail continues to open the current Test's authoring workspace. Authoring Back remains an explicit /tests/{testId} link. Legacy routes are retained.

## Validation

The focused production-like suite passed 5 cases, including new explicit analysis/access coverage and fix1/fix2/source-backed/foundation regressions. These overlap the full suite.

| Validation | Result |
| --- | --- |
| Backend authoring/diagram suite | 182 passed |
| Additional SHA/analysis-marker cases | 2 passed (10-case source adapter rerun passed) |
| Question/source ownership, ModelAnswer, Rubric, LaTeX, RuntimeManager backend regressions | 170 passed |
| Distinct backend cases | 354 passed |
| Normal production browser suite | 46 passed |
| Truncated Ricoh/reuse and unified math OCR browser suite | 5 passed |
| Distinct browser cases | 51 passed |
| TypeScript | passed |
| ESLint | 0 errors, 19 existing warnings |
| Ruff, changed Python files | passed |
| Production Next build | passed |
| git diff --check | passed |
| Grading jobs | 0 |

 It uses a production Next build, non-loopback HTTP, real FastAPI, disposable SQLite and actual RuntimeManager-managed stubs.

The new scenario verifies a non-latest Test entry, three editable Test rows, Home's single shortcut, compact desktop and safe narrow controls, PDF dimensions/stacking, list uploads for four roles, disabled reasons, no inference before explicit analysis, native role-aware analysis, loading and double-click prevention, reanalysis cancellation, analysis history, persisted analysis labels, source SHA matching, same Question context where possible, unchanged formal entities, and Test-detail Back/resume. Existing material/edit tests now enter Add through 一覧 and use the short selected-material 差換え action.

Backend additions exercise preserved Question/Answer snapshots, failed analysis without a backup, optimistic conflict rejection, selected-source SHA rejection and analysis marker resume. Existing domain authorization and source-integrity validators remain in use. No grading jobs or production/Q5 writes are performed.

## Production acceptance and remaining work

No known implementation or automated regression defect remains. Real deployment still needs compact source controls/PDF height, first analysis/reanalysis, list/add/replace and non-latest Test authoring entry validation. No deployment was performed. Atomic final publication remains intentionally out of scope.

## Required checklist

- [x] Compact source row, short labels, selected-material actions and global separator/List
- [x] Add inside List, role/name/SHA/current/replaced status, selection and replacement
- [x] Full-width tall PDF, vertical stacking, sticky desktop and safe narrow fallback
- [x] Explicit role-aware analysis/reanalysis, loading/error/disabled reasons, confirmation and retained prior saved copy
- [x] Upload/replacement/dropdown/list/navigation do not invoke inference
- [x] Every editable Test has authoring entry; non-latest Test tested
- [x] Home latest/active Test only; Test detail entry; explicit Back to Test detail
- [x] Formal entities unchanged; source SHA/provenance/auth retained; legacy routes retained
- [x] Authoring/domain/browser regressions and static checks
- [x] Grading jobs zero
- [ ] Real deployed visual/navigation/analysis acceptance

## Files and Git

Changes remain unstaged and uncommitted; no commit or push was made. Service files:

- frontend/app/globals.css
- frontend/app/offerings/[offeringId]/page.tsx
- frontend/app/tests/[testId]/authoring/page.tsx
- frontend/components/TestAuthoringEntry.tsx
- frontend/lib/api/testAuthoring.ts
- frontend/e2e/authoring-analysis-access-real.spec.ts
- frontend/e2e/authoring-preview-materials-real.spec.ts
- src/scoring/api/test_authoring.py
- tests/test_authoring_sources.py
- tests/test_authoring_diagrams.py
- tests/run_runtime_browser_e2e.py
- docs/reports/j-ui-12b-fix3-analysis-access.md
