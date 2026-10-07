# J.UI.12b-fix7 — Save/Resume Consistency & Analysis Readiness

## Result

READY_FOR_PRODUCTION_VALIDATION. Implementation and automated verification are complete; deployed Sample Q5 acceptance remains pending. No deployment, production database mutation, formal publication, or grading was performed.

## Root-cause audit

These are reproduced code-level causes; production request traces were not supplied.

- Save could abort when `editQuestionContent` could not reconcile teacher text across immutable source anchors. Dirty state consequently remained true and analysis stayed disabled. The legacy validator could also reconstruct text from source items instead of preserving the exact authoring buffer.
- A previous successful-save notice remained visible during later edits or failed saves. This made a failed current save appear successful. Leaving the page then restored the actual earlier persisted snapshot.
- Exact local text had no separate persisted representation when it could not be reconciled into verified source content. Reopening reconstructed text from source content rather than the teacher's buffer.
- Revision selection sorted by revision number without excluding `analysis_backup`; a higher backup could win over the editable draft. Generic saved-review import could also replace the teacher's Question tree when Question review tokens changed.
- The old message “問題文と元資料の対応を確認してください。未保存の編集は保持されています。” was produced by the Save validation error path for `ReviewError`/`ValueError`. It conflated failed persistence and unresolved source correspondence; it did not prove that edits had been saved.
- Explicitly continuing the authoring copy after an external review update did not acknowledge the new source token, allowing the same conflict to recur after resume.

## Persistence and synchronization

Working snapshots now optionally retain compact `question_text_buffers` by stable node key. Reconciliation continues to use the existing source engine. When reconciliation is unresolved, the raw teacher buffer is saved separately while the last validated source anchors remain intact. Forged anchors still fail server validation. This is an optional JSON field, requiring no database migration.

Successful Save applies the authoritative response: revision ID, edit version, snapshot, exact buffers, source tokens, dirty baseline, warnings and readiness. A guarded metadata refresh cannot turn a successful persisted Save into a failure. Duplicate saves are prevented. An edit-epoch guard preserves newer local changes if they arrive during Save; it also retains canonical source provenance from the returned baseline.

Save status is independent of analysis/import feedback. New edits clear old success feedback. Save failures explicitly report failure and retain local buffers. Source correspondence warnings may coexist with successful persistence and explicitly state that edits are saved. Their “確認する” action selects the relevant Question/body review without importing anything.

Resume selects the latest active editable draft/final-review revision before read-only confirmed state, excluding analysis backups. Sequence allocation still considers all revisions. If only backups exist, GET reports a recovery error instead of silently projecting formal content; explicit draft recovery can restore the preserved copy. Existing drafts always outrank initial formal/source projection.

Question keys, hierarchy, ordering, split structure, teacher text, points, Answers/alternatives/assignments, Rubric criteria and diagram/source/material references round-trip in the working snapshot. The source-backed adapter validates the retained source state separately from the exact raw buffer.

## Analysis readiness and UX

Typed states are `ready`, `unsaved_changes`, `missing_material`, `unsupported`, `stale_source`, `busy`, and `readonly`. They combine server material validity/analysis markers with local dirty and activity state; frontend reason-string parsing is unnecessary.

Dirty edits disable analysis and show a bordered yellow notice next to source controls: “未保存の変更があります。この資料を解析する前に保存してください。” Its Save button uses the same Save handler. Successful Save removes the notice and enables analysis/reanalysis immediately, without reload. It never starts analysis automatically.

Save feedback displays “✓ 保存しました”. A separate source-warning panel says the content is saved and offers source review. Source correspondence warnings alone do not mark dirty or disable otherwise valid material analysis. Replaced/stale materials remain subject to existing integrity checks.

The compact material controls, vertical PDF layout, preview/body/settings modes and stable textarea DOM are preserved. Back always targets Test detail; dirty navigation asks for confirmation, and browser unload is guarded. No content-dependent editor remount was introduced.

## Legacy import, revisions and concurrency

Explicit saved-review import uses the current authoring snapshot as base, merges the relevant Answer/Rubric source-backed state, preserves the current Question tree, records pending Question review updates and retains a backup. It requires an explicit action and warns about its scope. There is no automatic import during resume.

