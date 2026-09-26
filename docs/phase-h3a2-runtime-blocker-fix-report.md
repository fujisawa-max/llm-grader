# Phase H.3-A.2 Runtime Blocker Fix Report

## 1. Crop bug root cause

H.3-A.1 did not specify bbox units, axes or layout. The existing crop utility
assumed normalized 0–1000 xyxy. The old raw response has no coordinate declaration;
claiming a specific pixel offset or DPI error would be unsupported.
H.3-A.2 explicitly specified that contract and confirmed the numeric transform
in tests. Actual Ricoh still returned an inaccurate location. This remaining
model-grounding failure is distinct from coordinate transformation.

## 2. Coordinate contract

See `phase-h3a2-coordinate-contract.md`. Original 800×800 PNG is sent unchanged.
Origin top-left, x-right/y-down, normalized 0–1000 xyxy, then existing
`regions.crop_image` floor/ceil, 12-pixel margin and clipping. No PDF rotation,
DPI or scale operation occurs in this image fixture. No hardcoded bbox offset.

## 3. Overlay/crop verification

Region `answer-answer-page-formula-`, Ricoh bbox `[100,300,300,400]`.
Final source-pixel crop `[68,228,252,332]`, 184×104 pixels.
Crop SHA `bdb692165b9f5bb476bbe848cee0737fac7f71292ca0b6550c28c9747659a05f`.
`artifacts/h3a2-smoke/overlay.png` shows the box ABOVE the formula.
The crop contains only clipped character tops. Visual inspection FAILED.
No Uni-MuMER inference was allowed after this failure.

## 4. Ornith capability

Existing `/opt/llm-eval/vision-models.json` has Ornith Q4_K_M with an mmproj and
the local multimodal server binary. This is configuration evidence, not a live
capability proof. The adapter now checks `/props` vision capability and refuses
unsupported image input. Actual H.3-A.2 Ornith capability remains unverified
because the prior crop gate failed.

## 5. Ornith image transfer

Added an explicit image resolver, nonempty-image requirement, and page ID/SHA
checks against the target answer. Wrong-question image rejection is unit tested.
Actual Ornith image count in this smoke: zero (stage not reached).

## 6. Context budget

Previous Ornith log: context 4096, prompt 3800, output 296, truncated.
This smoke resolves existing registry context 8192; it does not invent a larger
context setting. Ricoh attempts 1/2: prompt 801, requested output 1024, actual
1024, finish_reason=length (40.22/40.23 seconds). Reasoning consumed the budget.
The binary advertises `--reasoning-budget 0`; setting it did not eliminate the
observed reasoning in this configuration. Attempt 3: prompt 801, requested 4096,
actual 2227, finish_reason=stop, 86.79 seconds. 801+4096 fits within 8192.
Ornith post-compaction token usage remains unmeasured.

## 7. Prompt compaction

Allow-list includes question ID/text (ancestor+self), source page IDs, normalized
OCR blocks, formula transcription/bbox and warnings. Raw response, reasoning and
duplicated artifact metadata are excluded. Full request/response audit callbacks
preserve actual JSON in the synthetic validation directory. Strict stop/JSON
parsing remains unchanged; partial JSON is not recovered.

## 8. Actual sentinel leak validation

Dedicated fixture contains MODEL_ANSWER_SECRET_TOKEN in ModelAnswer and
RUBRIC_SECRET_TOKEN/MAX_POINTS_SECRET_TOKEN in rubric criteria. max_points stays
a numeric 10; a string sentinel cannot be stored in that numeric field.
Actual request audit asserts all three absent. Ricoh requests passed, but an
actual Ornith request was not made, so Ornith actual sentinel proof is UNMET.

## 9. Japanese validation fixture

Test `930bf71c-f9cf-42d6-8d10-ec3a65633bc7`.
Submission `20bc7950-f3de-48db-985f-8163ab810f31`.
Question `80a8f584-7e61-40a2-aecf-0ccc5502ce88`.
Visible: 「私は次のように計算しました。」 / `2 + 2 = 5` /
「これが私の答えです。」. Newly created isolated synthetic Test, not sampleQ1/Q2/Q3.

## 10. Ricoh result

Final structured output correctly transcribed the Japanese text and the visible
incorrect formula. It returned the wrong spatial location and an empty model
region identifier. Raw response and normalized view are separately retained
in `artifacts/h3a2-smoke/ricoh.json` and timestamped raw-response artifacts.

## 11. Uni-MuMER result

Not executed: visual crop gate failed.

## 12. Ornith reconstruction

Not executed: no successful normalized reconstruction exists.

## 13. Wrong-answer preservation

Visible `2 + 2 = 5`; Ricoh transcription `2 + 2 = 5`.
Ornith preservation is unverified; it must not be inferred from the Ricoh output.

## 14. Persistence

Synthetic source/Test/association records were saved through DomainService.
No successful extraction/reconstruction record was generated or selected.
Previous failed H.3-A.1 artifacts were not changed.

## 15. H.2-G preview

Not reached; RECONSTRUCTED_FROM_DOCUMENT proof remains unmet.

## 16. Source immutability

Before and after JSON SHA:
`b5582f062f578af64b15b2db3cb0e282639b1dac9a565976c7b5bd028b505f95`.
Before and after page SHA:
`e1f26db12e18d87c7bc2f942cbaac2eb9bd2b19b588781f75694d0e0ca9d0e56`.
Both identical. No script writes targeted sampleQ1/Q2/Q3; a comprehensive
before/after database snapshot of those samples was not taken in this phase.

## 17. Model-call audit

H.3-A.2 actual calls: Ricoh 3, Uni-MuMER 0, Ornith reconstruction 0.
Ornith grading 0, grading-worker calls 0, GradingJob creation 0.

## 18. Runtime lifecycle

RuntimeManager created/cleaned owned Ricoh runtimes using dynamically allocated
port 18080. No manual server launch, borrowed stop or port-3000 action.
Final process check: no llama-server remaining.

## 19. Tests

unittest 214 OK; pytest 225 passed; Ruff clean.
Coverage added: normalized crop at identity, 2× and 1.5× dimensions; edge clipping;
raw exclusion; correct image transfer; wrong-page and missing-image refusal.
Existing length-rejection and ownership tests remain passing.

## 20. Frontend/Playwright

No frontend changes. No successful reconstruction exists to inspect; actual
result Playwright scenario was not claimed or run.

## 21. Remaining limitations

Ricoh's spatial localization fails visual validation even after the coordinate
contract is explicit. Uni/Ornith smoke, post-compaction Ornith budgeting, actual
Ornith sentinel proof, persistence/selection/preview remain gated behind this.
Unit tests establish wiring, not model quality or overall readiness.

## 22. Final status

H.3-A.2: NOT COMPLETE. H.3-A overall: NOT COMPLETE.

## 23. H.3-B readiness

NO. A correct visually verified crop and the subsequent complete reconstruction
smoke are still required. No actual grading was performed.
