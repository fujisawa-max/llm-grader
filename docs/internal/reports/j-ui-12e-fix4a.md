# J.UI.12e-fix4a — Hide Redundant Source-Confirmation UI After Manual Edit

## Result

**READY_FOR_PRODUCTION_VALIDATION** (2026-10-13). Local implementation and
validation complete. No production access/deployment, commit or push.
Baseline HEAD: `a12aede`; initial working tree clean. Parent reports are unchanged.

## Old contradictory behavior

`NodeEditor` always rendered `問題文を確認` for Questions with formula regions.
Its guidance depended on raw `contentChanged` and formula confirmation, without
recognizing fix4's scoped text review. A deliberate prose edit therefore continued
to show `元資料と問題文を照合してください。編集後は再確認が必要です。`, including
before Save; the generic button also remained after the server text receipt existed.

The existing button bulk-confirms **formulas** too. Removing all formula review along
with the redundant text UI would incorrectly approve separate mathematical content.

## Working-state transition

- Web authoring tracks each Question's latest explicit textarea input in an ephemeral
  `manualQuestionText` map keyed by its exact stable key.
- A current manual input with a meaningful difference from the saved authoritative
  text reviews that specific text immediately. The comparison uses fix4's Python
  whitespace semantics; focus, identical input, whitespace-only normalization and
  edit/revert do not produce new review.
- JSX derives the UI from working state; no DOM/CSS hiding and no client-side
  persisted `teacher_correction` or receipt is manufactured.
- For reviewed text, the generic button and contradictory text guidance disappear.
  If formulas remain unreviewed, the existing explicit operation remains as
  `数式を確認`, with formula-specific guidance. It does not become text confirmation.
- Formula state is checked on a detached reconciliation of the current buffer, so a
  newly changed formula still requires its own review before Save.
- Parser warnings, figures, diagrams, scores, classification, grouping and executable
  rubric requirements are untouched. The source-warning row remains visible.

## Save success/failure and lifecycle

Successful Save clears the ephemeral input map and uses the existing server-supplied
`teacher_correction.text_review` (`teacher_confirmed=true`, `manual_edit`) for the
corresponding saved text. Reload uses that same server state. Unsaved edits continue
to block final confirmation.

On Save failure, text and local review remain in working state; persisted revision
and receipt remain unchanged. A browser failure injection verifies both this and
that the outgoing Save payload contains no fabricated receipt.

An edit during an in-flight Save retains its unsaved input state through the existing
Save epoch handling; it is evaluated against the resulting saved revision.

Source/reanalysis/revision loads clear ephemeral input state. Split operations clear
only the affected Question/children, preserving unrelated unsaved inputs. Tool output
is not recorded as direct textarea input.

Actual Question reanalysis uses existing `merge_question_analysis`: fresh source
nodes replace the working nodes and raw text buffers are removed. Those fresh nodes
have no old manual-text receipt. The browser test performs native Sample Q5
reanalysis, proves the previous teacher-added text is replaced, and verifies the
confirmation button/guidance returns. Imports that preserve the same teacher-authored
Question content and its existing server provenance may retain durable review;
refreshing another domain does not revoke that Question's valid text review.

## Answer and Rubric coverage

Current Answer/Rubric editors have no separate generic **text** confirmation UI to
remove. Their explicit controls confirm Answer classification and Rubric grouping/
points; those must remain. The existing correction UX regressions verify text Save
receipts while preserving automatic evidence, classification, grouping, points and
levels. No classifier/grouping control was hidden or automatically approved.

## Validation

| Check | Final result |
| --- | --- |
| Focused fix4/fix4a, correction UX, source-review browser tests | 14 passed |
| Full normal production-like Chromium | 74 passed |
| TypeScript | PASS |
| ESLint | PASS; 0 errors, 19 existing warnings |
| Next production build | PASS (browser harness builds) |
| `git diff --check` | PASS |
| Grading jobs launched | 0 |
| Real inference | 0 |
| New scenario OCR/classifier/grader log call deltas | 0 |

The first focused run reached the reanalysis step but used the initial-analysis
modal label in the test. The test was corrected to the existing 再解析 label/action;
no product logic or assertion was weakened. Final runs pass.

Focused coverage includes:
- Meaningful session input, focus/no-op/whitespace and revert negatives.
- Saved scoped receipt, automatic replacement, and rejection of an unrelated generic
  teacher-confirmed flag as text review.
- Real Sample Q5: immediate hide **without Save**, independent pending formula review,
  other Question's geometry warning remains visible, failed Save keeps local text,
  successful Save persists receipt, reload stays reviewed, changed formula reopens
  formula review, actual native reanalysis restores text confirmation.
- No new model/grading request; runtime log deltas cover OCR, math OCR, rubric
  classifier and grader during the scenario.
- Existing fix4, correction UX and source-warning navigation regressions.

Backend/model/schema/migrations and fix4 receipt generation are unchanged, so backend
suites and Ruff are not rerun. The normal browser suite exercises the existing API
and immutable confirmation/revision/source/diagram paths with managed test stubs.
No real inference or grading is launched; no new phase begins.

## Handoff and exact git status

Operator frontend deployment and isolated production acceptance remain. No migration
or backend behavior change is required. Recheck 問題3(3) before Save, failed/successful
Save, reload, changed formulas and source reanalysis on dedicated records only.

Files changed:
- `frontend/app/tests/[testId]/authoring/page.tsx`: ephemeral manual input state and
  clear/reset paths for Save, source loads, analysis, split and revision navigation.
- `frontend/components/reviews/NodeEditor.tsx`: state-derived text/formula review UI.
- `frontend/lib/authoringTextReview.ts`: meaningful comparison and scoped receipt use.
- `frontend/e2e/authoring-working-text-review.spec.ts`: focused state/lifecycle E2E.
- This standalone report. No backend, migration, dependency or runtime config changes.

Exact final `git status --short`:

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/NodeEditor.tsx
?? docs/internal/reports/j-ui-12e-fix4a.md
?? frontend/e2e/authoring-working-text-review.spec.ts
?? frontend/lib/authoringTextReview.ts
```
