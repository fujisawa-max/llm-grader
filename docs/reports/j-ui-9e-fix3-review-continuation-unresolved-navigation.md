# J.UI.9e-fix3 Review Continuation & Unresolved Navigation Report

Phase result: **READY_FOR_PRODUCTION_VALIDATION**

Date: 2026-10-05. Base commit: `7ef4336`.

## Root cause and workflow audit

Question review already persisted revisions and supported authenticated reopening by review ID. However, `SourceUpload.reviewPdf()` always downloaded the PDF, created a native extraction, generated a draft, and created/opened a review. Its primary entry action did not discover existing reviews. The lower `ReviewEntries` panel could reopen them, but used the less explicit “確認を再開” wording. No new persistence layer or analysis service was needed.

The Question summary's “未確認を表示” jumped to the first unconfirmed formula instead of displaying a list. Warning targets used short labels rather than canonical paths. Only ordinary Save errors received field navigation; mark-reviewed errors fell through to a generic message. Several summary counts came from the saved revision even after local confirmation changes.

ModelAnswer/Rubric had a working source-scoped draft discovery/resume flow. ModelAnswer validation links could select a candidate, but candidate-less messages were not actionable and navigation focused an article. Unassigned counts and Rubric review requirements lacked a corresponding canonical-path list. Registration and classification rules remain unchanged.

## Canonical paths and issue navigation

`canonicalQuestionPath()` now supplies both reviewed Question paths and ModelAnswer/Rubric selector breadcrumbs through their existing adapters. It follows stable parent IDs, guards cycles, and retains the server's canonical path when structural ancestors are omitted from gradable-only choices.

`ReviewIssueTarget`, `ReviewIssueList`, and `focusReviewIssue()` provide a small shared target/list/focus mechanism. Targets retain domain, stable Question key, canonical path, issue type, stable item/section ID, and optional specific control selector. They use existing sticky selectors; they do not create another navigation state.

Question summaries open a current unresolved list for formulas, warnings, figures and point review. Links select the current reviewed owner, including split children, reveal source evidence when appropriate, scroll into view and focus the content-confirmation button, warning selector, figure control, point input or score-method selector. Save field errors and confirmation-blocking errors use the same navigation function. Point guidance during final registration also uses that function after the existing explicit editing-restart confirmation.

ModelAnswer registration blockers are clickable, with canonical nested paths where assigned. Additional issues expose unassigned candidates, classification review, criterion text/points, point conflicts, grouping confirmation and criterion point-total mismatch. These are navigation aids: advisory classification and Rubric issues do not become new ModelAnswer registration blockers. Registered Question point metadata is exposed as a read-only choice field to explain the existing Rubric total check. Unassigned candidates use **設問未割当**, without inventing hierarchy paths.

After selection renders, focus uses two animation frames; closed containing `details` sections are opened before focusing. No persistent error highlight is added. Issue counts/lists disappear when the corresponding local confirmation, warning or point state is resolved. The workspace remains selected.

## Review continuation and reanalysis

Question review discovery now returns persisted material ID, PDF SHA, current revision, resumability and an incompatibility code, ordered by draft creation time descending with a stable ID tie-breaker. It reads and verifies the existing source/revision artifacts. Corrupt or changed-source entries are marked non-resumable rather than hiding the entire discovery list; direct reopening retains existing strict validation.

The main Question PDF entry offers **前回の解析結果を編集** and a separate **再解析する** action. Resume verifies Test identity and PDF SHA and opens the existing review with GET requests. The original import flow stores a derived PDF material, so matching uses persisted SHA within the authorized Test as well as material ID. Explicit reanalysis retains previous reviews and asks for confirmation when one exists.

The lower review panel uses the same continuation wording, verifies an existing review before opening it, and disables incompatible entries. Its explicit initial “確認を開始” action for a draft without a review retains the existing idempotent review-creation behavior.

ModelAnswer/Rubric continuation was retained and tested through its existing source-specific main entry. It opens saved candidate assignments, text, criteria and merge history without classification. Reanalysis remains an independent explicit action.

## State, provenance and authorization

Navigation changes only selected Question/target and source display state. It does not reconcile the Question text buffer, save, cancel or register. Question per-node buffers survive issue navigation. Existing explicit Save/review/registration boundaries remain; ModelAnswer formal/saved/local layers remain distinct.

Question loading now installs the review after the independent review/history/confirmation GETs finish. This avoids exposing a transient disabled editor during initial loading. Stable textarea identity, caret, IME, paste and native undo/redo behavior remain covered by the existing regression scenario. No new content-dependent key was introduced.

Split source slices, mathematical Unicode tokens, repeated native tokens, source ownership, figures, geometry, SHA and OCR proof fields were retained. The shared OCR, Ricoh, Uni-MuMER and Ornith code and runtime configuration were not modified. No runtime is started/stopped by resume or issue navigation.

Existing staff/domain dependencies remain unchanged. Tests verify unrelated teacher and student requests receive 403 and unauthenticated requests receive 401 for both discovery and reopening. Existing generic text-tool authorization tests also pass.

## Automated validation

| Check | Result |
| --- | --- |
| Backend regression suite, 12 modules | **261 passed**, 5 existing warnings |
| Frontend Question content/editing/split/validation/issues helper suite | **37 passed** |
| Default production-build non-loopback Chromium suite | **33 passed**: 20 browser scenarios + 13 existing error-mapping checks |
| Hard formatting fallback + continuation suite | **3 passed**, including 1 additional formatting browser scenario; continuation cases repeat the default suite |
| TypeScript | PASS |
| ESLint | 0 errors; 19 existing warnings |
| Production Next.js build | PASS; existing CSS/autoprefixer warnings remain |
| Ruff | PASS |
| `git diff --check` | PASS |
| Disposable DB grading jobs | **0** |

