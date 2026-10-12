# J.UI.12 — Unified Test Authoring Workspace

Phase result: **PARTIAL**. This change supplies a working-copy foundation and a basic unified editor. It does **not** complete the requested authoring lifecycle. In particular, the final-confirmation endpoint deliberately rejects publication. This must not be presented as a production-ready replacement for the existing source-backed reviews.

## Existing lifecycle audit

Question review confirmation creates formal `TestQuestion` content, hierarchy and assets. ModelAnswer registration separately versions formal answers; Rubric registration separately approves a Rubric version. Their saved reviews/drafts and formal entities are distinct. Source-aware OCR, figure ownership after split, diagrams and source artifacts belong to those domain reviews.

The grading readiness/input services currently read the Test's formal Questions, current ModelAnswers and approved Rubric. Student submissions do not identify an immutable whole-test authoring revision. Existing individual registration services also commit independently. Therefore, calling those services successively is insufficient for an atomic final confirmation or for preserving a historical grading snapshot.

The new working copy leaves those entities intact. Its intended final boundary must eventually publish Questions/hierarchy/points, answers, accepted diagrams, Rubric and verified provenance together, and bind subsequent submissions/jobs to that confirmed revision. That boundary is not implemented in this change.

## Implemented foundation

- Additive `test_authoring_revisions` persistence: revision number, optimistic edit version, JSON working copy, snapshot hash, formal baseline hash and actor/timestamps.
- Domain-authorized read, explicit create/resume and whole-copy Save. Reading or resuming does not run analysis, extraction, diagram discovery or inference. Save uses a single transaction and never updates formal Question/ModelAnswer/Rubric rows.
- Source evidence from existing formal content is retained separately from the unified editing projection. The client cannot replace that original evidence during Save. Same-Test material IDs, role and SHA are checked.
- Hierarchy, finite points, target membership, size and shape checks reject malformed drafts. Changed formal baselines are surfaced during whole-test review instead of being overwritten.
- Confirmed-state working copies reject edits; explicit creation clones another draft revision. This state transition is tested using a fixture; there is no operational publication path that produces a confirmed revision yet.
- A new draft without formal Questions rejects student submission. Legacy formal Tests retain their existing submission behavior. This is a preliminary guard, not whole-test revision pinning.

## Workspace and materials

`/tests/{testId}/authoring` reuses `ReviewWorkspaceLayout`: sticky actions, left source/PDF and material dropdown, right canonical Question selector and display checkboxes, plus a final selector entry for test-wide review. Stable node IDs and per-node raw text buffers preserve ordinary textarea edits. Provenance-aware text conversion happens at explicit Save rather than on every keystroke.

The basic editor supports Problem text/hierarchy/points, primary answer text, generic LaTeX proposals and simple Rubric criteria/points. Visibility preferences are stored in the browser. Switching material or Question preserves local text. No individual formal registration buttons are introduced into this draft editor.

Multiple PDFs can be added with problem, answer, Rubric or supplementary roles. Existing sources are retained; selecting another PDF does not run extraction or change the selected Question. Adding a replacement PDF is currently an addition, not a complete replacement/reanalysis lifecycle. Classification is not inferred from upload role.

Test-wide review currently checks basic content, hierarchy-related targets, points, answers and Rubric totals, and provides canonical issue navigation. Publication always remains blocked with an explicit explanation. It does not yet implement the complete source/diagram/math readiness policy.

## Compatibility and management

Existing Question and Answer/Rubric review URLs remain available. There are no redirects that discard their saved reviews. The new legacy adapter starts from formal data, **not** the latest source-backed review/draft. A compatibility link opens the existing workflow; edits made there are not automatically merged into the new working copy.

Recent Course cards show recent Test links based on server metadata, including draft continuation. Course offering Test rows have an edit link and an archive action.

Archive requires an impact summary/hash and exact Test-name confirmation. It preserves all dependent records and adds a marker; queued/running/paused grading prevents archive. Archived Tests disappear from default lists and ordinary authorized domain access returns 410, including administrators. A domain-authorized restore endpoint removes the marker. There is no physical deletion, Course archive UI, or restore UI in this phase.

