# J.UI.9e Question-side Source-aware Math OCR & LaTeX Review Report

## Phase result

**PARTIAL.** Implementation and automated validation pass. One real deployed Question-side expression still requires teacher verification. RuntimeManager integration tests use managed model stubs; they do not establish actual NVIDIA/Ricoh/Uni-MuMER acceptance. No production credentials were requested or used.

## Current Question workflow

The source-backed editor is `/question-import-reviews/{review_id}`, implemented by `ReviewWorkspace` and `NodeEditor`. Native PDF import produces a verified source PDF, native IR and immutable automatic Question draft. The review projects native evidence into text/formula/figure items with source element IDs, page, bbox and reading order. Existing `PdfPreview` provides the shared source viewer.

The browser edits a local snapshot. `変更を保存` appends a server-side review revision. Formula/warning confirmation, `確認済みにする`, the import plan and `確認した問題を登録` remain separate actions. Formal registration creates TestQuestions through the existing append-only importer. Reviewed content can use the existing `新しい修正版で編集を再開`; editing/saving that review does not implicitly replace previously registered Questions.

The normal Question page continues to use its existing editor for manually authored Questions and read-only display for imported Questions. Existing registered-content correction APIs are unchanged. This phase adds OCR to the source-backed review editors, without inventing another draft layer or changing correction/versioning semantics.

## Shared architecture and domain adapter

New endpoint:

`POST /api/v1/question-import-reviews/{review_id}/nodes/{node_key}/items/{item_index}/math-ocr`

Input is current editing text, expected review revision and the saved item's immutable source reference. Arbitrary file paths, caller-generated crops and free-form page/bbox selection are not accepted.

`question_math_source.py` resolves the authorized review, verifies PDF/IR/draft/revision integrity, checks the saved item reference, and translates actual native IR elements into the existing segment representation. The shared `SourceMathOCR` engine receives only the verified PDF, native segments and current text. It does not need a Question entity or Question-specific transcription algorithm.

Reused without a second implementation:

- Geometry grouping, optional Ricoh prompt/schema validation and strict geometry fallback.
- Bounded PyMuPDF rendering, shared vision response parsing and Uni-MuMER inference.
- Candidate extraction, duplicate/noise filtering, source-guided detokenization and source validation.
- Ornith formatting-only eligibility, prompt, structural fingerprint and final validation.
- RuntimeManager lifecycle, shared API client conventions and `LatexNormalizationControl`.

The conservative core extensions are an optional `source_fragment` alignment mode and optional excluded native source regions. ModelAnswer callers retain the original `line` alignment and no exclusions by default.

## Source mapping, hierarchy and boundaries

Exact native strings are retained, including mathematical italic Unicode. Existing aliases are used only for math detection/validation; the Question document is not globally NFKC-normalized.

Question alignment accepts source fragments within a prose line, including Japanese text immediately adjoining a separately anchored expression. Lexical boundaries prevent matching inside a different Latin/Greek/math-font identifier, decimal or larger number. Ordered occurrence matching and neighboring source anchors preserve the two separate `24` numerators. Replacement uses explicit source spans; surrounding prose, numbering, line breaks and unrelated content are preserved.

Source IDs must belong to the automatic owner of the selected review node. Shared native IDs and source slices fail closed because their bbox can cross a sibling Question. Any padded crop intersecting native text outside that owner is rejected before Ricoh or Uni-MuMER inference. No neighboring Question content is borrowed. The operation does not modify hierarchy, IDs, parents, points, ModelAnswers or Rubrics.

Source-less/manual items and unaligned teacher-edited text do not receive guessed geometry. Structural edits must be saved before OCR; missing evidence returns a clear error/no-math result. A mixed native span containing Japanese prose cannot silently lose that prose: the shared source validator rejects a formula-only output missing the original text.

## Geometry, OCR and normalization

The supplied Precision geometry fixture retains seven source segments, including `𝑇𝑃` and both `24` occurrences. It becomes one confident geometry region and bypasses Ricoh. The observed union bbox is `[92.66400146484375, 502.7281188964844, 270.2300109863281, 521.2810668945312]`; padded crop is 380 × 62 px. A representative two-dimensional PDF fixture renders the numerator/denominator structure within those coordinates.

Managed Uni-MuMER returns a spaced/repeated response in `choices[0].message.reasoning_content`. Deterministic selection produces:

```latex
Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=\frac{24}{30}=0.800
```

Ornith remains stopped for this successful deterministic path. The harder formatting fixture invokes `ornith_rubric_draft`, passes strict structural comparison and final source validation, and reuses both managed runtimes on the second request. No model, GPU assignment, startup timeout or per-request stop policy changed. Existing Ricoh failure/truncation and semantic-mutation regression tests pass.

## Question UI and state semantics

Text and formula editors reuse `数式をLaTeX化`, loading spinner/aria-busy, crop/source diagnostics, reconstructed text and KaTeX preview. A valid proposal enables `この変換を適用` directly; there is no additional confirmation checkbox. The helper is `適用後も数式は編集できます。`

- Request/preview changes no local, saved or formal content.
- Cancel preserves the current editor.
- Apply updates only the browser-local editor and compact applied-proposal metadata.
- Manual editing remains available immediately.
- Explicit Save creates the review revision; formal Questions remain unchanged.
- Existing confirmation/final import controls formal registration.
- Changed editing text makes a proposal stale; changed node/revision resets the control. Rejected/no-change, invalid syntax, unavailable source and in-flight results cannot apply.

