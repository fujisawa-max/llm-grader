# Phase H.3-C.1 Completion Report

## 1. Environment

The four exact `MODEL_ANSWER_SOURCE` files were processed from
`testData/SampleQ/modelAnswer/`. PostgreSQL was the existing persistent
database (Alembic head `0011_student_answer_recon`). No migration was added.
The source rows use the existing `TestMaterial` table; drafts and visual
references are immutable artifacts under
[`artifacts/h3c1-model-answer`](../artifacts/h3c1-model-answer).

## 2. Source PDFs

| sample | SHA-256 | pages | source document ID |
|---|---|---:|---|
| Q1 | `c83b0e36566a0ba53b1803c66c5e982267d7da021d73f86adccf26b6712073ce` | 1 | `acfaa618-1e5b-4771-9f22-d54a6e4b4e99` |
| Q2 | `8e9a066d9e5b3d269ecd1b3d43bff1bc8b2d9092e281b719f5d967e8a8c23d09` | 1 | `a85599a9-d24e-4ce9-8d6d-fefc5c927f01` |
| Q3 | `4d467b25503a94d6a9fbb66501639df179abbfcdbe99c37dcd23951609fc9d9d` | 1 | `077a5124-1b47-434e-971b-4f6c9773edc0` |
| Q4 | `483a056690185c47334052d5ea7cc70e9e8908392ac5027cfb94cfeaced8c6bd` | 1 | `6c31f9af-3af3-41fc-b56f-9fb2e27deb54` |

The same-SHA rerun reused all four source rows; no duplicate source row was
created. The earlier missing-file state had no source row and did not become a
successful import. Question PDFs were never used as model-answer sources, and
the model-answer PDFs were never sent through question confirmation.

## 3. Import and mapping

`model_answer_import.py` performs PDF-native extraction, stores the original
PDF copy by SHA, keeps native Document IR, and creates per-question drafts. The
association is the current authoritative `TestQuestion.id` selected through
stable-key/hierarchy mapping. Structural nodes receive no independent draft.
The current corrected Q1 text is used; historical Confirmation text is not.

Draft counts are Q1 6, Q2 4, Q3 3, and Q4 4 (17 gradable questions). Question
text and scoring notes are separate from ModelAnswer body and Rubric Evidence.
No StudentSubmission, StudentAnswer, Reconstruction, grading result, or
student identity was read.

## 4. Rubric drafts

Explicit point evidence is represented as `EXPLICIT_SOURCE`. Forty-eight
criteria were structured from the source notes. The read-only Teacher Review
package currently marks seven entries `review_required`: Q2's ambiguous
“5点ないし10点” wording, plus Q4 rubric segmentation/total mismatches
including the Problem 3 source total conflict. No point value was silently
rounded or normalized. Q2's `max_points` remains unset and its source scores
are only reconciliation evidence.

The Q1 (3.1) production-path Rubric Draft smoke succeeded. Ornith returned
two explicit 5-point criteria; raw response and normalized response are in
[`rubric-draft-smoke.json`](../artifacts/h3c1-model-answer/sampleQ1/rubric-draft-smoke.json).
The result is still a draft and has `review_required=true`.

## 5. Q4 visual reference assets

Completed-answer assets were cropped from the original model-answer PDF, not
from a preview. They are separate from Q4's blank Question assets.

| role | owner question ID | bbox (`normalized`) | SHA-256 |
|---|---|---|---|
| completed graph | `705f1d12-4f19-4c33-b197-39212f24b3ca` | `[0.51, 0.46, 0.90, 0.61]` | `fd1c3e7ba0197b37955b9e4364b7b1b7722e87d1c4bc2abcd1c3fdf50fc70023` |
| completed complex plane | `4c567426-da7a-4aae-bccc-a0026b69f219` | `[0.08, 0.715, 0.42, 0.855]` | `3df8046ae0345de287a0062a294f6b2c7bbf4da1cfa6f30926084591271e9644` |

Both crops were visually checked for axes, labels, answer canvas, and point or
curve content. Adjacent scoring text is outside the final crop. The Q4
authoritative hierarchy and 30/20/20/40 scores remain unchanged; total is 110.

## 6. Model-call audit

- Ricoh: 0 (native extraction was sufficient)
- Uni-MuMER: 0 (no unresolved formula crop was required for this source run)
- Ornith Rubric Draft Generation: 1 successful call
- Ornith Reconstruction: 0
- Ornith Grading: 0
- GradingJob created: 0

The single Ornith call used RuntimeManager only, model
`ornith15-35b-q4km`, dynamically allocated port `18080`, and was stopped after
the request. `student_data=false` is recorded in the request and response
audit. No OpenWebUI port was touched and no owned llama-server remained.

## 7. Persistence and immutability

Database counts after import were ModelAnswer 14, RubricVersion 10, and
GradingJob 8, unchanged from the preflight baseline. Q1/Q2/Q3/Q4 Question
rows, Confirmation/Correction history, existing Question assets, and all
authoritative ModelAnswer/Rubric rows were not modified. No authoritative
ModelAnswer or approved RubricVersion was created.

## 8. Validation

The new source/draft tests passed: `5 passed`. Ruff passed for all changed
files. The repository-wide unittest/pytest commands were started, but the
existing full suite did not finish within the execution window and was
terminated; no failure from this feature was observed before the stall. The
targeted tests and compilation passed.

## 9. Teacher Review checkpoint

Review is required before any authoritative transition. In particular:

- accept/edit/reject each ModelAnswer Draft;
- resolve Q2 partial-credit ambiguity and its score reconciliation separately;
- resolve Q4 Problem 3's source-point conflict;
- review the two Q4 completed reference crops;
- review the Q1 candidate's two 5-point criteria.

No ModelAnswer Confirm, Rubric Approve, Q2 score correction, Student Answer
processing, Reconstruction, or grading was performed.

## 10. Final status

**H.3-C.1 source import and draft preparation: COMPLETE — Teacher Review
required.**

**H.3-D readiness: NOT READY.** It requires teacher-confirmed ModelAnswer and
approved Rubric for Q1 (3.1), plus a permitted real Student Answer and any
required Reconstruction. The next action is Teacher Review, not grading.
