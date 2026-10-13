# J.GRADING.1a — Safe Revision-bound Grading Package Preview

Status: **READY_FOR_PRODUCTION_VALIDATION**. Local implementation, API integration tests, and full backend validation pass. Production deployment and preview acceptance were not performed because this workspace has no deployment host access. J.GRADING.1 remains **PARTIAL** until the remaining production execution/review/finalization acceptance is completed.

## Design and shared assembly boundary

The prior production blocker was that the Web grading-job endpoint both assembled the package and committed a `queued` job. A separately managed worker may claim that row and call the real grader. The old `grading-input-preview` endpoint is read-only, but requires an existing reconstruction or accepted student visual and therefore could not build a package for the registration-only S1/S2 records.

Added `assemble_revision_execution_package` in `src/scoring/revision_grading.py` as the shared, inference-free package boundary. It verifies the Submission's pinned revision and confirmed snapshot, builds the input through `RevisionGradingInputAssembler`, validates the execution bundle and discrete rubric, revalidates the bundle against the immutable revision, and verifies frozen asset bytes. It returns the same canonical bundle and bundle SHA used by the worker path, along with immutable asset references.

`create_revision_execution_job` now uses that shared boundary before it reads grader configuration and creates the existing `GradingJob`/`GradingJobItem`. The Job's queue state, commit boundary, worker behavior, runtime configuration, and inference behavior are unchanged. The Job route still consumes the Submission pin and cannot select the active revision independently.

## Diagnostic API and read-only behavior

Added:

```text
POST /api/v1/tests/{tid}/submissions/{sid}/grading-package-preview
```

The request contains a `question_id` and may contain an explicit `synthetic_answer_text` (up to 20,000 characters). The route uses the existing staff authorization dependency and checks course ownership for the Test; a Submission from another Test is returned as not found. Normal requests use the existing selected reconstruction. Synthetic text is placed only into an in-memory, normalized reconstruction-shaped input and is never persisted or returned.

The response includes the Submission/revision/edition/hash identity, stable Question identity and hierarchy, effective Question text, ModelAnswer primary/alternatives, Rubric criteria and levels with maxima derived from those levels, frozen visual-reference IDs/SHA values, the canonical package hash, and a synthetic-input flag. It omits student IDs, student answer text, artifact paths, and internal artifact references.

The handler does not create Jobs, JobItems, events, queue entries, reconstructions, result records, or artifacts. It does not load grader configuration or invoke a worker, RuntimeManager, grader client, OCR, or reconstruction. It never commits and rolls back the read transaction in `finally`. Synthetic input is not logged by this path.

## Regression evidence

- The API-level preview and the actual Job-creation path were exercised against the same disposable FastAPI/SQLite fixture. For a persisted valid reconstruction, the preview's canonical package hash exactly equals the bundle hash stored by the Job created immediately afterward.
- Edition A / B regression: after B is active and current formal Question/ModelAnswer/Rubric projections are deliberately changed, S1's preview still returns A's Question and answer with `[0,10]`; S2 returns B's Question and answer with `[0,5,10]`. Each preview hash equals its subsequent Job bundle hash.
- Synthetic-preview safety test patches worker execution, RuntimeManager construction, GradingClient construction/execution, and reconstruction entry points to fail if touched. It verifies synthetic text is absent from the response, filesystem, and persisted state; Job, JobItem, grading-event, domain-event, extraction, and reconstruction counts are unchanged; and Submission/revision data and snapshot hash remain unchanged.
- Authorization regression verifies a teacher cannot preview a Test outside their course and cannot use a Submission belonging to another Test.
- Fail-closed API tests cover invalid stored snapshot hash, missing/incomplete grading definition, and unsupported schema. Existing reference-asset verifier tests cover modified bytes and invalid artifact paths; the shared package boundary invokes those verifiers before returning a preview.
- No migration was added. Alembic head remains `0018_revision_lineage`.

## Validation

- Focused revision/package, grading-definition, execution, review, and authoring groups: **126 passed**.
- Full backend suite: **1,062 passed, 2 skipped**. The 23 warnings are existing SQLAlchemy model collection warnings and a Starlette deprecation warning.
- Ruff on changed Python: passed.
- `compileall` on changed Python/tests: passed.
- `git diff --check`: passed.
- No frontend files changed. A search found no frontend caller for the new diagnostic route; the existing grading-job API contract remains unchanged, so TypeScript/ESLint/Next build were not needed for this backend-only API addition.
- The disposable API integration uses the real FastAPI router, authentication/authorization, SQLAlchemy session, package assembler, and Job-creation route. It does not use a frontend/browser because no frontend contract or UI changed.
- Local tests use controlled synthetic reconstruction/grader callbacks where the existing J.GRADING.1 integration requires them. Real OCR, LLM, or grader calls: **0**. Production Jobs created: **0**.

## Production deployment / acceptance

No production deployment was attempted. This workspace has no Docker executable, SSH agent, or SSH host configuration. The existing runbook requires stopping the separately managed worker, deploying, running checks, and resuming it; there is no authorized host control path here. The new API has therefore **not** been verified as deployed.

After deployment through the authorized runbook, production acceptance should call this preview for the existing dedicated S1 and S2 records, using explicit synthetic answer text because their registered PDFs have no reconstruction. Verify revision A/B identity, Question/ModelAnswer, score levels, distinct canonical package hashes, unchanged Job/event counts, and zero OCR/model calls. Do not create production grading Jobs. This phase does not validate teacher review or finalization; J.GRADING.1 remains PARTIAL for those outstanding checks.

## Files changed

- `src/scoring/revision_grading.py`
- `src/scoring/grading_execution.py`
- `src/scoring/api/domain.py`
- `tests/test_revision_grading.py`
- `docs/internal/reports/j-grading-1a-safe-package-preview.md`

The worktree also contains the already-modified J.GRADING.1 production-acceptance report from the preceding task; it was not edited during this phase.

## Exact git status

```text
 M docs/internal/reports/j-grading-1-confirmed-revision-binding.md
 M src/scoring/api/domain.py
 M src/scoring/grading_execution.py
 M src/scoring/revision_grading.py
 M tests/test_revision_grading.py
?? docs/internal/reports/j-grading-1a-safe-package-preview.md
```

No commit or push was made.
