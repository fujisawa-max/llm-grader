# J.UI.12b — Source-backed Unified Authoring Integration

Phase result: **READY_FOR_PRODUCTION_VALIDATION**.

The unified authoring workspace now integrates saved native Question reviews, ModelAnswer candidates, diagrams and advanced Rubric editing. Publication remains deliberately unavailable until J.UI.12c. Real deployed Sample Q5 acceptance has not been performed; managed-stub browser results are not evidence of real-model production success.

## Foundation audit and lifecycle

The foundation already supplied TestAuthoringRevision, revision/edit-version compare-and-swap, a whole-copy JSON draft, formal baseline hash, material uploads/dropdown, canonical selection, visibility checkboxes, shared sticky workspace layout, archive management and formal-data projection. It lacked native review adapters and offered basic domain editors.

Legacy Question confirmation imports formal Questions; ModelAnswer confirmation and Rubric approval separately create formal entities. Those legacy APIs and routes remain. Authoring Save calls none of them. The new working copy remains draft, stores source-backed domain state together, and does not freeze individual sections. The confirmation endpoint still rejects publication explicitly. Submission/job revision binding and atomic formal publication are J.UI.12c work, not defects in this phase.

No production migration or database operation was performed. A metadata-only Alembic merge joins the two existing 0015 heads; upgrade/downgrade contain no SQL or data operations. Existing formal entities and grades are preserved.

## Source adapters and identity

Authoring source projection prefers the latest valid persisted Question review and ModelAnswer draft for this Test, including saved Rubric edits/grouping. Formal entities provide fallback. Invalid saved source states produce diagnostics rather than silent reuse. An answer-only draft does not erase an approved formal Rubric; explicit saved Rubric state, including deliberate empty edits, remains authoritative.

The JSON working copy adds native domain contexts and entries, source revision tokens, an identity map, diagram decisions and Rubric operation histories. Native source element IDs, source slices, source review owner, SHA, page/bbox/order, formula/figure decisions and crop/artifact references survive. No crop base64 or raw model response is introduced.

Question stable keys are authoritative. The identity map links each key to its formal Question ID when available and its originating review/node. New split children use stable authoring keys before any formal ID exists. Virtual Question adapters supply those keys or established formal aliases to existing source engines; labels are never identities.

AuthoringQuestionReview adapts the existing QuestionReviewService to the working snapshot. AuthoringAnswers adapts native candidate geometry, classification, Rubric validation and ModelAnswerDiagramReview. Shared OCR, geometry, crop, trust, reuse and RuntimeManager engines are retained.

## Question integration

The shared NodeEditor retains unified problem text, exact local buffers, Markdown/LaTeX, score and hierarchy controls, formula/figure/source review, warnings and source evidence. Ordinary typing does not rebuild ordered content. Save reconciles through the existing provenance-aware helper. Newline deletion, insertion and DOM identity are verified in the unified browser; composition events preserve the editor. OS Japanese IME candidate selection still needs deployed/manual acceptance.

Manual cursor split, numbered split, managed range-only LLM split proposals, preview/apply/cancel and explicit source mapping reuse the existing split machinery. Existing native source ownership, repeated-token ordering, Unicode ranges and unsafe atomic boundaries remain strict. Reparenting preserves source origins; sibling ordering remains stable.

A split can turn an answer-owning leaf into a parent. Previously verified diagram artifacts are preserved as unresolved/unassigned; the adapter does not invent child assignments. Old derived answer/Rubric projections are cleared when their native assignments move. Children can receive independent answers, criteria and parent/shared diagrams using authoring keys without formal IDs.

Question source-aware math OCR uses the existing source adapter and proposal UI. Apply changes only local text and compact provenance; manual editing and stale-proposal checks remain. Question diagram discovery, preview, source highlight, accept/exclude, teacher trust decisions and manual crops use the shared DiagramReview and authorized endpoints.

## ModelAnswer and diagram integration

The candidate editor supports native/manual candidates, target assignment, inclusion/exclusion, primary/alternative answers, editable alternatives, category decisions and explicit classification confirmation. Saved text and current text remain distinct. Native source-backed OCR and generic formatting retain preview/Apply and local-only semantics.

