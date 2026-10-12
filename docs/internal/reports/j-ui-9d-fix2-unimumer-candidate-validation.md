# J.UI.9d-fix2 Uni-MuMER Candidate Extraction, Detokenization & Validation

Follow-up: [fix3 production observations, Unicode source evidence, Ricoh truncation and guarded formatting fallback](j-ui-9d-fix3-deterministic-ornith-formatting.md). The latest supplied production request failed at Ricoh grouping before candidate validation; see that report for the distinction.

## Phase result

**PARTIAL.** Implementation, production-build browser tests and managed runtime validation pass. A live request against the deployed Precision draft has not been possible from this workspace. The real production acceptance condition cannot be claimed from the supplied response example or managed stubs.

## Production root cause

The user reports that fix1 now produces a complete Precision crop, Ricoh grouping and Uni-MuMER inference succeed, and the shared parser obtains output from `choices[0].message.reasoning_content`. Those deployment observations were supplied by the user, not independently captured here.

The previous code validated the entire selected response. Replaying the supplied response shape reproduces the failure: character-spaced identifiers/numbers, repeated equations and unrelated text are treated as one transcription. The fix adds a focused deterministic post-processing module between shared response parsing and validation; geometry, Ricoh and runtime ownership remain unchanged.

## Candidate extraction

Candidates retain exact offsets into the raw selected response. Mathematical lines and repeated source equation labels define bounded candidates. Adjacent lines join only as explicit mathematical continuations or open-brace continuations, with source-compatible identifiers and no intervening prose. Independent expressions and explanatory prefixes are not blindly concatenated or peeled.

A source-unsupported trailing `\text{...}` may yield an additional complete formula prefix; the full rejected attempt remains diagnostic. Source-supported mathematical text is preserved. At most 64 candidates are evaluated.

## Source-guided detokenization

Only complete identifiers and exact numeric tokens found in the source region support recovery. Longer tokens are processed first, with boundaries preventing prefix recovery from a longer spaced number. Thus `P r e c i s i o n`, `T P`, `F P`, `2 4`, `3 0`, and `0 . 8 0 0` recover their source-supported spelling. Unknown sequences remain unresolved.

Control-sequence/brace/operator spacing is normalized as presentation syntax. Ordinary spacing inside supported `\text{...}` stays intact. There is no global whitespace deletion, term reordering, number correction, answer solving or additional model call.

Example:

```text
raw:
P r e c i s i o n = \frac { T P } { T P + F P } = \frac { 2 4 } { 2 4 + 6 } = \frac { 2 4 } { 3 0 } = 0 . 8 0 0

selected:
Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=\frac{24}{30}=0.800
```

`0.800` stays `0.800`; incorrect source calculations are not silently corrected.

## Repetition, scoring and validation

Exact normalized duplicates point to the first candidate and are not concatenated. Near-identical candidates are evaluated separately. Selection considers only accepted unique candidates, then uses deterministic source-identifier/numeric overlap, mathematical structure, unsupported-content penalties and compactness; ties prefer the earlier raw candidate. Added supported numbers are penalized rather than rewarded.

Validation operates on the selected normalized candidate. It requires source identifier coverage and ordered exact source numeric preservation, rejects unsupported identifiers/functions and numeric values, and rejects unresolved numeric spacing, malformed wrappers, unbalanced braces or incomplete common structural commands. Known repeated numeric values omitted by native extraction retain the existing explicit teacher-review warning. KaTeX is the final display/syntax gate before Apply.

Legal outer fences, dollars and bracket wrappers are accepted. Unclosed presentation wrappers are rejected. Validation is not globally relaxed.

## Observed fixture result

`tests/fixtures/math_ocr/precision_spaced.json` reconstructs the **user-provided production-like example**, not a captured live response. It contains three repeated Precision lines and one noisy line.

- response field: `choices[0].message.reasoning_content`
- extracted candidate count: **4**
- selected candidate index: **0** (zero-based)
- duplicate count: **2**
- rejected noise candidate: **1**, including unsupported `效` and source-incompatible numeric fragments
- normalized selected candidate: the Precision equality chain shown above
- validation: **accepted**, returned as a teacher-reviewed `ambiguous` proposal

These counts are fixture counts. The actual deployed response count/index/validation result remains unobserved after this change.

