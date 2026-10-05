# J.UI.9d-fix1 Geometry-First Math Grouping Report

## Result

**Phase J.UI.9d-fix1: PARTIAL.** Software implementation and managed-runtime/browser validation passed. Actual NVIDIA/Precision/Uni-MuMER acceptance remains unverified: this workspace has no exposed production RuntimeManager, source draft, `/models`, Docker or NVIDIA tooling. Stub results are not evidence of real model transcription.

## Root cause and geometry

The former algorithm followed native text segmentation and a vertical-gap rule that rejected strongly overlapping same-line fragments. Native text boundaries therefore became OCR crop boundaries.

The new algorithm aligns immutable source occurrences to editing text, clusters same-page math fragments using vertical overlap/center distance, horizontal gaps and fraction-layer proximity, and computes union boxes from source coordinates. Independent equation labels, intervening prose, distant fragments and separate rows constrain merging. Reading order supports identity and replacement rather than defining visual boundaries.

The representative synthetic Precision case has seven native fragments. Running the previous algorithm gives four regions; the new algorithm gives one, retaining all seven IDs. Union bbox is `[30,37,330,68]`; padded crop is `[24,31,336,74]`, rendered at **624 × 86 pixels**. The synthetic crop was visually inspected. These are fixture measurements, not measurements of the deployed sample.

## Ricoh fallback

Confident geometry bypasses Ricoh. Ambiguous bounded neighborhoods use the existing `ocr` vision profile with a WHERE-only prompt: return known source segment IDs and confidence, never coordinates, LaTeX, corrected values or answers. Strict validation rejects unknown, duplicate, missing, disconnected or low-confidence groups. Final boxes always derive from supplied source bboxes.

Methods are `geometry`, `geometry_ricoh_validation` and `ricoh_assisted_repair`. Unavailable or invalid Ricoh output produces a diagnostic rejection instead of an unsafe union sent to transcription. The standard Precision fixture needs no Ricoh; a wider-gap fixture verifies repair. Whether deployed Precision needs Ricoh is unknown.

Deployment defaults reference the already available Ricoh GGUF/mmproj filenames. Paths/profile remain configurable; no models were downloaded and no GPU IDs were hardcoded.

## OCR, reconstruction and diagnostics

Uni-MuMER remains the transcription model via `math_ocr`. Shared response parsing retains content/final/answer/reasoning fallbacks. Outer dollar, bracket and fenced wrappers are removed without rewriting their contents. Numeric and identifier safeguards remain; added source-missing numbers require teacher review, while removed/changed source numbers reject the proposal. No mathematical correction is performed.

Replacement uses explicit source spans, not the entire visual union range. It preserves intervening prose and edits; unresolved duplicate source occurrences remain untouched. Proposals do not mutate drafts.

Every attempt retains source IDs, boxes, crop dimensions/hash, grouping method, inference state, response field, raw selected output, normalized candidate and rejection reason. Failed attempts expose the actual crop and collapsible diagnostics to the already-authorized teacher. Logs contain metadata rather than image bytes or full text. Apply metadata excludes image bytes and complete raw response objects.

The managed stub returns a wrapped equality chain through `reasoning_content`, including `\\frac{TP}{TP+FP}`, `\\frac{24}{24+6}` and `\\frac{24}{30}`. This passes conservative validation as a teacher-reviewed proposal. **Actual Uni-MuMER response field, output and validation result are unknown.**

## UI, safety and runtime

The UI retains “数式をLaTeX化”, continuous spinner/disabled/aria-busy state, original/proposed text, KaTeX preview and explicit Apply/Cancel. Rejected attempts show crop, reason, grouping method and response field with Apply disabled. Formal answer, saved server draft and browser-local editing state remain separate.

Existing domain authorization, artifact/material/SHA checks and generic staff-only text-tool authorization are unchanged. Crop limits remain eight regions, 35% page area and four million pixels; aligned atoms are capped at 128. No page-wide OCR is introduced.

Real RuntimeManager with managed test processes confirms cold startup and identical PID/started_at on warm requests for Ricoh and Uni-MuMER. There is no per-request stop. Actual deployed model reuse remains pending.

## Tests

- Backend regression: **228 passed**.
- Production frontend + real FastAPI + isolated SQLite + real RuntimeManager + managed model stubs, non-localhost HTTP Chromium suite: **27 passed**.
- Subsequent focused source-math browser suite: **2 passed**, including failed crop diagnostics and retry.
- Ruff, TypeScript and git diff checks passed. ESLint passed with zero errors and 19 warnings (image optimization and hook dependencies).
- Managed tests cover empty/unsupported response, reasoning fallback, wrappers, malformed Ricoh groups, conservative failure, explicit noncontiguous replacement and warm reuse.
- Browser tests assert one region/all seven IDs, spinner, proposal/cancel/apply, draft/formal separation, save/register/reload and failure crop visibility. No unexpected browser errors were observed. Isolated fixture reports grading jobs **0**.

No PostgreSQL reset, Q5 data mutation, grading, model download or OpenWebUI change was performed.

## Files modified

- `src/scoring/math_region_grouping.py`, `source_math_ocr.py`, `vision_output.py`
- `frontend/components/LatexNormalizationControl.tsx`
- `frontend/lib/api/textTools.ts`, `frontend/lib/latexErrors.ts`
- `frontend/e2e/source-math-ocr-real.spec.ts`
- `config/runtime.deployment.json`, `compose.yaml`
- `tests/test_math_region_grouping.py`, `tests/test_source_math_ocr.py`
- `tests/runtime_fixture.py`, `tests/test_runtime_deployment.py`
- `tests/fixtures/runtime/llama_server_stub.py`, `tests/run_runtime_browser_e2e.py`
- `docs/operations/runtime-deployment.md`, this report and the prior report follow-up link

Changes are unstaged; no commit or push was performed. Local databases, crop inspection files and logs are not added to Git.

## Remaining production acceptance

1. Supply an accessible existing production RuntimeManager and authorized Precision draft/source; do not send secrets in chat.
2. Explicitly request math OCR for the real Precision candidate. Inspect native IDs/count, grouped count, union/crop boxes and dimensions. Verify the crop contains the complete equation.
3. Confirm Ricoh is skipped when confident, or inspect its known-ID grouping when required.
4. Inspect the actual Uni-MuMER response field, raw/normalized output and validation reason. A usable real transcription is mandatory.
5. Verify crop + KaTeX proposal, Cancel unchanged, Apply local-only, Save draft-only and Register formal update.
6. Repeat explicitly and verify identical PID/started_at with no reload/stop. Audit browser console/network.

All production acceptance items remain open. Correct grouping with failed real Uni-MuMER recognition must remain **PARTIAL**; software/stub success alone cannot satisfy COMPLETE.
