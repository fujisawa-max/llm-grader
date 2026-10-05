# J.UI.9d-fix3 Deterministic OCR Normalization with Ornith Formatting-Only Fallback

## Phase result

**PARTIAL.** The supplied production observations are reproduced, the backend tests and production-build browser tests pass, and a formatting-only fallback is implemented. No authenticated request to the actual NVIDIA deployment was made. Actual deployed Precision acceptance remains unverified; managed stubs are not evidence of real-model success.

## Production root cause and evidence

The latest supplied response (draft `32c7f8da-3446-48e2-8f24-3e48242bbff9`, entry `ce1bb8fa-161a-4d5d-ac14-7b6fc9bc2edb`, revision 8) fails **before Uni-MuMER**: Ricoh `choices[0].message.reasoning_content` ends in incomplete JSON, `finish_reason=length`, `completion_tokens=1024`, causing `math_ricoh_grouping_rejected`. It must not be described as a fix2 candidate-validation failure.

There are also two source-evidence defects confirmed in code: ASCII-oriented math filtering drops standalone mathematical-font `𝑇𝑃`; source identifier comparison treats mathematical-font `𝑃𝑟𝑒𝑐𝑖𝑠𝑖𝑜𝑛`/`𝑇𝑃`/`𝐹𝑃` differently from ASCII OCR `Precision`/`TP`/`FP`. A clean normalized candidate can therefore fail source identifier validation. The new comparison aliases only mathematical styled Latin letters, never globally NFKC-normalizing numbers, superscripts, fractions or the document. Original source strings, IDs, offsets and SHA remain unchanged.

Supplied crop metadata: union bbox `[92.66400146484375,502.7281188964844,270.2300109863281,521.2810668945312]`, padded bbox `[86.66400146484375,496.7281188964844,276.2300109863281,527.2810668945312]`, 380×62 px. User-observed counts were native 11, aligned 5, geometry 2, final 1, Ricoh used. The subsequent user reply supplied nine exact native segment records (of the reported eleven), including standalone numerator TP and both 24 numerators. Replaying these real coordinate records with complete source text retains all seven formula segments and produces one confident geometry-only region with exactly the observed bbox/crop dimensions; heading and answer prose are excluded. The two remaining source records and the actual PDF image were not supplied. This is coordinate replay, not a new deployed request.

## Upstream geometry / Ricoh correction

Math-font Latin aliases are used only for lexical math detection and evidence comparison. Ricoh remains optional WHERE assistance, never a LaTeX transcription model. Its request now supplies a strict JSON schema restricted to known source IDs, temperature zero, thinking disabled, and JSON-only instructions. Existing strict membership validation remains; incomplete JSON and explanatory reasoning are not repaired into trusted grouping. Truncation has the explicit code `math_ricoh_output_truncated`.

On Ricoh failure, the original atoms are independently regrouped using the existing strict geometry algorithm and full editing text. Fallback proceeds only if it proves exactly one unambiguous region with every source span and ID retained. Loose/ambiguous regions remain rejected; there is no unconditional union or validator bypass. Failure field, finish reason, token count, raw response and fallback method remain available. Metadata-only logs identify the failure and whether strict geometry fallback succeeded. Arbitrary paths, domain authorization and generic text-tool authorization are unchanged.

## Deterministic normalization

Candidate extraction precedes any text-model request. Repetition, exact normalized duplicates, source-incompatible noise and trailing unsupported text remain separate diagnostic attempts. Prefix completeness is checked after source-guided syntax recovery rather than against raw `\\frac { ... }` spacing.

Source-supported characters recover `P r e c i s i o n`, `T P`, `F P`, `2 4`, `3 0` and `0 . 8 0 0`. Token-local whitespace handles NBSP/thin spaces/zero-width presentation noise. Known LaTeX control words and braces/operators normalize conservatively. There is no global whitespace deletion, mathematical correction, numeric rewriting or term reordering.

Replay of the supplied real-output text with the supplied mathematical-font source gives:

