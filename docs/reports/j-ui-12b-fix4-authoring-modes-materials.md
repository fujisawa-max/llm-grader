# J.UI.12b-fix4 — Simplified Authoring Modes & Compact Material Selector

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Deployed acceptance is pending.

## Audit and before/after

The initial authoring GET returned either a revision or a formal projection. The page treated absence of a revision as read-only and required 編集用の下書きを作成 before editing. It now calls the existing authorized revision endpoint only if no revision exists, and initializes the working state from that response. Existing drafts resume directly. Existing confirmed revisions remain read-only and explicitly offer 修正版を作成; they are never silently revised.

NodeEditor previously placed Question text, source/math/figure controls, label, inclusion, hierarchy, ordering and points in the same fieldset. The authoring textareas had a 240px minimum; Question also inherited a more-specific legacy rule that imposed the same height. The source row had a visible 利用資料 label and 一覧 button, and materials management rendered in the right editor body. These explain the reported mode and space problems.

After this change, teachers enter an editable workspace directly, Question body and settings are separate presentation modes, initial Question/Answer textareas are compact, and material selection/addition/editing stays entirely in the left source pane.

## Automatic draft start and safety

Initialization uses the existing Course/Test authorization and source-backed/formal baseline adapters. It creates no analysis, OCR, diagram inference or publication. The existing create_draft returns the active draft on repeated calls and locks the Test row on PostgreSQL. For SQLite, which lacks SELECT FOR UPDATE, the existing unique Test/revision key handles concurrent creation; the endpoint rolls back the losing insert and returns the already-created active revision. A concurrent two-request backend test verifies one active draft and identical returned IDs. Reload resumes that ID.

Normal first-open UI has no draft-creation button. Confirmed content retains its explicit revision action. The introductory copy describes editing and preserved formal content rather than asking teachers to manage draft mechanics.

## Question modes and buffers

Question preview offers 本文編集 and 設問設定の変更. Body mode shows the existing exact-buffer textarea, math conversion/OCR, text/formula confirmation, figure/diagram review and relevant source controls. It hides label/inclusion, hierarchy, ordering, points and split controls.

Settings mode reveals the existing label/inclusion, hierarchy/reparent, ordering and score controls plus native/manual/AI split proposals. It hides the body textarea and OCR/diagram controls. Switching back to body or preview retains local text, dirty state, caret and split proposal state. Structural operations still use the existing source reconciliation/ownership/split services; no domain engine is duplicated.

NodeEditor has an optional presentation-only editorMode; legacy reviews default to all and retain their original behavior. Hidden subtrees remain mounted. AuthoringPreviewEditor similarly supports the auxiliary settings display without destroying its body DOM. Existing parent-owned per-node buffers and stable node keys remain authoritative. Text input, preview/body/settings switching, checkbox toggles and material modes do not save or reconstruct text. Existing text changes may invalidate a split proposal as before; merely switching modes does not.

The body/settings mode is held at Question-section level and persists across Question selection within the page. Reload starts in preview. When a panel is unchecked its data remains in the parent state; native Undo across an actual checkbox unmount is not promised. Preview/body/settings switching preserves the mounted editor DOM/history.

Test-wide score issues now carry a small optional field marker. Their navigation selects the Question, opens settings and focuses its numeric score control. Text/math/source issues open body mode and choose a visible control. This avoids trying to focus a hidden textarea after separating modes.

## Answer, Rubric and sizing

Answer preview uses 本文編集; editing retains the existing candidate text, math OCR, diagram-only/trust/fallback/reuse and alternative/manual controls. Authoring answer rows change from 8 to 4, and Question body uses 4 rows instead of legacy 14. Their full-width minimum is 132px with inherited font, line-height 1.6 and vertical resize. A scoped override defeats the legacy Question 240px rule only inside authoring; legacy reviews are unaffected.

Rubric retains rendered preview and its advanced editor: criteria, points, insertion, duplicate, merge/split, consolidation, Undo and LaTeX. No advanced domain state is replaced by a basic textarea.

## Compact source controls and material modes

The visible standalone 利用資料 label and 一覧 button are removed. The compact row has one growing dropdown and, only for a selected PDF, short 解析/再解析 and 差換え actions. The accessible dropdown label remains. The first option is 資料を選択・追加・編集; optgroups separate actual materials from 資料の追加 and 資料の編集.

Special values action:add/action:manage affect only sourceMode; they are never stored in materialId or passed to PDF, mapping, highlight or analysis APIs. The last real material ID stays available for cancel/return. Actions are hidden in management/add modes. Desktop uses one row, with safe narrow wrapping. The existing vertical PDF toolbar/body layout, tall sticky source pane and responsive shared workspace are preserved.

Selecting 資料の追加 replaces the PDF area with role/file upload and PDFに戻る. Selecting 資料の編集 replaces it with role/name/SHA/active/replaced/current status and selection/replacement actions. The right pane contains only domain editing and Test-wide review. Upload success selects the new material and restores PDF; choosing a listed material or PDFに戻る also restores it. Current Question, checkboxes, domain modes and unsaved buffers are not changed.

Selected-material 差換え and management-list replacement call the same existing flow. It preserves the old source reference, records the new SHA/replacement link, warns about stale decisions and never starts analysis automatically. Explicit role-aware analysis/reanalysis from fix3, prior-copy preservation and source integrity checks remain unchanged. No new analysis or crop engine is introduced.

