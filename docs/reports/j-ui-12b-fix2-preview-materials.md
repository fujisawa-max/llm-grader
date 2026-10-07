# J.UI.12b-fix2 — Authoring Preview/Edit Toggle & Material Management Polish

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Real deployment acceptance is pending.

## Current UI audit and root causes

Question NodeEditor already had a stable parent-owned exact text buffer, but always displayed its textarea and MarkdownMathPreview together. AuthoringCandidates always rendered the answer/Rubric editing controls. Its answer textarea had rows=8 but no authoring-specific full-width/font/minimum-height styling; Rubric fields defaulted to the browser's small textarea. The older model-answer-editor sizing class was not applied to these source-backed authoring candidates. This explains the small answer editor and inconsistent preview behavior.

Native Question buffers live in the authoring page, keyed by stable node key. Answer/Rubric data and operation history live in the working snapshot above optional panels. NodeEditor has a stable Question key; candidate/criterion IDs supply stable identity. Ordinary input does not reconcile the Question source map. Reconciliation remains at explicit Save/structural operations.

Upload and explicit native analysis were already available in a collapsed 試験資料 section inside authoring. They required no legacy route, but there was no nearby entry button/list/SHA display, and replacement was described as ordinary addition. The existing Back link already pointed explicitly to /tests/{testId}; it is preserved and tested.

## Preview/edit architecture and buffer lifecycle

A small AuthoringPreviewEditor controls presentation only. Default mode is preview. 編集する reveals the existing editor; プレビューを見る renders current unsaved text using the existing MarkdownMathText/KaTeX renderer. The edit subtree stays mounted and uses hidden/display:none while preview is shown. No content-dependent key, normalization, source reconciliation, Save or model call is introduced by switching modes.

The wrapper remembers the last focused textarea and focuses the retained DOM when editing resumes. It does not setSelectionRange or rewrite the textarea. Native caret/selection and editing history therefore remain with the DOM. The mode is held per domain in the page, independently for Question, Answer and Rubric, and persists across Question/checkbox switches within the page. Reload defaults to preview. Optional checkbox panels can unmount; their text/criteria/operation histories remain in the parent snapshot/buffers. Native Undo across such an unmount is not promised; mode switching itself retains the editor DOM/history.

Question preview uses the current exact buffer and accepted diagram previews. Edit mode retains NodeEditor hierarchy/points/source/formula/figure controls, split proposals, OCR and diagram review. An optional NodeEditor flag suppresses its simultaneous inline preview only in authoring; legacy editors keep their existing behavior.

Answer candidates render current text, alternatives and accepted diagrams in preview. Edit mode retains disposition, primary/alternative assignment, text, OCR, manual alternatives, classification and the shared diagram discovery/crop/trust/reuse controls. Diagram-only previews show 本文なし plus the accepted diagram, without fabricating answer text. Basic formal fallback answers use the same toggle.

Rubric preview renders individual criteria and points with Markdown/KaTeX. Edit mode retains insertion, duplicate, ordering, merge, manual/assisted split, consolidation, points, Undo and LaTeX. Proposals and operation history are preserved when preview is selected. The Rubric remains a criterion editor, not one combined textarea.

Authoring textareas use full pane width, inherited font, line-height 1.6, vertical resize and a minimum 240px height. Existing Question rows=14 and answer rows=8 remain. Text previews and controls no longer compete in the same displayed editor area.

## Materials, replacement and source safety

資料を追加, 差し替え and 資料一覧 are next to the source dropdown. They open the existing authoring materials panel in the right body so the left PDF remains tall and vertically stacked. The panel exposes material roles/names, source SHA/status, the existing upload control and explicit Question/Answer-Rubric analysis actions. Upload adds the file to the dropdown while preserving selection, section modes and unsaved editor state. It performs source registration only, with no automatic analysis.

Replacement is distinct: it selects a specific old material, keeps its role, warns/asks confirmation before upload, preserves the immutable old material and stores replaces_material_id on the new working-copy material reference. The relationship is saved with the whole-copy draft; upload itself does not save the authoring revision. Old files remain available and are marked 差し替え済み. Same-content replacement is rejected. Reload chooses an active material rather than a superseded one.

Server validation checks both references belong to this Test, their persisted SHA/role, matching roles, changed content, existing predecessor, self-reference and cycles. No migration, material overwrite or new parallel upload engine was introduced.

A Question bound to the replaced Question-source SHA, or an Answer domain bound to the replaced material ID, is reported as authoring_material_replaced after Save/reload. Old source evidence and decisions remain intact but require explicit source rebinding/reanalysis. Source-backed tool endpoints reject operations against the superseded binding with 409. Local stale detection warns immediately, suppresses accepted previews and disables stale OCR/diagram use. Ordinary text editing and preservation of the old draft remain possible. The existing explicit analysis/import pipeline is used to bind a newly analyzed source; no automatic inference or silent provenance rewrite occurs.

Material selection is independent of the right Question and visible-section/mode states. Existing source-matching highlight logic remains; another material is not given a foreign overlay. Left layout remains dropdown/actions, existing PDF toolbar and viewport, with desktop sticky sizing and narrow fallback unchanged.

## Navigation and semantics

