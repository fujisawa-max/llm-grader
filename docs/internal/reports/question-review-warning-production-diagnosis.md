# Production diagnosis — persisted Question 2 review warning

## Result

**Diagnosis complete; no product-code or production-content changes.**

Primary classification: **expected unresolved Question-specific source-review warning**, not stale state or a regression of J.UI.12e-fix2 ownership resolution. The parser flags a large horizontal gap inside Question 2's confusion-matrix table, not an invalid order of Questions. Two secondary UX/catalog findings are present: the label incorrectly suggests Question ordering, and the same node finding is also rolled up into an independently actionable document-level warning.

The PDF's table is visually clear, and the saved Question 2 body already represents it correctly as a Markdown table. This does not prove teacher acknowledgment has occurred: its persisted warning state is still absent/default-unreviewed. Save alone deliberately does not acknowledge it.

## Exact production records

- Course supplied for inspection: `Codex Debug - 20261013`.
- Test: `Repro - review`, `a7bc4d5a-014d-4067-a2ac-6672c3de28f6`.
- Offering: `0b7ad7a9-8dea-4d9e-9e58-2c4ff8cc3fa4`.
- Working authoring revision: `38e6a2e7-386c-4c07-b57d-90c34538b498`; revision 2, edit_version **5**, state `draft`.
- Last saved: `2026-10-12T23:36:02.210541+00:00`.
- Saved snapshot SHA: `fa738f95c62e82d986aab6fa1b83efd5ad3efe048c4455598b4154470a3b4eb0`.
- Question material: `f1eed9d5-d571-4545-803e-96b11a0906b4`, role `question_sheet`, filename `sampleQ5.pdf`.
- Extraction: `d4ebf6bd-5b30-4547-865a-7f08daed2137`.
- Source draft: `dc6cc8d0-9300-4636-b296-4acbc8acc9ba`.
- Source review/document: `a4444690-e868-40f6-ae7d-407daef57c67`; state `editing`, current revision **1**.
- Source PDF SHA: `6320a8911269978ebf8ca7067eb964d07055cb99c4b3e6f5cc5424fef784f260`.
- Source IR SHA: `37100dda709c53b12f7e4f38d09175fc00f67fe3669aeaf812a65c5f4fca04fc`.
- Source draft SHA: `42976e2978ad46fbb0a57c79701826ffb07b210e4d80ea642dcba47c9f604376`.
- Source review revision SHA: `9a80918d4fef63018a7ef99dbce17d3b521c903b8d6e9001ec3067f89e9a4520`.
- Parser: `native-question-structure`, `question-structure-v1.2.1`; configuration hash `8773d3cd81be5f7306dae3c828dd7ef8edcbc7d192c418ba63accbebb59e7532`. This equals the versioned default configuration hash from the current parser.

## All warnings and ownership

`domains.question.document.warnings` contains exactly these three records. `domains.question.snapshot.warning_states == {}`. The independently saved source-review snapshot also has empty warning states. All warnings are `blocking=true`; absent state means **unreviewed**.

| warning_id | code | owner | Resolved Question key | scope / source item | State | UI target |
|---|---|---|---|---|---|---|
| `draft:document:ambiguous_geometric_order` | `ambiguous_geometric_order` | null | null | `draft` / `document` | unreviewed | Test-wide review; not a Question-local row |
| `draft:document:unresolved_vector_evidence` | `unresolved_vector_evidence` | null | null | `draft` / `document` | unreviewed | Test-wide review; not a Question-local row |
| `node:q2:ambiguous_geometric_order` | `ambiguous_geometric_order` | `q2` | `q2` | `node` / `q2` | unreviewed | Question 2, `review-warning-node%3Aq2%3Aambiguous_geometric_order` |

The backend review endpoint emits three `question_source_warning` issues with exactly these IDs/ownerships. It does **not** project either owner-null document warning onto q2 or its children. There is no repeated warning ID and no second source review contributing the local warning.

The q2 issue's structured fields are:

- `section=question`, `domain=question`, `field=source_warning`, `correction_type=source_warning`.
- `question_key=q2`, `warning_id=node:q2:ambiguous_geometric_order`, `warning_code=ambiguous_geometric_order`.
- `source_item_id=q2`, `source_scope=node`, `source_review_index=3`.
- Material/review/SHA are the exact records above; **no formula/figure region ID** is attached to this warning.
- Message: 「出典確認: 設問の並び順が未確認です。」
- Action: 「出典確認へ」.
- Expected action: compare the PDF and item; select 確認済み if correct, or correct it and select 対応済み.

