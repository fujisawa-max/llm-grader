# J.UI.13a — Rubric Interaction Polish

Status: READY_FOR_PRODUCTION_VALIDATION.

## Interaction changes

- Normal criterion operations now say `位置を指定して2分割`. The position-selection dialog and criterion-body edit dialog both offer `カーソルの位置で分割`.
- Both entry points call the existing `split()` / proposal / `applyProposal()` workflow. The existing API accepts unsaved text and cursor offsets with the saved revision CAS check; no backend change was needed. The explicit split action transfers the dialog buffer into the working draft before requesting a proposal, so cancelling a proposal retains that text. It does not Save. Criterion IDs, source provenance, score allocation, merge behavior and operation history use the existing implementation.
- Score-level disclosures show `▶` / `▼` to the left of `得点段階`. Native summary activation supports pointer, Enter and Space. `aria-expanded` follows native toggle events, including programmatic expansion by issue navigation. Expansion is presentation state only.
- Excluded criteria initially display one inactive header row with selection, a clickable criterion title and `対象外`. Clicking the title expands/collapses the existing details; unchecking exclusion restores the active card immediately. Text, levels and provenance remain stored unchanged. Exclusion uses the existing working-state/Save flow.
- `数式をLaTeX化` now appears inside the criterion-text dialog. Its proposal applies to the dialog buffer and its result/guidance stays in a bounded, internally scrolling section. The existing conversion engine and review semantics are reused. The textarea starts at four rows.
- Cancel from text editing discards the dialog buffer; Done applies it to the working draft. Global Save is still the only durable persistence boundary. Score-level canonical authority, derived maximum, zero-point policy and confirmed revision immutability are unchanged.

## Validation

Disposable production-like harness: `python -m tests.run_runtime_browser_e2e`, with temporary SQLite/artifacts, real FastAPI/RuntimeManager, a managed synthetic model stub, and a freshly built production Next server.

- Focused group: **8 passed / 0 skipped / 0 failed** (13.1s). Specs: `rubric-interaction-polish-real`, `rubric-levels-canonical`, `authoring-rubric-reliability-real`.
- The new end-to-end scenario proves both split labels/entry points, unsaved dialog text in the split request and resulting child provenance/5+5 allocation, native mouse/keyboard disclosure and ARIA, one-row exclusion with measured height reduction and following-card movement, temporary inspection/restoration, dialog-local LaTeX apply/cancel, working-vs-saved snapshot isolation, and Save/reload retention.
- Canonical-level regression proves required zero level protection, level add/delete, dirty state, Save/reload, issue-navigation expansion with `aria-expanded=true`, Final Review, confirmation and immutable read-only history.
- Full normal production-like Chromium suite: **74 passed / 0 skipped / 0 failed** (4.4m). This includes source-backed Sample Q5, diagrams/reuse, split/merge/provenance, formula/LaTeX correction, issue navigation, Final Review, revision history and Save/resume/CAS.
- TypeScript: passed. ESLint: passed, 0 errors and 19 existing warnings. Next production build: passed with existing lint/Autoprefixer warnings. `git diff --check`: passed.
- Grading jobs: **0**, checked by both completed harness runs. Real model inference: **0**. The new scenario makes two LaTeX normalization requests through the managed synthetic stub; the standard analysis/formula regressions also use only isolated stubs.

## Handoff and files

Production acceptance remains for the operator after deployment. No production records, backend code, migrations, scoring rules or runtime configuration changed. No commit/push was performed. Earlier phase reports were left unchanged.

Changed files are listed in the exact final status below. The new browser test is a service regression test, and this report is an internal phase record.

## Exact git status

```text
 M frontend/app/globals.css
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/rubric-levels-canonical.spec.ts
?? docs/internal/reports/j-ui-13a-rubric-interaction-polish.md
?? frontend/e2e/rubric-interaction-polish-real.spec.ts
```
