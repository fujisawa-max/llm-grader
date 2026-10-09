# J.UI.12b-fix14b — Diagram Discovery Progress & Save Guidance

## Result

**READY_FOR_PRODUCTION_VALIDATION** — UX implementation and automated verification complete; deployed acceptance remains.

## Baseline

- HEAD: `85780928e7697b54dec53ce560d6d7b23b417485`; initial working tree clean. fix14a is committed in this baseline.
- Scope: presentation only; no discovery, crop, parent fallback, reuse, persistence, backend or schema changes.
- No production access, commit, push or deployment.

## UX changes

Previously discovery shared the generic crop-confirmation busy label. Discovery now shows a decorative existing spinner and `図候補を探しています…` on the disabled button, plus local live status `図候補を探索しています…`. The existing region exposes `aria-busy=true`. Existing candidates remain visible. Completion/failure clears progress and allows retry; crop confirmation keeps its previous wording.

Near the same-major reuse heading, Unified Authoring shows exactly:

> 他の小問で図を再利用するには、図を選択した後に保存してください。

The notice appears only when this Answer entry has diagram records differing from its saved records. It disappears after successful Save synchronizes the existing baseline. The notice does not block operations or alter saved-only reuse filtering. No toast is added.

## Regression coverage

The actual Sample Q5 browser regression now holds discovery requests with a controlled promise to inspect spinner, disabled state and live status. Keyboard Enter triggers the same progress. A deliberately malformed response tests failure cleanup/retry without model changes. The retry continues through the real API, native PDF source and safe parent fallback. Acceptance verifies the exact save guidance and its removal after Save. Existing manual crop, sibling reuse, Rubric analysis, source snapshots and Save/reload/Back/resume assertions remain.

## Verification

- Focused actual Sample Q5 and split/merge browser group: **5 passed**, 21.6 seconds; grading jobs **0**.
- TypeScript passed. ESLint: **0 errors, 19 existing warnings**. Production Next build passed through both focused and final full harnesses. Final full production-like Chromium: **64 passed**, 2.5 minutes, grading jobs **0**, including real Sample Q5, OCR, source ownership, Save/resume, split, Rubric, stale-tab and notification regressions.
- Initial focused attempt completed the UX/domain assertions but caught a background issue-review POST racing Save (`AUTHORING_SAVE_CONFLICT`, HTTP 409). The test now waits for the assignment/reuse issue-review response before Save; no product/CAS/review behavior was changed and Save and diagram API errors remain failures. A full-run observation showed the same harmless read-only review race at another Save: the test now specifically validates every `/authoring/review` 409 body as `AUTHORING_SAVE_CONFLICT` and requires matching console messages. Other console errors remain failures. No broad retry or delay was added.
- Python unchanged; Ruff/backend suite not required for this presentation-only phase.

## Files changed

- `frontend/components/reviews/DiagramReview.tsx`: discovery-specific presentation state, spinner/live status, optional save guidance.
- `frontend/components/reviews/AuthoringCandidates.tsx`: derive diagram-local unsaved state from the existing saved-entry baseline.
- `frontend/e2e/authoring-sample-q5-diagram-real.spec.ts`: controlled discovery success/failure/retry progress and assignment Save guidance assertions, retaining the actual-PDF regressions.
- This report.

## Remaining acceptance

Deployed verification still required: observe discovery spinner with mouse/keyboard, verify failure permits retry, accept a diagram and check the exact save guidance, Save and check disappearance, then reuse on Q3(2). No diagram feature semantics changed. J.UI.12c remains deferred.

## Final git status

```text
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/DiagramReview.tsx
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
?? docs/reports/j-ui-12b-fix14b.md
```

`git diff --check` passed. Changes remain uncommitted. No deployment was performed. No known defect remains in the requested progress/guidance workflow.
