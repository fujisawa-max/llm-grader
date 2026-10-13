# J.UI.15a — Unified Authoring presentation cleanup

Status: **READY_FOR_PRODUCTION_VALIDATION**. No production changes, commit or push.

## Presentation boundary

Previously the normal Question card repeated the selected Question label, and Question/Answer DiagramReview machinery appeared alongside accepted previews. Answer diagrams could therefore appear twice. Editable Rubric lists still said 採点基準候補 and repeated the max-score derivation rule.

Compact NodeEditor now omits only the duplicated outer Question heading; selector identity, editable label/settings, hierarchy, legacy editor headings and historical/Final Review labels remain unchanged. Rubric lists use 採点基準の一覧 as their accessible region name, retain the main 採点基準 section heading, and omit the candidate heading and persistent maximum explanation. Derived 最高点 remains in each score-level summary. Compact assigned Answer region labels say 模範解答; unassigned/analysis/import candidates remain candidates.

`AuthoringFigure` is a presentation wrapper. Normal content contains 図, one accepted preview through the existing AcceptedDiagramPreview renderer, or compact 図は登録されていません。 Candidate/stale/invalid records and existing structured server figure issues retain a visible scoped review status. The existing server issues are passed through for presentation only; no new issue state/count source is created. Native ▶/▼ 図を編集・確認 disclosure contains the unchanged DiagramReview component. Its exact ownership, candidate discovery, range correction, manual crop, parent fallback, sibling reuse, trust/revalidation, exclusion and callbacks remain authoritative. The disclosure resets when its Question/entry identity changes; keyboard and aria-expanded use native disclosure behavior. Opening/closing has no Save, analysis or model call.

DiagramReview remains mounted, retaining existing saved-record revalidation and source-pane selection behavior. Closed controls are inaccessible until their disclosure is opened; candidate-management imagery is not visible in the normal view. Editing figures retains its existing working-state persistence semantics: selecting/applying a candidate modifies working state; global Save persists it. Closing the operation panel is not a new transactional Cancel and does not roll back an already applied canonical figure change. Existing range/manual-crop Cancel controls remain unchanged.

Figure issue navigation opens the exact local figure disclosure before targeting its existing diagram row, opens ancestor disclosures, then scrolls/highlights/focuses through the existing path. No backend issue generation, counts, ownership or readiness changes. Existing text/formula/source-warning controls remain separate. Final Review/history stay read-only and use their existing accepted-diagram representation; no candidate-management UI or snapshot normalization is added there.

## Validation

Disposable production-like harness: real FastAPI/RuntimeManager, temporary DB/artifacts, fresh production Next build/server, managed synthetic stubs only where existing source/LaTeX regression fixtures require them. No OCR/reanalysis added merely for presentation.

- Main focused group: **9 passed / 0 skipped / 0 failed**, 52.6s. New normal presentation plus Sample Q5 accepted-once/discovery/correction/manual crop/sibling reuse/Save/resume, source-backed authoring, compact Question/Answer, Answer assignment/manual-edit receipts, Rubric polish/canonical levels and two-edition history.
- Final structured navigation/queue group: **3 passed / 0 skipped / 0 failed**, 3.6s. New presentation, exact assigned Answer figure-operation navigation/status, J.UI.14a assignment/mixed-domain bulk exclusion/filter/partial-failure behavior. The navigation test injects a structured figure issue into a real API response to exercise this frontend branch; it does not claim the fixture has a genuine backend visual-integrity defect or change saved content.
- Final latest-code full normal Chromium: **74 passed / 0 skipped / 0 failed**, 4.6 minutes, fresh production build/disposable real API/Manager. Earlier full run also passed 74/0/0; this final rerun includes the server figure-status pass-through.
- TypeScript passed; ESLint **0 errors / 19 existing warnings**; fresh Next production builds passed; `git diff --check` passed.

 Exploratory failures from obsolete region labels, hidden region lookup, nested summary ambiguity and operation-panel remounts are retained as failed runs, not feature passes; regression navigation is being adapted while preserving content/source/trust assertions.

No backend/schema/migration/scoring/runtime changes. Grading jobs **0**, real model calls **0**. Normal presentation, disclosure and navigation do not trigger model inference; explicit source/LaTeX/diagram regressions retain managed synthetic fixture calls, not zero synthetic calls. No Ruff/backend suite is required for this frontend-only change. No required J.UI.15a feature validation is skipped.

## Files / handoff

Product files: `frontend/components/reviews/AuthoringFigure.tsx` (new presentation wrapper), `NodeEditor.tsx` (compact-only heading), `AuthoringCandidates.tsx` (current terminology and local figure operations), `frontend/app/tests/[testId]/authoring/page.tsx` (Question/fallback figure presentation, server status pass-through, exact figure navigation).

Tests: new `unified-authoring-presentation-real.spec.ts`; existing `authoringEditMode.ts`, source-backed/split-merge/diagram-reuse/Sample Q5 diagram/three-child/confirmation/revision-history scenarios and Rubric reliability/polish/canonical-level scenarios now address the new accessible current-content labels and explicitly open figure operations after navigation/remount. Content, provenance, score/trust, CAS and snapshot invariants remain asserted. The optional truncated-Ricoh-only spec is adapted but is not a claimed feature pass; required reuse/ownership/crop validation uses the normal real Sample Q5 scenarios.

Frontend-only deployment; no migration. Production acceptance must use a dedicated validation Test: inspect normal Question/Answer accepted figures once, open/review figure operations, verify source warnings remain visible/actionable, Save/reload, and inspect Final Review/read-only editions. Do not run grading. COMPLETE remains reserved for operator production acceptance.

## Git status

Before J.UI.15a: clean. After final validation (no staging, commit or push):

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/NodeEditor.tsx
 M frontend/e2e/authoring-diagram-reuse-real.spec.ts
 M frontend/e2e/authoring-revision-history-real.spec.ts
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M frontend/e2e/authoringEditMode.ts
 M frontend/e2e/rubric-interaction-polish-real.spec.ts
 M frontend/e2e/rubric-levels-canonical.spec.ts
?? docs/internal/reports/j-ui-15a-unified-authoring-presentation-cleanup.md
?? frontend/components/reviews/AuthoringFigure.tsx
?? frontend/e2e/unified-authoring-presentation-real.spec.ts
```
