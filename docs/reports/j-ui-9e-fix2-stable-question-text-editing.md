# J.UI.9e-fix2 Stable Question Text Editing & Caret Preservation Report

Phase result: **READY_FOR_PRODUCTION_VALIDATION**

## Concrete root cause

The deployed symptom was reproduced with the production Next.js build in Chromium over non-loopback HTTP, using the existing source-backed Question PDF fixture. Deleting a native-item separator at offset 9 restored the original newline and moved both selection endpoints to offset 80, the end of the document. The textarea was the same DOM element before and after the edit.

The old `onChange` called `editQuestionContent()` immediately. `questionContent()` inserted a display newline between source items, but that separator belonged to neither item's text span. Deleting just that newline therefore produced no affected source span and reconciliation returned `null`. React then restored the old controlled value, resetting the caret to the end. Independently, editing a native formula automatically wrapped its raw text in dollar delimiters, also changing the controlled value beyond the user's input.

There was no content-dependent key on NodeEditor or the textarea. Node identity and server revision did not change during typing. The OCR control's node/revision key does not contain the active editor. No forced caret restoration or cursor-key interception was added.

## Before / after state flow

Before:

`ordered_content → questionContent → textarea → editQuestionContent on every input → ordered_content → questionContent → textarea`

After:

`server revision → initial per-node text buffer → exact browser edits → explicit Save / content confirmation / split reconciliation → validated review snapshot`

`questionEditing.ts` holds each stable Question key's exact text, baseline and pending compact OCR apply provenance. Ordinary input changes only that buffer. Spaces, newlines, incomplete Markdown/LaTeX and IME composition are not normalized. Switching the sticky selector retains every Question's local buffer. Explicit loads/history changes retain the existing discard confirmation.

NodeEditor reads its controlled value directly from the buffer. Snapshot comparison, source-reference matching, score derivation and source diagnostic serialization are memoized where appropriate; typing does not rebuild source items, scan source text for ownership, recompute geometry, create revisions or call models.

## Explicit reconciliation and provenance

Save reconciles all pending buffers before validation and the existing revision API. Confirmation reconciles the selected content before confirming its source formula decisions. Split reconciles before generating the existing provenance-aware split proposal; applied children receive their own initial buffers.

Reconciliation requires its projected result to equal the requested buffer exactly. It never silently installs a lossy projection. Deleted item separators include the two adjoining source anchors in the existing merge contract. Explicit blank lines are retained. Native formula edits without math delimiters retain the formula anchor and exact teacher transcription instead of inserting dollar delimiters. Changed source formulas remain unconfirmed until explicit review.

Source element IDs, slices, review owner, original source strings, SHA, bbox/page/order, merged anchors, figure references and split lineage retain their existing contracts. Unsafe edits across figure/score evidence fail closed at Save/review/split; the local text remains editable and an actionable error is shown. Automated coverage includes joining a heading across an intervening score item: local editing works, but Save deliberately refuses to move that evidence and issues no revision request.

Backend, domain authorization, Question hierarchy/max points, registration, OCR grouping/normalization and runtime lifecycle code were not changed.

## Caret, selection, paste, IME and Undo/Redo

The requested three-line example is included in a disposable source PDF. After joining the first two body lines, the selection endpoints remained at offset 26, with the same textarea DOM identity. The joined content saved and survived reload.

Production-build browser assertions cover:

- character insertion, repeated spaces, Backspace and Delete;
- Enter insertion, Delete/Backspace newline joining, selectionStart and selectionEnd;
- native Ctrl+Z and Ctrl+Shift+Z for newline editing;
- actual Ctrl+C/Ctrl+V multiline clipboard paste on non-loopback HTTP;
- multiline selected deletion and selection replacement;
- repeated edits without remount and raw formula typing without injected delimiters;
- incomplete Markdown/LaTeX remaining exact local text;
- Question switching and returning with two separate unsaved buffers;
- explicit Save/reload and unchanged formal Questions before registration.

Chromium's `Input.imeSetComposition` and `Input.insertText` exercised native compositionstart/update/end, hiragana composition and a Japanese commit. DOM identity and caret position remained stable; no revision or OCR requests occurred during composition. This cannot verify an operating system's actual Japanese conversion-candidate popup or all platform-specific IME behavior; that remains part of deployed manual acceptance.