```text
raw:
P r e c i s i o n = \frac { T P } { T P + F P } = \frac { 2 4 } { 2 4 + 6 } = \frac { 2 4 } { 3 0 } = 0 . 8 0 0

selected:
Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=\frac{24}{30}=0.800
```

Fixture result: four extracted candidates, one duplicate, selected index 0, final source validation accepted, Ornith not called. Unsupported `\\text { 效 } \\dot { 2 } : 0 . 9 0 0 ( 9 0 0 )` attempts remain rejected diagnostic evidence and do not block another accepted candidate. Repeated source-supported 24 omitted by native extraction still requires explicit teacher review; it is not silently treated as exact numeric equivalence. Japanese answer prose is preserved by source-span reconstruction.

## Ordered alignment follow-up from actual source records

`pdf-fe2e70db8c43126ef3cda496` (`𝑇𝑃`, reading order 35) is now recognized using controlled mathematical-font Latin aliases. `pdf-a62cc37f20638ab0fea3daba` and `pdf-12d7d670724bba5ed197b4ac` (both `24`, reading orders 37 and 39) align to separate occurrences in complete text. Both participate in fraction geometry; all seven source IDs survive and geometry is unambiguous, so Ricoh is skipped.

Alignment no longer takes a global equal-count shortcut. It always scopes repeated-token occurrences between unchanged neighboring source anchors, then uses source reading order within that interval. Even if a deleted numerator is replaced elsewhere by another `24`, the overall count cannot trick alignment into borrowing that unrelated occurrence. Additional unrelated `24` lines do not block correctly scoped numerators.

There is an important observational distinction: the earlier supplied editing text has only one standalone `24`, whereas the newly supplied source has two. Replaying that older text maps six formula segments after the Unicode fix, not seven. A missing or teacher-deleted occurrence is not assigned a fictional text range or silently restored. With both native occurrences present, all seven map exactly. The latest full editing/request text was not independently captured; disappearance of the second 24 in the older response cannot be attributed solely to global duplicate matching without this distinction.

Tests use the exact nine supplied IDs, bboxes, pages and reading orders, including reversed input-array order. A representative generated PDF at these coordinates verifies crop metadata and one managed OCR request; it is explicitly not the actual production PDF. Source-span replacement preserves the Japanese answer and heading, and request/proposal leaves editing text unchanged.

## Ornith formatting-only fallback

Only a unique plausible candidate with a provable source-compatible structural reference is eligible. Unsupported identifiers/numbers, missing structure, prose and semantic disagreement never trigger Ornith. A hard fixture splits the known `\\frac` control word across a newline; the reference can prove its structure, but the ordinary candidate remains unresolved. Only this selected candidate is sent, not the entire reasoning response or rejected noise.

The existing RuntimeManager-owned `ornith_rubric_draft` profile is reused (override via `LLM_GRADER_MATH_FORMATTING_PROFILE` or existing classifier profile setting). No model download, GPU hardcoding, unmanaged server or per-request stop is added. Narrow structured output is `{status: formatted|refused, latex: string}`. The prompt forbids solving, correction, changed values/variables/operators, reordering, missing-term inference and explanation.

Before/after fingerprints compare the entire ordered token stream, including exact numeric spellings, identifiers, controls, operators, equality count, braces, fraction count and numerator/denominator content. Swapping arguments, `24/(24+6)` to `24/30`, `FP` to `FN`, `0.800` to `0.8`, added prose or reordered terms is rejected even if mathematically equivalent. The actual returned output then runs through the existing source-aware validator again. Fingerprint reference recovery is never directly promoted as an output or a validation bypass.

The real supplied Precision replay needs no Ornith. Whether the updated deployed request needs it is not yet observed. Hard-fixture before/after structural comparison and final validation pass; mutation, timeout, refusal, malformed response and unavailable-runtime cases fail conservatively.

## Diagnostics / UI / state semantics

