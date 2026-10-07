# J.UI.12b-fix1 — Unified Authoring Entry Points & Source Pane Layout

Phase result: **READY_FOR_PRODUCTION_VALIDATION**. Real deployed acceptance has not been performed.

## Root causes

The Test page's next-action calculation inspected formal Questions, ModelAnswers, approved Rubrics and grading readiness. It did not inspect the latest authoring revision, and its navigation destinations only supported the legacy tabs/review flow. A saved authoring draft therefore did not become the primary next action. The page header also lacked a unified authoring edit action.

Home rendered every Test returned by RecentCourseTests. The API returned up to three Tests, sorted by saved-revision/Test timestamps without explicit active-draft priority. Recent Course cards placed the shortcuts after the Course details in ordinary document flow.

The shared ReviewWorkspaceLayout source aside used display:flex without flex-direction. Authoring supplied the material label and PdfPaneViewer as direct sibling children, so the default row direction placed the dropdown beside the viewer. This consumed PDF width. The PDF viewer already had a vertical internal layout and a wrapping horizontal toolbar; no viewer replacement was needed.

## Entry points and recent Course cards

An owned, read-only GET /tests/{testId}/authoring/status returns the latest revision state without loading source engines, creating a draft or performing analysis. The Test page uses it to select the unified editing action for draft/final-review revisions. Legacy draft/setup/rubric-review Tests without a revision also offer unified editing. The Next Action panel says テスト内容を編集してください。, with 編集を続ける for an existing draft and テスト内容を編集 otherwise. Both navigate to /tests/{testId}/authoring. The header also exposes the authoring destination. Existing grading next actions for completed/ready Tests remain, along with all legacy tabs and review URLs.

Home now displays one Test beside each Course: Course name, update date and 開く on the left; Test name, state and shortcut on the right. The authorized server query prioritizes the latest active draft/final-review revision, then the most recent of the Test update and authoring save timestamps, with stable Test-ID ordering for ties. It excludes archived Tests and returns at most one record. The UI also limits rendering to one Test. Draft shortcuts say 編集を続ける and open authoring; confirmed/registered shortcuts say テストを見る and open the existing Test detail page. Cards stack safely at narrow widths.

Navigation resumes the existing saved revision. For an unstarted Test it opens the existing authoring entry screen; creating a working copy remains explicit. It does not restart source analysis.

## Source pane layout and state

The shared source aside now uses a vertical flex layout. The material label/dropdown uses full width and fixed content height. The existing PdfPaneViewer fills the remaining height and full width, with its toolbar above its internal scrolling viewport. The toolbar continues to wrap horizontally; zoom, fit width/page, reset, page navigation and pan implementations are unchanged.

The existing 40/60 desktop grid, measured sticky offsets, viewport-height sizing and narrow-screen single-column fallback remain. At narrow widths the source still stacks dropdown, toolbar and PDF vertically. No editor logic, source geometry or crop engine changed.

Material switching only changes the source viewer. Current Question identity, section visibility and unsaved editing buffers remain. Existing source mapping controls page/highlight only for matching materials; missing mappings are not guessed. Legacy Question/Answer-Rubric source panes reuse the same layout rules and retain their existing workflows.

## Validation

Browser validation uses production Next builds, non-loopback HTTP, real FastAPI, disposable SQLite and the actual RuntimeManager with managed stubs. These are automated acceptance results, not real deployed Sample Q5 acceptance.

| Check | Result |
|---|---|
| Authoring backend foundation/status/recent/archive/auth | 23 passed |
| Source-backed authoring and diagram/trust/scopes/reuse backend | 152 passed |
| Entry/source-layout, foundation, source integration and legacy completion browser tests | 5 passed |
| Full production-like browser regression | 44 passed; includes the initial 5 cases |
| Truncated Ricoh/confirmed reuse and integrated authoring OCR browser regression | 5 passed; additional cases |
| TypeScript | passed |
| ESLint | 0 errors, 19 existing warnings |
| Ruff, changed Python files | passed |
| Production Next build | passed |
| git diff --check | passed |
| Grading jobs | 0 in all three isolated harness runs |

The new browser scenario checks Test entry before and after draft creation, the same saved revision after Home resume, active-draft priority over a newer unstarted Test, exactly one right-side shortcut and the retained Course open action. At 1920x1080 it checks dropdown bottom <= toolbar top <= PDF viewport top, PDF viewport width >=80% of source width, PDF width >400px, height >500px, left-source/right-editor geometry and sticky visibility. It checks narrow source/card layouts, PDF control actions, unchanged target/checkbox/text/dirty state after material switching, absence of an invented overlay and zero model-call delta for all navigation/layout/material actions. Page and console errors are also checked.

Backend tests verify that the status read does not create a revision, foreign ownership is rejected, only one recent Test is returned, an active draft outranks a newer legacy Test and the latest updated Test becomes the fallback once that draft is confirmed. Existing archive/auth tests pass.

The full browser suite verifies legacy Question/Answer-Rubric review, caret/DOM identity and composition/selection/undo behavior, split source ownership, both source math OCR workflows, native diagram preview/highlight/manual correction/persistence, advanced Rubric editing/split/points, unresolved navigation, continuation, authoring formal isolation and RuntimeManager warm reuse. The additional five cases verify corrected teacher-confirmable truncated-Ricoh acceptance, saved/resumed confirmed diagram reuse without inference, delayed-response protection and both unified OCR workflows. There are 175 passing backend tests and 49 distinct passing browser cases across the completed regression runs. The initial five-case browser run overlaps the full suite and is not added again.

## Safety, production acceptance and remaining work

No production database, Q5 content, grades or student submissions were changed. No grading jobs were created. No model/runtime configuration changed, and no analysis is started by the added navigation. Authoring Save/publication semantics are unchanged. J.UI.12c publication is outside this phase.

Real deployment still needs Home -> authoring, Test -> authoring, full-width vertical source layout, material switching and existing editing workflows checked on actual materials. No deployment was performed. No known implementation or automated regression defect remains. Deployed visual/navigation acceptance is the remaining gate.

## Required checklist

- [x] Home shortcut, one recent Test and right-side desktop placement
- [x] Test primary editing/Next Action goes to authoring
- [x] Legacy tabs and review routes retained
- [x] Material dropdown, toolbar and PDF vertically stacked
- [x] PDF uses full source width and remaining viewport height
- [x] Sticky sizing and responsive fallback retained
- [x] Material switching preserves Question, checkboxes and unsaved text
- [x] Navigation/material switching invokes no inference
- [x] Question, Answer, Rubric, OCR, diagrams/reuse and issue navigation regressions
- [x] Legacy review and archive/auth regressions
- [x] Browser E2E, TypeScript, ESLint, production build and diff-check
- [x] Grading jobs zero
- [ ] Real deployed visual/navigation acceptance

## Git and changed files

Changes are unstaged and uncommitted; no commit or push was performed. Local logs, artifacts, databases, credentials and AGENTS.md remain outside the change.

- frontend/app/globals.css
- frontend/app/page.tsx
- frontend/app/tests/[testId]/page.tsx
- frontend/components/RecentCourseTests.tsx
- frontend/lib/api/testAuthoring.ts
- frontend/lib/testWorkflowNavigation.ts
- frontend/e2e/authoring-entry-layout-real.spec.ts
- frontend/e2e/question-completion-real.spec.ts
- src/scoring/api/test_authoring.py
- tests/test_test_authoring.py
- tests/run_runtime_browser_e2e.py
- docs/reports/j-ui-12b-fix1-authoring-entry-source-layout.md
