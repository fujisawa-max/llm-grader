# J.UI.12e-fix5 — Domain-scoped Issue Counts and Filtering

## Result

**READY_FOR_PRODUCTION_VALIDATION** (2026-10-13). Local implementation and
validation passed. No deployment, production access, commit or push.
Baseline HEAD: `f17af90`; working tree was clean. Completed parent phases are unchanged.

## Old behavior and metadata audit

Both the toolbar popup and the per-Question overlay rendered the entire server
`issues` array (or the entire directly owned Question subset), regardless of the
問題／解答／採点基準 visibility checkboxes. Answer-only editing could therefore still
show Rubric requirements, obscuring whether Answer work was complete.

Existing API metadata is sufficient; no backend change is needed:

| Structured owner | Display/count group |
| --- | --- |
| `question` | 問題 |
| `answer` | 解答 |
| `rubric` | 採点基準 |
| `model_answer` (existing review vocabulary) | 解答 |
| Unscoped `source`, `metadata`, `save`, `publication`, unknown future sections | 共通 |

A recognized explicit `domain` takes priority; otherwise the structured `section`
is used. Message wording never determines ownership. Unscoped source issues do not
currently expose a reliable individual domain, so they remain visible as common
requirements rather than being guessed or dropped.

## Count/display design

- Toolbar: existing full-Test total plus `問題(N) 解答(N) 採点基準(N)`, in the same
  order and terminology as the visibility checkboxes. `共通(N)` appears when needed.
- These domain counts always describe the **complete current server issue set**,
  including hidden domains. Each issue contributes to exactly one group.
- Global popup: only enabled domains plus common requirements. Its header states
  `表示中 F件 / 全体 N件`.
- Per-Question overlay: the same filter, applied after exact direct Question
  ownership. Its counts describe that Question, without inheriting child issues.
  The floating tab counts the displayed subset. If all owned requirements are
  hidden, the tab shows 0 and explains the filter; the popup directs the teacher to
  Final Review for all requirements. If no owned issue exists, the tab remains absent.
- Counts use named accessible outputs such as `解答 0件`; color is not required.
- One shared structured-domain helper supplies both counts and filters. Visibility
  checkbox labels use the same ordered domain list. No new readiness state exists.

## Safety and navigation

Filtering is presentation only. The server issue array, order and identities are
retained; no acknowledgment, Save or analysis is triggered by a visibility toggle.
Previous backend aggregate deduplication is untouched; the frontend does not perform
additional deduplication.

Final Review and ordinary テスト全体確認 continue to show the complete issue set and
use server `can_confirm`, independent of visibility. Question selector `*` markers
continue to reflect all directly owned requirements, including hidden domains.

Issue actions retain the existing exact navigation/scroll/highlight path. Opening an
issue from Final Review enables the required hidden editor; global source actions
open material management, and save/metadata/publication actions keep their existing
special targets. Unknown future sections remain readable as common requirements.
The overlay remains positioned over the editor, with no width/scroll reflow.

## Regression validation

| Check | Result |
| --- | --- |
| Focused frontend (new domain tests + correction UX + Final Review issues) | 8 passed |
| Full normal production-like Chromium | 74 passed |
| TypeScript | PASS |
| ESLint | PASS; 0 errors, 19 existing warnings |
| Next production build | PASS; run by both browser harness invocations |
| `git diff --check`, new-file whitespace | PASS |
| Grading jobs launched | 0 |
| Real model inference | 0 |

The focused new browser scenario also asserts no analysis/OCR/normalization/grading
request occurs. Changed-file credential audit passed without printing values.

Focused coverage:
- Structured ownership versus misleading message text; explicit domain priority.
- Common source/total/Save/publication/unknown issues stay visible when all domains
  are disabled.
- Direct Question ownership, stable server ordering and selected-domain union.
- Fresh disposable Test with complete Answer and missing Rubric: Answer count 0,
  Rubric count > 0, Answer-only popup/overlay contain no Rubric issue.
- Enabling Rubric updates the open overlay immediately without changing counts.
- Real Question + Rubric issue union has the expected count and no extra entries.
- Hidden issues retain `*`, remain in Final Review and still disable Confirm.
- Global correction opens/highlights the hidden Rubric editor.
- Visibility toggles/reload do not change the saved revision or server issue set.
- Existing correction UX and Final Review overlay/no-reflow tests.

No grading jobs or model inference was requested by the feature/scenario. The normal
browser harness uses managed analysis stubs during its existing setup/regressions;
no real models are used. Backend suites are not rerun because backend code, API
semantics, schema, migrations and issue generation are unchanged.

## Handoff and exact git status

Operator deployment and isolated production acceptance are required after local
validation. No other phase was started.

Changed/new files:
- `frontend/lib/authoringIssueDomains.ts`: shared structured grouping/filtering.
- `frontend/components/reviews/AuthoringIssues.tsx`: accessible counts and filtered
  per-Question overlay.
- `frontend/app/tests/[testId]/authoring/page.tsx`: toolbar counts, filtered popup,
  shared visibility labels; Final Review/selector markers unchanged.
- `frontend/app/globals.css`: compact count layout.
- `frontend/e2e/authoring-issue-domains.spec.ts`: focused pure/browser regression.
- This standalone report. No parent report, backend, migration or config changes.

Exact final `git status --short`:

```text
 M frontend/app/globals.css
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringIssues.tsx
?? docs/internal/reports/j-ui-12e-fix5.md
?? frontend/e2e/authoring-issue-domains.spec.ts
?? frontend/lib/authoringIssueDomains.ts
```
