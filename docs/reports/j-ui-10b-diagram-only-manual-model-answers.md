# J.UI.10b — Diagram-only Model Answers & Manual Candidate Diagram Review

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Real deployed Sample Q5 acceptance has not been performed; synthetic production-build tests do not establish real-model acceptance.

## Root cause

The ModelAnswer page explicitly excluded `teacher_manual` entries from `DiagramReview`, and `model_answer_diagram_candidates()` rejected that same origin even with an assigned Question and saved spatial region. New manual candidates exist only in browser-local state until Save, so the existing server entry lookup also returned 404. Finally, frontend registration checks (including a separate click handler) and backend confirmation required nonempty answer text unconditionally. The database already permits empty/nullable ModelAnswer text, so no migration or placeholder text is necessary.

## Implementation

- Reuses the J.UI.10a extractor, rendering, artifact storage, DiagramReview UI, overlay, authorized preview routes, and optional Ricoh WHERE integration. No second crop engine or discovery API.
- Manual entries resolve the assigned Question's persisted ModelAnswer-side spatial regions. Native vectors and bounded short labels are selected within exclusive regions; same/deeper competing regions remain excluded. Missing mapping fails closed; no whole-page fallback.
- Existing diagram endpoints accept an optional Question ID for an unsaved `teacher-entry-{UUID}`. The server verifies editable draft, authenticated domain access, and same-Test gradable Question, then constructs only an in-memory discovery context. Existing entries cannot be remapped through this parameter. Discovery/preview do not save a draft, change its revision, or create formal answers.
- Draft responses expose spatially mapped Question IDs. All candidates show the same diagram section and explicit discovery button, with unavailable-source reasons and an unexplored state. Query context is preserved through preview and manual correction requests; asynchronous target-switch protection includes Question ID.
- GET revalidation invalidates stale accepted local records as well as the visible crop state, so registration readiness cannot retain a stale accepted flag. This does not save or rediscover.
- Content readiness is `nonblank text OR accepted valid diagram`. Empty/unreviewed/excluded/stale content is blocked with an actionable text-or-diagram message. Automatic/manual origin does not affect that rule. Existing primary/alternative and Rubric rules remain independent.
- Server confirmation validates all diagram records before testing content readiness and reuses the canonical records for formal transfer. The shared validator rejects inconsistent saved source SHA, domain, Question, page, source IDs, or automatic bbox rather than silently overwriting those identity fields. Paths/crop bytes remain server-derived.
- Explicit Save persists decisions/manual bounds; reload/resume uses GET, not discovery. Explicit registration transfers only accepted canonical artifacts. Manual text provenance remains manual while accepted diagrams retain actual material/SHA provenance. Reviewed alternative diagrams remain within existing alternative provenance.
- Registered-answer disclosure reports `本文: なし` and the registered diagram count. No generated description, `図参照`, or other fake text is inserted.

## Validation

The stale-GET UI test deliberately substitutes an unresolved authorized discovery response while keeping persisted valid fixture data unchanged; backend stale-source rejection is separately tested against the real API.

The browser fixture includes 問題3 > (1), (2), (3), with three separate completed diagrams. All three transient manual contexts return exactly their own region; (1) is manually added, left empty, discovered, excluded (registration disabled), accepted, saved, reloaded, and formally registered without fabricated text. PDF overlay and registered diagram count are checked. Existing Question/automatic ModelAnswer diagram correction, exclusion, persistence and formal transfer are also tested.

- Backend focused diagram + ModelAnswer suites: **102 passed** after the stale-source validation fix.
- Final shared diagram identity/GET validation suites: **70 passed**, overlapping the broader runs.
- Broad backend regression: **279 passed**; includes diagram, Question split/review/import, source/math candidate/formatting, and ModelAnswer APIs/drafts.
- Non-loopback production-build browser regression: **39 passed** (real FastAPI, isolated disposable SQLite, actual RuntimeManager, managed stubs).
- Final nested manual/Question/automatic diagram browser suite: **4 passed**, overlapping the broader suite; repeated after final shared-validation change.
- Hard Ornith formatting fallback regression: **1 passed**.
- TypeScript and production Next.js builds pass. ESLint: **0 errors, 19 existing warnings**; existing CSS autoprefixer warnings remain. Ruff and `git diff --check` pass.
- Diagram geometry/discovery, manual correction, Save, reload/resume and registration add **0 model calls** in these confident-geometry scenarios. Existing ambiguous Ricoh WHERE behavior remains; no Uni-MuMER/Ornith use for diagrams. Runtime lifecycle is unchanged.
- Grading jobs: **0**. Production/PostgreSQL/Q5 data untouched. Domain authorization, Question boundaries, local/saved/formal separation, continuation, issue navigation, caret/IME, math OCR, Rubric and workspace regressions pass.

## Files and Git

Changed service files:

- `src/scoring/api/model_answer_imports.py`
- `src/scoring/diagram_sources.py`
- `src/scoring/diagram_review.py`
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`
- `frontend/components/reviews/DiagramReview.tsx`
- `frontend/lib/api/modelAnswerImports.ts`
- `frontend/lib/modelAnswerRegistrationValidation.ts`
- `frontend/e2e/diagram-review-real.spec.ts`
- `tests/test_diagram_review_api.py`
- `tests/run_runtime_browser_e2e.py`
- this report

Git changes are unstaged; no commit/push performed. No model downloads, host-specific model paths, auth changes, schema migration, or production data changes.

## Remaining production acceptance

On deployed Sample Q5, manually add an empty answer for 問題3 > (1), discover the completed diagram, verify PDF highlight/full crop, accept, Save, reload/resume, and explicitly register only if the teacher chooses. Verify empty text remains empty, accepted artifact persists, and (2)/(3) neither borrow sibling diagrams nor fall back to whole-page discovery. No graph interpretation/comparison/scoring is implemented.