Raw Uni-MuMER response and selected response field, candidates/scores, deterministic candidate/reason, source identifiers/numbers, Ornith profile/raw response/output, structural comparison, final candidate and final validation remain distinct. General logs use hashes, lengths, profiles and codes, not document text. Crop and failure diagnostics remain available in the authorized response. A collapsible UI section exposes the final validation and formatting details; compact method labels distinguish deterministic processing from deterministic + Ornith formatting.

The button remains `数式をLaTeX化`, with spinner, disabled duplicate submission, KaTeX syntax/display gate, explicit teacher confirmation, Apply and Cancel. Request/proposal mutates nothing; Apply affects local editing text only; draft save updates server draft; registration updates formal ModelAnswer. Error codes distinguish fallback unavailable, timeout, invalid output, semantic change and final validation failure. Raw runtime responses/crop bytes are excluded from applied edit provenance while existing source provenance is retained.

## Tests

- Targeted backend suite after coordinate/ordered-alignment follow-up: **224 passed**, one existing dependency deprecation warning. Includes source OCR, candidate/formatting, geometry/Ricoh, shared response parsing, generic LaTeX, classification, geometry mapping and RuntimeManager tests.
- Grouping suite after actual-coordinate follow-up: **43 passed**.
- Production `next build`: pass for both browser runs.
- Non-loopback HTTP Chromium regression: **27 passed**; real FastAPI, isolated SQLite, actual RuntimeManager and managed runtime stubs; grading jobs **0**.
- Dedicated hard-formatting non-loopback Chromium scenario: **1 passed**; cold start, warm same PID/started_at, crop, reasoning field, structural/final validation, KaTeX, Cancel, Apply, save/reload, registration and formal/saved/local isolation.
- After the ordered-alignment follow-up, source-math non-loopback Chromium scenarios were rebuilt and rerun: **2 passed**, including state isolation, crop/preview and managed runtime reuse.
- TypeScript: pass. ESLint: zero errors, 19 existing warnings. Ruff and diff whitespace check: pass.
- Browser tests monitor unexpected console/page errors and assert actual state changes. No unexpected errors were observed in these scenarios.

Runtime reuse is confirmed against the real RuntimeManager with managed stubs, not actual deployed Ornith/Uni-MuMER. Production auth and Q5 data were not accessed or altered. No commit/push/staging was performed.

## Files changed

- Backend: `math_source_tokens.py`, `math_ocr_syntax.py`, `math_ocr_formatting.py`; `math_ocr_candidates.py`, `math_region_grouping.py`, `source_math_ocr.py`.
- Frontend: `LatexNormalizationControl.tsx`, `lib/api/textTools.ts`, `lib/latexErrors.ts`.
- Tests: `test_math_ocr_formatting.py`, `test_math_region_grouping.py`, production-observation JSON fixture, managed llama-server stub, runtime browser harness, existing source-math spec and new formatting-only browser spec.
- Documentation: this report and follow-up link in fix2 report.

## Remaining production validation

Rebuild/restart the API/frontend through normal deployment, then repeat the same Precision request without applying or registering first. Inspect `grouping_summary`, region `segment_ids/source_spans` (standalone `𝑇𝑃` retained), `grouping_method`, Ricoh `finish_reason/ricoh_rejection_code`, Uni-MuMER `source_field`, `candidate_count/selected_candidate_index`, `deterministic_candidate`, `ornith_used`, `final_candidate`, `final_validation` and `rejection_code`. Verify complete crop, KaTeX proposal, enabled Apply after teacher confirmation, Cancel, local-only Apply and warm reuse.

The supplied per-segment bboxes now reproduce a confident geometry-only region. If the updated deployed request differs, compare its full request editing text and aligned span IDs against these supplied source records. Credentials, cookies, tokens and crop bytes are not requested. Current supplied observations establish the previous failures, not success of this patch on the deployed models.

## Final decision

**Phase J.UI.9d-fix3: PARTIAL.** Software and production-like managed tests pass. COMPLETE requires the actual deployed Precision expression to reach an applicable teacher-reviewed proposal; that acceptance condition has not yet been observed.
