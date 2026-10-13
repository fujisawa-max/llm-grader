# J.UI.14 — Compact Question Editing UX

Status: READY_FOR_PRODUCTION_VALIDATION.

## Question interaction

Previously, Question body editing depended on the broad Preview/Edit switch, with textarea, normalization guidance and split controls in the main workspace. Unified Authoring now keeps the current authoritative `question_text_buffers` readable in a compact Question card, with a local `編集` action. Short content has no empty textarea height; the browser scenario measures its footprint against the four-row editing textarea. Required source/formula/figure review and parser warnings stay outside the dialog and remain actionable.

`NodeEditor` gains an opt-in compact presentation. Existing import/review screens retain their original editor. The existing score/label/hierarchy settings and inclusion controls remain accessible through `設問設定の変更`; Question `配点` remains distinct from Rubric `最高点`. Parent/child nodes use the same card, including structural parents with little or no own text. Source/PDF selectors, accepted diagrams and hierarchy are preserved.

## Dialog, split and LaTeX

- Shared `AuthoringDialog` supplies modal semantics, title association, textarea focus, Escape/Cancel and focus return. The textarea begins at four rows and remains resizable.
- Done applies the local dialog buffer to the existing authoring working buffer. Cancel discards dialog-only edits. Neither operation Saves. A failed Save retains working content through the existing lifecycle.
- `問題の操作` contains the optional split actions. `位置を指定して2分割` opens a position-selection dialog; both that dialog and the ordinary text-edit dialog offer `カーソルの位置で分割`.
- Both caret entry points reconcile the current unsaved text through the existing `editQuestionContent` / `splitQuestionAtCaret` / `reviewQuestionSplit` / `applyQuestionSplit` workflow. Unsafe source boundaries still fail closed. Source mapping, IDs, hierarchy, allocations, duplicate checks and operation history are unchanged. No backend/API change was required, and no automatic Save occurs. Cancelling a proposal retains text explicitly transferred to the working draft by the split action.
- Question LaTeX/source-math conversion is inside the text dialog. Results stay in the bounded dialog section, apply to its buffer and become working state on Done. Cancel leaves working/saved text unchanged. Existing source references, routing, conversion validation and math provenance are preserved, including a manual edit after applying conversion.
- Dialog invalidation uses working-revision/document identity and read-only state: reanalysis/revision replacement discards an obsolete dialog. An ordinary Save response alone does not discard an unfinished dialog.

## Review, navigation and immutable editions

Done uses the existing `manualQuestionText` and meaningful-edit logic; it creates no alternate review model. Meaningful manual text becomes locally reviewed immediately, while the server-owned `text_review` receipt persists only after successful Save. No-op, whitespace-only and edit-and-revert retain the review requirement. Reanalysis restores the source-confirmation requirement when it replaces teacher text. Formulas, figures, parser warnings and source mappings remain independent.

Text/source-text correction actions focus the card's Edit action, score issues focus the existing score input, and source/formula issues still expand/focus their exact review row. Browser coverage uses real saved text/source warnings and a disposable Sample Q5 fixture with an explicit pending formula decision; the formula issue is emitted by server readiness. No frontend issue suppression was added.

Final Review includes a read-only Question-text disclosure alongside the existing hierarchy, scores and issues. Confirmation/CAS/readiness rules remain unchanged. Browser coverage confirms a revision, edits/saves a revised Question draft, and proves the active original snapshot is unchanged and its history has no text edit controls. No historical snapshot normalization occurs.

## Validation

Established disposable harness: `python -m tests.run_runtime_browser_e2e`, temporary DB/artifacts, real FastAPI/RuntimeManager, fresh production Next build/server, managed synthetic model fixtures only.

- Final focused group: **22 passed / 0 skipped / 0 failed** (50.7s), including 16 browser scenarios and 6 semantic checks. Covers compact/Cancel/dirty state, both caret splits with unsaved buffers, hierarchy/Save/reload, manual review/no-op/whitespace/revert/formula independence, reanalysis, dialog-local LaTeX apply/cancel, exact text/score/source/formula targets, Sample Q5 source/diagram reuse, Final Review, immutable history and Rubric canonical/local-dialog regressions.
- Final full normal production-like Chromium suite: **74 passed / 0 skipped / 0 failed** (4.5m). Includes Sample Q5 confirmation/hash/diagram guarantees, revision history, source/manual mapping, overlay navigation, formula correction, Save/resume/endurance and stale/in-flight Save protection.
- Existing browser specs/helpers now explicitly open/complete Question dialogs. Native caret/IME/undo behavior is tested within the dialog; persistence, CAS, provenance and role-isolation assertions remain active.
- TypeScript: passed. ESLint: 0 errors, 19 existing warnings. Next production build: passed, existing lint/Autoprefixer warnings only. `git diff --check`: passed.
- Grading jobs: **0**, checked at the end of both completed harness runs. Real model inference: **0**; source/LaTeX/analysis regressions use managed synthetic stubs.

## Handoff and changed files

Local validation is complete; operator deployment and dedicated production acceptance remain. No production changes, backend/scoring changes or migrations were made. No commit/push. Earlier reports were left unchanged.

Product changes are limited to `NodeEditor.tsx`, the Unified Authoring page and scoped CSS. The browser helper, new compact-Question scenario and affected regression specs are listed exhaustively below.

## Exact git status

```text
 M frontend/app/globals.css
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/NodeEditor.tsx
 M frontend/e2e/authoring-analysis-access-real.spec.ts
 M frontend/e2e/authoring-endurance-real.spec.ts
 M frontend/e2e/authoring-entry-layout-real.spec.ts
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-manual-text-review.spec.ts
 M frontend/e2e/authoring-math-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-revision-history-real.spec.ts
 M frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts
 M frontend/e2e/authoring-save-resume-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M frontend/e2e/authoringEditMode.ts
 M frontend/e2e/rubric-interaction-polish-real.spec.ts
 M frontend/e2e/rubric-levels-canonical.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
?? docs/internal/reports/j-ui-14-compact-question-editing.md
?? frontend/e2e/compact-question-real.spec.ts
```