Backend command:

```sh
python -m pytest -q tests/test_question_math_ocr.py tests/test_question_reviews.py tests/test_question_import.py tests/test_source_math_ocr.py tests/test_math_region_grouping.py tests/test_math_ocr_candidates.py tests/test_math_ocr_formatting.py tests/test_model_answer_import_api.py tests/test_model_answer_drafts.py tests/test_review_document_text_editing.py tests/test_text_tool_authorization.py tests/test_authentication.py
```

Frontend commands:

```sh
cd frontend
npm run typecheck
npm run lint
npx playwright test e2e/question-content.spec.ts e2e/question-editing.spec.ts e2e/question-split.spec.ts e2e/review-validation.spec.ts e2e/review-issues.spec.ts --reporter=list
```

Production-like browser commands (repository root):

```sh
python -m tests.run_runtime_browser_e2e --insecure-origin
LLM_GRADER_STUB_MATH_RESPONSE_MODE=formatting_hard python -m tests.run_runtime_browser_e2e --insecure-origin --spec e2e/source-math-formatting-real.spec.ts --spec e2e/review-continuation-real.spec.ts
```

Environment: production `next build`/`next start`, non-loopback HTTP (`172.19.0.2`), real FastAPI, disposable SQLite/source artifacts, actual RuntimeManager and managed model stubs. No production database or credentials were used.

## Browser evidence

New continuation scenarios establish two unconfirmed Question formulas and nested ModelAnswer/Rubric blockers without executing models. They assert canonical paths, exact selected stable keys, focus, disappearance after resolution, preservation of another Question's unsaved text, actionable confirmation rejection and exact saved revision after resume.

Both scenarios compare all four managed profiles' PID, `started_at` and inference log counts before/after navigation and resume: unchanged. Resume browser requests are GET-only; extraction, classification, OCR, revision creation and grading are absent.

The split Question OCR scenario now leaves the workspace and resumes through the Test's PDF action, asserting the same revision, hierarchy and source provenance before executing explicit OCR. The unified answer/Rubric scenario resumes its saved merged criteria through the Test entry and compares the full server state before continuing registration. Existing split/merge/edit, registration, source OCR, numeric safety, formatting fallback and warm runtime reuse regressions pass.

Unexpected page/console/network errors: none in the new scenarios. The deliberately rejected mark-reviewed request produces one expected 422 and its handled actionable list; this expected failure is distinguished from unexpected errors.

## Files changed

Shared paths/issues:

- `frontend/lib/canonicalQuestionPath.ts` (new)
- `frontend/lib/reviewIssues.ts` (new)
- `frontend/lib/questionReviewIssues.ts` (new)
- `frontend/components/reviews/ReviewIssueList.tsx` (new)
- `frontend/lib/modelAnswerQuestionNavigation.ts`
- `frontend/lib/reviewValidation.ts`

Question and answer UI/API types:

- `frontend/components/SourceUpload.tsx`
- `frontend/components/reviews/ReviewEntries.tsx`
- `frontend/components/reviews/ReviewWorkspace.tsx`
- `frontend/components/reviews/NodeEditor.tsx`
- `frontend/components/reviews/WarningPanel.tsx`
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`
- `frontend/types/reviews.ts`
- `frontend/lib/api/modelAnswerImports.ts`

Service and tests:

- `src/scoring/question_reviews.py`
- `src/scoring/model_answer_drafts.py`
- `tests/test_question_reviews.py`
- `tests/run_runtime_browser_e2e.py`
- `frontend/e2e/review-continuation-real.spec.ts` (new)
- `frontend/e2e/review-issues.spec.ts` (new)
- `frontend/e2e/model-answer-review-ux-real-isolated.spec.ts`
- `frontend/e2e/question-editor-caret-real.spec.ts`
- `frontend/e2e/question-math-ocr-real.spec.ts`
- `frontend/e2e/reviews-real.spec.ts`
- `frontend/e2e/unified-answer-rubric-review-real.spec.ts`
- This report (new).

Git: 19 tracked files modified and 7 new service/test/report files; all unstaged. No commit or push. Local `AGENTS.md`, credentials, databases, source fixtures, logs and runtime artifacts were not added to Git.

## Production acceptance and remaining work

Real deployment validation has **not** been performed. No production/Q5 data, grades, models, OpenWebUI or runtime lifecycle configuration was changed. There is no known outstanding implementation/test defect in the validated scope.

Deployment acceptance:

1. Open an existing saved source-backed Question review with unresolved formulas. Expand the list, click a canonical path and verify the selected child/control; resolve one and verify count/list update.
2. Make an unsaved edit in another Question, navigate via an issue and return; verify it remains local. Save explicitly, return to the Test and choose **前回の解析結果を編集**. Verify the same review/revision, saved split/content/provenance and confirmations, with no analysis POST or runtime inference.
3. In ModelAnswer/Rubric, check a nested assigned issue and an unassigned candidate. Verify exact selection/focus and issue clearing. Save explicitly and resume from its PDF entry; verify assignments and edited/merged criteria remain, formal data is unchanged and no classification/model request occurs.
4. Confirm reanalysis remains separate. Formal registration is not required for this acceptance unless the teacher chooses it.

Phase J.UI.9e-fix3: **READY_FOR_PRODUCTION_VALIDATION**. Mark COMPLETE only after the deployed checks succeed.
