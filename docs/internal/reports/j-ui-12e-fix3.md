# J.UI.12e-fix3 — Source Warning Wording and Aggregate Deduplication

## Result

**READY_FOR_PRODUCTION_VALIDATION.** Local implementation and all required automated validation passed. Production deployment/acceptance is not performed. Completed parent phases remain COMPLETE. No production data, parser threshold, geometry algorithm, model behavior or migration was changed.

## Previous behavior and source provenance

The separately recorded production diagnosis found `node:q2:ambiguous_geometric_order` correctly owned by q2. Sample Q5's confusion-matrix table contained a 90.919998pt horizontal gap, exceeding the existing 90pt threshold. The parser conservatively requested review of element relationships, not reordering of Questions. Saving correct table text did not acknowledge the separate source-warning decision.

The producer also unions node flags into document flags. `warning_catalog()` therefore generated both the local node ID and `draft:document:ambiguous_geometric_order`. Teachers could be asked to approve the same underlying finding twice.

The distinction is now explicit in a detached, server-owned requirement catalog:

```text
coverage.schema_version = source-warning-coverage.v1
coverage.producer = native-question-structure-v1.2.1-node-union
coverage.covered_warning_ids = [node:q2:ambiguous_geometric_order, ...]
coverage.independent_evidence_ids = [] or concrete independent evidence identities
```

For the current `native-question-structure` / `question-structure-v1.2.1` producer, inspection establishes that this specific document flag is collected exclusively from node flags at the final node union. Preamble layout flags are not themselves added to that union. The helper uses that known producer contract and the actual immutable Draft's node flags; it does not infer coverage from a warning code/message or null owner in isolation.

An explicit `warning_provenance` envelope can represent independent/mixed document evidence. Unknown producers or absent/invalid coverage fail closed. No parser detection or sensitivity was changed to create new header findings. Independent/mixed negatives are controlled fixtures for this provenance contract.

## Requirement rule

The document aggregate is independently non-actionable only if:

- its structured coverage has the supported schema and a nonempty, unique list of concrete node warning IDs;
- every referenced warning is present, blocking, node-owned, and matches the referenced source owner and warning family;
- each covered warning resolves to an actual included Question using the existing exact-owner helper;
- there is no independent document evidence.

This excludes a redundant aggregate from preflight issues while retaining its ID, blocking flag, raw record and coverage for diagnostics. It creates **no acknowledgment state**.

| Case | Actionable requirements |
|---|---|
| Only q2 finding, document is its roll-up | q2 only |
| q2 + q3, document is their exact roll-up | q2 and q3 separately |
| Independent document-only evidence | document requirement retained |
| q2 plus independent document evidence | q2 and document requirements retained |
| Missing/malformed coverage, unknown producer, missing/ambiguous/excluded owner | document requirement retained |

Acknowledging q2 does not approve q3 or any independent document finding. Text edits, Save and related acknowledgments never manufacture source review approval.

## Wording and affected surfaces

Primary wording, exactly:

> 設問の図表や数値・文字・文章の位置関係を確認してください

Explanation, exactly:

> 本来意図されている位置関係の認識に失敗した可能性があります。元資料と照合してください。

`reviewLabels.ts` supplies this wording to the authoring/source WarningPanel, ordinary source review, saved/read-only review and review-issue navigation. Backend source issue metadata supplies the same primary message/explanation to actionable cards and Final Review; the technical source caption also describes position relationships rather than Question ordering. Technical warning codes and coverage stay in diagnostic metadata, not the primary explanation.

The real structural `duplicate_order` validation message remains unchanged; it describes an actual Question ordering error and is a different condition.

## Compatibility and server authority

Existing `warning_states` and warning IDs are preserved. Previously acknowledged document aggregates remain available as audit evidence; they do not implicitly confirm nodes. Previously acknowledged nodes remain acknowledged. Covered aggregate records remain readable even when not independently actionable.

For old authoring snapshots without coverage metadata, `authoring_warning_catalog()` reads their pinned server source Draft through existing artifact-integrity checks. It verifies the source review/Draft identity, source SHA, immutable automatic nodes and matching warning identity fields before deriving coverage. The enriched catalog is returned alongside readiness, **outside** the saved/confirmed snapshot. Neither a compatibility read nor Confirm writes it back into historical content. If proof is unavailable or does not match, the old independent requirement is retained.

