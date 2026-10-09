# J.UI.12b-fix15 — Manual PDF Diagram Crop Fallback

## Result

**READY_FOR_PRODUCTION_VALIDATION** — implementation and automated verification complete; deployed manual-crop acceptance remains.

## Baseline

- HEAD: `af8d2ccf077c4dd63b0bcdd7056a9a1fea3194c6`; initial git status clean, fix14b committed.
- Scope: Answer manual PDF crop only. No schema migration, publication, StudentAnswer crop, production access, commit, push or deployment.

## Architecture and UI

The final fallback appears after automatic candidates and the same-major reuse section: **PDFから切り取る**. It explicitly identifies the Answer entry's own source PDF and switches the left viewer to that binding. A different currently displayed Question/Rubric PDF is not silently used. Teachers can select a page, drag a rectangle, preview, then choose **使用する**, **やり直す** or **取消**. Escape cancels. Cancellation changes no working-copy assignment; preview only creates an unassigned cached artifact.

The existing DiagramOverlay maps pointer offsets from the SVG bounding rectangle into unrotated PDF coordinates using its PDF-sized viewBox and rotation transform. Zoom and scroll alter the bounding rectangle, not the saved PDF coordinate system. This preserves existing viewer pan/zoom and source range editing. Selection is one page at a time.

`ManualPdfDiagramReview` renders the teacher-selected rectangle through the existing native crop renderer. It does not run native grouping, Ricoh, LLM or OCR. Manual crop uses zero extra renderer margin and permits a valid full-page rectangle; renderer resource limits still apply. Page/bbox validity and source SHA integrity are enforced. Automatic child/parent matching is not applied to manual crops.

An immutable server manifest binds the crop to Answer source identity, material ID, page, original bbox and target Question identity. Records retain `source_type=manual_pdf_crop`, `scope=manual`, source PDF/IR hashes, material, target, crop SHA/artifact, page/bbox and explicit teacher confirmation. The containing Answer entry retains its source draft/artifact binding. Save revalidates the manifest, source and artifact; client-supplied paths and provenance are not authoritative.

Existing Answer diagram assignment, dirty state and saved-entry baselines are reused. After acceptance the exact fix14b guidance appears:

> 他の小問で図を再利用するには、図を選択した後に保存してください。

Save clears the guidance. Only saved accepted valid diagrams enter existing same-major reuse; manual provenance survives independent sibling assignments and reload/Back/resume. Automatic discovery, source-bound crop correction and fallback rules are unchanged.

## Verification progress

- Initial manual backend group: 6 passed after correcting the expected existing Save-validation status (409, `AUTHORING_ANSWER_SOURCE_INVALID`). Invalid page, zero area, page-external bbox, stale edit version and forged material ID are rejected.
- Combined manual/authoring/source geometry backend group: 32 passed before the additional same-major manual-reuse regression.
- Real Sample Q5 manual browser: passed (18.5 seconds). Actual PDF upload, split, discovery, manual correction, accept, Rubric interaction and old Save/resume remain covered; added manual fallback cancel, fit-mode coordinate checks, crop preview, acceptance, saved provenance, reload/Back/resume and sibling manual reuse.
- Additional direct same-major reuse regression prohibits native candidate grouping and verifies unrelated-major exclusion, artifact access and independent assignment.
- Final focused actual Sample Q5 + split group: **5 passed**, 27.7 seconds, grading jobs **0**. Page fit, width fit and exactly 74% displayed zoom preserve the same PDF bbox after scrolling.
- Full backend checkpoint: **942 passed, 1 skipped, 22 warnings**, 209.08 seconds. A final rerun follows the explicit Answer-role guard added to both manual source/preview endpoints.
- Full Chromium checkpoint: **64 passed**, 2.6 minutes, grading jobs **0**. Final verification follows the last manual-response lifecycle guard and presentation wording.
- Manual targeted tests: **7 passed**; includes explicit foreign-Test, deleted-binding and forged material rejection, plus same-major manual reuse without native discovery.
- TypeScript passed; ESLint has **0 errors / 19 existing warnings**; Ruff and diff checks passed. Production Next builds pass through the browser harness.

## Diagnostics encountered

The first manual browser run reached saved manual reuse but used an incorrectly nested `has` locator; the candidate was present. The locator is now relative to each article. A backend artifact-path test initially omitted the existing preview-manifest step required by the HTTP flow; it now exercises `preview` before requesting the preview path. No safety assertion was removed.

## Remaining acceptance

Real deployment must verify manual selection/preview/accept, cancellation/Escape, zoom/scroll coordinate accuracy, Save/reload/Back/resume, and Q3(1) → Q3(2) manual reuse. J.UI.12c and drag-and-drop remain deferred.

## Lifecycle safety

