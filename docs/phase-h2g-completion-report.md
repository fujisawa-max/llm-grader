# Phase H.2-G Completion Report

## Architecture and identity

The repository has no separate Assignment or StudentAnswer table. A
`StudentSubmission` points to a `TestMaterial`; the material is the existing
submission JSON containing `submission_id`, pages, and `answers[].question_id /
page_ids`. `ModelAnswer.question_id` and approved
`RubricVersion.rubric_json.questions[].question_id` are the authoritative
associations.

Resolution uses exact `TestQuestion.id`, then `stable_question_key`, then an
exact unique same-Test `question_number` (with
`LEGACY_QUESTION_NUMBER_MAPPING`). Display labels, titles, text, order, and
fuzzy matching are never used. Structural questions are rejected as mapping
targets.

## Implementation

`src/scoring/grading_mapping.py` adds the deterministic
`QuestionIdentityResolver`, `GradingInputAssembler`, submission ownership and
page-hash checks, orphan/duplicate/cross-Test validation, and dry-run legacy
snapshot equivalence. Bundles contain question context and hash, current
authoritative provenance/corrections, max points, answer page IDs/hashes,
current ModelAnswer, exact rubric entry, assets, and a semantic SHA-256. They
contain no absolute paths, timestamps, score, feedback, or model output.

The existing `prepare_inputs` path now uses the same exact question and
approved-rubric resolver and validates the dry-run bundle before constructing a
legacy job snapshot. No job is enqueued by H.2-G.

Read-only endpoints are available at:

* `/api/v1/tests/{test_id}/submissions/{submission_id}/grading-input-readiness`
* `/api/v1/tests/{test_id}/submissions/{submission_id}/questions/{question_id}/grading-input-preview`

`GradingMapping` displays identity, answer/model/rubric status, blockers,
effective context, asset hashes, and bundle hash in Test Workspace.

## Synthetic validation

The isolated `H.2-G mapping validation` fixture has structural parents A/B and
leaves A1/A2/B1. A1 and B1 deliberately share `(1)`. Answers were created in
B1/A2/A1 order; rubric entries in A2/B1/A1 order; model answers in a separate
order. Unique `QUESTION_TOKEN_*`, `STUDENT_TOKEN_*`, `MODEL_TOKEN_*`, and
`RUBRIC_TOKEN_*` values prove four-way identity. Tests cover swaps, missing and
duplicate answers, structural/cross-Test answers, rubric reorder/duplicate/
unknown/structural entries, asset integrity, ancestor isolation, deterministic
and content-sensitive hashes, and legacy snapshot equivalence.

## Real PostgreSQL audit

PostgreSQL is 16.15, database `grader`, Alembic head
`0010_test_question_correction`. Existing sampleQ1/Q2/Q3 were read only:
gradable counts are 6/4/3 and each has zero submissions. Q2 remains score
unset and uses its corrected current title/display label and formulas. Q3's
corrected authoritative formulas and figure asset are resolved from current
TestQuestion state; historical Review/Confirmation state is not used. No
sample ModelAnswer, Rubric, StudentAnswer, or grading job was added.

The dedicated synthetic Test was created through `DomainService` in
PostgreSQL. A complete attempt builds all bundles; a separate attempt with one
missing answer is blocked while the other two bundles remain valid. Existing
rows, import artifacts, and `llama-server` process state were hashed/checked
around the audit.

## Validation

* `python -m unittest`: 202 passed
* `python -m pytest -q`: 213 passed
* `ruff check`: clean
* Node v22.14.0 / npm 10.9.2: typecheck and production build passed; lint has
  the pre-existing React hook warning only
* Playwright Chromium 134 with the documented Ubuntu override: real browser
  mapping preview passed, including missing-answer `MISSING_STUDENT_ANSWER`
  display and effective-context preview. No model or worker was started.

The bundle currently represents the registered submission page artifacts
(`input_stage=answer_pages_before_reconstruction`); OCR/reconstruction remains
the later grading phase. Thus a submission can be identity-ready while actual
grading remains unavailable until H.2-F readiness and the later answer
reconstruction contract are satisfied.