Text fields retain Markdown. Raw-LaTeX formula fields have a small target-format adapter: one expression strips display delimiters; multiple independently reviewed expressions become an ordered `gathered` environment. The actual field value is KaTeX-checked before Apply. Prose-bearing proposals that cannot fit a raw formula field remain unappliable. This is presentation conversion, not a second OCR/normalization engine. Existing Question formula confirmation remains distinct; manual formula edits follow its existing unreviewed/confirm workflow.

## Authorization and provenance

The new route uses the unchanged staff/domain dependency, authorizing the owning Course/Test through the review resource. Unauthenticated requests, students and other-course teachers are denied before OCR. Generic text-tool staff-only authorization is unchanged.

Applied metadata retains review/node/item/revision, material ID, source PDF/IR hashes, original/normalized text hashes, native segment IDs/text, page/bbox/crop bbox, grouping/normalization method, Ornith use and accepted validation. Save validates IDs against the source node and coordinates/text against immutable native IR. Formal Question provenance retains this compact history. Extra debug fields, wrong hashes, invented text/coordinates and neighboring IDs are rejected. Crop images and huge raw responses are not persisted into formal Question data. No database migration is required.

## Tests and browser results

- **278 backend tests PASS** across Question OCR/review/import, grouping, candidates, formatting fallback, source OCR, generic LaTeX and ModelAnswer draft/import/API tests. Question-specific tests: **26 PASS**.
- An existing recursive-score test also failed on untouched HEAD because its fragmented native formula was unresolved. Its fixture now performs the existing teacher-edit confirmation; production registration validation was not relaxed.
- **28 production-build Chromium regression tests PASS** on non-loopback HTTP, using real FastAPI, disposable SQLite, actual RuntimeManager and managed llama-server stubs.
- **1 additional formatting-fallback browser test PASS** with cold/warm PID reuse and local/saved/formal isolation.
- Final Question/ModelAnswer source-OCR rerun: **3 PASS**, including surrounding-prose preservation, multiple-expression target formatting, stale/rejected/invalid proposals, keyboard Apply, Cancel, manual editing, explicit persistence and final registration.
- TypeScript PASS; production Next.js build PASS; ESLint **0 errors / 19 warnings**; `ruff check src tests` PASS; `git diff --check` PASS.
- Unexpected browser/page errors: **0**. Grading jobs: **0**. ModelAnswer/Rubric values are explicitly unchanged in the Question scenario.

Pytest reports existing Starlette deprecation and ORM collection warnings. Builds report existing lint warnings; neither is a test failure.

## Real deployment acceptance still required

1. Open an existing source-backed Question review and select a Question containing a real PDF equation. Use the existing edit-resume action if necessary.
2. Request `数式をLaTeX化`; verify the correct material/source SHA, page, complete crop and source spans, including standalone numerators.
3. Inspect grouping method/Ricoh diagnostics, actual Uni-MuMER response field, selected candidate/final validation and KaTeX preview.
4. Confirm Apply is available. If the teacher chooses to Apply, verify immediate manual editing remains possible and saved/formal content is unchanged before explicit persistence.
5. Cancel or discard unsaved changes if acceptance is observation-only. Do not register production data merely for testing.
6. A second explicit request should retain the managed PID/started_at. Do not require Ricoh or Ornith when the deterministic path succeeds.

Useful non-secret observations: review/node/item/revision, source IDs/SHA, grouping summary, bbox/crop dimensions, selected response field, normalized candidate, final validation/status and UI Apply availability. Credentials, cookies, tokens and image bytes are unnecessary.

## Files changed and Git status

Backend:

- `src/scoring/question_math_source.py` (new)
- `src/scoring/api/question_reviews.py`, `src/scoring/api/app.py`
- `src/scoring/math_region_grouping.py`, `src/scoring/source_math_ocr.py`
- `src/scoring/review_document.py`, `src/scoring/question_reviews.py`, `src/scoring/question_import.py`

Frontend:

- `frontend/lib/questionMathSource.ts` (new)
- `frontend/components/LatexNormalizationControl.tsx`
- `frontend/components/reviews/NodeEditor.tsx`, `ReviewWorkspace.tsx`
- `frontend/lib/api/textTools.ts`, `frontend/lib/latexErrors.ts`, `frontend/types/reviews.ts`

Validation/documentation:

- `tests/test_question_math_ocr.py` (new), `tests/test_question_import.py`, `tests/run_runtime_browser_e2e.py`
- `frontend/e2e/question-math-ocr-real.spec.ts` (new)
- This report (new).

All changes are unstaged; no commit/push. New files are service source/tests/report, not local-development helpers. Production/PostgreSQL/Q5 grading data, artifacts, formal grades, OpenWebUI and deployment model files were not touched.

## Remaining issues / final decision

Actual deployed Question-side model acceptance is unverified. Partial/sibling-shared native spans are intentionally rejected until a safe finer source mapping exists; the normal registered-content correction UI is unchanged. Diagram extraction and production debug-mode cleanup remain out of scope.

**Phase J.UI.9e: PARTIAL — implementation and automated tests pass; real Question-side production acceptance is pending.**
