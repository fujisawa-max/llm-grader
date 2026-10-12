# Phase H.3-E.0a — Multimodal Preflight Repair

Implementation and regression: complete. Real-sample Execution readiness: **BLOCKED**.
No actual grading was performed. Teacher reconstruction review and rubric contract clarification remain.

## Scope and immutability

- Test: `e14aeeb5-924c-4c72-b2a2-583f1be9f48e`
- Submission (s2): `a3f18d80-78a7-41b1-9b07-9db3fe3056e6`
- Problem 2(1): `02669a76-cb99-4ea1-bfd4-c742ff1617a3`
- Problem 2(2): `705f1d12-4f19-4c33-b197-39212f24b3ca`
- Original PNG: 4825 × 6817.
- Source SHA before/after: `dd89f67075824aff671081c57916f25e21093b92cbf9e66d3d46fe5bd823c9f8`.
- Test, TestQuestion, ModelAnswer, RubricVersion, Question assets, corrections,
  confirmations, submissions, existing GradingJob/GradingJobItem table hashes are unchanged.
- Only the selected student's extraction/reconstruction and visual asset records were added.
- Structural parent was not reconstructed or graded; both child contexts include its stored quadratic function.

## Coordinate repair

Production Ricoh schema specifies exactly four bbox numbers, each in [0,1].
The parser checks finite values, strict bounds, positive dimensions and declared units
for text, formula and visual regions. No unit inference occurs.
Explicit `normalized_1000` conversion is available only with an explicit parser opt-in;
the current Ricoh request requires `normalized`.

Scoped full-page extraction permits at most one coordinate-contract correction retry.
Invalid output can remain as raw audit evidence, but is never returned/persisted as
validated layout or passed to crop generation. The former unchecked diagnostic helper
now delegates to the production adapter. Each attempt uses a new artifact directory.

This phase: first Ricoh response passed the contract; correction retries = 0.

| Region | Ricoh bbox | Visually reviewed crop bbox |
|---|---|---|
| Formula | [0.1, 0.5, 0.4, 0.75] | [0.14, 0.506, 0.445, 0.684] |
| Graph | [0.5, 0.4, 0.9, 0.7] | [0.50, 0.442, 0.98, 0.68] |

The Ricoh regions were spatially inaccurate despite valid units: they omitted rightmost
writing/curve and included neighboring Problem 3. Original-image visual inspection
adjusted their coverage. This was not a 0–1000 conversion. Raw model layout and the
coverage correction are retained in provenance; it is labeled assistant visual inspection,
not Teacher acceptance. Crops use original pixels, not preview pixels.

## Problem 2(1) extraction and Teacher Review

Uni-MuMER received one formula crop only. Actual crop pixel bbox (including 12px pipeline
padding): `[663,3437,2160,4675]`; SHA:
`1bd972fd78852ed0aacdf5ad170687a5baa7df9227ed9253864155b5aff64a4c`.

Uni transcription (spacing preserved in the normalized artifact):

```latex
y = - \frac { 1 } { 3 } ( x ^ { 2 } - 2 x - 1 5 ) = - \frac { 1 } { 3 } ( x - 5 ) ( x + 3 ) y = - \frac { 1 } { 3 } ( x ^ { 2 } + 6 x ) - \frac { 5 } { 3 } = - \frac { 1 } { 3 } ( x + 3 ) ^ { 2 } + 3 - \frac { 5 } { 3 } = - \frac { 1 } { 3 } ( x + 3 ) ^ { 2 } + \frac { 4 } { 3 }
```

Parser warnings: `exact_duplicate_removed`, `native_vision_disagreement`,
`reasoning_output_requires_review`. Raw response is preserved.

Reconstructed answer:

```latex
y = -\frac{1}{3}(x^2 - 2x - 15) = -\frac{1}{3}(x - 5)(x + 3)
y = -\frac{1}{3}(x^2 + 6x) - \frac{5}{3} = -\frac{1}{3}(x + 3)^2 + 3 - \frac{5}{3} = -\frac{1}{3}(x + 3)^2 + \frac{4}{3}
```

- Extraction run: `9f845e6a-b7a5-4356-947a-0d4c9fae4584`
- Reconstruction: `225a70bd-5094-47db-b7ae-321611852255`, version 1.
- Reconstruction SHA: `0673de434558624879f7a2e003c050b7f61430a968a682427509819e1d6aa1f4`.
- Status: `REVIEW_REQUIRED`; not usable for execution before Teacher ACCEPT/EDIT.

Ornith retained the student's first expression and factorization. It also emitted an
uncertainty comparing the first expression with the question function. This is a model
annotation, not a grading result or an authorized correction. We did not resolve it
automatically. Its generated segment bboxes extend beyond the verified formula crop;
they are unverified raw reconstruction annotations and are not used for crops/assets.
Teacher review should use the original formula crop and transcription above.

The actual reconstruction request contained the selected formula crop, the current
question context and OCR evidence. ModelAnswer, Rubric, max_points, score, grading
policy and previous grading result keys were absent. Full raw responses, normalized
outputs, request payload and generation provenance are stored separately.

