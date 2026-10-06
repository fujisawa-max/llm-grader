# J.UI.10 Diagram Region Extraction & Review Report

## Phase result

**PARTIAL.** The shared extraction foundation and ownership adapters are
implemented and tested. The teacher-facing diagram workflow is **not implemented
yet**. This is not READY_FOR_PRODUCTION_VALIDATION: API/UI integration, review
persistence and formal registration of the new diagram records remain required.

## Existing architecture

- Question native IR retains image objects with IDs, bbox and image artifacts.
  Before this change, vector drawing paths were reduced to a page-wide
  `vector_summary`; individual axes/ticks could not be grouped independently.
- `question_structure.py` currently produces figure regions from embedded image
  groups. Vector evidence remains an unresolved flag. This routing is unchanged.
- Review nodes retain `figure_region` content anchors and `figure_decisions`.
  `EvidencePanel` already displays existing figure crops and source information.
  Accepted figures are existing registration requirements; no new blocker was added.
- `question_source_ownership.py` and `_source_owner()` preserve transformed
  ownership through reviewed source slices and explicit origins. Figure items
  currently have exclusive ownership; duplicated atomic references must fail closed.
- Question registration already has `TestQuestionAsset`, copies pinned PNG crops
  into confirmation artifacts and stores source/review provenance. It still uses
  the existing vision-pin path; new diagram crop records are not wired into it.
- ModelAnswer source entries retain native text segments and persisted spatial
  Question regions. The new adapter uses those regions rather than nearest text.
- Both review screens retain `ReviewWorkspaceLayout`, left PDF/right editor,
  sticky actions/selectors. Existing PNG/SVG Question highlighting and PDF.js
  Answer source viewer remain unchanged.

## Shared extraction foundation

`diagram_regions.py` provides one geometry/crop implementation. No mathematical
or diagram interpretation is performed.

Native extraction now additionally retains `vector_elements`, separately from
historical text/image `elements`. Each drawing path has a source ID, bbox, native
path order, primitive count and horizontal/vertical line counts. Zero-area path
bounds are preserved because individual coordinate axes are lines, not rectangles.
The extraction config records `native-vector-paths-v1`. Historical artifacts are
not rewritten or silently upgraded.

Geometry groups connected visual primitives with a 4pt adjacency threshold.
Short owned labels inside the visual envelope can be attached; prose never
connects components. Components smaller than 25pt in either dimension are
discarded. Separate disconnected diagrams remain separate. Source-array reorder
does not change candidate identity or grouping; raw IR SHA still records the
original IR ordering.

Rectangular line grids are ambiguous rather than automatically treated as
diagrams. Without assistance they return `diagram_geometry_ambiguous`. This
heuristic does not claim to distinguish all tables from diagrams.

## Ownership adapters

`diagram_sources.py` contains minimal adapters using the same extractor:

- Question: loads a verified review revision through `QuestionReviewService`,
  resolves transformed source origin, uses the current node's exclusive figure
  references, and retains ordered native text ownership for labels. Unresolved
  slices, duplicate/shared figure references and stale revisions fail closed.
- ModelAnswer: uses the entry's assigned Question and saved spatial Question
  boundaries. Competing same/deeper Question regions exclude a primitive.
  Missing source mapping is not guessed.

These are internal helpers, not exposed endpoints. They do not accept browser
filesystem paths. The Question adapter currently requires an existing owned
figure anchor; automatic vector-only figure discovery/ownership integration is
still pending. Historical IR without `vector_elements` is not backfilled.

## Ricoh

The shared engine accepts an optional bounded grouping callback only for
ambiguous geometry. Confident axes bypass it. Results must be JSON containing
known element-ID groups and finite confidence >= 0.9. Unknown/duplicate IDs,
coordinates, prose fields, malformed and truncated JSON are rejected.

**No production Ricoh client is connected yet.** Callback behavior is tested with
stubs. Existing RuntimeManager profiles/lifecycle are unchanged. Uni-MuMER and
Ornith are not used for diagram extraction.

## Crops and provenance

- Reuses `PyMuPdfRegionRenderer`, `crop_geometry`, coordinate transforms and
  `RunArtifactAdapter`; no parallel PDF renderer.
