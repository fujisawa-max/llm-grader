# J.UI.12e-fix4 — Manual Edit Implies Source Confirmation

## Result

**READY_FOR_PRODUCTION_VALIDATION** (2026-10-13). Local implementation and required
regressions passed. No deployment, production mutation, commit or push. Completed
parent phases remain unchanged.

## Diagnosis and exact old behavior

The user identified 問題3(3). Read-only inspection of the dedicated `Repro - review`
Test (`a7bc4d5a-014d-4067-a2ac-6672c3de28f6`) found the representative split child
`teacher-4f66e5ce-d00d-4415-ab26-79af448880ff`, parent `q3`, saved edit version 13.
At inspection its formulas were already confirmed and its source-text warning was
absent; its remaining issue was rubric points. We therefore reproduced the editing
transition locally from the saved source shape, without acknowledging or saving the
production record.

Two related defects were demonstrated:

1. `editQuestionContent.resetEmbedded()` reset **all** merged formula confirmations
   during a prose-only edit, including an unchanged `B(2,2)` and a saved teacher
   transcription `、`. The ordinary `問題文を確認` control confirms formulas in bulk;
   it is not a text-only review control.
2. `prepareAuthoringSave()` required every merged formula transcription to be inside
   math delimiters. A previously saved punctuation transcription therefore caused
   even safely reconciled prose edits to fall back to old ordered content while
   retaining the new raw buffer. Backend `source_warnings()` correctly detected that
   resulting raw/executable-text difference.

The local production-shape probe now reports `preparedMatches=true` and
`formulaStatesPreserved=true`. The unchanged backend source-anchor validator also
accepted the prose-edited production-shaped local copy. A subsequent read-only
inspection observed edit version 15 with the same relevant text/formula shape; no
production Save was performed by this task. This does not assert new production
acceptance.

## Transition and scope

- Meaningful text correction is derived on the server in `save_draft()`, after source
  and material validation and before grading-definition freeze/CAS persistence.
- Existing teacher-correction conventions hold a scoped `text_review` receipt:
  `teacher_confirmed=true`, `confirmation_origin=manual_edit`, saved edit version,
  before/after canonical text hashes, and the prior review receipt when present.
- Question: `node.teacher_correction.text_review`.
- Answer: `entry.teacher_correction.text_review`.
- Rubric: `criterion.provenance.text_review`.
- Compare the proposed text with the current saved item. Whitespace-only changes,
  identical text and an edit restored before Save create no new receipt. Exact user
  text itself is preserved; comparison does not normalize stored content.
- Question receipts are restored from server state before source validation. Answer
  and criterion text receipts are likewise server-derived at Save; client-supplied
  receipts cannot manufacture text approval.
- Unmapped raw Question buffers retain their source-integrity issue and receive no
  new text attestation. A receipt never suppresses a raw/executable mismatch.

Prose-only editing preserves existing formula states, including **unreviewed** states;
no formula is newly approved. Changed formula content still requires independent
review. The Save adapter preserves a non-math transcription only when its saved
anchor/decision/transcription remains represented and the math content is unchanged.
An absent literal mapping remains an unresolved draft source condition.

## Answer/Rubric audit and preserved obligations

There is no separate generic Answer-text acknowledgment blocker in current preflight;
Answer classification, assignment and diagrams are independent. The scoped receipt
records prose review without changing classifier status, disposition or diagrams.

Rubric's generic `この採点基準を確認` control currently confirms **grouping**, not
just criterion prose. Criterion text correction records text review but does not
approve grouping, points, executable levels or partial-credit conditions. Those
independent obligations intentionally remain. Original source text, segments,
automatic classification and operation history are retained.

Parser warnings (`ambiguous_geometric_order`, vector/formula/figure warnings), warning
acknowledgment maps, score issues, unassigned candidates and other items are unchanged.
The existing server preflight remains the source for overlays, selector `*` and Final
Review. Save dirty state remains independent. Confirmed snapshots are not rewritten;
manual edits still require an editable revised draft.

## Validation

| Check | Final result |
| --- | --- |
| Focused backend (authoring, text receipts, source review) | 83 passed |
| Full backend | 1,044 passed, 2 skipped; 23 existing warnings |
| Focused browser (new text review + existing correction UX) | 9 passed |
| Full normal production-like Chromium | 74 passed |
| TypeScript | PASS |
| ESLint | PASS; 0 errors, 19 existing warnings |
| Ruff, changed Python | PASS |
| Next production build | PASS (production-like browser harness builds) |
| `git diff --check` | PASS |

The initial full backend run found one existing test whose exact expected node
payload omitted the new server text receipt. Its expected payload now explicitly
checks the before/after hashes, manual-edit origin and revision; formal-data/CAS
assertions were retained. The final full backend run passed. Early browser failures
were diagnosed as a missing editor-mode action in the new test and an inaccurate
synthetic punctuation fixture; neither required weaker product validation.

Focused coverage includes production-shaped merged formulas/punctuation, unchanged
confirmed/unreviewed math, no-op edits, changed math, invalid literal mapping,
Sample Q5 prose Save/reload/Back/resume, preserved source warnings, scoped Answer and
Rubric receipts, preserved automatic history/classification/grouping/points/levels,
server receipt round trips, CAS rejection and injected late Save failure rollback.
Existing confirmation exactness, immutable snapshots, revision history, diagrams,
source navigation, overlay/no-reflow and Final Review regressions are retained.

Operational grading jobs launched: **0**; real model calls: **0**. Existing full-suite
backend fixtures may construct synthetic grading-history rows. Browser setup uses the existing managed
analysis stubs; Save/text-review transitions introduce no inference calls. Production
inspection used login and GET requests only. No secret values/cookies/tokens were
included in repository artifacts. Final changed-file and read-only evidence audits
for the configured production credentials passed, without printing their values.

## Handoff

Operator deployment and dedicated production validation are required after local
checks pass. Recheck 問題3(3) prose edit/Save without another bulk formula confirmation;
verify independent parser warnings and genuinely edited formulas still need review.
No migrations. Do not rewrite old confirmed revisions or automatically acknowledge
existing warnings. No follow-on phase started.

## Files and git status

Baseline HEAD: `195d286`; initial working tree clean. No DB model, migration,
runtime configuration, deployment configuration or parent report was changed.

Changed/new files: frontend reconciliation and Save adapter, optional review-node
metadata type, server review-node validation, draft Save integration, the scoped
text-review service, backend/browser regressions, and this standalone report.

Exact final `git status --short`:

```text
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/lib/authoringState.ts
 M frontend/lib/questionContent.ts
 M frontend/types/reviews.ts
 M src/scoring/review_document.py
 M src/scoring/test_authoring.py
 M tests/test_authoring_sources.py
 M tests/test_test_authoring.py
?? docs/internal/reports/j-ui-12e-fix4.md
?? frontend/e2e/authoring-manual-text-review.spec.ts
?? src/scoring/authoring_text_review.py
?? tests/test_authoring_text_review.py
```
