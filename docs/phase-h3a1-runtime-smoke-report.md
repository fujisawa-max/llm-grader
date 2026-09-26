# Phase H.3-A.1 Runtime Smoke Validation Report

## 1. Runtime configuration

Actual local registry inspected: `/opt/llm-eval/vision-models.json`.
RuntimeManager managed all starts/stops and allocated port 18080 sequentially.
Ricoh: Qwen3VL Ricoh 8B Q8, runtime ID `ocr`.
Uni-MuMER: Qwen3.5 4B Q4_K_M, runtime ID `math_ocr`.
Ornith: 1.5 35B A3B Q4_K_M, runtime ID `ornith_reconstruction`.
All runtimes were owned. No external/borrowed runtime was stopped.
The temporary smoke script copied registry paths into its configuration; it
does not satisfy the requested reproducible registry-resolution contract.

## 2. Validation submission

Submission: `226d5f3b-86fa-48cc-a4e4-824389eebd1d`.
Test: existing isolated H.2-G validation Test `5e9b6804-94eb-418b-8e09-7f7493fa6cce`.
Source JSON SHA: `b89fec836beded64230dc6225b0c486bfa0287d94cc7c51d82ad85121a4dc949`.
Three synthetic pages contain `2 + 2 = 5` and `x^3 = -8`.
The heading is English; the required Japanese-text fixture was not supplied.
No sampleQ1/Q2/Q3 records were targeted.

## 3. Ricoh actual smoke

Seven inference requests are counted in `/tmp/h3a-ocr.log` across retries.
Eight starts/cleanups include one pre-request image-argument failure.
Raw-response fidelity is incomplete: the adapter saves parsed JSON as raw,
and early truncated responses were not persisted. Therefore elapsed time and
complete request/response provenance cannot be certified per call.

## 4. Formula crop

Visual inspection of run `47819b10-8bcd-41fd-9c76-f1069c973dc8`,
`answer-h3a-page-1-formula-1/crop.png`, shows the heading fragment
`Japanese an`, not the formula. This is a decisive smoke failure.
The crop utility expects normalized 0–1000 coordinates; the prompt did not
specify that contract. Model-generated region IDs also collided across pages;
page-prefixed IDs were added to prevent that collision.

## 5. Uni-MuMER actual smoke

Six actual requests and six cleanup events are recorded. Crops, not full pages,
were submitted. Because the crops were wrong, their transcription is not a
successful formula OCR validation. Existing Uni output parser is reused.

## 6. ReconstructionInput

H.2-G question identity and effective question context were used. However,
`ornith_reconstruction()` supplies an empty image list. Original image evidence
therefore did not reach Ornith, which violates this smoke's required input.

## 7. Leak verification

The two stored reconstruction-input artifacts contain zero occurrences of
`MODEL_ANSWER_SECRET_TOKEN`, `RUBRIC_SECRET_TOKEN`, and `MAX_POINTS_SECRET_TOKEN`.
This is only an artifact scan: those exact sentinels were not established in
the fixture and serialized HTTP request bodies were not retained. An actual
request-level sentinel leak proof is therefore NOT established.

## 8. Ornith actual reconstruction

Three actual requests/cleanup events are recorded under the reconstruction
runtime ID. Two parsed question outputs exist as artifacts with REVIEW_REQUIRED.
The final attempt failed on truncated JSON: 3800 prompt tokens left only 296
generation tokens in a 4096 context. The temporary permissive JSON slicing
fallback was removed; `parse_response` again requires finish_reason=stop.

## 9. Wrong-answer preservation

Visible: `2 + 2 = 5`.
Two saved parsed outputs: `2 + 2 = 5\nx^3 = -8`, REVIEW_REQUIRED.
They did not change 5 to 4. This is insufficient proof because original images
were absent from Ornith input and crop evidence was incorrect.

## 10. Persistence

Both substantive attempts failed; the temporary script rolled back the DB
transaction. For this submission the extraction-run, extraction-result and
reconstruction tables each contain zero rows. Partial files remain unchanged.
Failed-run persistence is an additional unmet requirement.

## 11. H.2-G preview integration

Not validated: there is no persisted, selected reconstruction for this smoke.
Idempotency/resume of a completed real-model run is likewise unverified.

## 12. Source immutability

Source JSON SHA before and after is identical (section 2).
All three page SHA values match the values recorded in the source JSON:

- page 1: `79f01161ba79eff8af457d6e12db635ddb3ee48158fbf29cf7d2ea3f9f39fbec`
- page 2: `3c4528284aab4748f8b298884c7fe58f8724c364b736af5f01ccd376898d2781`
- page 3: `530c518632bd01fedee606bcf1ba3fb96e7b8522a773652c38d0e6808d63100f`

## 13. Runtime lifecycle

All observed starts were RuntimeManager managed and sequential. Final process
inspection found no llama-server or smoke-script process. Port 3000 was not
used or stopped. Cleanup on ensure_running failure is now also inside finally.

## 14. Model-call audit

Across smoke retries: Ricoh 7, Uni-MuMER 6, Ornith reconstruction 3.
Ornith grading calls 0; grading-worker calls 0; GradingJob creation by this
script 0. Counts derive from server processing-task log entries.

## 15. Artifact verification

Partial Ricoh parsed views, Uni raw/normalized data, crops and two parsed
reconstruction outputs remain under the submission's reconstruction directory.
No successful pipeline manifest exists. A post-run SHA inventory was written
to `artifacts/h3a-runtime-smoke/failure-artifact-inventory.json`; it is explicitly
not a successful pipeline manifest or evidence of before/after immutability.

## 16. Backend tests

unittest: 211 tests OK. pytest: 222 passed. Ruff: clean.
Regression added: even syntactically valid JSON with finish_reason=length is
rejected and the owned runtime released. Existing lifecycle tests updated for
the dedicated non-grading HTTP payload.

## 17. Frontend/Playwright

No production frontend changes in H.3-A.1. No actual-result UI validation is
claimed because no successful persisted result exists.

## 18. Problems / limitations

Crop coordinate contract, absent Ornith image input, response/raw persistence,
context budget, failed-run persistence, registry configuration and a Japanese
sentinel fixture remain unresolved. Passing unit tests does not establish the
actual smoke acceptance criteria.

## 19. Final status

H.3-A.1: NOT COMPLETE. H.3-A overall: NOT COMPLETE.
The actual smoke is FAILED, not replaced by mock evidence.

## 20. H.3-B readiness

Blocked pending correction and successful re-validation of the above issues.
No actual grading was performed.