## Validation

Backend regression: 355 passed, including concurrent start/resume and existing authorization, formal isolation, diagrams/trust/reuse, stale validation, Question ownership/OCR, ModelAnswer, Rubric, LaTeX and RuntimeManager cases. The 26-case authoring foundation suite was rerun after the issue-field adjustment and passed.

Updated browser scenarios test automatic first open/reload/no inference; default previews; body/settings visibility; current text across settings; retained DOM, caret, Japanese CDP composition, paste and native Undo/Redo across preview/edit; initial height between 120 and 200px; left-only material management and PDF restoration; right Answer edit mode/unsaved text/Question preservation; replacement cancellation and acceptance; explicit role-aware analysis; compact desktop/narrow layout; universal Test entry and Back.

The integrated math scenario additionally exercises numbered source-backed Question split after OCR from settings, creates two children, returns to body and saves without formal Question creation. This exposed an existing helper defect: multiline display LaTeX was treated as separate prose lines and its formula origin was matched only as single-dollar inline math. The shared split helper now preserves blocks without numbered boundaries, groups continuation lines until the next marker, and uses the existing math parser to match the uniquely reviewed inline/display formula with its actual delimiters and whitespace. Native source IDs and atomic formula anchors remain intact; ambiguous matches still fail closed. A dedicated helper regression covers one retained multiline formula anchor. Server source-anchor and ownership validation are unchanged. Existing diagram/OCR/Rubric controls and legacy routes are covered by the production-like regressions.

The browser harness uses production Next, non-loopback HTTP, real FastAPI, disposable SQLite and actual RuntimeManager-managed model stubs. No production database/Q5 content or grades are edited. J.UI.12c publication remains out of scope.

Initial validation found the more-specific legacy textarea rule and old completion tests expecting zero revision creation when entering authoring. The CSS was corrected; completion tests now allow exactly one initial authoring revision and still reject native reanalysis/review duplication. An early build preceded upload/PDF-return changes and was superseded by the final rerun.

| Check | Result |
| --- | --- |
| Backend regression | 355 passed |
| Normal production-like browser suite | 46 passed |
| Distinct browser scenarios | 51 passed |
| Critical production-like browsers | 7 passed (2 overlap normal suite) |
| Frontend split helper tests | 18 passed |
| TypeScript | passed |
| ESLint | 0 errors, 19 existing warnings |
| Ruff, changed Python files | passed |
| Production Next build | passed |
| git diff --check | passed |
| Grading jobs | 0 |

## Production acceptance

No known implementation or automated regression defect remains. No deployment was performed. Real acceptance still needs auto-start from any Test, compact body/settings controls, real OS IME behavior, smaller editors, left dropdown add/edit and PDF restoration, unsaved-state preservation, explicit-only analysis and existing OCR/diagram/Rubric workflows. No inference is added to initialization or view/material switching; explicit OCR/diagram/LLM actions retain their existing behavior.

## Required checklist

- [x] Automatic draft create/resume, single active draft, no creation button or inference
- [x] Question preview/body/settings; structural controls and body/OCR/diagrams separated
- [x] Exact buffer, dirty state, retained DOM/caret/IME/native Undo/Redo; no mode-switch Save
- [x] Source-backed split after OCR with two children and retained formula provenance
- [x] Compact Question/Answer textareas; Answer body edit/OCR/diagrams/reuse
- [x] Rubric preview/advanced editor preserved
- [x] Visible 利用資料 label and 一覧 removed; placeholder/materials/special actions dropdown
- [x] Add/edit replace left PDF area, right editors unchanged, PDF restored
- [x] Explicit-only analysis/reanalysis and existing replacement/stale checks
- [x] Test-wide review, score/body issue navigation, Home/Test entry, Back and legacy routes
- [x] Backend/helper/critical browser checks and static checks
- [x] Final normal browser rerun
- [x] Grading jobs zero, formal/Q5 data untouched
- [ ] Real deployed UX/OS IME acceptance

## Files and Git

Changes are unstaged and uncommitted; no commit or push was made. Service files:

- frontend/app/globals.css
- frontend/app/tests/[testId]/authoring/page.tsx
- frontend/components/reviews/AuthoringCandidates.tsx
- frontend/components/reviews/AuthoringPreviewEditor.tsx
- frontend/components/reviews/NodeEditor.tsx
- frontend/lib/api/testAuthoring.ts
- frontend/lib/questionSplit.ts
- frontend/e2e/authoring-analysis-access-real.spec.ts
- frontend/e2e/authoring-diagram-reuse-real.spec.ts
- frontend/e2e/authoring-entry-layout-real.spec.ts
- frontend/e2e/authoring-math-real.spec.ts
- frontend/e2e/authoring-preview-materials-real.spec.ts
- frontend/e2e/authoring-source-backed-real.spec.ts
- frontend/e2e/authoringEditMode.ts
- frontend/e2e/question-completion-real.spec.ts
- frontend/e2e/question-split.spec.ts
- frontend/e2e/test-authoring-foundation-real.spec.ts
- src/scoring/api/test_authoring.py
- src/scoring/test_authoring.py
- tests/test_test_authoring.py
- docs/reports/j-ui-12b-fix4-authoring-modes-materials.md
