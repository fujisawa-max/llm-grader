# Phase H.3-A Completion Report

## Implemented

H.3-A now has a dedicated `StudentAnswerReconstructionInputBuilder` and
`StudentAnswerExtractionPipeline` in `src/scoring/student_answer.py`.
Question identity is resolved with the H.2-G exact resolver before any OCR.
The builder uses only the selected TestQuestion context and the submission's
source pages. Its schema has no ModelAnswer, Rubric, max_points, score, or
grading policy fields.

The pipeline stores append-only extraction runs, per-question extraction
results, and versioned reconstructions. Migration `0011_student_answer_recon`
was applied additively to PostgreSQL; head is now that revision. Source files
are never modified. Run artifacts contain source/page hashes, Ricoh raw and
normalized evidence, original-source formula crops, Uni evidence, reconstruction
input/raw/normalized output, and a manifest hash.

`RuntimeStudentAnswerStages` is the RuntimeManager-only adapter for the three
H.3-A roles. It owns/stops managed runtimes and does not expose a grading role.
Borrowed runtimes are never stopped.

H.2-G bundle assembly now uses a selected COMPLETE or REVIEW_REQUIRED
reconstruction when present, retaining source submission identity, source hash,
reconstruction identity/version/status, and `RECONSTRUCTED_FROM_DOCUMENT`.

Read-only/API paths include reconstruction input preview, run listing/status,
result inspection, safe answer-page serving, and explicit run selection. An
HTTP request cannot implicitly start a runtime.

## Safety checks

Synthetic tests prove source hash mismatch rejection, cross-question/structural
identity protection, no ModelAnswer/Rubric/max_points leak, preservation of the
intentional wrong answer `2 + 2 = 5`, uncertainty → `REVIEW_REQUIRED`, append-only
versioning, deterministic hashes, idempotent reuse, crop provenance, and bundle
integration. Ricoh is cached per source page; Uni-MuMER receives only original
formula crops. Student evidence is treated as untrusted quoted content.

## Validation

* PostgreSQL 16.15, database `grader`, Alembic `0011_student_answer_recon`.
* `python -m unittest`: 210 tests, all passed.
* `python -m pytest -q`: 221 passed.
* Ruff: clean.
* Node v22.14.0 / npm 10.9.2: typecheck and production build passed; lint has
  the existing React hook warning only.
* No grading job, worker, score, feedback, or RuntimeManager invocation was
  made during tests.

## Runtime smoke limitation

The actual runtime smoke is not complete in this environment. RuntimeManager
and the configured Ricoh/Uni-MuMER/Ornith endpoints (`8081`, `8082`, `8080`)
are stopped. The model files are present locally, but starting a server
directly would violate the RuntimeManager ownership rule; no direct launch or
substitute model was used. The synthetic injected-stage smoke passed, but it
does not claim actual Ricoh, Uni-MuMER, or Ornith model quality.

## Status

Implementation and non-model validation are complete. Phase H.3-A remains
`NOT COMPLETE` until the three configured roles are available through
RuntimeManager and one validation submission is run through Ricoh → original
formula crop/Uni-MuMER → Ornith reconstruction. H.3-B actual grading remains
deferred.
