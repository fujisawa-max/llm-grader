# J.UI.12b-fix8 — Analysis Scope Messaging & Notification Center

## Result

`READY_FOR_PRODUCTION_VALIDATION`. Implementation and automated checks passed. No deployment or production acceptance was performed.

## Baseline

- HEAD at start: `507ae09db70742528b71c8e0a6fd6f11fbfffe2f`
- Working tree at start was already dirty from the uncommitted J.UI.12b-HARDEN-1 implementation, regression tests, and report. Those changes were preserved.
- No production database, deployed Sample Q5, formal production data, or production grading jobs were accessed.

## Message audit and classification

| Existing/current message | Category | Treatment |
| --- | --- | --- |
| Save success | transient notification | Bottom-right success Toast + session history |
| Save failure / API failure | error | Inline alert remains; error Toast is also recorded |
| Question/Answer/Rubric analysis success and assignment counts | transient result | Role-specific success or warning Toast; unresolved candidates remain actionable issues |
| Source correspondence warning | unresolved issue / action required | Separate persistent inline warning with existing source-review navigation |
| Unsaved changes before analysis | blocking/action required | Prominent inline Save guidance remains beside the source analysis action |
| Pending split proposal | blocking/action required | Existing proposal status explains apply/cancel requirement |
| Stale/replaced source | action required | Existing source state/warning remains inline |
| External review conflict | persistent system/action state | Inline conflict and explicit keep/import choices remain |
| Test-wide readiness issues | unresolved issues | Separate count/panel uses the existing review issue model and navigation |
| Material add/replace/import result | transient notification | Toast/history; errors remain inline as well |

## Changes

- Added an authoring-session notification center with typed success/info/warning/error entries, bottom-right accessible Toasts, auto-dismiss, manual close, unread badge, ordered history, and “すべて既読”. No notification database/schema was added.
- Added a distinct “要修正” control whose count reflects the current unresolved `AuthoringIssue[]`; it does not count notifications. The panel and Test-wide review use the same existing review endpoint/model and `navigate()` path.
- Replaced the generic browser analysis confirm with a role-specific in-app dialog. It explains which domain may change and which domains remain, keeps the current saved state in history, and offers `キャンセル` plus `解析`/`再解析`. Focus is moved into the dialog, Tab is contained, Escape closes it, and focus returns to the triggering action.
- Save, analysis, explicit source import, material add/replace, and informational outcomes now produce Toast/history entries instead of accumulating as page-top success text. Save-before-analysis guidance, source warnings, conflicts, and operation failures remain visible inline.
- Answer/Rubric results include assigned and unresolved counts. A zero-assignment result remains an actionable inline error state and also records a warning notification.
- Added browser coverage for notifications/history/read state, role-specific scope/cancel behavior, issue count/navigation, and Toast result counts.

## Defects and test corrections

### Defect 1 — transient outcomes and actionable issues shared the page-top message area

- **Symptom:** Successful saves and imports accumulated near the top, while actionable issues had no separate count/history distinction.
- **Root cause:** The authoring page held one `notice`/`error` display area for unrelated outcomes; success and issue state had no separate typed presentation.
- **Fix:** Introduced the reusable session Notification Center; retained only blocking/action-required and operation failure inline; added an Issues panel over the existing issue model.
- **Regression:** Focused notification, Save/resume, source-backed import, and split/analysis browser scenarios are being run; results below will be finalized after the full suite.

### Defect 2 — analysis confirmation described internal revision mechanics rather than domain impact

- **Symptom:** The generic browser confirmation said a new draft would be created without clearly saying which teacher-edited content could change.
- **Root cause:** `analyzeSource()` used one fixed `window.confirm()` string for all material roles.
- **Fix:** Added an accessible in-app confirmation with role-specific updated/retained content and correct initial/reanalysis labels. Confirmation itself invokes no analysis; cancel makes no model call.
- **Regression:** `authoring-analysis-access-real.spec.ts` covers Question, Answer, and Rubric wording, cancellation and analysis result counts.

### Test correction — split tree assertion assumed array position encoded hierarchy

- **Symptom:** The focused regression failed after a correct split because the expected root had no children.
- **Root cause:** `authoring-split-merge-real.spec.ts` treated `snapshot.nodes[0]` as the root; this array is not guaranteed to be preorder. The actual root was resolved by its stable `parent_key === null` relationship.
- **Fix:** Updated the assertion to locate the root semantically and compare its children. No product assertion was relaxed.
- **Regression:** The split/merge scenario passed after the correction.

## Verification

- Focused notification + hardening + split/merge run: **12/12 passed** (includes 10 Save/reload/Back/resume cycles, 5 dirty→Save→analysis-readiness cycles, stale-tab Save, edit-during-Save, source warning, Answer/Rubric merge, and notification scenarios).
- Truncated-Ricoh / diagrams / reuse / OCR: **4/4 passed** in a disposable production-like harness; grading jobs **0**.
- Full production-like browser regression: **56/56 passed**; harness grading jobs **0**.
- Backend regression: `python -m pytest -q tests` — **913 passed, 1 skipped, 13 warnings**.
- `npm run typecheck`: passed. `npm run lint`: **0 errors, 19 existing warnings** in unrelated legacy files. `ruff check src tests`: passed. `git diff --check`: passed.
- Production Next.js build: passed in the isolated browser harness. Existing Autoprefixer compatibility warnings remain in CSS.
- No backend source or database schema changes were needed. No formal publication occurred.

## Git / safety

- Changes remain uncommitted for review. No push or deployment occurred.
- Production PostgreSQL, production Q5, production grades, and production grading jobs were not accessed or modified.

## Remaining / deferred

- Production visual and deployed acceptance remain required; this phase is not marked complete.
- Question drag-and-drop ordering remains deferred.
- J.UI.12c atomic final publication remains deferred.
