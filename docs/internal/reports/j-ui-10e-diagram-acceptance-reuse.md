# J.UI.10e — Diagram Acceptance Reliability & Confirmed Diagram Reuse

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Actual deployed Sample Q5 acceptance/reuse has not been observed in this work; managed stubs are automated validation only.

## Acceptance root cause and fix

The previous component already sent `teacher_confirmed=true` into local diagram records, but its initial asynchronous saved-record GET failure handler could arrive after newer discovery, correction and acceptance. It then replaced the newer accepted record with the old closure's hard-invalid candidate and cleared readiness. The browser regression reproduced this by holding the old GET, explicitly discovering/correcting/accepting a PDF-wide truncated-Ricoh candidate, then releasing the old failure. Before the fix, `使用中` disappeared. This is a concrete reproduction; the exact deployed request timeline was not accessible.

There were also misleading feedback gaps: the accepted Use button remained enabled with its original label, and the candidate dirty indicator compared answer text only, ignoring diagram decisions.

Operation counters now reject obsolete discovery/preview/saved-validation responses, including failures, and invalidate pending work on target/revision transitions. Rendering does not repeatedly overlay saved props onto current candidates. The existing stable entry identity stays unchanged. Current valid hard-invalid server revalidation still clears readiness; obsolete responses cannot erase newer verified teacher work.

Explicit Use sets local accepted state and confirmation provenance, displays `使用中` and `教師が確認して使用`, disables the accepted Use button, and updates diagram dirty state and existing local registration readiness. The saved draft is unchanged until explicit Save. A corrected confirmable crop remains a candidate until Use. No auto-save, auto-register or answer text fabrication is added.

A second issue found during integration was the cache context: its hash described pre-Ricoh candidates, while the cached list could contain post-grouping candidates. Cache-only Save/reuse validation now retains the original context inputs. Historical caches validate all current native IDs, union geometry, source identity, owner, assignment, bounds and crop hashes without trying to reconstruct the old hash input through inference.

## Confirmed reuse architecture

The existing domain-authorized diagram GET accepts `scope=reuse`; crop-preview/crop serving use the same routes with a server-generated `reuse_ref`. No parallel crop engine or database layer is added. Only accepted records from the current persisted draft are offered. Browser-local unsaved acceptance is deliberately not advertised as saved reuse.

The same major Question is derived by walking stable parent IDs to the root Question, never by display-label equality. Candidates must belong to the current authorized Test/draft, verified current ModelAnswer PDF/material SHA and same hierarchy root. Excluded entries/diagrams, unaccepted, stale, hard-invalid, missing/corrupted artifacts and foreign sources are omitted. If there are no accepted records, GET returns an empty reuse list without loading an irrelevant source or causing errors in historical/text-only reviews.

A compact server artifact manifest attests the accepted source assignment and canonical native provenance. It stores metadata, not crop bytes or model responses. Native origin and used-by assignment are distinct. Reuse creates an independent current-child assignment, keeping original source owner, source candidate ID, source SHA, final bbox and crop SHA. Records retain:

- `reuse_ref` and `reused_from_assignment_id`;
- reused-from entry/Question ID and canonical path;
- original source Question and current assigned Question;
- `source_teacher_confirmed`, source trust-at-accept and source confirmation reason;
- `acceptance_method=reused_confirmed_diagram` on explicit acceptance.

Current trust and source integrity are revalidated on crop access, Save, resume and formal transfer. A client-provided reference, assigned Question or trust/reason field cannot bypass server policy. Reuse does not override foreign/stale/unsafe sources.

The shared `DiagramReview` shows `この大問ですでに使用している図`, its canonical used-by path, preview, PDF inspection and `この図を再利用`. Listing/inspection changes nothing. Clicking Reuse accepts locally for the current child and marks it dirty; the sticky selector remains on that child. Exact/parent/PDF discovery remains available and does not automatically choose a reuse candidate.

