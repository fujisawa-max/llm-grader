# J.UI.12e-fix2 — Actionable Question Source-Review Issues

## Result

**READY_FOR_PRODUCTION_VALIDATION**. Local implementation and required automated validation passed. Operator deployment and isolated production acceptance are the remaining step; no production access was performed. J.UI.12e, J.UI.12e-fix1 and J.UI.12d remain COMPLETE; none has been reopened.

## Baseline / root cause

- HEAD: `5a0748257cc64a9e9aa6a701539607f8a4997983`.
- Initial status: only the untracked previous `authoring-save-blocker-diagnosis.md`; preserved unchanged.
- `test_authoring.preflight()` generated `元資料の確認事項を確認してください。` for each blocking warning with an unreviewed state, but discarded warning ID, code/type, source item/scope, material/review identity. It emitted a Question issue without a concrete code/field target.
- `authoring_issue_guidance.issue_guidance()` consequently used the generic Question action and generic expected-state text. Frontend `navigate()` selected the Question but only targeted `authoring-question`, making the body editor appear to be the correction target.
- A second demonstrated defect is false ownership: the old predicate compared `n.get("source_draft_stable_key") == warning.get("owner")` without excluding null. A Test-wide warning with `owner=None` matched a split teacher child with `source_draft_stable_key=None`. Two Test-wide warnings could therefore be attached to the same Accuracy child even though its body was correct and its local warning panel did not contain those warnings. The new exact owner resolver uses the document/region identity; a Test-wide `document` warning remains `question_key=None`.
- This class is **unacknowledged source-warning review**, governed by `domains.question.document.warnings[]` and `domains.question.snapshot.warning_states[warning_id]`. It is not a demand to rewrite the body. Formula/figure confirmation and raw-body/source differences are separate requirements and are now identified separately.

### Two similar-looking cards

A controlled `q2.2` parent → `accuracy` teacher-child fixture reproduces both old owners as `accuracy`; corrected readiness keeps both Test-wide warnings unassigned to any Question. This proves the null-owner misattribution mechanism in addition to missing guidance.

The supplied production screenshot/workflow did not include the saved snapshot or warning IDs. No production connection was made, so the two exact Accuracy-item IDs cannot be reported as independently verified. The previous code could render every distinct warning as an indistinguishable card.

Actual unchanged Sample Q5, locally imported through native extraction, contains:

- `draft:document:ambiguous_geometric_order`: Test-wide ordering review.
- `draft:document:unresolved_vector_evidence`: Test-wide vector-figure reading review.
- `node:q2:ambiguous_geometric_order`: Question 2 ordering review.

These are distinct catalog identities and acknowledgment states; they must not be collapsed solely because their codes or wording overlap. A controlled Accuracy body fixture also proves two different source warnings remain distinguishable. Repeated representations of the **same warning ID** are deduplicated; no global code/message-based suppression was introduced. Formula review and source-warning acknowledgment remain independent even if both concern a formula.

## Structured issue metadata / actions

Server readiness retains `domain=question`, `correction_type`, `warning_id`, `warning_code`, source item/scope, source-review index/label, review ID, source SHA, material ID and region ID when available. Material resolution uses the exact Question-role binding and SHA already present in the saved snapshot; ambiguous binding resolution fails closed instead of choosing another PDF. Owner resolution mirrors the editor's exact source-owner lookup, without Question-label/prefix matching or automatically propagating children onto parents.

Actions are derived server-side from structured semantics:

- Question body: `本文を修正`.
- Score: `配点を修正`.
- Source warning / formula / figure review: `出典確認へ`.
- Genuine raw text/source difference: `本文と出典を確認`, explicitly explaining that merely acknowledging a warning cannot repair the difference.

Warning guidance identifies the actual reading/ordering/score/figure condition and says to compare against the PDF, choose `確認済み` if correct or correct it and choose `対応済み`. Codes remain internal metadata/technical details, not primary teacher text. Distinct item indexes also distinguish equally named review categories.

This phase does not create Save/Confirm/Warning severity classification, rewrite score aggregation or add a new issue state.

## Exact navigation / resolution

- Per-Question action selects the exact Question and opens its existing source-review row; Test-wide source warning navigates to the all-Test view.
- If the saved binding is resolved, the left PDF viewer selects that Question source explicitly.
- Warning target is existing `reviewWarningId(warning_id)`; region targets use `reviewFieldId(question_key, source/figure:region_id)`. Existing collapsed details are expanded for region evidence.
- Existing content-first scrolling clears sticky controls, focuses the actual confirmation select/control and transiently highlights the review row. It no longer scrolls only to the Question body.
- Per-Question warning panel is outside the hidden body-editor content, so source acknowledgment does not require entering a body-edit mode.
- `確認済みにする` is opt-in for authoring warning panels only (legacy panels retain their existing controls) and invokes the existing warning-state transition (`acknowledged`) and preserves teacher notes. Existing state select and correction controls remain available. No automatic acknowledgment occurs.
- Resolution updates the same server `reviewLocal` / saved readiness path as the overlay, selector `*` and Final Review. Unsaved state remains independent; confirmation stays disabled until Save.
- Correct Question content requires no artificial edit. Real text/source mismatch remains blocking and is tested separately.

Confirmed/read-only genuine drift retains the existing server revision-oriented `修正版を作成` guidance and does not enter a disabled source editor. Existing fix1 negative tests for Question/Answer/Rubric/diagram drift remain included in broader validation. Immutable snapshots/hashes, CAS/idempotency/rollback and source-review reconciliation are unchanged.

