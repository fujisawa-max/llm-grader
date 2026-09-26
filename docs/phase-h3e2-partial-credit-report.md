# Phase H.3-E.2 — Partial-Credit Decision Robustness

Comparison executed once for Q4 s2 Problem 2(1) only. The desired partial-credit decision was **not achieved**; no further model attempts were made.

| Result | Factorization /10 | Completing square /10 | Total /20 |
|---|---:|---:|---:|
| Original AI | 0 | 10 | 10 |
| Teacher approved | 5 | 10 | 15 |
| New prompt | 0 | 10 | 10 |

The new raw response explicitly considered the 5-point level but rejected it because the internally correct factorization was for an incorrectly transformed expression. It added the interpretation that partial credit requires valid work for the correct original function. This remains inconsistent with the Teacher decision. Structured validation establishes allowed scores and response consistency; it does not establish correctness of this pedagogical judgment.

The prompt asks the model to compare allowed levels in descending order, assess partial credit before zero, and return a selected level with a concise justification. It includes neither the previous score nor the Teacher override or target score. A comparison-only response schema requires the selected-level fields. Default grading prompt behavior is unchanged.

## Identity and persistence

- Question: `02669a76-cb99-4ea1-bfd4-c742ff1617a3`
- Submission: `a3f18d80-78a7-41b1-9b07-9db3fe3056e6`
- Approved RubricVersion: `169af71b-c1ec-4d42-900f-89513d3e1fe3`
- Prompt version: `partial-credit-decision.v1`
- Comparison Job: `99b0dff2-b072-4eca-99c8-4b7d2a0a4070`
- Bundle: `f1e1cd6f8053224582c0ab2add1d8fed48543681aafcca7ebf2b5d9294b2c68a` (unchanged)
- Snapshot: `e9fdbc57bc8b63a46153fc101068e13dc5c7d4d8e6eeb2566948e0b1db877337`
- Raw SHA: `585a143df120d26b7916febc04a0c7c4fad5cfe6d16e4eb99f5fa2f98bfc326e`
- Normalized SHA: `de176ddb9e52afbb355dcc972986aa1ea2f1f218282181a17833f5d3061537df`

Production Worker → RuntimeManager → Ornith → validator → PostgreSQL completed. Raw and normalized outputs are retained under `artifacts/h3e2-q4-partial-credit/`; `report.json` contains exact output and provenance.

Existing Jobs/items and Teacher Review file hashes were unchanged. Question, ModelAnswer, Rubric, and Reconstruction row fingerprints were unchanged. The comparison result is not a new Teacher approval and does not replace the approved 15/20.

## Validation and scope

- Ornith grading: 1; Ricoh / Uni-MuMER / Reconstruction: 0.
- Completed Worker resume refused re-execution; runner reused the validated manifest without inference.
- Owned runtime stopped; no llama-server process remained.
- unittest: 253 tests OK, 8.207 seconds.
- pytest: 271 passed, 9.11 seconds; deprecation warnings retained.
- Ruff: all checks passed.
- Initial sandbox unittest was interrupted after the known TestClient hang; the complete non-sandbox run above succeeded.
- No other question/student was graded.

Experiment execution: COMPLETE. Desired 5/10 robustness outcome: NOT ACHIEVED. One example and one call cannot establish general robustness. A future change would need to address the model's interpretation of valid intermediate work after an earlier error; no additional attempt is authorized or performed in this report.