## Math OCR and shared regressions

The shared control receives the current buffer text. Editing still makes an outstanding proposal stale, with Apply disabled. Apply stores only local text and compact pending provenance. Explicit Save persists it, and explicit registration remains separate.

Existing Question tests passed for unsplit OCR, split/save/reload, the formula-owning child, sibling exclusion, crop/KaTeX/Apply/Cancel, post-Apply manual editing, native/merged formula provenance, reparented source origin, Unicode TP, repeated 24 ownership, shared/atomic source boundary refusal, and final registration. ModelAnswer/Rubric merge, split, add/duplicate/undo, registration, draft persistence, generic LaTeX authorization/error mapping and managed runtime reuse regressions passed.

## Tests

| Check | Result |
| --- | --- |
| Targeted backend: Question math/reviews/import, source math OCR, grouping, candidates, formatting | 197 passed; 5 existing pytest collection warnings |
| Frontend helpers: Question content/editing/split/review validation | 32 passed |
| Production-build non-loopback HTTP Chromium default suite | 31 passed, including 2 new editor scenarios |
| Hard formatting-only Ornith fallback browser fixture | 1 passed; cold/warm reuse and state isolation verified |
| TypeScript `tsc --noEmit` | PASS |
| ESLint | 0 errors; 19 existing warnings |
| Ruff `src/scoring tests` | PASS |
| Production Next.js build | PASS |
| `git diff --check` | PASS |

The browser harness uses the real production FastAPI entrypoint, disposable SQLite, actual RuntimeManager, managed model stubs and production Next.js. Its grading-job assertion is zero. The caret scenarios themselves issue zero math-OCR/LaTeX requests and no automatic revision requests. Console/page errors after authentication are empty in the new editor scenarios; existing failure-path suites retain their expected-error checks. The login bootstrap's expected unauthenticated `/auth/me` response is outside the authenticated console audit.

## Files changed

- `frontend/components/reviews/NodeEditor.tsx`: stable buffer value, explicit confirmation, memoized source/diagnostic work.
- `frontend/components/reviews/ReviewWorkspace.tsx`: per-node buffers, dirty state, explicit reconciliation/save/split boundaries and local OCR provenance.
- `frontend/lib/questionEditing.ts`: focused buffer and exact reconciliation helper.
- `frontend/lib/questionContent.ts`: separator reconciliation and exact native-formula transcription.
- `frontend/e2e/question-content.spec.ts`: separator, newline and raw-formula provenance cases.
- `frontend/e2e/question-editing.spec.ts`: deferred reconciliation, preserved buffer, fail-closed figure boundary and compact provenance cases.
- `frontend/e2e/question-editor-caret-real.spec.ts`: two real-browser editing/caret/IME/persistence scenarios.
- `tests/run_runtime_browser_e2e.py`: disposable three-line Question PDF/test fixture and default-suite inclusion.
- `docs/reports/j-ui-9e-fix2-stable-question-text-editing.md`: this report.

## Git status and data safety

Base: `8a623b3` (Unify question review and preserve split source provenance). Five existing service files are modified and four new service files are untracked, all unstaged. No commit or push was performed. Local-only instructions, credentials, logs, databases and browser artifacts were not added to Git.

No production database was accessed. No Q5/sample grades, formal production Questions, ModelAnswers or Rubrics were modified. No model download, grading call, OpenWebUI change or runtime configuration/lifecycle change was made.

## Production acceptance and remaining issues

Implementation and automated tests are complete. Actual deployed editor validation is pending; production credentials are neither needed nor requested.

After deployment, select a multiline source-backed Question and check newline joining, typing at the join, inserting a newline, OS Japanese IME, selection replacement/paste, Undo/Redo, explicit Save/reload and selector navigation. On a formula-owning Question/child, verify source-aware OCR, stale proposal blocking and editable local-only Apply.

Conservative provenance rejection at unsafe figure/score boundaries remains intentional, with local edits preserved. OS IME conversion-candidate behavior and deployed browser behavior require the teacher's manual check. This phase must remain **READY_FOR_PRODUCTION_VALIDATION** until that deployed acceptance succeeds.