Migration `0015_test_authoring` only adds the revision/archive tables. It tolerates tables already created by the existing metadata bootstrap. Production migration and deployment have **not** been performed.

## Remaining required implementation

1. Transactional all-domain final publication and immutable grading snapshots; submission/job revision references and historical input assembly.
2. Source-backed Question review and ModelAnswer/Rubric saved-draft adapters, including shared stable Question identity before formal registration.
3. Source-aware OCR, Question/answer diagrams, diagram-only readiness, exact/parent/PDF fallback, teacher confirmation and confirmed reuse inside the unified editor.
4. Advanced Rubric merge/split/insert/consolidation/LaTeX and alternative/manual answer candidate editing.
5. Unified source review decisions, accepted-only formal artifact transfer, stale-source validation and complete test-wide issue navigation/readiness.
6. Materials-first analysis, later replacement/reanalysis and compatibility continuation that restore the authoritative saved source-backed review rather than a formal projection.
7. Operational confirmed/revision UI and complete end-to-end final-confirmation/revision browser scenarios.
8. Real deployed end-to-end acceptance, including existing Q5 data preservation.

Existing diagram/math/Rubric functionality remains in the compatibility workflows. Passing its regressions does not demonstrate integration into the new Workspace. No missing content is fabricated, no diagram meaning is interpreted, and no grading or model behavior is changed.

## Validation

All runtime browser tests use production Next.js, non-loopback HTTP, real FastAPI, disposable SQLite, actual RuntimeManager and managed model stubs. Stub results are not real-model production acceptance.

| Check | Result |
| --- | --- |
| Backend authoring/auth/domain/diagram trust and reuse/Question import and reviews/math OCR/formatting | 192 passed, 6 warnings |
| Additional split editing, Rubric split/consolidation, diagram scopes/regions/API/vision | 140 passed, 3 warnings |
| New authoring backend scenarios (included above) | 21 passed |
| Default production-build browser suite | 42 passed |
| Truncated Ricoh override, confirmed reuse, answer readiness and hard formatting fallback browser suite | 10 passed |
| Dedicated new authoring browser scenario (also in the default suite) | 1 passed |
| TypeScript | Passed |
| ESLint | 0 errors; 19 existing warnings |
| Ruff, all changed Python files | Passed |
| Production Next.js build | Passed in both browser harness runs |
| git diff --check | Passed |
| Grading jobs in browser fixtures | 0 |

The new browser scenario verifies raw editor DOM identity and newline-deletion caret position, per-section local state, three-domain Save/reload, two material uploads and material switching, no formal rows created, unchanged runtime state, dashboard continuation and archive/cancel/restore. It explicitly verifies that final publication is unavailable; it does not stand in for the requested final-confirmation end-to-end test.

Existing caret/IME, source-backed split, source OCR, review continuation, unresolved navigation, Rubric editing and unified layout scenarios passed in the regression suite. Existing diagram teacher-confirmation/reuse and formatting fallback passed in the configured critical suite. These validate compatibility routes, not yet the missing domain features in the new Workspace.

## Files and Git state

Added: `src/scoring/test_authoring.py`, `src/scoring/api/test_authoring.py`, `migrations/versions/0015_test_authoring.py`, `frontend/app/tests/[testId]/authoring/page.tsx`, `frontend/lib/api/testAuthoring.ts`, `frontend/lib/localId.ts`, `frontend/components/RecentCourseTests.tsx`, `frontend/components/TestArchiveButton.tsx`, `tests/test_test_authoring.py`, `frontend/e2e/test-authoring-foundation-real.spec.ts`, and this report.

Modified: `src/scoring/db/models.py`, `src/scoring/api/app.py`, `src/scoring/api/domain.py`, `src/scoring/auth.py`, `src/scoring/domain.py`, `src/scoring/source_registration.py`, `frontend/app/page.tsx`, `frontend/app/offerings/[offeringId]/page.tsx`, `tests/run_runtime_browser_e2e.py`.

Git state: 9 modified tracked files and 11 untracked service-related files. Nothing staged or committed. Runtime databases, crop artifacts, browser logs and credentials are not included.

Production acceptance: **not performed**. No production database reset, Q5/formal grade mutation, model download, deployment, commit or push was performed.
