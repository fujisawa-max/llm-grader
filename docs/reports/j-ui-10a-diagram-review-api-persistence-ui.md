# J.UI.10a Diagram Review API, Persistence & UI Integration

Phase result: **READY_FOR_PRODUCTION_VALIDATION**.

The Question and ModelAnswer teacher workflows are implemented and pass automated validation. Actual deployed Sample Q5 Question3 / answer diagrams have not been tested; this report does not claim real-model or production acceptance.

## Foundation and ownership

J.UI.10's `diagram_regions.py`, `diagram_sources.py`, native `vector_elements`, `PyMuPdfRegionRenderer`, `crop_geometry`, `RunArtifactAdapter` and transformation-aware Question ownership remain the shared foundation. No Question-specific or ModelAnswer-specific crop engine was created.

Previously, Question discovery required an owned figure anchor. It now derives exclusive page bands from retained native text/figure IDs and their geometry through `owned_native_ids()` / `_source_owner()`. Reviewed splits and reparenting use source origin/slices, not global text equality or newly edited prose. Different owner anchors bound each band. Unresolved/overlapping/duplicated source evidence and excluded sibling anchors reserve boundaries rather than allowing a neighboring Question to expand into them. Figure-only historical nodes retain a bounded figure envelope. Shared/atomic ambiguous ownership remains unresolved; no exclusive ownership is invented.

Historical IR without vector paths is augmented in memory from its hash-verified original PDF; immutable IR/artifacts are not rewritten. `native_vector_elements()` is shared by new extraction and this compatibility path. Candidate IDs depend on domain, target, source SHA, page, sorted source IDs and deterministic union geometry, and remain stable under source-array reorder.

ModelAnswer uses saved Question spatial regions and rejects overlapping same/deeper competing regions. Question and ModelAnswer retain separate identities and decisions even when storage can reuse crop bytes.

## API and authorization

Both resource paths provide:

- `GET .../diagrams`: geometry/cache plus saved decisions; no Ricoh inference.
- `POST .../diagrams` with `expected_revision`: explicit discovery; Ricoh only for ambiguous geometry.
- `POST .../diagrams/{candidate_id}/crop-preview` with revision and four `final_bbox` coordinates: validated preview proposal, not persistence.
- `GET .../diagrams/{candidate_id}/crop?crop_sha=...`: authorized source-derived crop preview.

Question prefix: `/api/v1/question-import-reviews/{review_id}/nodes/{node_key}`.
ModelAnswer prefix: `/api/v1/model-answer-import-drafts/{draft_id}/entries/{entry_id}`.
Formal ModelAnswer preview: `/api/v1/model-answers/{answer_id}/diagrams/{candidate_id}/crop`.
Formal Question assets use the existing authorized TestQuestionAsset endpoint.

Existing review/draft/Test/Course authorization remains in force. Tests cover anonymous 401, student/other-Course teacher 403 and foreign candidate rejection. Paths, source PDF selection and automatic bounds are server-derived. Client artifact paths/hashes are not trusted: Save rederives canonical metadata. No filesystem path is returned as a preview URL.

## Geometry, Ricoh and crops

Connected native visual primitives form bounded candidates; short owned labels may join, prose does not connect components. Separate diagrams retain order by page/bbox. Ambiguous grids remain untrusted without successful assistance.

`diagram_vision.py` connects the optional grouping callback to RuntimeManager's existing `ocr` Ricoh profile. The task is WHERE only: known element IDs/groups/confidence, no coordinates, description, graph meaning, transcription or solving. Temperature is zero, thinking is disabled where supported, JSON schema constrains IDs and strict validation rejects unknown/duplicate IDs, extra fields, malformed/truncated output and low confidence. No broad-union rescue is used when exclusive geometry cannot be proved. Diagnostic codes/response field/finish reason are retained.

Clean geometry, resume and manual correction call no models. Managed Ricoh cold start and warm PID/started_at reuse pass. Uni-MuMER and Ornith are not used by the diagram engine. Runtime configuration/lifecycle is unchanged.

Existing crop policy remains: deterministic union, 6pt padding/page clamp, 2x render, 55% maximum page area, 4096px per-side/8M pixel limits, 16 candidates and 2048 visual elements per page. Manual bounds must additionally keep the **padded** crop inside the current exclusive Question/entry band and outside competing source bounds. Page containment alone is insufficient. Automatic/final/padded bounds, dimensions, SHA and teacher-adjusted flag remain separate.

## UI and persistence

A shared `DiagramReview` section appears below Question content (図の確認) or inside the Answer editor (模範解答の図). It provides ordered crop previews, page/state/source diagnostics and explicit この図を使用 / 対象外にする / 範囲を修正. Accepted state is 使用中; excluded state is 対象外. Nothing is automatically accepted, saved or registered.

Selecting a candidate highlights its source on the existing left PDF and changes page. Shared `DiagramOverlay` supports drag rectangles in PDF coordinates, including rotation transforms; four coordinate inputs provide a keyboard-accessible alternative. Preview update is server-validated; 範囲を適用 and キャンセル remain explicit. Existing PDF zoom/fit/navigation/pan and sticky workspace layout are retained. Async responses cannot populate another selected target.

Local accepted/excluded/manual decisions are submitted through the **existing** Question revision Save and ModelAnswer draft Save. Compact metadata is validated and persisted in optional `diagram_records`; crop bytes remain content-addressed artifacts, not JSON/base64 in entities. Save/reload and continuation restore state using GET/cache, without inference. Ownership/source changes mark old decisions stale; invalid decisions cannot be saved/applied blindly, and obsolete crop refs are not served as current previews. The teacher can explicitly remove stale records.