## Problem 2(2) Student Visual Answer Asset

- Asset ID: `30580b31-35d8-57c4-ab2f-21a7e46317a1`
- Owner Question: `705f1d12-4f19-4c33-b197-39212f24b3ca`
- Submission: `a3f18d80-78a7-41b1-9b07-9db3fe3056e6`
- SHA: `853ef5a82cccc6e313411c76752224cf1254f50ce930949278b625312fd4b77e`
- Canonical bbox: `[0.50,0.442,0.98,0.68]`, `normalized`.
- Pixel bbox: `[2412,3013,4729,4636]`.
- MIME: `image/png`.
- Visual check: axes, complete student curve, labels and necessary blank canvas included;
  neighboring Problem 3 excluded. No OCR text substitutes for the image.
- Original bytes unchanged. Idempotent registration uses existing TestMaterial and
  append-only DomainEvent infrastructure; no migration needed.

Three distinct roles and assets:

| Role | ID | SHA |
|---|---|---|
| Question blank canvas | `003a889e-aa53-4872-ad5d-c656de1beaef` | `38b76fdc5604d461b42eed6d22bbb4acf43610c1053efc46e62672625d64dc0d` |
| ModelAnswer reference | `6163634f-fa79-52e1-b33f-673c32d8bc74` | `fd1c3e7ba0197b37955b9e4364b7b1b7722e87d1c4bc2abcd1c3fdf50fc70023` |
| Student answer | `30580b31-35d8-57c4-ab2f-21a7e46317a1` | `853ef5a82cccc6e313411c76752224cf1254f50ce930949278b625312fd4b77e` |

## Production support and actual readiness

Before implementation, RuntimeManager started the current `ornith15-35b-q4km` profile
with its mmproj, `/props` returned `modalities.vision=true`, and the owned runtime stopped.
This was a capability GET, not an inference or grading request.

The GradingInputAssembler now carries role-separated visual refs. Production validation
checks ownership, source/crop/metadata hashes, coordinates and required reference assets.
Job creation uses the same preview and seals the image identities and paths in the snapshot.
The Worker resolves only snapshot assets, verifies hashes/roles, checks live `/props`, and
sends actual image_url inputs labeled with their roles through the existing grading adapter.
It never substitutes a Ricoh description for the Student graph.

An isolated fake-transport Worker test verified all three images in the actual LocalClient
serialized payload, identical preview/snapshot input, and resume without another request.
No production job was created for this verification.

| Child | Mapping | Execution | Bundle SHA |
|---|---|---|---|
| 2(1) | Exact identity, BLOCKED pending reconstruction review | BLOCKED | Not generated |
| 2(2) | READY | BLOCKED on existing rubric | `9009ca6752e1dadfe16bbe7f17d4293ad0f9a4f11738a5034eeb1fdcef23c7fd` |

Problem 2(2) bundle integrity/visual validation: PASS. Both current approved rubric
entries fail the existing production rubric validator:

- Version: `84ca25fb-baf4-4a31-93a5-688d200c10a6`.
- 2(1): `sampleQ4-2.1-approved-1/2`, 10 points each, no levels.
- 2(2): `sampleQ4-2.2-approved-1/2/3/4`, 5 points each, no levels.
- IDs contain dots; all criteria lack approved discrete scoring levels.

No rubric content or status was changed. ID normalization can be mechanical, but scoring
levels require Teacher clarification and an append-only approved version. Q1's previous
binary-score approval was scoped to Q1 and was not applied to Q4.

Context SHAs:

- 2(1): `ade40813e9cd8cc49633431fd5d0115dc6492cacfd990ce4111781bae2c7f897`
- 2(2): `d82fb622a874d1c8be0405237f96589384823253c0dcea7b5dda13097237fe41`

## Calls, regression and handoff

This H.3-E.0a attempt: Ricoh 1, Uni-MuMER 1, Ornith Reconstruction 1,
Ornith Grading 0. New production GradingJob 0; score/feedback generation 0.
Owned llama-server remnants: 0 (host process check). Port 3000 untouched.

- Full unittest: 252 tests, OK.
- Full pytest: 270 passed; existing deprecation/collection warnings remain.
- Ruff: all checks passed.
- Both full test commands completed under non-sandbox permissions, per tests/README.md.
- Frontend unchanged; frontend/Playwright validation not applicable.

Artifacts: `artifacts/h3e0a/preflight.json`, `capability.json`, `model-call-audit.json`,
and immutable per-attempt directories. Source-bearing audit files are private artifacts.

H.3-E.0a repair implementation: complete. H.3-E.0: **BLOCKED**.
H.3-E.1 actual grading: **NOT READY**.

Required Teacher input: ACCEPT/EDIT/REJECT for the 2(1) transcription, and explicit
allowed scoring levels/conditions for the two 10-point and four 5-point Q4 criteria.
No further model call or grading is authorized by this report.
