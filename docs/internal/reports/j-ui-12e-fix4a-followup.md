# J.UI.12e-fix4a production follow-up

## Result

The operator correctly identified a gap in the first follow-up: it tested only
the unsaved working-state transition and then closed the page without saving. It
did not verify that the button stayed hidden after Save and returning to the Test.
The saved revision had no text receipt, so reopening it could show the button.

The local fix now persists a receipt for a meaningful saved teacher text buffer
even when that text cannot be projected into the old PDF-anchored
`ordered_content`. The frontend also uses the saved buffer as its post-Save
comparison baseline. The independent source-mapping warning remains. Local tests
pass; production Save/reload acceptance remains required. No production data was
saved or otherwise changed, and no commit or push was made.

## Production reproduction and observed state

Inspected the existing `Repro - review` Test (`a7bc4d5a-014d-4067-a2ac-6672c3de28f6`)
and selected Question `問題3 > (3)` (`teacher-4f66e5ce-d00d-4415-ab26-79af448880ff`).
The saved draft was at edit version 19. Its Question had two associated formula
regions and no persisted `teacher_correction.text_review` receipt.
Its current saved buffer, `body_text`, and source-projected text were equal.
Because the production browser edit was not saved, this read-only observation
does not establish whether the operator's separate saved edit had an
anchor/buffer mismatch.

The browser interaction was limited to loading and reading the Test, then entering
an unsaved text edit in the page. Save, confirm, analysis, and other mutation
requests were blocked. The saved revision remained at edit version 19 and had no
`text_review` receipt. Therefore after leaving/reopening that saved revision, the
confirmation button is expected to return. This was not evidence that post-Save
behavior worked; the earlier follow-up report overstated its conclusion.

| State | `manualQuestionText` / input | `meaningfulTextEdit` | `NodeEditor.textReviewed` | Confirmation button | Guidance |
| --- | --- | --- | --- | --- | --- |
| Before edit | No manual input for this edit | false | false | `問題文を確認` visible | The review toolbar showed `元資料との照合済み`; it did not show the reported “編集後は再確認が必要です” message in this loaded state. |
| Immediately after meaningful textarea edit | The Question-keyed working input matched the textarea value | true | true | No review-confirmation button | The review toolbar and its guidance disappeared. The unsaved-state indicator appeared. |
| After leaving/reopening without Save | Ephemeral manual state is gone; saved revision has no receipt | false | false | Button visible again | Expected because this session deliberately did not Save. |

The DOM-backed `NodeEditor` props after input were `textReviewed=true` and
`contentChanged=true`. The final confirmation-button count was zero. A subsequent
GET confirmed that the persisted edit version had not changed. Thus the requested
working-state transition succeeds on the current production runtime, although the
reported failure was not reproducible in this session.

## State transition and receipt precedence

The textarea `onChange` handler in the authoring page updates both `buffers[key]`
and `manualQuestionText[key]`. The latter records the latest direct teacher input
for that stable Question key. `questionTextReviewed` compares the edited content
against the saved Question text using the existing meaningful-text normalization;
when the latest manual input matches the current content and the change is
meaningful, it returns `true` for the unsaved working state.

That result is passed directly to `NodeEditor.textReviewed`. The final button
condition only renders a text-confirmation action when text is not reviewed, or a
separate formula review is still pending. For the observed meaningful edit,
`textReviewed` became true and no formula action remained pending, so the button
and text-review guidance were absent.

The defect was in the durable boundary. The server previously derived Question
receipt text only from source-projected `ordered_content`, and refused to issue a
receipt whenever `question_text_buffers[key]` differed from that projection. A
teacher's saved raw text can be authoritative for the editor while retaining the
last safe PDF anchors; in that case Save succeeded but no durable receipt was
created. Separately, the frontend reopened from `question_text_buffers` but used
`questionContent(savedNode).text` as its receipt comparison baseline. The
persisted editor value and comparison baseline could therefore disagree.

The fix derives before/after receipt text from the persisted Question buffer when
present (and requires it to agree with the saved `body_text`). It records a
server-owned receipt only for a meaningful change from the previous saved text.
The frontend now passes the same saved buffer as the reviewed-text baseline. On
successful Save, `synchronize(row)` clears `manualQuestionText`; the receipt is
then the durable state. This gives the intended lifecycle:

```text
meaningful textarea edit -> local manual-review state -> Save
    -> server text_review receipt -> reload remains reviewed
```

The source-mapping warning is still computed independently from the saved buffer
and source-projected content. This change does not approve formulas, figures,
diagrams, parser warnings, or source-mapping differences. A receipt suppresses
only the redundant text confirmation UI for the exact saved Question text.

## Independent review behavior

Formula review remains independent. The selected Question retained its formula
decision state, and the transition uses the existing `NodeEditor` formula-pending
check. No formula/source-warning state was acknowledged or modified. Source
warnings, figure/diagram review, scores, classification, and other review domains
remain outside the text receipt.

Reanalysis/load paths clear `manualQuestionText`. Fresh system-rebuilt content
therefore does not inherit unsaved manual-review state; a new text confirmation
is required unless an applicable saved receipt exists for that exact content.

## Validation

- Production browser: meaningful unsaved edit produced `textReviewed=true` and
  hid the confirmation action. Post-Save behavior was not tested in production;
  the operator correctly caught that gap.
- Backend focused tests: 24 passed across text-review and source-backed authoring,
  including an unmapped saved-buffer edit that receives a text receipt while
  retaining its independent source warning.
- Focused Playwright checks: 4 passed (working-state transitions, no-op/revert,
  scoped receipt, and saved-buffer baseline); 1 Sample Q5 integration test was
  skipped because local runtime-manager E2E environment variables are not set.
- TypeScript typecheck passed.
- ESLint passed with 0 errors and 19 existing warnings; Next production build
  passed with existing CSS/autoprefixer and lint warnings.
- `git diff --check` passed.
- No Save or production mutation was issued; no grading or model inference was
  launched.
- Product changes: server receipt now follows saved teacher text buffers; client
  post-Save comparison uses that same saved buffer. Formula/source review remains
  separate. The full disposable Sample Q5 Save/reload/reanalysis integration test
  was not rerun because its local harness variables are unavailable.

## Files and repository state

Changed files: `src/scoring/authoring_text_review.py`,
`frontend/lib/authoringTextReview.ts`,
`frontend/app/tests/[testId]/authoring/page.tsx`,
`tests/test_authoring_text_review.py`,
`frontend/e2e/authoring-working-text-review.spec.ts`, and this report.

Baseline HEAD: `236623fba68fbfdef8e48063c9b5625ddb4cf8e7`.

Production deployment and production Save/reload acceptance are still required.
Exact git status after the local fix:

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/e2e/authoring-working-text-review.spec.ts
 M frontend/lib/authoringTextReview.ts
 M src/scoring/authoring_text_review.py
 M tests/test_authoring_text_review.py
?? docs/internal/reports/j-ui-12e-fix4a-followup.md
```
