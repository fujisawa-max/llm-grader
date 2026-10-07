# J.UI.12b-fix5 — Question View Separation & Preview Metadata Polish

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Implementation and automated validation complete; real deployed UX acceptance remains. No deployment performed.

## Audit and root cause

The main editor already used mutually exclusive branches for a selected Question and `selected === "all"`. The mixed content came from the Question body editor's WarningPanel: it received every warning in the source review document, without Question ownership filtering, and omitted its target-label callback. Consequently global warnings and other Questions' warnings appeared beneath the current Question with the default 試験全体 label. Even an empty warning array rendered a 確認事項 panel.

The manual 設問を追加 button was placed after both branches, at the bottom of the editor body. Its action was already safe and local; its location was the problem. Preview/body/settings were controlled by retained AuthoringPreviewEditor subtrees, the body editing flag and a separate settings flag. The settings return action reused the body wording プレビューを見る. Preview had existing Markdown/KaTeX and accepted diagrams, but lacked a metadata summary and body frame.

## View separation and warning ownership

Question view retains only warnings whose owner matches the selected stable node key, or uniquely matches its original source key. Region assignment supplies the owner when needed. Ambiguous source ownership after a split is not attributed to multiple children. An empty scoped warning list does not render a panel. Canonical Question paths replace the default global label.

All source warning decisions remain available in テスト全体確認, alongside existing test-wide readiness, issue navigation, metadata and ordering information. Ordinary Question/Answer/Rubric editors are absent from that branch. No backend warning state, source provenance or registration rule changes.

## Selector and manual addition

The sole 設問を追加 action now sits at the right of the sticky target-selector row, after section visibility controls. It remains present for both normal Questions and テスト全体確認. The original local working-copy action is reused: create a stable manual node, initialize its text buffer, select it and mark the copy dirty. It does not create formal Questions, save, publish or infer. Controls wrap on narrow screens; no bottom duplicate remains.

## Preview metadata, score semantics and frame

Preview actions precede a text summary: 大問 or 小問, the canonical hierarchy path, effective points and the semantic label 直接配点 / 小問合計 / 未設定. Historical each-child records retain an explicit legacy semantic label. Unset values use －点. The existing `effectiveQuestionScore` resolver supplies both preview and test-wide per-node scores, preserving complete child aggregation and existing protection against double-counting structural parents. No preview-specific aggregation is introduced. Values come from current local nodes, so settings changes are visible before Save.

The body renderer and accepted diagram preview share a subtle bordered, padded block. The existing Markdown/KaTeX and diagram rendering remain unchanged. Body return is プレビューを見る; settings return is プレビューに戻る.

## State, navigation and inference

Retained editor DOM, parent-owned exact text buffers, stable keys and mode flags remain unchanged. View switches do not save, reconstruct text or infer. Existing score issue navigation opens settings and focuses the number control; body/source issues open body editing, and Answer/Rubric issues enable their section. Material selection/add/edit/replace stays in the left source pane and is unchanged.

No publication, source analysis, runtime configuration, grading logic or production Q5/grade mutation is added. Explicit existing OCR, diagram discovery and assisted editing actions retain their prior inference policy.

## Validation

Final validation passed. The harness uses production Next, real FastAPI, disposable SQLite and RuntimeManager-managed model stubs over non-loopback HTTP. Browser coverage adds direct 30, child-sum 40 and unset metadata, canonical child labels, KaTeX within the frame, isolated all-Test view, top-only manual addition from both contexts, responsive placement, zero inference and no formal Questions. Existing editor coverage verifies immediate local point changes, exact settings/body wording, local preview, native Undo/Redo, CDP IME, retained textarea identity, Save/reload, materials, source-backed diagrams and advanced Rubric.

An initial added test used an exact 配点 label despite the existing required indicator being part of its accessible label. The locator was corrected to the number input within the Question editor; no application change was needed for that test failure.

| Check | Result |
| --- | --- |
| Backend targeted/regression | 355 passed |
| Final normal production-like Playwright suite | 47 passed (34 browser scenarios + 13 error-mapping helpers) |
| Final critical truncated-Ricoh Playwright suite | 27 passed (9 browser scenarios + 18 split helpers) |
| Distinct browser scenarios | 39 passed; 4 scenarios overlap the two suites |
| Distinct frontend helpers | 31 passed |
| TypeScript | passed |
| ESLint | 0 errors, 19 existing warnings |
| Ruff, relevant authoring backend/test files | passed; no Python files changed |
| Production Next build | passed; existing CSS autoprefixer warnings retained |
| git diff --check | passed |
| Grading jobs | 0 |

Final normal rerun includes the new metadata test. Final critical rerun includes the final warning-owner resolver and corrected settings locator; all 27 passed. No known implementation/test defect remains.

## Required checklist

- [x] Normal Question excludes whole-Test list; all-Test branch excludes domain editors/preview metadata
- [x] Question warnings scoped by stable/current source ownership, no empty generic panel
- [x] Sole top selector-row Add, local-only action from normal/all views, controlled narrow wrap
- [x] Preview controls above canonical 大問/小問 metadata and framed body
- [x] Direct, child-sum and unset points from existing domain resolver; current local settings reflected
- [x] Settings return プレビューに戻る; body return プレビューを見る
- [x] Existing score/body/Answer/Rubric issue navigation preserved
- [x] Exact local text, dirty state, retained DOM/caret/IME/Undo, no mode-switch Save
- [x] Question/Answer OCR, diagrams/trust/reuse, split provenance, advanced Rubric regressions
- [x] Source materials/add/edit/replace, Home/Test access, archive, compatibility routes regressions
- [x] Backend, production-like browser, TypeScript, ESLint, Ruff, production build and diff checks
- [x] Zero added inference on selection/modes/points/manual addition and zero grading jobs
- [x] DnD ordering explicitly deferred
- [ ] Real deployed acceptance

## Production acceptance and deferred work

No real deployment verification was performed. Required acceptance remains: normal Question excludes global confirmations; all-Test view contains them; top Add works; direct/child-sum/unset metadata and local settings changes display correctly; body frame renders math/diagrams; narrow wrap is safe; source/material and editing workflows remain intact.

Question drag-and-drop ordering: **deferred to future phase**. No sortable list, drag handle or DnD dependency added. J.UI.12c final publication remains explicitly out of scope.

## Files and Git

Service files changed:

- frontend/app/tests/[testId]/authoring/page.tsx
- frontend/app/globals.css
- frontend/e2e/authoring-preview-materials-real.spec.ts
- frontend/e2e/authoring-source-backed-real.spec.ts
- docs/reports/j-ui-12b-fix5-question-view-preview.md

Changes are unstaged and uncommitted. No commit or push made. No backend/schema migration or production data change.
