# Phase H.3-C.1 Teacher Review & Approval Completion Report

## 1. Teacher decisions

The supplied decisions were applied through append-only workflows. Q1 and Q3
clean entries were accepted, Q2 score and partial-credit decisions were saved
as teacher edits, and Q4's Problem 3 rubric ownership correction was retained
with its raw extraction evidence.

## 2. Q1

Six current ModelAnswer versions and one approved RubricVersion were created.
The H.3-D candidate is:

- Question: `8a2a7955-2347-4c67-8581-f800721ec558`
- ModelAnswer: `6479d287-0c79-490e-9c4b-4d15adb2589b`
- ModelAnswer SHA: `253335e8b2ef12171d6c42e4d6ac5d8997785c61de5e3c0c0a134c2111780b66`
- RubricVersion: `ffbf23b3-80a6-4856-9005-e814752d41e2`
- Rubric SHA: `bef1ff5363a88126e0bcdfb10a8a99a061253cf5fb8098a839516a69d82c5f35`
- Rubric total: 10

The two criteria are 5 points each and retain `EXPLICIT_SOURCE` provenance.

## 3. Q2 score reconciliation

The actual database mapping was used. One identifier in the request ended in
`475f`; the actual TestQuestion ID is
`dbd8a6e7-8fdd-475c-adb7-652db377ab8a`.

| Question ID | Before | After | Correction ID |
|---|---:|---:|---|
| `24a42587-a730-408c-8565-1221cba11453` | unset | 20 | `dadf9e27-fd37-458c-a9a2-d26a2bc30e86` |
| `dbd8a6e7-8fdd-475c-adb7-652db377ab8a` | unset | 20 | `ed61cf70-ad28-4e70-8ce1-3caed217ae59` |
| `5928d0e3-ea16-48e4-b9ff-a96209e4eb37` | unset | 40 | `fab46c9b-3d0d-4cae-93dd-af67b26104ca` |
| `8c8c578c-1635-4f13-91e8-4b40dbe3e258` | unset | 20 | `32dc0a47-c9fb-4af5-9413-8b859ba2b571` |

Q2 total is 100. The correction notes include source PDF ID/SHA, teacher ID,
evidence provenance, and the reconciliation reason. Question content hashes
were not changed.

The Q2 rubric contains seven `TEACHER_EDITED` criteria. Calculation partial
credit is 10/5/0, final answer is 10, Problem 2 is 20/10 for each operation,
and Problem 3 is 20/10/0.

## 4. Q3

Three ModelAnswer versions and approved RubricVersion
`6ae61984-e57b-43e0-8cb9-dd3c1d98e843` were created. The rubric totals are
30, 30, and 40. Current corrected formulas are used; historical escaped text
was not used.

## 5. Q4

Four ModelAnswer versions and approved RubricVersion
`84ca25fb-baf4-4a31-93a5-688d200c10a6` were created. The authoritative totals
remain 30 / 20 / 20 / 40, with Test total 110.

The apparent Problem 3 50-point conflict was classified as native rubric block
cross-question contamination. The 15-point calculation and 15-point final
answer entries remain in raw evidence and are assigned to Problem 1. Problem 3
now has seven criteria totaling 40, including four visual criteria.

The completed graph and complex-plane reference assets were accepted without
recropping. Their existing SHA-256 values remain unchanged.

## 6. Provenance and persistence

- Current ModelAnswer versions created: 17
- Approved RubricVersions created: 4
- `EXPLICIT_SOURCE` criteria: 42
- `TEACHER_EDITED` criteria: 7
- `LLM_PROPOSED` criteria approved: 0
- unresolved approved-question drafts: 0
- source PDFs, Question history, Confirmation, and prior Correction history: unchanged

Review decisions are recorded in
`artifacts/h3c1-model-answer/teacher-review-revision-1.json`; application
results are in `teacher-review-apply-result.json`.

## 7. Readiness and isolation

Question-side grading readiness is READY for all 17 gradable questions. Actual
H.3-D execution was not started because no Student Answer was selected or
processed. StudentAnswer content, reconstruction, and grading results were not
read.

## 8. Model-call audit

- Draft-generation Ornith Rubric call: 1 (previous phase)
- Additional Ornith calls during Teacher Review: 0
- Ricoh: 0
- Uni-MuMER: 0
- Ornith Reconstruction: 0
- Ornith Grading: 0
- GradingJob created: 0

## 9. Regression

- `python -m unittest`: 242 tests, OK
- `python -m pytest -q`: 258 passed
- Ruff: pass

The full suites were run in the documented non-sandbox execution environment;
the sandbox-only Starlette TestClient portal hang was avoided without changing
the tests.

## 10. Final status

**H.3-C.1: COMPLETE.**

**H.3-D: NOT STARTED / NOT READY FOR ACTUAL GRADING.** A permitted real Student
Answer and its mapping/reconstruction selection are still required. No grading
model was started.