The local row is labeled 「確認事項 1」 because it is the first/only row in that Question's filtered panel. The global catalog index is 3. Both refer to the **same exact warning ID**; this numbering difference does not misroute acknowledgment.

## Neighbor comparison

| Question | stable_key / source_draft_stable_key | parent | Original draft relationship retained? | Local review_flags | Local warning rows |
|---|---|---|---|---|---:|
| 問題1 | `q1` / `q1` | null | yes | none | 0 |
| 問題2 | `q2` / `q2` | null | yes | `ambiguous_geometric_order` | 1 |
| 問題2 > (1) | `q2.1` / `q2.1` | `q2` | yes | none | 0 |
| 問題2 > (2) | `q2.2` / `q2.2` | `q2` | yes | none | 0 |
| 問題３ | `q3` / `q3` | null | yes | none | 0 |

These nodes retain original imported identities, rather than newly teacher-created/null-source split aliases. There is no ancestry fallback involved in resolving this warning. The only formula regions are `formula-0001` through `formula-0006`, assigned to q3, not q2. Question 2's warning belongs to text/table geometry and its source-node identity, not a formula/figure review region.

Other options currently also have `*` because of unrelated missing Answer/Rubric/score issues. That is not evidence that the order warning belongs to them. The complete saved review has 15 issues; exactly one is the q2-local order warning.

## Actual PDF evidence and parser trigger

Downloaded the existing source PDF through the authenticated GET material-file endpoint and visually inspected a locally rendered copy. Its SHA matches the saved material/document SHA above. No production source was changed or re-analyzed.

Question 2 contains a normal confusion-matrix table:

| | Actually Positive | Actually Negative |
|---|---:|---:|
| Predicted Positive | 24 | 6 |
| Predicted Negative | 8 | 42 |

The exact source IR page was also fetched read-only. Reconstructing **only the pure layout projector locally** identifies this triggering table line:

- PDF page_index **0** (page 1), `line-00012`, geometric_order **12**.
- Text: `Negative と予測 8 42`.
- Line bbox: approximately `[164.30, 366.61, 434.80, 376.57]`, unrotated PDF points, origin top-left.
- `Negative と予測` right edge: `241.7899932861328`.
- `8` left edge: `332.7099914550781`.
- Horizontal gap: **90.91999816894531pt**, greater than the verified parser's **column_gap=90.0pt**.
- Source spans: `page-0001-span-0011-0000-0000`, `page-0001-span-0011-0001-0000`, `page-0001-span-0011-0002-0000`.

`LayoutProjector.project()` sorts fragments left-to-right and flags a large gap as possible multi-column reading-order ambiguity. `QuestionStructureParser.parse()` attaches that line's flags to the current imported node, q2. Neighboring Questions do not own this line. This is why q2 is singled out.

The page header also has a large-gap layout flag, but it is preamble/context; that flag is not added to a Question node. The q2 node is the only imported node carrying `ambiguous_geometric_order`, and the parser's final document flag union includes that node's flag.

There is **no evidence of ambiguous Question hierarchy or an actual Question-order error**. The detector conservatively asks for review of a multi-column table. The existing teacher-edited q2 body correctly represents the table; its correctness does not itself change the separate review acknowledgment state.

## Exact code paths and previous fix2 involvement

1. `src/scoring/question_structure.py:170`: gap predicate in `LayoutProjector.project()` emits `ambiguous_geometric_order`.
2. `question_structure.py:353`: current node inherits the line review flags; `:433` adds node flags to document-level aggregate flags.
3. `src/scoring/review_document.py:49`, `warning_catalog()`: emits a document aggregate (`:58`) and node-owned warning (`:60`) under independent IDs.
4. `src/scoring/question_reviews.py`, `QuestionReviewService.get()`: exposes persisted review snapshot, warning catalog and source identities.
5. `src/scoring/authoring_sources.py`: imports the pinned document and source-review snapshot into `domains.question`.
6. `src/scoring/test_authoring.py:363`: `preflight()` reads document warning states. For each unique, blocking, unreviewed warning it uses `warning_question_key()` and `question_source_target()` to emit structured issues.
7. `src/scoring/authoring_question_issues.py:46`: exact owner/source-key resolution returns q2 for the node warning and null for both document warnings. **J.UI.12e-fix2 is involved and functioning correctly**, not bypassed.
8. `src/scoring/api/test_authoring.py:863`: GET `/api/v1/tests/{test_id}/authoring/review` returns this saved-state readiness.
9. `frontend/app/tests/[testId]/authoring/page.tsx:398`: `warningQuestion()` uses the same exact-owner resolution; `questionWarnings` filters to the current Question. `WarningPanel` renders the local row.
10. `frontend/lib/reviewLabels.ts:60`: `ambiguous_geometric_order` maps to misleading 「設問の並び順を確認してください」. No specific reason exists for this code, so it uses the generic automatic-analysis explanation.
11. `authoring/page.tsx:164`, `navigate()`: selects the correct Question/material and targets `reviewWarningId(issue.warning_id)`, expands ancestors, scrolls/highlights the exact row. Live read-only navigation from the aggregate issue list reached/highlighted `review-warning-node%3Aq2%3Aambiguous_geometric_order` with its acknowledgment control visible.

