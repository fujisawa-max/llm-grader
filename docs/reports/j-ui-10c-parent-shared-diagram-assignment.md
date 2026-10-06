# J.UI.10c — Parent-Fallback & Shared Diagram Assignment

Phase result: **READY_FOR_PRODUCTION_VALIDATION**.

## Root cause and production evidence limits

J.UI.10b resolved an entry exclusively through `question_regions` matching the assigned child ID. Missing child regions were rejected; existing child regions containing no native diagram returned an empty list. The adapter never traversed `TestQuestion.parent_id`, and the UI ended at the empty-result message. A diagram remaining in the original Problem3 parent source region therefore could not be discovered/assigned by its split children. Diagram identity and UI highlight/readiness also used the discovery target as if it were the answer assignment.

The current deployed Q5 draft's persisted spatial mappings/IDs were not available in this workspace. No production database, cookie, credential or model connection was used. It is not possible to distinguish “missing child mapping” from “mapped child contains no diagram” in that particular deployed record without its response. New authorized diagnostics distinguish those cases explicitly.

Read-only inspection of the locally retained real Q5 ModelAnswer PDF did confirm the source shape, rather than assuming three independently drawn answers:

- Source SHA: `6ce6cc39071755205e905e60b2a70feaaf8d63456113c77ff4c529c9c9b1c420`.
- One page; 1,824 extracted native characters; 112 drawing objects and 5 images.
- `問題３ 決定境界の作図【30 点】` appears in the left column, with numbered tasks 1/2/3 below it. This original source does not provide separate `(1)/(2)/(3)` answer headings for each reviewed child.
- Whole-PDF geometry inspection (temporary artifacts only, no VLM) found five components. The lower-right component covering the relevant answer area has bbox `[318.5, 523.5199584960938, 567.7000122070312, 774.6759643554688]`, 37 source elements, and `geometry_ambiguous`/`unresolved` status. This is a geometry observation, not a claim that all of that component is the diagram or that a deployed crop passed teacher review. Ricoh WHERE and/or teacher crop review still need deployed validation.

Existing Q5 files, PostgreSQL and grading records were not changed. Historical local source inspection is not substituted for current production acceptance.

## Discovery and architecture

`ModelAnswerDiagramReview` is a small domain coordinator over the existing `DiagramReview`, `DiagramRegionExtractor`, source adapter, renderer and content-addressed storage. It does not contain a second crop engine or vision prompt.

1. Exact scope uses the existing entry geometry/source boundary. If it has candidates, no ancestor or PDF discovery is performed, and broader-scope API requests are rejected.
2. If exact is empty, traverse the current same-Test Question tree nearest parent first. Only parents having saved spatial regions are eligible. Continue to higher ancestors when a nearer region is empty. Existing same/deeper competing source boundaries remain excluded; a parent's candidate does not silently borrow a child's exclusive source.
3. If all eligible ancestors are empty, offer PDF scope. Page-wise geometry discovery occurs only on an explicit teacher request (or validation of a previously saved PDF assignment). It creates individual bounded diagram candidates, never a default whole-page crop.

Existing diagram endpoints accept `scope=exact|parent|pdf`; omitted scope retains exact discovery behavior, while GET resume derives the scopes from saved records. Transient manual entry authorization/revision handling from J.UI.10b remains intact. No free source path, owner ID, page or automatic bbox is accepted from the browser.

Responses include `fallback` metadata and authorized `diagnostics`:

- `assigned_question_id`
- `source_sha256`
- `exact_source_region_present`
- `exact_candidate_count`
- `exact_source_element_count`
- `exact_reason_code`: `diagram_exact_source_region_missing` or `diagram_exact_no_candidates`
- `parent_source_question_id`
- `fallback_scope`

These are available in the existing UI's collapsible “図の探索情報”. Parent labels use the existing canonical `question_choices()` path builder.

## Ownership versus assignment

A parent candidate keeps `target_key` and `source_question_id` equal to its source parent, while `assigned_question_id` is the edited child. Its source IDs, automatic bbox, candidate ID and crop SHA remain source-derived. Parent review cache identity is based on the source owner, not a transient answer entry. Parent region ordering is canonicalized.

PDF candidates have a PDF-source target key. `source_question_id` is reported only when one unique deepest saved Question region contains the candidate; otherwise it remains null. Source ownership is never invented.

Each answer entry stores its own accepted/excluded/candidate assignment. Children can reference the same candidate ID and content-addressed artifact without sharing decision state. The same unmodified geometry reuses crop bytes. Each assignment can also have a different final bbox/crop SHA; the original automatic candidate remains shared.

Save and formal registration independently validate source/material SHA, candidate membership, scope eligibility, source owner and assigned child. Foreign material provenance, invented candidate IDs/owners, changed assignments and stale source values are rejected. Existing records lacking scope/assignment fields are treated as exact assignments; no migration is required.

## UI and persistence

The existing `DiagramReview` is extended, rather than replaced:

- Exact candidates retain the prior interaction.
- Empty exact discovery offers `親設問「問題3」に図候補があります。` and `親設問の図候補を表示`.
- If all ancestors are empty, offer `このPDFのすべての図候補を表示`.
- Preview shows source scope/path/page; the sticky editor selector stays on the current child.
- PDF page, rectangle highlight, crop preview, accept/exclude and manual correction use existing components.
- Merely viewing parent/PDF candidates does not mutate a draft or enable diagram-only registration. `この図を使用` is required.
- Explicit Save persists assignment decisions. GET resume/reload restores them without discovery POST or inference.
- Explicit formal registration transfers accepted diagrams only, retaining both source owner and assigned ModelAnswer Question. Empty text remains empty; no explanatory/placeholder text is generated.

Parent crop correction uses existing source-owner bounds and competing regions. For PDF candidates with a known owner, manual correction must remain within that owner's safe boundary. Unknown-owner correction is limited to a 24-point envelope around the automatic component (including crop padding) and cannot overlap another diagram. Page/pixel/area limits still apply. Malformed saved bounds return structured rejection rather than a 500.

## Concurrency and model behavior

The first browser run exposed an existing concurrent artifact write race: GET/POST sharing a new diagram cache used the same fixed `.tmp` filename. Diagram JSON cache, preview and crop metadata writes now use unique temporary files with atomic replacement. The general grading/CLI JSON writer is unchanged. An eight-request concurrent shared-parent API regression passes and reuses one candidate/crop SHA.

Geometry remains first. Exact success skips parent/PDF work. Confident scopes do not start Ricoh. Ambiguous scopes reuse the existing managed Ricoh WHERE callback and strict known-ID JSON checks; cached attempted results are not inferred again merely to display a parent candidate. Failed/unresolved groups remain untrusted. Save, GET resume, correction and registration run no inference. Uni-MuMER and Ornith are not used for diagrams; RuntimeManager lifecycle/config is unchanged.

## Automated validation

Environment: production Next.js builds, non-loopback HTTP, real FastAPI, disposable SQLite, actual RuntimeManager and managed stubs. No production data was used for persistence tests.

- Broad backend regression: **295 passed** (includes the initial 16 new scope tests).
- Final scope tests: **20 passed**, including additional malformed-bounds, foreign-material, no-inference and stable-ID checks; overlap with the broader run.
- Diagram/extraction/vision regression: **86 passed** before the last additional scope cases (overlapping counts).
- Production-like browser suite: **41 passed**.
- Dedicated diagram browser suite: **6 passed**, overlapping the full suite.
- Hard formatting-only Ornith regression: **1 passed**, separately configured.
- TypeScript and production builds pass.
- ESLint: **0 errors, 19 existing warnings**. Existing CSS autoprefixer warnings remain.
- Ruff and `git diff --check`: pass.
- Grading jobs: **0**.

The new browser fixture deliberately has one completed shared diagram beneath the original Problem3 tasks, with saved parent-owned mapping after split; it does not fabricate a separate diagram per child. It verifies child (1) exact-empty → parent offer → preview/highlight → explicit accept → manual correction → Save/reload, then child (2) using the same source candidate. A separate no-region fixture verifies explicit PDF fallback, absence of automatic acceptance, Save/reload and formal transfer. Both preserve child selection, empty text and separate source/assignment provenance. The geometry scenarios add zero model calls, including reload and registration.

Existing Question diagrams/split ownership, automatic/manual ModelAnswer diagrams, stale validation, continuation, issue links, caret/IME, source math OCR, Rubric operations and left-source/right-editor layout pass their existing regressions. No authorization or grading rules are loosened.

## Files / Git

Modified:

- `src/scoring/api/model_answer_imports.py`
- `src/scoring/diagram_sources.py`
- `src/scoring/diagram_review.py`
- `src/scoring/diagram_regions.py`
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`
- `frontend/components/reviews/DiagramReview.tsx`
- `frontend/lib/modelAnswerRegistrationValidation.ts`
- `frontend/types/diagrams.ts`
- `frontend/e2e/diagram-review-real.spec.ts`
- `tests/run_runtime_browser_e2e.py`

New service files:

- `src/scoring/model_answer_diagram_review.py`
- `tests/test_model_answer_diagram_scopes.py`
- this report

Changes remain unstaged/uncommitted. No commit/push, model download, host-specific configuration, schema migration, production data update or formal grading change.

## Remaining deployed acceptance

On real Sample Q5, verify exact discovery for Problem3 > (1), the offered parent/PDF scope, correct completed-diagram preview/highlight, explicit acceptance, Save/reload/resume and diagram-only readiness. Verify (2)/(3) can reuse the source diagram as shared assignments without pretending exclusive child ownership. Actual ambiguous geometry must successfully pass real Ricoh WHERE or remain rejected; automated stubs do not prove this.

If the deployed offer differs from expectation, obtain only the authorized discovery response's `diagnostics`, `fallback`, and each candidate's `id/scope/source_question_id/assigned_question_id/page_index/automatic_bbox/grouping_method/status/reason_code`. These distinguish missing child mapping, empty geometry, missing ancestor region and unresolved grouping without needing credentials or crop bytes.