Diagram-only answers remain valid only with an accepted, valid trusted or explicitly teacher-confirmed diagram. Candidate visibility alone does not resolve readiness. Exact, parent, PDF fallback, manual correction, hard-invalid rejection and confirmed diagram reuse are the existing shared workflow.

The shared DiagramReview now accepts an assignment identity alias separately from the authoring target key. This fixes the native formal-ID versus authoring-key mismatch that otherwise made acceptance appear to do nothing. Guarded asynchronous callbacks and latest-state refs prevent target-switch responses from replacing newer local edits.

Source owner and current assignment remain separate. Shared crop SHA/artifact references are reused; decisions belong independently to each child. Reuse, teacher confirmation, manual correction, Save and resume do not invoke Ricoh. Geometry-only discoveries do not invoke Ricoh; ambiguous explicit discovery may use the existing managed Ricoh WHERE path.

Browser roundtrip exposed another concrete integration problem: JavaScript serializes integral native floats as integers, changing a native context hash despite equivalent geometry. After immutable-context equality checks, adapters restore server-native source context before strict diagram validation. Hash checks were not weakened.

## Advanced Rubric integration

The unified screen uses extracted existing Rubric projection/manual-merge helpers rather than a basic textarea replacement. It supports criteria, insertion, duplication, ordering, manual merge, range-only manual/managed split, operation history/Undo, point conflict review, explicit grouping review and shared LaTeX conversion.

Explicit consolidation uses the existing backend grouping/reconstruction engine. Current edited criteria can be proposed for consolidation even on manual candidates without native classification segments. Points come from supplied current criteria, not model inference. Apply maps known criterion memberships back to native source IDs or teacher-manual provenance and retains split/merge operation ancestry. Proposal baselines and request guards reject stale Apply operations.

Approved formal Rubric fallback also uses the advanced editor and remains a draft working-copy edit. No approved formal Rubric is changed by Save.

## Workspace, Save, resume and conflicts

The shared J.UI.9g layout remains: sticky actions, left material dropdown/PDF, right sticky canonical Question selector and independently visible problem/answer/Rubric sections. Material selection does not change the target Question. Known matching-source page/bbox mappings drive PDF navigation/highlight; another material is not given a foreign overlay. Missing mappings are not guessed.

Section buffers and dirty state live above optional panels. Checkbox/material/Question switches preserve edits. Save canonicalizes native state, validates source identity and ownership, and atomically updates one authoring revision with expected edit-version. It changes neither legacy saved reviews/drafts nor formal entities. Artifact bytes remain in existing content-addressed storage with authorized serving.

Resume restores the persisted working copy and performs source validation, without extraction, classification, OCR or diagram inference. Browser-only unsaved text is not claimed to survive a restart.

Persisted legacy revision/SHA tokens detect external updates. Save rejects silent overwrite until the teacher explicitly continues the authoring copy or imports the latest reviews. Import is an explicit warned replacement, not a silent merge. Source replacement/staleness also remains actionable. Explicit analysis delegates existing native factories, supports working Questions without formal IDs, and binds results into the authoring copy. Authoring-only native drafts cannot be individually published through legacy registration APIs.

Test-wide review can inspect current local content without saving or publishing. It includes native unresolved source decisions, candidate assignment/classification/primary conflicts, diagram-only readiness, Rubric points/grouping and stale-source diagnostics. Canonical issue buttons select the Question, enable the section and scroll/focus the relevant editor. Final confirmation remains visibly unavailable.

Course/Test authorization and source/artifact validation remain server-side. Foreign source/context forgery, stale diagrams and unsafe source ownership cannot be bypassed through working-copy JSON.

## Validation

All browser runs below used production Next builds, non-loopback HTTP, real FastAPI, disposable SQLite and actual RuntimeManager with managed stubs. No real model downloads or production grading ran.

