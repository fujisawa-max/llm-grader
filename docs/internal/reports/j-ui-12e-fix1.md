# J.UI.12e-fix1 — Prevent false source-review blockers after confirmation

## Result

**COMPLETE** — local regression and production acceptance passed on 2026-10-11 after operator deployment. A fresh dedicated source-backed Sample Q5 Test stays at zero issues after Confirm, duplicate Confirm, reload and Back/resume. Genuine attestation mismatch still produces revision-oriented guidance. J.UI.12e remains COMPLETE and J.UI.12c is not reopened. J.UI.12d and Undo/Redo are not started.

## Baseline and reproduction

- HEAD: `82c366255d823acd3373a35643f4da8a990e7ab4`.
- Initial `git status --short`: empty (clean).
- The new backend reproduction failed before the fix: after a zero-blocker successful Confirm, the working row's old baseline hash differed from the newly projected formal state.
- Review produced `元の正式内容が変更されています。出典付きレビューを確認してください。` even though no external edit occurred.

## Root cause

`GET/POST /authoring/review` compared `TestAuthoringRevision.baseline_sha256` against `baseline_hash(projection(session, test))`. The baseline represented the formal content at draft creation. Confirm legitimately replaced/projected Question, current ModelAnswer and approved Rubric rows but only changed the working row's state to `confirmed`; it did not reconcile that mutable formal-review baseline. Generated formal IDs, versions, provenance and content therefore looked like an independent edit to readiness.

The immutable confirmed snapshot was correct; this was a freshness/reconciliation defect, not a confirmed-payload/hash mutation. The warning panel's unconditional “確認状態を保存しても、元の警告は残ります。” compounded the false issue with an impossible correction loop in read-only state.

## Review-basis reconciliation

Confirm now reads its flushed deterministic formal projection using DB-normalized values and atomically sets the working row's `baseline_sha256` together with `state=confirmed` under the existing edit-version/state CAS. This metadata is mutable review/projection state. The exact saved and confirmed snapshots, their hashes, diagram revisions and authoring edit version are untouched. Pre-confirm external-baseline checks remain in place. A transaction failure rolls back projection and reconciliation together.

`projection(..., refresh=True)` refreshes formal rows/Test metadata before hashing so integer-to-Float DB coercion cannot itself create a post-reload mismatch. Ordinary projection calls retain their existing behavior.

For already-confirmed pre-fix records with an old baseline, readiness has a read-only compatibility attestation. It requires the active confirmed revision to belong to the same working revision, a valid canonical confirmed hash, exact working/confirmed snapshot equality, and the formal content to match the deterministic projection. It compares metadata, stable identities, hierarchy, ordering, body/content, score semantics, source provenance/content SHA, current Answer text/entries/accepted diagrams/material identity, Rubric criteria and generation keys, and retained Question assets. Unexpected shapes/extra rows fail closed. It does not rewrite old confirmed records or update metadata on GET/duplicate Confirm.

This is not a suppression based only on `state=confirmed`, a review checkbox, or accepted diagrams. Real content/provenance/source changes still generate issues.

## Guidance and read-only behavior

- Genuine editable formal drift uses the `formal_review_stale` code and instructs the teacher to check changed formal content against PDF/body/diagrams and explicitly use `保存済みレビューを取り込む`.
- Genuine confirmed source/formal drift says `確定後に正式内容・出典との対応に差異が検出されました。`, explains `確定済みの内容は変更できません。`, and offers `修正版を作成`.
- The source issue action uses the existing revised-draft entry point rather than navigating into a disabled editor. No revision-management feature was added.
- The generic warning footer now gives editable PDF/content review instructions. A genuinely unresolved warning in a confirmed view directs the teacher to create a revised draft. Reviewed warnings do not display an impossible-save footer. Temporary busy/disabled UI is distinguished from confirmed state.
- The confirmed stale-PDF alert likewise gives revision-oriented guidance.

## Regression evidence

- Backend: zero issues before Confirm and zero after GET/POST readiness; reconciled persisted formal baseline; unchanged payload/edit version; duplicate Confirm preserves baseline and creates no duplicate confirmation event.
- Legacy confirmed basis: clean deterministic projection recognized without modifying the old metadata or immutable payload.
- Negative: controlled SQL mutation of formal Question, Answer, Rubric or Question asset is rejected by readiness both with new and legacy baselines. Normal ORM/API confirmed-edit guards remain active. Confirmed guidance points to a revision, not Save.
- Negative: changed source PDF bytes still produce confirmed source issues; reconciliation does not override actual source checks.
- Existing rollback/CAS/idempotency/immutable snapshot tests remain in the suites. Automatic, manual, reused and multiple accepted diagrams retain exact saved/confirmed equality and unchanged diagram revisions.
- Chromium: ordinary and actual Sample Q5 source-backed confirmation keep `要修正` at zero, all Question `*` markers clear, and the confusing warning absent after Confirm, duplicate Confirm, reload, Back and resume.
- The Sample Q5 test also exercises an old confirmed baseline with automatic/manual/reused diagrams, then a controlled disposable-only real formal edit. The confirmed view shows revision guidance; its action creates an editable draft without altering the confirmed snapshot. A subsequent controlled draft formal edit displays actionable import/review guidance and disables Confirm.
- Direct SQL browser seams assert `RUNTIME_MANAGER_E2E=1` and a disposable `llm-grader-runtime-e2e-*` SQLite database. They cannot run against production through this harness.

