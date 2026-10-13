# J.GRADING.1b — Isolated Synthetic Grading Execution and Review Acceptance

Status: **READY_FOR_PRODUCTION_VALIDATION**. Local isolated execution, review, finalization, regression, and static validation pass. No production execution was performed. J.GRADING.1 remains **PARTIAL** until an operator-approved deployed Job → Worker → Review → Finalize acceptance is completed.

## Architecture and isolation decision

The ordinary `JobWorker` accepts a Job ID, atomically claims that queued row, and runs `recover_stale_jobs()` over every stale nonterminal Job in its database before the claim. There is no worker-role or execution-mode filter in the claim path. A metadata flag or a new `execution_mode` value alone would therefore not isolate synthetic Jobs: a normal worker pointed at the same database could claim one, and stale recovery could mutate other rows in that database.

J.GRADING.1b uses a dedicated, file-backed SQLite database below a disposable test root. The validation helper checks the exact database path, config path, and run directory; requires an explicit allowlisted Test; and refuses to call the ordinary worker unless every Job in that database is a correctly marked, revision-pinned synthetic validation Job. The metadata marker is audit data, not the isolation boundary. The physical database separation is the boundary. The ordinary worker uses a second disposable database, so it cannot see or claim validation Jobs. The validation worker cannot see ordinary Jobs. An unmarked Job in the validation database is refused before the ordinary worker and its global stale-job recovery are invoked.

No public synthetic API, production queue mode, worker setting, model setting, or migration was added. This keeps synthetic execution out of the deployed Web path until a separately approved production validation design is provisioned.

## Shared execution and persistence boundaries

The normal `create_revision_execution_job` path and the isolated harness now share `build_revision_execution_snapshot`. It consumes the already assembled package and creates the same sealed `grading-execution.v1` snapshot, including the confirmed revision ID/hash, edition label, bundle, model-generation configuration, and frozen asset references. Normal Job creation still assembles from the saved Submission reconstruction and persists the existing `GradingJob` / `GradingJobItem` shape.

The isolated harness obtains its package from J.GRADING.1a's `assemble_revision_execution_package` with an explicitly supplied synthetic answer. The answer is not written to `StudentAnswerReconstruction`, extraction records, or a separate artifact. The pending validation Job stores it only inside the sealed bundle in the disposable validation database. The production Submission and confirmed snapshot are not modified.

The production and synthetic runners share `verify_sealed_revision_execution_job`, which verifies the bundle and snapshot hashes, revision/job/item identity, rubric levels, asset SHA values, and visual asset roles before execution. They also share result validation, manifest verification, `persist_execution_result`, and the normal `JobRepository.sync_item_from_artifacts` persistence path. The synthetic runner replaces only the grader response: it does not instantiate `RuntimeManagerClient` or `GradingClient`, and it does not perform OCR or reconstruction.

## Edition A / B execution evidence

The production-like FastAPI fixture confirmed Edition A, registered S1, confirmed Edition B, and registered S2. With B active, it created S1's delayed Job from S1's A pin and S2's Job from B's pin. Current formal Question, ModelAnswer, and Rubric projections were deliberately changed before package creation.

| Submission | Job revision | Frozen Question | Frozen ModelAnswer | Frozen levels | Synthetic score / max |
|---|---|---|---|---|---|
| S1 | Edition A / 第1版 | `Question edition A` | `ModelAnswer edition A` | `[0, 10]` | 10 / 10 |
| S2 | Edition B / 第2版 | `Question edition B` | `ModelAnswer edition B` | `[0, 5, 10]` | 5 / 10 |

For both Jobs, the package hash exactly matched the J.GRADING.1a read-only preview hash for the same Submission, Question, and synthetic answer. Their snapshot hashes differed and remained unchanged through execution and retry. The deterministic score rule selects the maximum for a two-level policy and the lowest positive explicitly configured level when a partial level exists. It does not create a level. Every result uses the criterion ID from the pinned bundle and a reason stating `合成検証結果です。実採点ではなく、確定版の得点段階を検証しています。`; evidence is marked as synthetic in the quote.

## Worker, review, and finalization

