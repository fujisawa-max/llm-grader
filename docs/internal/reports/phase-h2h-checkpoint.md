# Phase H.2-H — Approval checkpoint (NOT COMPLETE)

PostgreSQL 16.15 / Alembic 0011_student_answer_recon。

## sampleQ1 corrected PDF diff

Test ID: `70a63c23-f1b1-46b7-852c-046148b6f451`

Original Confirmation: `1452d9f4-e598-409c-892c-c6538ba79565`

Corrected source: `testData/SampleQ/sampleQ1.pdf` (1 page)

SHA: `bd7cc3fa1e665af61d28ecd2776252624f5853d54938724b55545edd6bb8f0e9`

Material ID: `a6a79d68-07db-4e59-ad6f-70e6842b1e40`

Extraction: `80ff05e1-5c65-4439-b120-bda13b54f037`

Comparison Draft: `9f02bc0f-857b-44eb-b6ee-b14a1e4bc778`

Review (editing, not approved): `4c5091ae-2c78-4be8-a8d9-c55ad56cc0bd`

Structure identical: YES. 8 nodes / structural 2 / gradable 6.
Scores identical: YES. 20/20/30/10/10/10; total100.
Node count, hierarchical paths/labels, ordering, node types, gradability and scores all matched before text comparison. No fuzzy alignment.

Differences: 1 (TEXT_ONLY).

Question ID: `3d5d8e20-46b7-42c2-96bd-3e7aeb62963b`

Stable key: `review-48e6195a-5d0-q1.1`

Current: `（１）反表型AI、特化型AI とは何か説明しなさい。 `

Corrected PDF: `（１）汎用型AI、特化型AI とは何か説明しなさい。 `

Proposed Correction: replace only this text segment (反表型 → 汎用型), preserving its remaining text/space and all other items. No formula or asset differences. No score/hierarchy/label changes.

Approval: PENDING. Correction Apply: NOT EXECUTED. No Correction IDs or changed authoritative hashes yet.

The existing correction service currently supports formula and title/label changes; a minimal validated text-segment operation is needed for applying the approved correction. This checkpoint does not claim it has already been applied.

## Duplicate protection

New upload purpose `correction_comparison` stores material_type `corrected_question_sheet`. Import planner adds `correction_comparison_not_confirmable`; Confirm rechecks plan and refuses. DB migration unnecessary (existing string type). New test checks API refusal and zero TestQuestions. Normal new imports preserve existing behavior.

## sampleQ4 preflight

Located Question PDF: `testData/SampleQ/sampleQ4.pdf`.
SHA: `c3be971d251e67d0f66b994b0e2afe68ef781721efc0666fe972e12955ae6966`.
Rendered page inspected: matrix/vector problem, quadratic function, blank graph axes, blank complex plane with Re/Im, explicit30/20×2/40. Expected reviewed total110, never100.

Existing native extractor/structure parser run locally. Native Draft currently has4 nodes, not expected5; problem2 child labels merged, effective points unresolved,4 formula regions,0 accepted figure regions. Warnings: inline_subquestion_label / unassigned_formula_region / unresolved_vector_evidence. DO NOT CONFIRM this automatic Draft.

No Q4 Test/DB Draft/Review/Confirmation has yet been registered. It needs structure Review, Selective Vision as required, correct blank drawing crops, formula decisions and Import Plan. No durable assets claimed. Page render is inspection only.

## Protection

Original baseline and all original historical artifact hashes rechecked unchanged. All existing TestQuestion rows unchanged; no new TestQuestion. Existing Confirmation/ReviewRevision/Correction/asset rows unchanged. Q2/Q3 unchanged, Q1 H.3-D candidate ID preserved.

Ricoh0 / Uni-MuMER0 / Ornith reconstruction0 / Ornith grading0 / GradingJob creation0. No model-answer PDF read; no ModelAnswer/Rubric/StudentAnswer created.

## Status

H.2-H: NOT COMPLETE. H.3-C.1: NOT READY.
Q1 awaits explicit YES/NO for the above actual difference. Q4 import work remains pending; automatic draft is not authoritative.

Evidence: `artifacts/h2h-preflight/q1-registration.json`, `baseline-comparison.json`, `original-baseline.json`, and sample-specific native IR/draft files.