Artifact bytes are content-addressed and shared; acceptance/exclusion/manual correction belongs to each assignment. The approved source final bbox is the reuse default. Further correction changes only the new assignment. A saved reused assignment can itself be offered with its own corrected crop and actual used-by path. Removing/excluding the original assignment does not silently revoke an independently saved assignment, but current source/ownership/artifact validity remains mandatory.

## Persistence, registration and runtime

Existing Save/expected-revision conflict handling, continuation and formal registration paths remain. Accepted-only formal transfer includes source owner, assigned child, reuse reference and source confirmation provenance. Empty text plus accepted reuse satisfies diagram-only readiness; merely displaying a reuse candidate does not. Empty text remains empty; Rubric semantics are independent.

Cache-only native validation configures current ownership/boundaries without geometry grouping. Reuse listing, preview, Save/resume and formal registration do not call Ricoh or regroup accepted source diagrams. Identical crop artifacts are reused without rendering. An actual further correction may render the newly requested bounded crop, with existing safety checks. No RuntimeManager lifecycle/model profile, auth policy, scoring or student-diagram flow changes.

## Automated validation

Environment: production Next build, non-loopback HTTP, real FastAPI, disposable SQLite, actual RuntimeManager and managed llama-server stubs. No production/PostgreSQL/Q5 data was changed.

- Broad existing backend regression: **275 passed**.
- Final focused diagram/reuse/trust/API/scope/vision regression: **136 passed**, overlapping the broad run; includes **19 new reuse cases**.
- Existing production-like browser suite: **41 passed**.
- Truncated diagram override/reuse, hard formatting and review-target tests: **10 passed** (3 browser scenarios and 7 frontend logic cases).
- Final dedicated acceptance/reuse browser rerun after the last safety change: **1 passed** (overlaps the 10-case run).
- TypeScript: pass. ESLint: **0 errors, 19 pre-existing warnings**.
- Production Next build: pass; existing CSS autoprefixer warnings remain.
- Ruff on changed Python files and `git diff --check`: pass.
- Grading jobs: **0**. Reuse/correction/confirmation/Save/reload/formal operations add **0 inference calls**. Backend cache-path tests additionally forbid geometry grouping and crop rerender during unchanged reuse.

An expired reuse offer cannot create a new assignment after its source assignment has been excluded. Already saved independent assignments remain usable only while current source/ownership/artifact validation passes.

The critical browser fixture uses one shared completed diagram under Problem3 with children (1)(2)(3), no exact/parent region, ambiguous geometry and truncated managed Ricoh. It covers correction, immediate acceptance/dirty/readiness, obsolete GET failure, saved/local separation, save/reload, reuse by (2) and (3), PDF preview/highlight, canonical source paths, unchanged child selection, independent assignments, empty-text formal registration and unchanged inference counters.

Backend tests cover accepted/excluded/unaccepted eligibility, current hierarchy root, forged assignment/reference/source identities, cross-draft references, missing artifacts, saved correction reuse, independent assignment state, historical cache/teacher-confirmed reuse, source owner preservation and formal transfer. Existing trust, exact/parent/PDF fallback, Question diagram/provenance, math, editor, continuation, issue navigation and Rubric regressions remain required.

## Git and production acceptance

Changes are uncommitted and unstaged. No commit/push was requested or performed. Modified service files: ModelAnswer review page, shared DiagramReview/types, diagram review/source/coordinator modules, ModelAnswer API and browser harness. New service files: confirmed reuse module, backend reuse tests, acceptance/reuse E2E and this report.

Remaining acceptance: deploy and verify Sample Q5 Problem3 (1) teacher-confirm immediately becomes `使用中`, save/reload retains it, (2)/(3) explicitly reuse it independently, source ownership stays unchanged, diagram-only readiness holds and no extra Ricoh request occurs. No deployed COMPLETE claim is made.