Both validation Jobs completed through the real `JobWorker`, its atomic claim/state transitions, result-manifest checks, and JobItem projection. The ordinary worker given a synthetic Job ID found no row in its separate database and returned without claiming anything. The synthetic worker given an ordinary Job ID likewise found no row. A normal unmarked Job placed in the validation database was refused, and the concurrent claim regression showed exactly one of two claimers can acquire a queued Job. A duplicate run after completion returned no work. A stale-job recovery retry revalidated the existing manifest and retained S1's A pin and score.

The normal authenticated grading review API showed S1 as 第1版 with A's Question, ModelAnswer, `[0,10]`, and score 10; it showed S2 as 第2版 with B's content, `[0,5,10]`, and score 5. Unauthenticated review was denied. Both were finalized through the normal finalize API, which recorded the correct edition label and total. Repeating finalization returned `created=false`. Neither Submission was published; the publication service reported `published=false`, and there were no `results_published` or `results_unpublished` events.

The synthetic answers were absent from reconstruction tables before and after execution. Confirmed snapshots remained unchanged. The J1b fixture created two local validation Jobs and two JobItems; execution added normal Job state events only within the disposable database. No production Job, Submission, reconstruction, result, or event was created or changed.

## Security and fail-closed coverage

- The isolated harness rejects a Test that is not explicitly allowlisted before creating a Job.
- A legacy Submission with a null revision pin cannot enter the synthetic package path; it fails with `WEB_GRADING_REVISION_REQUIRED`.
- A worker refuses unmarked Jobs and Jobs outside its allowlist. Its database-wide preflight prevents normal rows from being touched by the ordinary worker's stale recovery.
- The shared worker contract rejects cross-Test or missing revision pins and revalidates the confirmed snapshot and frozen package before the synthetic runner is invoked.
- Existing regression coverage rejects corrupted confirmed snapshot hashes, tampered/resealed bundles that disagree with the confirmed revision, asset hash tampering, unsupported or incomplete definitions, invalid/unknown/duplicate criterion IDs, invalid scores, and cross-Test package access.
- Review authorization remains the existing teacher authorization path; there is no synthetic bypass.
- Finalization does not publish. Student result publication remains a separate explicit API operation and was not called.

The focused J1b test patches RuntimeManager and grader-client construction/chat to fail if touched during its isolated acceptance. It also patches student reconstruction to fail if invoked. All stayed untouched. Real LLM, OCR, reconstruction, grader, or RuntimeManager calls: **0**.

## Migration and production prerequisites

No migration was added; `alembic heads` reports `0018_revision_lineage`.

Production acceptance remains a separate operator-approved step. The current production workers must not share a database with synthetic validation Jobs. A future production validation must provision a separate disposable database and a dedicated validation process with a strict Test allowlist, then stage only the selected confirmed revision, Submission binding, required immutable source references, and explicitly synthetic input into that isolated environment. Existing production S1/S2 do not have persisted reconstructions; the synthetic answer must be supplied to the shared in-memory package assembler, never written into their production reconstruction tables. No production API or worker currently provides this isolated staging boundary, so the local acceptance must not be treated as deployed acceptance. Do not run this against the ordinary production database or queue.

## Validation

- Focused revision grading, execution, review, publication, and worker groups: **53 passed**.
- Full backend suite: **1,063 passed, 2 skipped**. Warnings were existing SQLAlchemy test-class collection warnings and a Starlette deprecation warning.
- Ruff on changed Python: passed.
- `python -m compileall -q src/scoring tests`: passed.
- `git diff --check`: passed.
- Alembic head: `0018_revision_lineage`.
- Production grading Jobs/model/OCR calls: **0**. Local J1b synthetic Jobs: **2**; no real model calls.

## Files changed

- `src/scoring/grading_execution.py` — shared sealed snapshot builder, shared immutable Job verification, and shared result manifest persistence used by production and isolated synthetic execution.
- `tests/synthetic_validation.py` — disposable-DB-only package/job helper and allowlisted deterministic worker/runner; not exposed as an application API.
- `tests/test_revision_grading.py` — A/B delayed-job, worker isolation, review/finalize, authorization, no-persistence, duplicate/retry, and claim-race regression.
- `docs/internal/reports/j-grading-1b-isolated-synthetic-execution.md` — this report.

## Exact git status

```text
 M src/scoring/grading_execution.py
 M tests/test_revision_grading.py
?? docs/internal/reports/j-grading-1b-isolated-synthetic-execution.md
?? tests/synthetic_validation.py
```

No commit, push, deployment, production Job, or production data mutation was performed.