Fresh source-review responses expose the decorated catalog. Review summary, explicit mark-reviewed validation, authoring preflight and Confirm share the same requirement helper. The authoring API returns `question_warning_catalog`; warning panels and ordinary review issue lists consume only the server's `actionable` decision. No frontend code/message deduplication heuristic was added. The last server-attested catalog is retained by source-review identity while dirty-state readiness refreshes, preventing old pinned catalogs from briefly presenting a redundant action during recomputation.

`要修正(N)`, Question `*` and Final Review counts still come from the same preflight issues. Exact-owner resolution is unchanged: q2 remains q2, not a child or null-owner fallback.

## Navigation and resolution

The existing `出典確認へ` path is retained. The actual Sample Q5 E2E selects q2 and the correct source material, reveals/highlights the exact warning row, positions it below sticky controls and focuses its state selector. Explicit acknowledgment removes the q2 requirement without editing correct body text. No second document-equivalent action remains, and no aggregate acknowledgment is written.

An unrelated document-wide vector warning remains independently actionable and can be resolved separately. A controlled server-response browser fixture also verifies the independent document-level spatial-warning wording, exact Test-wide target/highlight and explicit resolution. Real independent/mixed provenance semantics are verified separately in backend tests; the browser fixture does not change parser behavior.

Save/reload/Back/resume retain the resolved states, consistent issue counts/markers and unchanged Question bodies.

## Validation

- Focused backend: **33 passed** (coverage/readiness, legacy attestation, fix2 source-warning and review-text editing tests).
- Full backend: **1035 passed, 2 skipped, 23 warnings**.
- Focused Chromium: **13 passed** (real Sample Q5, controlled document negative, correction UX, Final Review/overlay, source-backed authoring and warning semantic tests).
- Full normal production-like Chromium: **74 passed**; grading-jobs-zero harness audit passed.
- TypeScript: passed.
- ESLint: 0 errors; 19 existing warnings.
- Ruff for changed Python: passed.
- Next production build: passed; the browser harness additionally builds with its isolated API proxy target.
- `git diff --check`: passed, including the new report; credential literal audit passed.

Initial browser setup used a build whose proxy targeted the default API port while the harness had allocated another port. Rebuilding through the established harness resolved that environment mismatch. The extended Back/resume assertion initially targeted the wrong existing CTA label; it was corrected to `テスト内容を編集`. No product semantics, assertions, retries or delays were weakened to clear these failures.

Warning compilation/readiness/confirmation reconciliation add **0 model calls**. New source-warning acceptance needs no inference. Broader existing suites use managed-stub analysis as designed; no real model inference is performed. Authoring browser harness asserts **grading jobs=0**. No production requests were made in this phase.

## Deployment handoff

Deploy frontend/backend together; **no migration**. Production acceptance is pending and should use a new dedicated Sample Q5 Test. Do not mutate the existing `Repro - review` record without operator authorization.

Verify the exact new wording, q2 ownership and one effective local requirement; acknowledge q2 once, Save/reload and confirm the count decreases exactly once with no redundant document-equivalent blocker. Verify unrelated document findings remain. Existing saved catalogs/decisions should remain readable and immutable. No grading job is required.

No follow-on phase, deployment, commit or push was performed.

## Files and repository

Changed frontend: authoring page, WarningPanel, server requirement API/types, questionReviewIssues, reviewLabels and focused browser specifications.

Changed backend: new `source_warning_requirements.py`; warning_catalog/summary/mark-reviewed validation; QuestionReviewService response; source issue labels/guidance; authoring preflight/review/Confirm integration. Added coverage tests and legacy saved-catalog attestation regression. No `question_structure.py`, migrations, runtime manager or grading model changes.

The untracked `question-review-warning-production-diagnosis.md` already existed at phase start and was left unchanged. Completed parent reports and J.GRADING reports were not edited.

Exact `git status --short` after local validation (the prior diagnosis report is pre-existing untracked work):

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/WarningPanel.tsx
 M frontend/e2e/authoring-question-source-issues-real.spec.ts
 M frontend/e2e/review-issues.spec.ts
 M frontend/lib/api/testAuthoring.ts
 M frontend/lib/questionReviewIssues.ts
 M frontend/lib/reviewLabels.ts
 M frontend/types/reviews.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/authoring_question_issues.py
 M src/scoring/question_reviews.py
 M src/scoring/review_document.py
 M src/scoring/test_authoring.py
 M tests/test_authoring_question_issues.py
?? docs/internal/reports/j-ui-12e-fix3.md
?? docs/internal/reports/question-review-warning-production-diagnosis.md
?? src/scoring/source_warning_requirements.py
?? tests/test_source_warning_requirements.py
```
