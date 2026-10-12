# J.UI.10d — Teacher-confirmed Diagram Override & Actionable Trust UX

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Deployed Sample Q5 acceptance remains pending; managed stubs do not substitute for it.

## Concrete root cause

`RicohDiagramGrouping` detects `finish_reason=length`/truncated output and raises `diagram_ricoh_output_truncated`. The geometry extractor correctly preserves the original server-derived visual component as `status=unresolved`, retaining source IDs/bbox and the failure reason. However:

- `DiagramReview.record(state=accepted)` rejected **every** unresolved candidate, including after a safe manual crop correction.
- `DiagramReview.validate()` reused that unconditional rejection during Save and formal registration.
- `DiagramReview.tsx` disabled Use for every unresolved status.
- ModelAnswer content readiness rejected every unresolved/reason-bearing diagram, regardless of teacher action.

Thus the automated grouping failure was conflated with source-integrity failure at all layers. Manual correction changed bbox but could not change that policy. The reported production reason maps directly to this code path. No production database/model session was accessed or changed during this phase.

## Server trust policy

A small `diagram_trust.py` helper derives trust from canonical server candidate evidence **after** verified crop/source validation:

| State | Meaning | Accept rule |
| --- | --- | --- |
| trusted | Verified source/crop and confident detection | Existing explicit Use action |
| teacher_confirmable | Verified source/crop; automated detection uncertainty remains | Explicit `teacher_confirmed: true` |
| hard_invalid | Integrity/boundary/stale/membership failure, or unknown failure | Cannot accept or override |

The confirmable allowlist is deliberately narrow:

- `diagram_ricoh_output_truncated`
- `diagram_ricoh_unavailable`, `diagram_ricoh_timeout`
- `diagram_ricoh_invalid_json`
- `diagram_ricoh_low_confidence`
- `diagram_geometry_ambiguous`, `diagram_grouping_ambiguous`

JSON parse failures now have a distinct Ricoh reason. Valid-schema, known-ID low-confidence results are distinguished from invalid membership/schema; they are still rejected as automatic grouping. Unknown IDs, duplicate membership, malformed schema, unsafe shared source ownership and unknown reasons remain non-overrideable. No failed Ricoh response becomes trusted grouping.

Existing server-generated candidate lookup, native source membership, verified PDF/material SHA, current authorized Test/Question assignment, page bounds, finite bbox, area/pixel limits, sibling boundaries and artifact hash checks remain mandatory. Crop/source checks execute before confirmation can authorize acceptance. Browser-supplied trust state, acceptance reason or acceptance-method metadata is never authoritative. `teacher_confirmed` must be an actual boolean; client strings/integers cannot satisfy the requirement.

Exact, parent and PDF scopes use the same shared policy. Discovery ownership and child assignment remain separate. Each entry independently confirms its assignment; source candidates/content-addressed crop bytes can remain shared.

## Teacher interaction

Trusted candidates keep `この図を使用` with no additional warning or click.

Teacher-confirmable candidates show:

> 図の出典範囲を自動では確認できませんでした。PDFと図の範囲を確認してください。教師が確認した図は使用できます。

Their enabled action is `この図を確認して使用`. No checkbox is added. A candidate is not accepted just because it is shown or its range is corrected.

`範囲を修正` still uses the existing PDF rectangle/numeric controls, server crop-preview validation and original/final bbox provenance. Applying corrected bounds to a confirmable diagram leaves it a candidate and clears confirmation; another explicit Use/Confirm is required. Trusted accepted diagrams retain their existing correction interaction.

Hard-invalid candidates keep Use disabled and show a Japanese explanation and recovery direction. Read-only/loading/structural-source-stale states also explain why actions are unavailable. Technical reason codes and trust/confirmation fields are in collapsible source/verification details, including API-error codes. The sticky selector, left PDF/right editor, crop preview and rectangle highlights are unchanged.

Server revalidation on GET may downgrade stale accepted diagrams. Canonical hard-invalid state cannot be overwritten by a saved local accepted record during rendering. A failed source-revalidation HTTP request also clears local acceptance/readiness conservatively, without saving or changing the persisted draft. Reloading a valid persisted source restores it normally.

## Persistence and formal transfer

Canonical records add:

- `trust_state`
- `trust_state_at_accept`
- `teacher_confirmed`
- `confirmation_reason_code`
- `acceptance_method`: `accepted_by_teacher_after_unresolved_detection` for confirmed uncertainty

Existing Ricoh used/finish reason/response-field diagnostics, automatic/final bbox, teacher-adjusted flag, source/material SHA, candidate ID, crop SHA, scope, source owner and assigned Question remain intact.

Save and formal registration recompute trust and source safety. Forged metadata is overwritten by canonical values; an explicit confirmation cannot bypass source checks. Resume restores the confirmation only after source revalidation. Stale records lose confirmation and become hard-invalid candidates. Historical trusted accepted records without new fields remain valid with `teacher_confirmed=false`; no migration or placeholder answer text is needed.