Manual operations share the existing request epoch and target scope. A delayed source/preview response after switching Question or unmounting its editor is discarded. An E2E delays the real source response, switches to the sibling, releases it and verifies selection mode does not reappear. Both endpoints also verify the bound material is actually ModelAnswer-role; legacy mixed sources cannot silently become the manual crop source.

## Files changed

- `src/scoring/manual_pdf_diagrams.py`: teacher crop manifest, page/source validation, pure native rendering, decision/artifact revalidation.
- `src/scoring/api/test_authoring.py`: authorized Answer-only manual source metadata and crop-preview endpoints; existing diagram image URLs serve manual artifacts.
- `src/scoring/model_answer_diagram_review.py`: manual records load/validate/preview alongside existing scopes.
- `src/scoring/model_answer_diagram_reuse.py`: revalidate manual origins through the existing same-major saved-assignment reuse engine.
- `src/scoring/diagram_review.py`: allow the explicit manual provenance field in diagram records.
- `src/scoring/diagram_regions.py`: instance crop policy support; default automatic policy remains unchanged.
- `frontend/components/reviews/DiagramReview.tsx`: final-fallback controls, page choice, PDF selection, preview/accept/cancel/retry, manual labels and stale-response guard.
- `frontend/components/reviews/AuthoringCandidates.tsx`: enable fallback only for Authoring Answer diagrams.
- `frontend/app/tests/[testId]/authoring/page.tsx`: show the explicit Answer material in the source pane during manual selection.
- `frontend/types/diagrams.ts`: explicit manual scope.
- `frontend/e2e/authoring-sample-q5-diagram-real.spec.ts`: actual-PDF manual workflow and coordinate/cancel/lifecycle/persistence/reuse assertions.
- `tests/test_manual_pdf_diagrams.py`: seven focused API/domain regressions.
- This report.

## Final automated results

- Full backend after final backend change: **942 passed, 1 skipped, 22 warnings**, 207.75 seconds.
- Final normal production-like Chromium after final product change: **64 passed**, 2.6 minutes; grading jobs **0**. Two preceding full normal checkpoints also passed (64 each).
- Actual Sample Q5 scenario in the final suite: **passed**, 19.0 seconds, including manual cancellation/Escape, delayed source/target-switch safety, fit/74%/scroll coordinate agreement, preview-only clean state, explicit acceptance dirty state, saved manual provenance, reload/Back/resume and sibling reuse. Existing auto discovery, crop correction, Rubric/shared-source interaction and sibling reuse remain covered in the same scenario.
- RuntimeManager counters remain unchanged for the whole manual flow and reuse. The backend test also forbids native grouping during manual creation, validation and reuse.
- Foreign Test/source, deleted binding, stale version, zero area, outside-page bbox, invalid page and forged material provenance are rejected. Server manifest and crop geometry remain authoritative.
- Formal Questions/Answers/Rubrics stay unchanged; the actual fresh Test has no published formal entities. No authoring grading jobs are launched.
- TypeScript: passed. ESLint: **0 errors, 19 existing warnings**. Ruff: passed for changed Python files. Production Next build: passed. `git diff --check`: passed.
- Additional existing truncated-Ricoh trust/override/reuse browser group: **3 passed**, 9.3 seconds, grading jobs **0**.

## Deliberate limits

The source is explicitly the current Answer entry's Answer-role PDF; arbitrary other-role PDF selection is not offered. A valid Answer source and saved gradable target are required. The page selector supports one page per crop. Preview creates a cached, unassigned artifact; acceptance changes only the local Answer working copy until Save. Unaccepted cache cleanup is out of scope. No polygon, cross-page selection, external image upload, semantic recognition or StudentAnswer feature is added.

## Final checkpoint

After the last product change, the normal production-like Chromium suite passed **64/64** (2.6 minutes), including the real Sample Q5 manual flow. During manual source/preview requests, competing diagram controls are disabled and `aria-busy` reflects the operation. Question navigation remains available and invalidates the pending result. Final TypeScript, ESLint (0 errors / 19 existing warnings), Ruff, Next production build and diff checks passed.

No known reproducible defect remains in the requested manual-crop workflow. Only deployed acceptance is outstanding. All acceptance fixtures are disposable; production Q5 was not accessed or mutated. No schema migration, commit, push or deployment was performed.

## Final git status

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/DiagramReview.tsx
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/types/diagrams.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/diagram_regions.py
 M src/scoring/diagram_review.py
 M src/scoring/model_answer_diagram_reuse.py
 M src/scoring/model_answer_diagram_review.py
?? docs/reports/j-ui-12b-fix15.md
?? src/scoring/manual_pdf_diagrams.py
?? tests/test_manual_pdf_diagrams.py
```
