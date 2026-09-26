# H.3-G.0b Ricoh structured generation diagnosis

## Reproduction and scope

Single source: sampleQ1 / s1, submission `fcf9d128-4dbb-4aee-b49b-1c715fdcfd16`.
Source SHA-256: `aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba`.
No DB writes, reconstruction, crops, grading or batch execution.
Raw diagnostics in `artifacts/h3g0b/` are restricted to the workspace owner;
raw model output can contain source personal information and must not be published.

## Root cause

The embedded Ricoh template unconditionally starts `<think>` at the generation
boundary and does not consult `enable_thinking`. The baseline emitted 3801
characters in `reasoning_content`, then repeated transcriptions as JSON.
It exhausted 2048 completion tokens before completing JSON. There was no completed
JSON followed by runaway output. `--reasoning off` alone reproduced the failure.
The schema was already present in the request; a prompt-only JSON request was not
the problem.

## Changes

`config/chat-templates/ricoh-nonthinking.jinja` preserves the embedded template
except its generation boundary: with thinking disabled it closes an empty thinking
block before content begins. RuntimeManager's Ricoh profile uses this file with
`--reasoning off`. The adapter also explicitly sends `reasoning_effort=none`.
No custom stop sequence, guessed JSON repair or output clipping is used.

Compact page extraction uses a GBNF grammar with bounded strings/region count,
normalized numeric coordinates and a single root object, with no trailing prose.
The baseline schema converter accepted numeric values outside minimum/maximum
for fractional numbers; these were rejected by local bbox validation. GBNF
constrains the number spellings before sampling; the local validator still checks
bbox geometry and the exact compact object schema. The model must reobserve and
generate valid fractions; no 0–1000 conversion is performed.

## Batch boundary

This phase diagnoses generation only. The existing H.3-G runner still calls
per-question extraction and has not been converted into an immutable page-cache
consumer. It must not be run as a production batch until page reuse, per-question
ownership and existing-selection preservation are integrated and tested.
Do not interpret a successful generation smoke as full batch readiness.

## Results

| Probe | Finish | Tokens | Inference seconds | Outcome |
|---|---|---:|---:|---|
| Original template | length | 2048 | 95.88 | Hidden reasoning 3801 characters; incomplete JSON |
| Reasoning off only | length | 2048 | 96.19 | Same failure |
| Patched template | stop | 237 | 22.36 | Valid JSON/bbox, but one whole-page region |
| Scoped prompt | stop | 611 | 37.55 | Out-of-range bbox rejected |
| Numeric grammar | stop | 509 | 33.41 | Zero-area bbox rejected |
| Final grammar/prompt | stop | 441 | 30.62 | JSON and bbox PASS; 7 regions, one duplicate |

The final result has zero reasoning characters, seven regions representing six
question labels, and one identical duplicate. It is diagnostic evidence only,
not a READY production extraction. Duplicate evidence is preserved and flagged
`DUPLICATE_RICOH_REGION`, with `review_required=true`; no automatic deduplication
or teacher acceptance occurs. This phase is COMPLETE for generation diagnosis;
batch retry remains NOT READY pending extraction fidelity/ownership verification
and page-cache integration. A two-stage fallback is not needed to fix termination.
If later required for fidelity, its projected calls are 8 layout calls plus N text
crop calls (N depends on validated regions); it has not been implemented.