Formal registration transfers accepted diagrams and compact provenance through the existing mechanism. Large Ricoh responses and crop base64 are not added to formal entities. A teacher-confirmed accepted diagram satisfies diagram-only ModelAnswer content readiness; an unaccepted/unconfirmed, excluded or hard-invalid diagram does not. Empty answer text stays empty. Text-only/text-plus-diagram and independent Rubric semantics remain unchanged.

The shared Question API also saves/reloads explicit teacher confirmation. Existing figure confirmation/blocking rules are unchanged; discovering a diagram does not introduce a new blocker.

## Runtime and safety

Only explicit ambiguous discovery invokes the existing RuntimeManager-managed `ocr` Ricoh WHERE profile. No new profiles, servers, GPU settings or lifecycle changes are added. Geometry-confident candidates still skip Ricoh. Teacher confirmation, crop correction, Save, GET resume and formal registration run no inference. Diagrams never use Uni-MuMER or Ornith. Model calls used by separate math regression tests remain separate from diagram decisions.

Authorization endpoints/ownership checks are unchanged. Foreign candidate/source identities, stale SHA, unsafe bbox/boundary and corrupted crops cannot be overridden. No PostgreSQL reset, Q5 mutation, grading/scoring change or answer-text fabrication occurred.

## Automated validation

Environment: production Next.js build, non-loopback HTTP, real FastAPI, disposable SQLite, actual RuntimeManager and managed llama-server stubs.

- Broad backend regression: **320 passed**.
- Final focused diagram/trust/API/scope/vision regression: **117 passed**, overlapping the broad run, including later additional integrity/Question tests.
- Production-like existing browser suite: **41 passed**.
- Dedicated final override / hard-formatting / review-target readiness run: **9 passed** (1 override browser scenario, 1 hard-formatting browser scenario, 7 frontend logic tests). No overlap with the 41-case default suite.
- TypeScript and production build pass.
- ESLint: **0 errors, 19 pre-existing warnings**; existing CSS autoprefixer build warnings remain.
- Ruff and `git diff --check` pass.
- Grading jobs: **0** in disposable integration fixtures/harness.

The critical fixture has one connected ambiguous completed grid diagram, no exact or parent region, and actual managed Ricoh returns truncated `reasoning_content` with `finish_reason=length`. It verifies PDF fallback, preview/highlight, Japanese guidance, enabled teacher action, no checkbox, correction without acceptance, explicit confirmation, empty-text readiness, Save/reload, compact formal provenance and no fake text. It also checks stale hard-invalid UI and forged SHA confirmation rejection. Model-call counters prove one discovery Ricoh call and zero additional calls during correction/confirmation/Save/reload/registration; math/Ornith/grader calls stay unchanged during that scenario.

Backend tests additionally cover every allowed reason, missing/invalid confirmation, canonical reason overriding client metadata, artifact corruption, unknown/foreign ID, SHA mismatch, invalid/non-finite/page-outside bbox, stale source, trusted historical records, Question persistence and all three scopes. Existing exact/parent/shared diagrams, source boundaries/manual crop, formal transfer, continuation, issue navigation, layout, caret/IME, math OCR and Rubric workflows pass their regressions.

An existing stale-message browser assertion was updated to the new Japanese guidance. A previously unrun review-target unit fixture passed a fallback label only on the target argument while its node-list entry lacked that label; the fixture now supplies the same source-backed node in both places. Production canonical path/navigation code is unchanged.

## Changed files and Git

Service source:

- `src/scoring/diagram_trust.py` (new)
- `src/scoring/diagram_review.py`
- `src/scoring/diagram_regions.py`
- `src/scoring/diagram_vision.py`
- `src/scoring/model_answer_diagram_review.py`
- `frontend/components/reviews/DiagramReview.tsx`
- `frontend/types/diagrams.ts`
- `frontend/lib/modelAnswerRegistrationValidation.ts`

Service tests/fixtures:

- `tests/test_diagram_trust.py` (new)
- `tests/test_diagram_review_api.py`
- `tests/test_diagram_regions.py`
- `tests/test_diagram_vision.py`
- `tests/test_model_answer_diagram_scopes.py`
- `tests/fixtures/runtime/llama_server_stub.py`
- `tests/run_runtime_browser_e2e.py`
- `frontend/e2e/diagram-review-override-real.spec.ts` (new)
- `frontend/e2e/diagram-review-real.spec.ts`
- `frontend/e2e/model-answer-review-targets.spec.ts`

This report is service-facing documentation. Initial Git status was clean; changes remain unstaged/uncommitted. No commit/push was performed. No local databases, artifacts, credentials or Codex-only files are added.

## Production acceptance still required

Deploy and verify Sample Q5 Problem3 > (1): PDF fallback with real truncated Ricoh must show Japanese confirmation guidance, correct crop/highlight, permit safe correction and explicit teacher Use, retain accepted/teacher-confirmed state after Save/resume, and permit empty-text registration readiness. Technical details should retain reason/finish/trust fields while normal guidance stays Japanese. Also verify unsafe/stale source cannot be overridden and confirmation/Save/reload make no extra Ricoh calls. Formal registration is explicit and is not performed against production merely for automated acceptance.

Only this deployed validation remains. This report does not claim real-model production success from synthetic fixtures.