## Tests / validation

Final validation results:

- Six new backend tests: distinct structured targets, same-ID deduplication, partial acknowledgment without body changes, raw-body mismatch not acknowledged away, independent formula review, plus actual-PDF Save/readiness resolution and a split-child null-owner regression across the six test functions.
- Related backend group: **111 passed, 1 existing warning**; final source-issue group: **6 passed, 1 existing warning**. Full final backend: **1002 passed / 2 skipped / 23 existing warnings** (including confirmation exactness, rollback/CAS/idempotency, confirmed drift negatives and source/diagram/revision regressions).
- Final focused production-build Chromium: **14 passed**, grading jobs **0**. Includes the new actual Sample Q5 scenario, three J.UI.12e correction UX scenarios, Final Review overlay/markers/no-reflow, source-backed authoring, preview/material workflows and legacy Question/Answer diagram review.
- Full normal production-like Chromium: **74 passed**, **grading jobs 0**. Includes actual Sample Q5 confirmation/hash/diagram invariants, revision history, Answer/Rubric isolation, manual crop/reuse, source-backed authoring, correction UX, source-review/read-only behavior, overlay, Save/resume and stale tab.
- Actual-PDF browser assertions cover per-Question and Test-wide exact warning targets, visible row below sticky controls, focus/highlight, one-condition resolution, preservation of another condition, count/marker consistency, saved body preservation and reload.
- TypeScript passed; ESLint **0 errors / 19 existing warnings**; Ruff changed Python passed; production Next build passed in the fresh browser harness; diff check passed.

### Findings during test preparation

The first browser equality assertion compared raw initial extraction body against the normal saved editor representation. Existing Save preparation normalizes that representation; the final test establishes the ordinary saved baseline first and then asserts that source-only acknowledgment does not alter it. No product normalization behavior was changed or assertion on post-review content weakened.

An initial API fixture omitted the normal registered-material Save before analysis, leaving the working material list empty. The final fixture follows registration → Save → analysis and proves the metadata identifies the actual source material.

A skip-build browser rerun retained the previous harness's compiled API origin and failed login. Final focused and full runs build against their own disposable API origins; no delay/retry or authorization workaround was added. Initial failure counts are not represented as final passes.

The first full Chromium run had 71 passes / 3 failures: one cold-login pre-hydration submission with no POST in the trace, one old score-action label assertion, and a legacy warning-panel button-name collision. The score test now checks the requested `配点を修正` action; the quick acknowledgment button is authoring-only so the legacy whole-review confirmation button is unambiguous; cold-login readiness is awaited in the existing correction test. The corrected final 14-test focused group and entire 74-test normal suite both passed. No product authentication behavior was changed.

## Safety / scope

No production access/mutations/deployment, migrations, configuration/dependency changes, grading launch, model inference added for acknowledgment/readiness, Undo/Redo, manual Uni-MuMER recrop, revision-binding follow-on or other phase implementation. No commit or push. Previous diagnosis report remains untracked and unchanged; parent reports are unchanged.

## Files changed

- `src/scoring/authoring_question_issues.py`: server-owned source-review target and teacher-facing type metadata.
- `src/scoring/test_authoring.py`: retain concrete source issues, same-ID deduplication, separate body/formula/figure requirements.
- `src/scoring/authoring_issue_guidance.py`: semantic action and current/expected correction guidance.
- `frontend/lib/api/testAuthoring.ts`: structured issue target fields.
- `frontend/app/tests/[testId]/authoring/page.tsx`: exact warning/evidence navigation, PDF selection, source panel visible independently of body editing.
- `frontend/components/reviews/AuthoringIssues.tsx`: source category from structured metadata.
- `frontend/components/reviews/NodeEditor.tsx`: stable formula-source evidence target.
- `frontend/components/reviews/WarningPanel.tsx`: explicit existing acknowledgment action.
- `tests/test_authoring_question_issues.py`: focused backend/domain/actual-PDF regression.
- `frontend/e2e/authoring-question-source-issues-real.spec.ts`: actual-PDF correction flow regression.
- `frontend/e2e/authoring-preview-materials-real.spec.ts`: expect the intentional score-specific action label while retaining exact score focus/settings assertions.
- `frontend/e2e/authoring-correction-ux-real.spec.ts`: wait for initial authenticated-provider readiness before filling the cold login form; no login retries or weakened assertions.
- `tests/run_runtime_browser_e2e.py`: include the new browser scenario in the normal suite.
- This separate report.

## Remaining production acceptance

After operator deployment, inspect the real Accuracy Question's warning IDs/types, verify both cards identify their conditions, navigate to each actual row, acknowledge only the intended item, Save and verify count/markers update while other requirements remain. Validate PDF visibility and confirmed genuine drift still points to revised-draft creation. No completed parent phase status changes are required.

## Exact git status

All changes unstaged; the previous diagnosis report is pre-existing and unchanged. No commit or push.

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringIssues.tsx
 M frontend/components/reviews/NodeEditor.tsx
 M frontend/components/reviews/WarningPanel.tsx
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/lib/api/testAuthoring.ts
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/test_authoring.py
 M tests/run_runtime_browser_e2e.py
?? docs/internal/reports/authoring-save-blocker-diagnosis.md
?? docs/internal/reports/j-ui-12e-fix2.md
?? frontend/e2e/authoring-question-source-issues-real.spec.ts
?? src/scoring/authoring_question_issues.py
?? tests/test_authoring_question_issues.py
```