## Diagnostics and UI

The complete raw response, raw selected text, source field, crop, source IDs and grouping metadata remain intact. New diagnostics include `raw_ocr_text`, `normalized_ocr_text`, `candidate_count`, `duplicate_count`, `selected_candidate_index`, `selected_candidate`, `normalization_steps`, `candidate_scores` and rejection reasons. Every candidate records raw offsets/text, normalized text, source matches, unsupported/missing tokens, score, duplicate relationship and acceptance.

Authorized collapsible OCR diagnostics show candidate count, selected formula, normalization steps and per-candidate rejection. Failed attempts retain the crop and raw output with Apply disabled. Logs add candidate counts/index/duplicate metadata without full response text or image bytes.

No proposal applies automatically. Apply updates browser-local editing state only; Save updates the server draft; Register updates the formal version. Original text remains unchanged during request, failure and Cancel.

## RuntimeManager and security

Existing `math_ocr` and optional Ricoh profiles, lazy startup, warm PID/started_at reuse and no per-request stop are retained. Managed cold/warm tests and browser assertions pass. No new model, download, GPU assignment, auth change, database migration, PostgreSQL reset, Q5 data change, grading or OpenWebUI modification was performed.

## Tests and browser validation

- Backend regression: **246 passed**, one dependency deprecation warning.
- Rebuilt non-localhost production Chromium suite: **27 passed**.
- Focused production source-math scenario with the final source/build: **2 passed**.
- TypeScript, Ruff and `git diff --check`: **PASS**.
- ESLint: **PASS**, zero errors and 19 image/hook warnings.
- Production frontend build: **PASS** through the E2E harness.

The production frontend is built and served with `next start`, real FastAPI, isolated SQLite, real RuntimeManager and managed model stubs on a non-localhost HTTP origin. The source-math browser scenario observes the production-like spaced `reasoning_content`, four candidates, two duplicates, accepted selected LaTeX, crop and KaTeX preview, explicit confirmation, Apply/Cancel, draft/formal isolation, save/register/reload, same PID/started_at, failure diagnostics and retry. Console errors are asserted absent and isolated grading jobs remain zero.

An initial broader run using `--skip-build` failed because Next's compiled proxy still referenced the previous isolated API port. Rebuilding with the current API endpoint resolved the test setup; the rebuilt full browser suite passed. This was not a deployed application validation result.

## Files changed and Git status

- `src/scoring/math_ocr_candidates.py` — new focused extraction/normalization/scoring/validation helper
- `src/scoring/source_math_ocr.py` — post-processing integration and metadata logs
- `src/scoring/vision_output.py` — incomplete outer wrapper rejection
- `frontend/components/LatexNormalizationControl.tsx` — candidate diagnostics
- `frontend/lib/api/textTools.ts` — diagnostic response types
- `frontend/lib/latexErrors.ts` — actionable normalization/syntax/missing-identifier reasons
- `frontend/e2e/source-math-ocr-real.spec.ts` — actual candidate/state assertions
- `tests/test_math_ocr_candidates.py` — focused source recovery and safety tests
- `tests/fixtures/math_ocr/precision_spaced.json` — production-like supplied response example
- `tests/fixtures/runtime/llama_server_stub.py` — managed spaced/repeated response mode
- this report and the fix1 report follow-up link

Changes are unstaged; no commit or push was performed. No local databases, logs, credentials or artifacts are added to Git.

## Remaining real production acceptance

1. Deploy/restart the updated API/frontend and resume the existing Precision draft without re-analysis.
2. Explicitly request “数式をLaTeX化”; inspect the complete source crop and `reasoning_content` diagnostics.
3. Record actual candidate count, selected index, duplicates, discarded content, normalized formula and exact validation result. Verify all three fractions and `0.800` against the crop.
4. Confirm proposal/KaTeX visibility, teacher confirmation enabling Apply, Cancel unchanged and Apply changing editing content only.
5. Save/reload to check saved draft; Register/reload to check formal content. Verify unchanged PID/started_at on a second explicit request.

Production acceptance remains open. If the real response still rejects, export the authorized region diagnostics (not image bytes or full text into general logs) and report the exact candidate and rejection code. **Do not mark COMPLETE until the actual deployed sample reaches an applicable teacher-reviewed proposal.**