- 6pt padding, page clamp, 2x scale, existing 4096px per-side/8M pixel limits,
  stricter 55% maximum page-area ratio, maximum 16 candidates and 2048 visual
  elements per page.
- Hash-verified source PDF is checked at construction and again before crop.
- Candidate metadata includes domain/target, material/source/IR SHA, page,
  source IDs, source text/type/bbox/order, automatic bbox, grouping method and
  optional grouping confidence/result.
- Crop metadata includes final/padded bounds, dimensions, PNG SHA and relative
  artifact ref. Image bytes are content-addressed and reused. Question and
  ModelAnswer candidate identities are distinct even when crop bytes can deduplicate.
- Manual bounds are validated by the internal crop helper and preserve
  automatic/final bbox plus `teacher_adjusted`. **There is no manual-correction UI
  or public endpoint yet.** Domain boundary checks for manual expansion must be
  enforced when that endpoint is added; page containment alone is insufficient.

## Persistence and browser behavior

Only the low-level crop artifact cache is implemented. New accepted/excluded
diagram review state, explicit Save/reload, formal Question/ModelAnswer transfer,
PDF selection overlays and interactive bounds correction remain unimplemented.
Existing figure confirmation/import behavior is unchanged. No auto-accept,
auto-save or auto-registration was introduced.

## Validation

- New extraction/adapter tests: **36 passed**.
- Existing Question review/import, split/text provenance, Question/ModelAnswer
  math OCR, grouping, candidates, formatting, ModelAnswer import/drafts and
  generic text-tool authorization: **258 passed**.
- Native PDF tests: **8 passed**; one existing duplicate-upload expectation fails.
  That failure was reproduced against an isolated archive of unchanged HEAD
  source: `test_same_test_same_sha_is_rejected_but_different_test_is_allowed`.
  Current service supports compatible previous-analysis reuse, whereas this
  test still expects duplicate upload to raise. It was not changed in this phase.
- Existing production-build/non-loopback RuntimeManager browser suite:
  **35 passed** (22 browser scenarios plus 13 error-mapping checks).
- Separate managed hard-formatting fallback browser suite: **1 passed**.
- TypeScript: PASS. ESLint: 0 errors, 19 existing warnings.
- Production Next build: PASS; existing two CSS autoprefixer warnings.
- Ruff for changed Python: PASS. `git diff --check`: PASS.
- Browser harness reports **grading jobs = 0**. No production database/Q5 data,
  formal grades, OpenWebUI, auth or runtime configuration was changed.

The passing browser suites are **existing workflow regressions**, not acceptance
tests for a new diagram UI. No new diagram browser scenario exists yet.

## Files and Git

- `src/scoring/pdf_native.py` — modified.
- `src/scoring/diagram_regions.py` — new shared foundation.
- `src/scoring/diagram_sources.py` — new adapters.
- `tests/test_diagram_regions.py` — new tests.
- This report — new.

No commit, push or staging was performed. Source/report/test additions are
service-facing; no local databases, credentials, logs or generated crop artifacts
were added to Git.

## Remaining implementation and acceptance

1. Integrate vector candidates with Question figure ownership and legacy source
   handling without rewriting immutable source artifacts.
2. Add domain-authorized discovery/crop/manual-correction endpoints and validate
   manual expansion against sibling ownership and page boundaries.
3. Connect optional RuntimeManager-managed Ricoh WHERE assistance with strict
   JSON generation/truncation handling and safe failure diagnostics.
4. Add shared diagram review UI to both existing workspaces: crop, PDF highlight,
   accept/exclude, bounds correction and multiple diagrams.
5. Save validated compact diagram decisions into existing revisions/drafts;
   transfer only accepted artifacts/provenance at explicit formal registration.
6. Add new persistence/auth/manual/highlight browser acceptance scenarios.
7. Validate the actual existing Sample Q5 Question3 blank plane and ModelAnswer
   completed drawing on the deployed system. The synthetic fixture is not a
   replacement for production acceptance.

Production acceptance has **not** been performed. J.UI.10 remains **PARTIAL**.