Back is always a normal link to the same Test's detail page, independent of browser history or legacy entry route. Legacy upload/review URLs remain available. Preview toggles, checkbox changes, material selection, upload-only actions and Back do not save, publish or run inference. Explicit authoring Save still writes one draft working copy and never updates formal Questions, ModelAnswers or approved Rubrics. J.UI.12c publication, grading snapshot/submission binding and student workflows remain outside this phase.

## Automated validation

Production-like browsers use production Next builds, non-loopback HTTP, real FastAPI, disposable SQLite and actual RuntimeManager with managed stubs. No production data or models were modified.

| Check | Result |
|---|---|
| Focused backend authoring/source/diagram | 43 passed |
| Combined backend authoring/diagrams/trust/scopes/reuse | 179 passed, includes focused tests |
| Full normal browser regression | 45 passed |
| Truncated Ricoh/reuse and source OCR browser regression | 5 passed, including current KaTeX/accepted-diagram preview assertions |
| Final entry/preview/material/source/foundation browser check | 4 passed; overlaps normal suite; includes replacement cancellation/retry |
| TypeScript | passed |
| ESLint | 0 errors, 19 existing warnings |
| Ruff, changed Python files | passed |
| Production Next build | passed |
| git diff --check | passed |
| Grading jobs | 0 in all successful production-like harnesses |

The new browser test verifies all three default previews, independent modes, textarea height, exact multiline editing, newline Delete/Enter caret positions, native Undo/Redo, Japanese CDP composition/commit, multiline selection replacement, retained DOM/caret across preview/edit and Undo/Redo after returning to edit. It verifies current unsaved previews, unchanged server revision and model-call counts, Rubric duplicate/merge/point preview/Undo, checkbox preservation, upload, explicit replacement confirmation, replacement cancellation/retry, saved replacement reference, reload previews and Back destination. Strengthened OCR cases render the applied local LaTeX in KaTeX previews; the reuse case checks the accepted diagram preview has actual image pixels and no model-call increase.

Native browser Undo grouping is preserved; Chromium groups the tested keyboard input by individual character. CDP composition exercises the browser composition path but cannot certify real OS conversion-candidate interaction. Real Japanese IME acceptance remains part of deployment validation.

Existing authoring editing regressions now explicitly enter edit mode through a shared test helper. Production entry/layout, source-backed split/advanced Rubric, issue navigation, formal isolation, legacy caret/IME/paste/Undo, OCR, diagrams, continuation and archive scenarios pass the full suite. Backend tests cover replacement reference validation, saved roundtrip, source-rebinding diagnostics and rejecting stale Question/Answer diagram operations without mutating native reviews or formal data.

Initial new-test failures were expectations rather than product failures: native Undo removed one character, existing duplicate-criterion merging retained 5 points, and a generic alert locator also matched Next's route announcer. Expectations/locator scope were corrected; the final normal suite passed.

## Production acceptance and remaining issues

No deployment or real Q5 editing was performed. Real validation still needs current local previews, sufficiently large editing areas, Japanese OS IME, OCR/diagram/Rubric controls, material addition/replacement and Back -> Test detail. Existing formal/Q5 grades/content remain untouched. No known implementation or automated regression defect remains. There are 50 distinct passing browser cases (45 normal plus 5 additional critical cases); focused reruns overlap these totals. Deployment validation is the remaining gate.

## Required checklist

- [x] Default preview, edit/preview buttons, independent domain modes
- [x] Current local buffer and dirty state preserved without Save/inference
- [x] Large full-width textarea and retained editor DOM/caret/history across mode switches
- [x] Question preview/edit, caret/IME, split and math OCR
- [x] Answer preview/edit, OCR, diagram-only, diagrams and confirmed reuse
- [x] Rendered Rubric criteria/points, advanced merge/split/Undo and LaTeX
- [x] Material add, roles, dropdown and PDF
- [x] Explicit replacement, old source reference, stale warning and explicit reanalysis
- [x] Replacement cancellation/retry
- [x] Back -> Test detail; legacy routes retained
- [x] Backend, production-like browsers, TypeScript, ESLint, Ruff, build and diff-check
- [x] Grading jobs zero; formal data unchanged
- [ ] Real deployed visual/edit/material/OS IME acceptance

## Git status and files

Changes remain unstaged/uncommitted. No commit or push was made. Service files changed:

- frontend/app/globals.css
- frontend/app/tests/[testId]/authoring/page.tsx
- frontend/components/reviews/AuthoringCandidates.tsx
- frontend/components/reviews/AuthoringPreviewEditor.tsx
- frontend/components/reviews/NodeEditor.tsx
- frontend/lib/api/testAuthoring.ts
- frontend/e2e/authoringEditMode.ts
- frontend/e2e/authoring-preview-materials-real.spec.ts
- frontend/e2e/authoring-diagram-reuse-real.spec.ts
- frontend/e2e/authoring-entry-layout-real.spec.ts
- frontend/e2e/authoring-math-real.spec.ts
- frontend/e2e/authoring-source-backed-real.spec.ts
- frontend/e2e/test-authoring-foundation-real.spec.ts
- src/scoring/api/test_authoring.py
- src/scoring/test_authoring.py
- tests/run_runtime_browser_e2e.py
- tests/test_test_authoring.py
- tests/test_authoring_sources.py
- tests/test_authoring_diagrams.py
- docs/reports/j-ui-12b-fix2-preview-materials.md