Explicitly choosing to keep the authoring copy acknowledges current external source tokens on the server without replacing its tree or domain evidence. Subsequent resume/Save does not repeat the same acknowledged conflict. Optimistic edit-version CAS rejects stale-tab saves before mutation; stale responses do not silently overwrite local edits.

Save, resume, readiness, warning display and navigation run no inference. Only existing explicit analysis/OCR/diagram/assisted actions may call models. Formal Questions, ModelAnswers and approved Rubrics remain unchanged.

## Verification

- Backend regression suite: 385 passed (5 pre-existing warnings).
- Final focused backend suite after external-token acknowledgment addition: 67 passed, including 13 new fix7 cases across revision selection, persistence, readiness, source warning isolation, anchor forgery rejection and external-review acknowledgment. These counts overlap the broader suite.
- Production frontend browser suite: 52 passed (39 browser scenarios and 13 rendering/error helper cases).
- Additional truncated-Ricoh/diagram/split regression: 30 passed (9 browser scenarios and 21 helper cases; four browser scenarios overlap the primary suite).
- Added real Save/readiness and source-warning scenarios; enhanced split → Answer → Rubric → Back/resume round-trip with exact revision/snapshot comparison.
- Final browser recheck: both Save/resume scenarios passed; the enhanced source-backed external-conflict → keep-current → Save → Back/resume scenario also passed. Two intermediate test runs used an incorrect accessibility locator for the Test-detail action; the test now uses the existing button name “編集を続ける ›”.
- TypeScript passed; ESLint: zero errors, 19 existing warnings. Ruff passed. Production Next build passed through the browser harness. `git diff --check` passed.
- Isolated browser harness grading-job count: 0. No production grading jobs were created or production results altered.

Coverage includes Question caret/composition, split review and provenance, source-aware math OCR, Answer/Rubric advanced operations, diagram trust/override/reuse and crop, material management/replacement, issue navigation, dashboard/Test entry, archive safety, continuation and legacy routes. Model responses use managed stubs through the existing RuntimeManager; live deployed model acceptance is not claimed.

## Changes and remaining acceptance

Changed implementation: authoring page/CSS, API types, shared authoring buffer/readiness helpers, authoring service/API and Question adapter. Changed tests: authoring browser specifications, isolated browser harness and two backend suites. Git changes are uncommitted; no commit or push was performed. See `git status --short` for the exact file list.

Pending production acceptance: real deployment Save immediately enables analysis; split/text/points and Answer/Rubric survive Back/reload; source warnings remain distinct from Save success; explicit analysis only. No known implementation failure remains in the verified paths.

Question drag-and-drop ordering is explicitly deferred to a future phase. Final publication, grading snapshot binding and student revision binding remain deferred to J.UI.12c or later.

## Git status / files changed

```text
 M frontend/app/globals.css
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/e2e/authoring-analysis-access-real.spec.ts
 M frontend/e2e/authoring-diagram-reuse-real.spec.ts
 M frontend/e2e/authoring-entry-layout-real.spec.ts
 M frontend/e2e/authoring-math-real.spec.ts
 M frontend/e2e/authoring-preview-materials-real.spec.ts
 M frontend/e2e/authoring-source-backed-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
 M frontend/lib/api/testAuthoring.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/authoring_question.py
 M src/scoring/test_authoring.py
 M tests/run_runtime_browser_e2e.py
 M tests/test_authoring_sources.py
 M tests/test_test_authoring.py
?? docs/reports/j-ui-12b-fix7-save-resume-readiness.md
?? frontend/e2e/authoring-save-resume-real.spec.ts
?? frontend/lib/authoringState.ts
```

## Acceptance checklist

- [x] Persisted snapshot, authoritative revision/edit version, cleared dirty state and explicit Save feedback
- [x] Separate, actionable source warning; unresolved source correspondence does not prevent draft persistence
- [x] Typed readiness, prominent save guidance, immediately enabled analysis after Save, no automatic analysis
- [x] Latest active draft resume; exact Back/reload round-trip including split/hierarchy/points/Answers/Rubrics
- [x] Stale Save rejected; external review acknowledgment and scoped explicit import preserve the working tree
- [x] Existing source-backed, OCR, diagram/reuse, material, issue-navigation and legacy regressions
- [x] Backend/browser/TypeScript/ESLint/Ruff/production-build/diff checks; grading jobs zero
- [ ] Deployed real workflow acceptance (not performed)
- [x] Question drag-and-drop and J.UI.12c publication explicitly deferred