Existing figure anchors/confirmation remain compatible. Diagram decisions synchronize with legacy figure decisions; excluded figures no longer block registration. Multiple legacy anchors belonging to one accepted visual candidate transfer one artifact. New vector candidate presence adds **no registration blocker**. Existing actionable figure review controls and issue navigation remain available.

## Formal transfer

Only explicit formal registration transfers accepted records. Question registration copies the hash-verified PNG into existing confirmation assets and creates TestQuestionAsset with source/review/domain provenance. ModelAnswer registration stores compact accepted diagram provenance with a durable relative artifact reference and authorized formal preview. Excluded/unreviewed records are not transferred. Local diagram actions and Save alone do not modify formal Question/ModelAnswer data.

Hierarchy, scores, source fidelity, review confirmation, saved/local/formal separation and Rubric behavior are unchanged.

## Validation

- Backend review/OCR/normalization/formatting/Question import/ModelAnswer/Rubric/auth regression suite: **377 passed**.
- Final focused diagram suite: **63 passed** (overlaps the regression suite; includes an additional stale-preview regression).
- Native PDF and RuntimeManager deployment/hardware/lifecycle suite: **69 passed, 1 deselected**. The excluded duplicate-upload assertion is the documented pre-existing J.UI.10 test mismatch: it expects rejection while compatible analysis continuation is supported. It was not changed here.
- Production Next build, non-loopback HTTP, real FastAPI, disposable SQLite, actual RuntimeManager and managed stubs: **37 browser/check tests passed**, including two new diagram workflows.
- Final dedicated diagram browser suite: **3 passed** (two overlap the main suite; additional saved-split child/sibling ownership scenario).
- Separate hard-formatting fallback browser suite: **1 passed**.
- Diagram browsers verify Question crop/highlight, drag adjustment, accepted/excluded Save/reload, explicit formal asset transfer; ModelAnswer separate artifact, numeric adjustment, Save/reload and accepted-only formal transfer. The additional split scenario persists a source-backed reviewed split through the real API, then selects the child/parent/sibling in the browser and verifies exclusive crops. Runtime call counters do not increase during diagram discovery/decision/manual correction/reload.
- Existing browser coverage includes sticky layout/PDF controls, caret/newline/DOM/IME paths, split source ownership, OCR, issue navigation, continuation and Rubric editing/registration.
- TypeScript: PASS. ESLint: **0 errors, 19 existing warnings**, no new warnings. Production build: PASS (existing CSS autoprefixer warnings remain).
- Ruff on changed Python/tests: PASS. `git diff --check`: PASS.
- **Grading jobs = 0** in isolated API/browser tests. Production/Q5 databases, grades, OpenWebUI, runtime config and model files were not modified; no model download occurred.

## Files and Git

Backend: `diagram_regions.py`, `diagram_sources.py`, new `diagram_review.py` / `diagram_vision.py`, `pdf_native.py`, Question/ModelAnswer API routes, Question revision/import handling and review-document compatibility.

Frontend: shared new DiagramReview/DiagramOverlay/types; existing Question workspace/EvidencePanel, Answer review page, both PDF preview integrations, API/review types and small styles.

Tests: new diagram API/vision/browser scenarios, managed vision stub support and isolated browser fixture seed. This report is service-facing documentation.


Changed service files (19 modified, 9 new; all unstaged):

- `frontend/app/globals.css`
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`
- `frontend/components/PdfPaneViewer.tsx`
- `frontend/components/SourcePdfPreview.tsx`
- `frontend/components/reviews/EvidencePanel.tsx`
- `frontend/components/reviews/PdfPreview.tsx`
- `frontend/components/reviews/ReviewWorkspace.tsx`
- `frontend/lib/api/modelAnswerImports.ts`
- `frontend/types/reviews.ts`
- `src/scoring/api/model_answer_imports.py`
- `src/scoring/api/question_reviews.py`
- `src/scoring/diagram_regions.py`
- `src/scoring/diagram_sources.py`
- `src/scoring/pdf_native.py`
- `src/scoring/question_import.py`
- `src/scoring/question_reviews.py`
- `src/scoring/review_document.py`
- `tests/fixtures/runtime/llama_server_stub.py`
- `tests/run_runtime_browser_e2e.py`
- `docs/reports/j-ui-10a-diagram-review-api-persistence-ui.md`
- `frontend/components/reviews/DiagramOverlay.tsx`
- `frontend/components/reviews/DiagramReview.tsx`
- `frontend/e2e/diagram-review-real.spec.ts`
- `frontend/types/diagrams.ts`
- `src/scoring/diagram_review.py`
- `src/scoring/diagram_vision.py`
- `tests/test_diagram_review_api.py`
- `tests/test_diagram_vision.py`

Changes remain unstaged and uncommitted. No commit/push was performed. Local databases, logs, browser artifacts and credentials are not included.

## Production acceptance remaining

On the deployed Sample Q5, verify Question3's blank coordinate plane and the corresponding completed ModelAnswer diagram separately:

1. Discover the correct candidate; full axes/labels and plotted content are included without excessive prose or sibling source.
2. Select it; left PDF page/highlight matches the crop.
3. Accept, adjust via drag/numeric inputs and explicitly Save; reopen/reload and verify final bounds/state.
4. Exclude another candidate and verify saved exclusion.
5. Verify Question/ModelAnswer artifacts stay distinct and J.UI.9g layout/PDF controls remain usable.
6. Confirm confident geometry makes zero Ricoh calls; if ambiguity needs Ricoh, inspect its known-ID result/finish reason.
7. Formal registration need only be tested if the teacher explicitly chooses it; automated tests already verify accepted-only transfer.

Diagram meaning, comparisons and grading remain out of scope. Real Q5 crop quality and real Ricoh output are the remaining acceptance checks; synthetic/managed stubs do not substitute for them.
