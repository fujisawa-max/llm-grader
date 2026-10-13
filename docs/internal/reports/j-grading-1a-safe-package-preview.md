# J.GRADING.1a — Safe Revision-bound Grading Package Preview

Status: **COMPLETE**. Local implementation, API integration tests, full backend validation, and the deployed production preview acceptance below pass. J.GRADING.1 remains **PARTIAL** until production Job execution, teacher review, and finalization acceptance is completed.

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

The operator deployed J.GRADING.1a before this acceptance. Using the authenticated Codex teacher account, `GET /api/v1/openapi.json` returned 200 and listed `POST /api/v1/tests/{tid}/submissions/{sid}/grading-package-preview`; login returned 200 with role `teacher`. No Course, Test, Submission, authoring record, or worker setting was created or changed.

### Health and baseline

`GET /api/v1/health` returned 200 before and after preview: `status=ok`, `database=ok`, artifact root exists/readable/writable, and global job counts were `pending=0`, `failed=0`, `review_required=0` at both checks.

The read-only Test history and Submission list showed active edition B (`b9a17f19-b38e-4d8e-8969-2773fa70b0e6`), S1 pinned to A (`9fd3981c-ee1b-4046-8525-a98f687e8b06`), and S2 pinned to B. The pre-first-preview Test event feed contained 7 events and 0 grading/job events. After preview, the feed still contained 7 events; before and after the repeat-preview batch the event types were `test_created=1`, `authoring_draft_created=2`, `authoring_draft_saved=2`, and `authoring_revision_confirmed=2`. Submission pins and active revision also remained unchanged.

The reconstruction-run list returned 0 for both S1 and S2 before the repeat-preview batch and after it. The earlier acceptance record also confirms that the registered synthetic PDFs had not been OCR-processed or reconstructed. No grading Job was created: the Test had zero job-related events before and after, and global health job counts did not change. The API has no Test-filtered persisted-Job count endpoint; its unfiltered Job listing was not queried to avoid reading unrelated Test data. The preview route returns only the synthetic-answer hash, not the synthetic text. No production database or artifact was directly inspected.

### Preview results

Each Submission was previewed twice with the exact same Question ID and synthetic answer text. All four preview calls returned 200 and `synthetic_input=true`.

| Submission | Pinned revision / edition | Snapshot SHA-256 | Question | ModelAnswer | Rubric levels | Canonical package hash |
|---|---|---|---|---|---|---|
| S1 `fe0f55c4-29e6-401d-a765-6e9153f23643` | A `9fd3981c-ee1b-4046-8525-a98f687e8b06` / 第1版 | `bcfdeebc2917ca97f10fadca6000bf966c9f5e489b8461540b1cdb350a01a0ec` | `Edition A question` | `Edition A answer` | `[0,10]`; max 10 | `073346e9a31af6743399bfa531ccdb3cb2f40a44c8eb6cdc01c4eefdec6ec68b` |
| S2 `5f9a6b5d-dd30-482a-99ef-e1be6b9600fb` | B `b9a17f19-b38e-4d8e-8969-2773fa70b0e6` / 第2版 | `7bb5dd91217637cc95cd9c745c0d0ccf479268394c3619b1c36701a54d1a75dd` | `Edition B question` | `Edition B answer` | `[0,5,10]`; max 10 | `eec54659f379191cc7065aa7587465621456ac21158a842b9d238af10baffe4e` |

Both packages used stable Question identity `1b915527-42cc-488d-9554-17f36d08fca3`. Both had no alternatives and no visual references. The B rubric description remains `Edition A criterion` in the fixture; its frozen B scoring levels are `[0,5,10]` as expected. A and B canonical package hashes are different.

The second preview for each Submission exactly repeated its first canonical package hash, snapshot hash, revision ID, Question text, ModelAnswer, rubric levels/conditions, and visual-reference list. Thus S1 continued to use edition A while B was active, and S2 used edition B. The preview-triggered GradingJob, OCR, grader/LLM, and RuntimeManager call counts were 0; the health endpoint does not expose a separate model-call counter.

### Deployment identity

OpenAPI identifies the service as `llm-grader API` version `1.0`, which is not a build identifier. OpenAPI has no Git SHA or Alembic-version route; `/api/v1/version`, `/api/v1/system/version`, and `/api/v1/admin/alembic` returned 404. Deployed Git SHA and production Alembic version are **unverified**. The new route's presence and behavior are verified directly against production.

This acceptance does not exercise production Job execution, teacher review, or finalization. J.GRADING.1 remains **PARTIAL** for those outstanding checks.

## Files changed

- `src/scoring/revision_grading.py`
- `src/scoring/grading_execution.py`
- `src/scoring/api/domain.py`
- `tests/test_revision_grading.py`
- `docs/internal/reports/j-grading-1a-safe-package-preview.md`

The J.GRADING.1 production-acceptance report received a brief cross-reference to this acceptance; J.GRADING.1 remains PARTIAL as recorded above.

## Exact git status

```text
 M docs/internal/reports/j-grading-1-confirmed-revision-binding.md
 M docs/internal/reports/j-grading-1a-safe-package-preview.md
```

No commit or push was made.
