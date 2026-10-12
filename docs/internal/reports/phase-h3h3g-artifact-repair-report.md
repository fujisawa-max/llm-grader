# H.3-H.3g Reconstruction Artifact Repair Report

## A. Artifact Audit

| Review | Target | Revision | Artifact Before | Repair | Artifact After |
|---|---|---|---|---|---|
| #11 | Q3/s1/1 | 8e8b7fcc-5d65-49b7-b14a-ec4cbaa56e10 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #14 | Q3/s2/3 | 913ec784-0c90-4d52-8b4b-e62933236ae1 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #15 | Q2/s1/1.1 | 5ef2923c-8ab0-48e5-9b9e-20de17dec56e | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #16 | Q2/s1/1.2 | ab019ec9-cb1c-4324-a026-b55d5da5c7a6 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #17 | Q2/s1/3 | 547c2aff-d4d2-4fe2-9508-35ac4f18438d | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #18 | Q2/s1/2 | a9ed9bd5-4bd0-4025-b227-7863860cc041 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #19 | Q2/s2/1.1 | 67a927c1-be06-4188-a2cc-503ce9bcaa63 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |
| #20 | Q2/s2/1.2 | c66f11c2-5d92-4801-9979-38d4eb3927c0 | input/legacy hash contract incomplete | immutable sidecar; retry reused | VALID |

## B. Finalization

| Review | Target | Selected Reconstruction ID/version | Artifact ID/SHA | Final Student Answer | Preview | Final Status |
|---|---|---|---|---|---|---|
| #11 | Q3/s1/1 | 8e8b7fcc-5d65-49b7-b14a-ec4cbaa56e10 / v2 | [8e8b7fcc-5d65-49b7-b14a-ec4cbaa56e10](/opt/llm-scoring/artifacts/reconstruction-repairs/8e8b7fcc-5d65-49b7-b14a-ec4cbaa56e10/artifact.json) / `65036dcbe3fa32da08b5519b458f46cd1649a9f275b6a2c54c6fb47e7464cf33` | 2 sin(π/4) cos(π/6) = √6/2 | PASS | READY_FOR_GRADING |
| #12 | Q3/s2/2 | NONE | historical evidence retained | 未確定（旧誤答／placeholderは未選択） | NOT RUN | TEACHER_TRANSCRIPTION_REQUIRED |
| #13 | Q3/s2/1 | NONE | historical evidence retained | 未確定（旧誤答／placeholderは未選択） | NOT RUN | TEACHER_TRANSCRIPTION_REQUIRED |
| #14 | Q3/s2/3 | 913ec784-0c90-4d52-8b4b-e62933236ae1 / v2 | [913ec784-0c90-4d52-8b4b-e62933236ae1](/opt/llm-scoring/artifacts/reconstruction-repairs/913ec784-0c90-4d52-8b4b-e62933236ae1/artifact.json) / `ffc8808aad4872435d45a64f5b82e756ffbc0f16b629d7bcf2df9f4a4088c55c` | y = 3 cos x | PASS | READY_FOR_GRADING |
| #15 | Q2/s1/1.1 | 5ef2923c-8ab0-48e5-9b9e-20de17dec56e / v1 | [5ef2923c-8ab0-48e5-9b9e-20de17dec56e](/opt/llm-scoring/artifacts/reconstruction-repairs/5ef2923c-8ab0-48e5-9b9e-20de17dec56e/artifact.json) / `78bbdc41a2f20b51eba74802c9b0e7d74ddaf69536a8c90e0e1fbc7ab083abf0` | x=1,-1; x=2; (x−2)(2x²−17x+35)=(x−2)(2x−7)(x−5); x=2,7/2,5 | PASS | READY_FOR_GRADING |
| #16 | Q2/s1/1.2 | 005f91b4-78ba-45f2-ab23-e66445e3f754 / v2 | [005f91b4-78ba-45f2-ab23-e66445e3f754](/opt/llm-scoring/artifacts/reconstruction-repairs/005f91b4-78ba-45f2-ab23-e66445e3f754/artifact.json) / `0be3a68379e26089d237f83e14f5698aa7433b11f8d256aabf9c1b1062e12c99` | x^3 + 8 = 0<br>(x + 2)(x^2 - 2x + 4) = 0<br>x = -2, 1 ± √3 i | PASS | READY_FOR_GRADING |
| #17 | Q2/s1/3 | 547c2aff-d4d2-4fe2-9508-35ac4f18438d / v1 | [547c2aff-d4d2-4fe2-9508-35ac4f18438d](/opt/llm-scoring/artifacts/reconstruction-repairs/547c2aff-d4d2-4fe2-9508-35ac4f18438d/artifact.json) / `6de50efdd71438006d479698dbb870ac1271cf57ccfd47f5d552c79491fb8f98` | 三重根−1、(x+1)^3、x^3+3x^2+3x+1=0 | PASS | READY_FOR_GRADING |
| #18 | Q2/s1/2 | 817ed9c5-43af-45af-89c1-d4c2e01478d6 / v2 | [817ed9c5-43af-45af-89c1-d4c2e01478d6](/opt/llm-scoring/artifacts/reconstruction-repairs/817ed9c5-43af-45af-89c1-d4c2e01478d6/artifact.json) / `c33cf5eee379a85446aa706bb0bf27ea51e35706733a2af1b8eea9dd781ade07` | (1)<br>y = -1/3(x^2 + 6x + 5)<br>  = -1/3(x + 1)(x + 5)<br><br>(2)<br>y = -1/3(x^2 + 6x) - 5/3<br>  = -1/3(x^2 + 6x + 9 - 9) - 5/3<br>  = -1/3((x + 3)^2 - 9) - 5/3<br>  = -1/3(x + 3)^2 + 3 - 5/3<br>  = -1/3(x + 3)^2 + 4/3 | PASS | READY_FOR_GRADING |
| #19 | Q2/s2/1.1 | 45d34b74-4b80-400c-b052-c385c463c669 / v2 | [45d34b74-4b80-400c-b052-c385c463c669](/opt/llm-scoring/artifacts/reconstruction-repairs/45d34b74-4b80-400c-b052-c385c463c669/artifact.json) / `658ac93c7620f100d573ec3078c1f7f96cbef21e6a0f5e1bbdeb05d6d4ae7bb5` | x = 1, 1<br>x = 2<br>(x - 2)(x^2 + 12x - 5)<br>x = 2, -6 ± √41 | PASS | READY_FOR_GRADING |
| #20 | Q2/s2/1.2 | 88597e81-c405-44ef-8037-9a9de2547ea1 / v2 | [88597e81-c405-44ef-8037-9a9de2547ea1](/opt/llm-scoring/artifacts/reconstruction-repairs/88597e81-c405-44ef-8037-9a9de2547ea1/artifact.json) / `2df83c9a7b062651944e273db6b02fd8d449c5b9d07941df84560fc30c69210b` | x = -2 | PASS | READY_FOR_GRADING |