## Validation

- Initial focused backend: 85 passed, 1 warning.
- Focused browser: 6 passed (31.6 seconds), grading jobs = 0. Covers 12e correction UX, fix1 issue overlay, ordinary confirmation, and real Sample Q5 confirmation/stale negatives.
- One early browser attempt used a multi-option locator with a scalar text assertion; the test locator was corrected to assert zero marked options. No product logic/assertion requirement was weakened.
- Final expanded focused backend: **101 passed, 1 warning** (55.35 seconds).
- Full normal production-like Chromium suite: **72 passed** (3.6 minutes), grading jobs = **0**. After the final defensive compatibility guards, the focused browser group was rerun: **6 passed** (31.8 seconds), including the actual source-backed Sample Q5/old-baseline/stale-negative scenario.
- TypeScript passed; ESLint **0 errors / 19 existing warnings**; Ruff passed on changed Python; production Next build passed in the browser harness; `git diff --check` passed.
- Final full backend: **991 passed, 2 skipped, 23 warnings** in 233.03 seconds. This includes the final compatibility guards, genuine drift negatives, atomicity/rollback, CAS/idempotency, immutable snapshot/hash integrity, and authoring/diagram/source regressions.
- No inference is added by reconciliation/compatibility/readiness. Existing browser model-call assertions cover Confirm, idempotency, navigation and revised-draft creation. No authoring grading jobs are launched.

## Files changed

- `src/scoring/api/test_authoring.py`: atomic mutable-basis reconciliation, strict legacy attestation and state-appropriate source guidance.
- `src/scoring/test_authoring.py`: optional DB-normalized formal projection refresh.
- `src/scoring/authoring_confirmation.py`: pure read-only deterministic-projection compatibility comparison.
- `src/scoring/authoring_issue_guidance.py`: actionable editable formal-drift wording.
- `frontend/app/tests/[testId]/authoring/page.tsx`: confirmed source action/alert and explicit confirmed warning-panel state.
- `frontend/components/reviews/WarningPanel.tsx`: replace impossible-save footer with actionable state-specific guidance.
- `tests/test_test_authoring.py`: normal/legacy clean readiness, real drift, persisted basis, immutable state and duplicate-event regressions.
- `tests/test_authoring_diagrams.py`: post-confirm clean readiness and real stale-PDF negative.
- `frontend/e2e/authoring-final-confirmation-real.spec.ts`: clean immediate/duplicate/reload/Back confirmation readiness.
- `frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts`: source-backed diagram clean/legacy/stale/editable-guidance regression.
- `docs/internal/reports/j-ui-12e-fix1.md`: standalone fix report. Parent reports are unchanged.

## Remaining acceptance

Production acceptance is complete. No remaining fix1 blocker was found. Dedicated validation records remain for inspection.

## Production acceptance — 2026-10-11

- Acceptance checkout HEAD: `e65173410d44d610c230046c99fa77faab9bb5da`; initial working tree clean.
- Operator deployed fix1. Its execution was verified by the reconciled persisted baseline hash and the deployed genuine-mismatch guidance, not assumed from the local checkout.
- Fresh Test: **`Codex Validation - J.UI.12e-fix1 Sample Q5 2026-10-11T22-31-35-454Z`**, created inside the existing dedicated 12e validation Course/Offering. No unrelated Course/Offering/Test was changed.
- Used actual `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`; Question analysis, Q3 three-child split, saved Answer analysis, native/corrected automatic diagram, manual PDF crop, and same-major saved reuse were exercised in Chromium.
- The two saved origin diagrams were reused for the third child; four accepted diagram records were retained. Actual PDF content was reviewed, including the confusion matrix/formulas and decision-boundary plot. Teacher-authored scores/criteria follow the Sample Q5 100-point scheme. Unassigned non-answer candidates were explicitly excluded, classification confirmations performed, and three source-review warnings explicitly acknowledged after checking the PDFs. No blocker was suppressed.
- Answer analysis exceeded an initial 30-second automation response wait but completed successfully on the server. Persisted completion was inspected and reused; it was not blindly reanalysed. An attempted resume expecting `解析` found the correctly updated `再解析` control and made no additional inference request.