| Check | Result |
|---|---|
| Broad backend regression | 447 passed; Question/source/split/math, answers, Rubric, diagrams/trust/scopes/reuse, LaTeX, RuntimeManager and auth |
| Latest focused backend regression | 44 passed, including approved Rubric fallback and current manual consolidation; overlaps broad suite |
| Normal production-like Playwright suite | 43 passed |
| Final integrated OCR/diagram/trust/reuse/split Playwright suite | 23 passed; overlaps normal suite |
| Hard formatting fallback + source authoring + foundation suite | 3 passed; overlaps other suites |
| Earlier source/math/split integration suite | 20 passed; not added to totals |
| TypeScript | passed |
| ESLint | 0 errors; 19 existing warnings, no new errors |
| Ruff, changed Python service/test files | passed |
| Production Next build | passed in browser harnesses |
| git diff --check | passed |
| Grading jobs | 0 in isolated browser harnesses |

Backend source tests verify latest review/draft preference, formal fallback, exact source roundtrip, source tampering/foreign context rejection, external revision conflicts, local review without Save, native diagram decisions, browser numeric roundtrip, split children without formal IDs, parent/shared reuse, structural demotion, explicit analysis without publication and no legacy/formal mutation.

New browser cases verify unified source content and buffers, real selectionStart/caret and editor DOM identity, composition-event path, Question/Answer OCR Apply/edit/Save/reload, Question diagrams, manual diagram-only answers, corrected truncated-Ricoh acceptance, confirmed reuse, advanced manual Rubric split/duplicate/merge/Undo/consolidation, alternatives, materials/checkboxes, local test-wide review, issue focus, external legacy-update continuation and formal-data isolation. Existing legacy caret/IME/paste/Undo, Rubric, continuation, layout, OCR and trust workflows passed their regression suites.

An initial browser fixture used read-only draft fields in a legacy PUT; the test was corrected to the existing update contract. Issue-focus assertions now wait for the intentional post-render animation-frame navigation. Failed intermediate runs were rerun successfully; they are not counted as passing acceptance.

## Production acceptance and remaining work

No deployment or real Sample Q5 editing was performed. Production/Q5 grades, formal content and data were not touched. Formal immutability is demonstrated with isolated existing-formal fixtures, not claimed as a deployed Q5 acceptance result.

The remaining gate is deployed acceptance: open Sample Q5, resume native state, compare all three sections, exercise source OCR, diagrams/reuse, advanced Rubric editing and Save/reload, and verify formal content unchanged and no unexpected inference. Real OS IME/Undo and PDF visual fidelity should be checked there. No known automated implementation defect remains. Atomic whole-test publication, grading input changes and submission/job revision binding are intentionally deferred to J.UI.12c.

## Git status and files

Changes remain uncommitted and unstaged. No commit or push was made. Local databases, logs, artifacts, credentials and AGENTS.md were not added. Service files changed in this phase:

- frontend/app/model-answer-import-reviews/[draftId]/page.tsx
- frontend/app/tests/[testId]/authoring/page.tsx
- frontend/components/reviews/DiagramReview.tsx
- frontend/components/reviews/NodeEditor.tsx
- frontend/components/reviews/ReviewWorkspace.tsx
- frontend/e2e/question-split.spec.ts
- frontend/lib/api/testAuthoring.ts
- frontend/lib/api/textTools.ts
- frontend/lib/questionSplit.ts
- src/scoring/api/app.py
- src/scoring/api/model_answer_imports.py
- src/scoring/api/test_authoring.py
- src/scoring/model_answer_classification.py
- src/scoring/rubric_consolidation.py
- src/scoring/test_authoring.py
- tests/fixtures/runtime/llama_server_stub.py
- tests/run_runtime_browser_e2e.py
- frontend/components/reviews/AuthoringCandidates.tsx
- frontend/e2e/authoring-diagram-reuse-real.spec.ts
- frontend/e2e/authoring-math-real.spec.ts
- frontend/e2e/authoring-source-backed-real.spec.ts
- frontend/lib/questionSplitApply.ts
- frontend/lib/rubricEditing.ts
- migrations/versions/0016_merge_authoring_review.py
- src/scoring/authoring_answers.py
- src/scoring/authoring_question.py
- src/scoring/authoring_sources.py
- tests/test_authoring_diagrams.py
- tests/test_authoring_sources.py
- docs/reports/j-ui-12b-source-backed-authoring.md