## C. Summary

Artifacts repaired: 12 revision artifacts (8 historical + 4 new EDIT revisions).
New Teacher EDIT revisions: 4.
Preview PASS: 8 / 8.
READY_FOR_GRADING: 8.
TEACHER_TRANSCRIPTION_REQUIRED: 2.
BLOCKED: 0.

## D. Invariant

Selectable Reconstruction without Artifact among the 8 audited targets: 0.
Duplicate artifacts created by repair: 0; full repair retry reused all 12.
Repair sidecars retain historical revision binding, original output SHA, source SHA/material, available region provenance, normalized output and DB-sealed artifact SHA. No inferred bbox or source text was introduced.
Legacy bbox provenance is marked historical/unverified or NOT_RECORDED, never fabricated.
Historical malformed output hashes remain in history; the repaired normalized output has its own valid SHA used by production preview.
Q3 #14 Student Visual Asset remains in history, excluded through an append-only event. Question-side graph remains in the context.

## E. Safety / Regression

New GradingJob: 0. Ornith Grading: 0. Other model calls: 0. Score/feedback generation: 0. #8 changed: NO.
unittest: 270 tests OK. pytest: 288 passed (9236 warnings). Ruff: PASS.
No frontend changes.

### Recovery incident

The provisional /tmp/h3h3g.py script overwrote existing reconstruction-input.json files with {} before the reusable repair implementation was introduced. The two pre-existing input files (#11/#14) were restored from copies matching their original manifests exactly; original SHA values:
- #11: 3394f0b40eb33571d1196f43459fddb5cc2515cc017408073e756314f4e5a4a3
- #14: 896226999e3b8b0b8e7e444ca71ffee57011adb25d53f98edd39d58efc61fba2
The six legacy Teacher-origin v1 inputs were originally absent. The sealed sidecars are now the production repair path; empty provisional inputs are not accepted as valid provenance. Historical DB revision content was not rewritten.

H.3-H.3g: COMPLETE — 8 production previews PASS; #12/#13 await explicit transcription.