### Normal confirmation/readiness

| Stage | Server actionable issues | Browser state |
| --- | --- | --- |
| Saved Final Review before Confirm | 0 | Confirm enabled; source review satisfied |
| Immediately after successful Confirm | 0 | Confirmed/read-only; `要修正事項、未解決0件` |
| Duplicate Confirm | 0 | Same confirmed revision; formal projection and baseline unchanged |
| Reload/reopen Final Review | 0 | Confirmed state retained |
| Back → `テスト内容を見る` → Final Review | 0 | Confirmed state retained; no Question `*` markers |

The false `元の正式内容が変更されています。出典付きレビューを確認してください。` issue and the old `確認状態を保存しても、元の警告は残ります。` text were absent. Server issues, badge and dropdown markers agreed.

### Persisted reconciliation and integrity

- Pre-confirm mutable baseline: `11238a3a9f895558a76ee05629a16d920de635a0538353451d34fc8a64840ae1`.
- Post-confirm mutable baseline and recomputed formal projection hash both: `f83a3d49b4137bfab881a67c07572124fc907ee19b8adbb34698b24226d13b15`.
- Saved working snapshot, confirmed snapshot and stored confirmed SHA all: `ac39d0699ad05b885b13b77809573d07e1d509622913bad0615bb375ea4fc1e0`.
- Complete recursive saved/confirmed snapshot equality passed. Working edit version and all four diagram record revisions were unchanged by Confirm. Canonical hashes were recomputed from raw API JSON with Python to preserve numeric representations.
- Duplicate Confirm returned the same confirmed revision, preserved the baseline, and did not change the formal Question/Answer/Rubric projection. Reload/resume preserved snapshot and confirmed identity.

### Genuine-mismatch negative, without unsafe production mutation

Teacher APIs correctly prevent arbitrary confirmed formal/material edits. No SQL, filesystem tampering, guard bypass or artificial response injection was used in production.

Instead, the known protected historical validation record **`Codex Validation - J.UI.12c Sample Q5 2026-10-11T14-02-08-019Z`** was inspected read-only. This is the pre-fix confirmation-integrity evidence already preserved from the earlier 12c acceptance: its actual confirmed payload hash disagrees with its stored attestation, so it is a genuine review-basis inconsistency rather than a normal successful projection.

- Production readiness retained one `formal_review_stale` source issue.
- Browser displayed `確定後に正式内容・出典との対応に差異が検出されました。` and `確定済みの内容は変更できません。`.
- The affected issue card provided an enabled **`修正版を作成`** action and explicit revision guidance. It did not direct the teacher into an impossible Save loop; the old lower message was absent.
- Before/after authenticated authoring responses were identical. The action was not executed on this protected evidence record; no immutable content or old grading basis was rewritten.
- Thus the production negative is a real existing attestation mismatch, not a newly injected external edit. Controlled post-confirm Question/Answer/Rubric/asset mutations and actual revised-draft action execution remain separately proven by the local backend/Chromium negatives above.

### Production safety

- Dedicated Test grading jobs: **0**; submissions: **0**; grading-start requests: **0**.
- Confirm/idempotency/navigation observation window: **0** explicit analysis/OCR/discovery/normalization requests, **0** browser page exceptions and **0** unexpected HTTP errors. Initial explicitly requested analysis/discovery was separate. Runtime-wide model logs were not accessed with the Teacher account; local RuntimeManager regressions provide direct inference-call assertions.
- No agent deployment, migration, DB reset, user administration, runtime configuration change or unrelated-data mutation occurred. New dedicated authoring/confirmed rows were created only for this acceptance; the negative evidence record was read-only. No J.UI.12d or Undo/Redo work occurred.
- Environment credentials were never printed or embedded in files. No screenshots, HAR, authentication tokens/cookies or browser traces were saved. Changed report and local acceptance scripts/results/logs passed a literal credential audit without displaying credential values.

## Local implementation git status (historical)

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/WarningPanel.tsx
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/authoring_confirmation.py
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/test_authoring.py
 M tests/test_authoring_diagrams.py
 M tests/test_test_authoring.py
?? docs/internal/reports/j-ui-12e-fix1.md
```

No migration, DB reset, commit or push. Parent 12e/12c reports are unchanged.

## Production acceptance final git status

```text
 M docs/internal/reports/j-ui-12e-fix1.md
```

Only this standalone fix report changed. Parent reports, application code and tests were not edited during production acceptance. No commit or push.
