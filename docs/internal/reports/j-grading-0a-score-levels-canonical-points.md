# J.GRADING.0a — Score Levels as Canonical Criterion Points

## Result

**READY_FOR_PRODUCTION_VALIDATION.** New Web authoring now treats executable score levels as the sole source of a Rubric criterion's effective maximum. Production deployment and acceptance remain outstanding; this run made no production changes.

## Behavior

Previously, an editable criterion stored `points` beside executable levels and required both values to agree. The Web Rubric editor now removes the editable 配点 input, shows a read-only maximum derived from the levels, and persists `points` only as a server-derived compatibility projection. The grading-definition compiler independently derives `max_score` from the maximum valid level and ignores stale `points` values.

New criteria start with the zero level `0点 / 基準を満たしていない。`. When a known positive maximum accompanies an imported candidate, one positive level is created; no intermediate levels are synthesized. Ambiguous or unknown conditions remain blank and block confirmation until completed. A new criterion without a known maximum gets a blank positive-score row. Incomplete policies remain savable, while Final Review requires complete, unique, nonnegative levels with conditions and a positive maximum.

Legacy editable drafts with `points=N` and no levels retain their points on unrelated saves. Opening the Rubric editor explicitly prepares the draft as `0` plus an `N`-point level. The zero condition is supplied by the system; when the existing criterion body is a safe full-credit condition it seeds that level, otherwise the condition remains visibly incomplete. Historical confirmed snapshots are never normalized: history remains read-only and displays the old points value when levels are absent. Forking remains exact until the teacher enters and prepares the editable Rubric editor.

The separate legacy ModelAnswer import-review route retains its existing points semantics. Canonical levels are applied within the new Unified Authoring path, preventing new fields from leaking into legacy draft saves. Rubric split/merge, source provenance, classification, grouping, and operation history remain intact. Split rows get independent levels from explicit split allocations; ambiguous allocations remain incomplete. Merging preserves identical existing level policies and otherwise requires review rather than inventing partial credit.

Question totals continue to come from the Question score contract. Rubric totals sum the highest level per criterion; any mismatch remains a confirmation blocker targeted at 得点段階と部分点の条件. Final Review shows the derived highest point and each level/condition. The immutable `grading_definition` carries the levels and derived maximum, so it can be reconstructed from the confirmed revision without a separate criterion-points authority.

## Validation

- Backend focused: **84 passed** (`test_test_authoring.py`, `test_grading_definition.py`).
- Full backend: **1,047 passed, 2 skipped**.
- Focused browser: **8 passed** for canonical levels and Final Review; a further **7 passed** for the new canonical flow and affected legacy Rubric import/split/LaTeX regressions.
- Full production-like Chromium: **74 passed**. Includes Sample Q5 authoring, diagram acceptance/reuse, revision history, source-backed workflows, and legacy import-review flows.
- TypeScript: passed.
- ESLint: 0 errors; 19 existing warnings.
- Ruff: passed for changed Python files.
- Next production build: passed; existing CSS autoprefixer warnings remain.
- `git diff --check`: passed.
- Alembic head remains `0018_revision_lineage`; no migration was added.
- Grading jobs: **0**. Browser validation used test fixtures/stubs; no real grading or model inference was run.

## Production handoff

Deploy the application changes through the established operator workflow, then validate on a fresh dedicated Test. Acceptance should check that an incomplete policy saves but blocks Confirm, explicit levels make it confirmable, and each new confirmed revision retains its independent executable levels. No production acceptance was performed in this phase.

## Files changed

- `frontend/app/tests/[testId]/authoring/page.tsx`
- `frontend/components/reviews/AuthoringCandidates.tsx`
- `frontend/components/reviews/AuthoringRevisionHistory.tsx`
- `frontend/components/reviews/ExecutableRubricLevels.tsx`
- `frontend/e2e/authoring-final-confirmation-real.spec.ts`
- `frontend/e2e/authoring-final-review-issues-real.spec.ts`
- `frontend/e2e/authoring-preview-materials-real.spec.ts`
- `frontend/e2e/authoring-rubric-reliability-real.spec.ts`
- `frontend/e2e/authoring-source-backed-real.spec.ts`
- `frontend/e2e/test-authoring-foundation-real.spec.ts`
- `frontend/e2e/rubric-levels-canonical.spec.ts` (new)
- `frontend/lib/rubricEditing.ts`
- `frontend/lib/rubricLevels.ts` (new)
- `src/scoring/authoring_issue_guidance.py`
- `src/scoring/authoring_sources.py`
- `src/scoring/grading_definition.py`
- `src/scoring/test_authoring.py`
- `tests/test_grading_definition.py`
- `tests/test_test_authoring.py`

No commit or push was made.

## Exact Git status

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/AuthoringRevisionHistory.tsx
 M frontend/components/reviews/ExecutableRubricLevels.tsx
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
 M frontend/lib/rubricEditing.ts
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/authoring_sources.py
 M src/scoring/grading_definition.py
 M src/scoring/test_authoring.py
 M tests/test_grading_definition.py
 M tests/test_test_authoring.py
?? docs/internal/reports/j-grading-0a-score-levels-canonical-points.md
?? frontend/e2e/rubric-levels-canonical.spec.ts
?? frontend/lib/rubricLevels.ts
```