No alternate owner resolution, label-prefix matching, parent inheritance, wrong warning ID or stale-source reconstruction was found in this path.

## Why Save/reload preserves it; acknowledgment scope

`domains.question.snapshot.warning_states` is the authoritative acknowledgment map. Empty maps default to unreviewed. `authoring_sources.py:545–554` preserves the immutable imported document while allowing only submitted document warning-state decisions to change. `test_authoring.save_draft()` persists those decisions; it does not convert ordinary text edits or Save into source-review approval. On reload, preflight reconstructs the same unresolved issue from the unchanged warning and empty state map. This is correct persistence.

`WarningPanel` passes the exact `warning.id` into `onChange`; the q2 panel writes only:

`domains.question.snapshot.warning_states["node:q2:ambiguous_geometric_order"]`

It would not acknowledge a document-wide warning or another Question. This operation was **not performed on production**.

A detached local copy of the fetched snapshot was used to simulate that one decision with the existing pure preflight function. Issues changed **15 -> 14**; only the q2 warning disappeared. Both document-level warnings remained unreviewed. This proves exact-ID targeting and the independent document aggregate requirement without modifying production.

### Aggregate duplication distinction

`draft:document:ambiguous_geometric_order` and `node:q2:ambiguous_geometric_order` have distinct IDs and scopes, but this Test's document flag is a roll-up of the same q2 node finding. They therefore duplicate the underlying finding across global and local review scopes and require separate decisions today. This is a catalog/UX duplication concern, **not** duplicate backend emission of the same ID and **not** the cause of erroneous Question ownership. There is only one order warning under q2 itself.

## Narrow recommendations — not implemented

1. For the observed local warning, preserve the source-review requirement and exact owner/ID. Clarify this code's labels/reason consistently in `reviewLabels.ts` and `authoring_question_issues.py`: e.g. 「本文・表の読み取り順を確認してください」, explaining that spaced/table columns caused uncertain extraction order. Do not instruct teachers to reorder Questions or make meaningless body edits.
2. Where feasible, expose the existing page/source-span/bbox evidence for the flagged line, so teachers can compare the table rather than guess. This is separate from ownership repair; none is needed here.
3. If removing redundant aggregate acknowledgments is desired, make a separate narrowly scoped catalog/readiness change: distinguish genuinely document-only findings from aggregates fully covered by owned warnings. Preserve true document warnings and explicit decisions. Do not suppress all owner-null warnings or automatically acknowledge findings merely because body text was edited.

Existing saved Tests need **no ownership/state migration** for this case. Wording clarification can apply without changing stored warning IDs or decisions. A future aggregate-dedup change must handle old pinned warning catalogs non-destructively and keep historical/confirmed snapshots immutable; it must not require re-analysis or silently lose review decisions. Other Tests with wide tables/multi-column content can receive the same conservative flag and misleading label, but this inspection found no evidence that neighboring Questions inherit it.

## Read-only safety and repository

Only login/session authentication plus GET requests were sent to production. Browser non-GET content requests were blocked defensively; no content-write attempt occurred. Navigation/highlight was inspected without pressing 確認済みにする, changing state, Save or analysis. Exact working revision payload before/after reload was unchanged, including edit_version, timestamp and hash. Dedicated Test impact reports **Submissions=0, grading jobs=0**. No inference or grading request was sent. No deployment, migration, source/content edit, warning acknowledgment, commit or push occurred.

Credential literals were checked without displaying them; no credential screenshots, tokens, cookies or HAR were saved. Temporary fetched source/API evidence stayed outside the repository. No product/test/migration/configuration file changed.

Git status before diagnosis: **clean** (`git status --short` produced no output).

Git status after diagnosis:

```text
?? docs/internal/reports/question-review-warning-production-diagnosis.md
```

`git diff --check` passed. Implementation/regression suites were not run because this is diagnosis-only.
