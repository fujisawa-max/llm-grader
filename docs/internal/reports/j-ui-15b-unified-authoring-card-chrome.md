# J.UI.15b — Unified Authoring card chrome / heading consistency cleanup

Status: READY_FOR_PRODUCTION_VALIDATION

## Changes

Unified the normal Question, ModelAnswer, and Rubric presentation around a heading row outside one readable content frame. The compact Question editor no longer draws a surrounding panel or a second frame around the Question body; its `問題文` heading and Edit action sit above the single body frame. ModelAnswer headings remain above their body frames, and accepted alternatives now use the same framed presentation. Rubric criteria now use a heading row with `編集` and `対象外` controls above a single body frame, without the former outer criterion card.

The Rubric checkbox on the left was not dead: it selected criteria for the existing bulk-merge operation. It has moved into `基準の操作` and now says `一括結合の対象として選択`. This removes an unexplained checkbox from the normal title row while retaining the selection and merge behavior. `対象外` remains a clearly labeled checkbox and keeps the existing exclude/restore behavior.

No authoring semantics, persistence boundaries, APIs, backend files, schema, or migrations changed. Existing operation disclosures, edit dialogs, warning navigation, diagram handling, Final Review, and history remain in place.

## Validation

- Focused disposable production-like API + production Next.js + Chromium run: `python -m tests.run_runtime_browser_e2e --spec e2e/authoring-preview-materials-real.spec.ts` — 2 passed, 0 skipped. Assertions cover no duplicate Question heading, one Question frame, one ModelAnswer frame, Rubric heading/body frame, the moved bulk-merge selector, and the `対象外` control, alongside existing Save/reload and authoring interactions.
- Full disposable production-like Chromium suite: `python -m tests.run_runtime_browser_e2e` — 74 passed, 0 skipped, 0 failed. This includes Question/Answer/Rubric authoring, issue navigation, Save/resume/CAS, revision history, Final Review, Sample Q5 diagrams/reuse, and source-backed authoring.
- `npm run typecheck` — passed.
- `npm run lint` — passed with 0 errors and 19 pre-existing warnings.
- Next production build — passed in both disposable harness runs; existing Autoprefixer and lint warnings remain.
- `git diff --check` — passed.
- Grading jobs: 0. Real model calls: 0. The browser suite used the harness's managed synthetic runtime for existing analysis/LaTeX regression scenarios; no production model was called.

The first focused run had two test-only assertion issues before passing: the initial selector used `基準1本文…` while the checkbox's accessible name is `基準1…`; the next assertion queried the bulk-merge button while its existing `基準一覧の操作` disclosure was still collapsed. The selectors were corrected to use the actual accessible name and open the disclosure before inspecting its button. The implementation did not require a behavioral correction for either run.

## Files changed

- `frontend/app/globals.css`
- `frontend/components/reviews/AuthoringCandidates.tsx`
- `frontend/components/reviews/CompactModelAnswerText.tsx`
- `frontend/components/reviews/NodeEditor.tsx`
- `frontend/e2e/authoring-preview-materials-real.spec.ts`
- `docs/internal/reports/j-ui-15b-unified-authoring-card-chrome.md`

## Git status

```text
 M frontend/app/globals.css
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/CompactModelAnswerText.tsx
 M frontend/components/reviews/NodeEditor.tsx
 M frontend/e2e/authoring-preview-materials-real.spec.ts
?? docs/internal/reports/j-ui-15b-unified-authoring-card-chrome.md
```

No commit or push was made. Production handoff: `READY_FOR_PRODUCTION_VALIDATION`.
