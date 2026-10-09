# J.UI.12b-fix15d — Saved diagram entry inclusion diagnosis

## Result

**PARTIAL.** The reported production exclusion is confirmed by the user's diagnostics, but its originating disposition transition is not established. No inclusion transition or reuse safety predicate has been changed. Added opt-in saved-entry diagnostics and a real Sample Q5 three-child regression so the remaining production difference can be identified safely.

## Baseline

HEAD: `e3df861f305881f573ec65ecc5f1e9bd1300b809`. Initial `git status --short`: clean. No commits or pushes performed.

## Exact predicate and audit

`ConfirmedDiagramReuse.available()` excludes an origin when `entry.get('disposition', 'include') != 'include'`, after excluding the current target. This prevents ignored/excluded/unassigned entries from becoming saved diagram reuse origins. Missing disposition means legacy/default include; explicit null does not.

The production observations establish two saved accepted diagrams, both origins rejected as `entry_not_included`, target rejected as `same_target`, target root `q3`. They do not distinguish ignored, excluded, unassigned or explicit null, nor automatic classification from teacher choice.

Possible existing transitions identified (not claimed as the production root cause):

- `model_answer_imports.classify_entries`: blank source text → ignored / blank_or_whitespace; confidently question/note-only text → excluded / classified_as_non_answer.
- `merge_answer_analysis`: unmapped import → unassigned / needs_review.
- `AuthoringAnswers.validate`: a target changed into a non-gradable structural parent loses assignment and becomes unassigned; source diagram is retained as invalid evidence.
- `AuthoringCandidates`: diagram acceptance updates diagram_records, leaving entry disposition intact. The visible editor collection is filtered by target key, not inclusion, so a non-included entry can still display a diagram.

No unconditional accept→include rule was added. Such a rule could override an explicit teacher exclusion. No working-copy diagrams were injected into the saved reuse UI.

## Added diagnostics and production acquisition

Existing GET endpoint remains:

`/api/v1/tests/{test_id}/authoring/entries/{target_entry_id}/diagrams?question_id={target_key}&scope=reuse&reuse_diagnostics=true`

The diagnostic-only response now includes `reuse_diagnostics.entry_states`, with entry_id, question_id, authoring_question_key, disposition_present, disposition, effective_disposition, mapping_state, ignore_reason, classification_status, source_draft_id and accepted_diagram_count. Default responses are unchanged. Reads remain owned-Test authenticated operations with no inference.

After deploying this diagnostic change, open Q3(3) and inspect its GET diagrams request with scope=reuse in browser Network tools. Append `&reuse_diagnostics=true` to that same URL, then request it using the logged-in browser (same origin). Inspect entry_states for the origin IDs identified by decisions. Do not change snapshot data.

Without deploying this change, the existing authenticated GET `/api/v1/tests/{test_id}/authoring` already exposes `revision.snapshot.domains.answer.entries`. Match origin entry IDs from existing decisions and read disposition, mapping_state and ignore_reason directly. Omitted disposition must be distinguished from null.

## Real Sample Q5 evidence

Uses actual `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`, real FastAPI/disposable DB/RuntimeManager path, Chromium and managed deterministic model responses. Q3 split applied through the existing dialog, saved, Answer analyzed, automatic diagram accepted in child 1, a distinct PDF-drag manual crop accepted in child 2, then child 3 queried.

Observed saved states in this harness:

| Entry | disposition | mapping_state | ignore_reason | root | accepted diagrams after both Saves | reuse decision |
|---|---|---|---|---|---:|---|
| Q3(1) | absent; effective include | automatic | absent | q3 | 1 | included |
| Q3(2) | absent; effective include | automatic | absent | q3 | 1 | included |
| Q3(3) | absent; effective include | automatic | absent | q3 | 0 before reuse | same_target |

Persisted path: `revision.snapshot.domains.answer.entries[*].diagram_records`.

Transitions: before first Save, working accepted=yes / persisted accepted=no / reuse=0; after first Save persisted accepted=yes / reuse=1; after second manual acceptance but before Save reuse remains1; after second Save saved accepted origins=2 / reuse=2. Same-major roots are derived from canonical parent links, not label or filename grouping. Actual generated stable keys, entry IDs, binding IDs, revisions, source SHA/artifact and complete records are attached to the Playwright report per evidence stage.

The dedicated test verifies both reuse actions, reload/Back/resume, and explicit ignore of origin1 while its accepted record remains: only origin2 offered, origin1 reason entry_not_included. Cached display, Save, reuse and resume do not increase recorded model calls.

## Verification

Browser: existing actual Sample Q5 regression 1 passed (25.3s); new three-child test 1 passed (14.3s). Both harnesses verified grading jobs=0. The initial new test reached candidate_count=2 but timed out by clicking the first already-used disabled reuse button on the second loop; corrected the locator to select an enabled reuse button and reran successfully. Relevant Chromium reuse/review group: 8 passed (7.5s), truncated managed geometry mode; grading jobs=0. Total successful browser assertions across these runs: 10 tests (4 production-like browser scenarios plus 6 helper tests). Full backend/full browser suites not run for this diagnostic-only behavior-preserving change.

Backend: 46 passed, 2 existing warnings (26.85s), authoring diagrams + confirmed reuse suites. New negative matrix covers ignored/excluded/unassigned/explicit-null accepted origins. No safety relaxation.

TypeScript passed; ESLint 0 errors / 19 existing warnings; Ruff passed; production Next build passed in browser harness; git diff --check passed. No schema change, formal publication, grading flow, production Q5 mutation, crop UI change, source-provenance change or J.UI.12c implementation.

## Files and remaining work

- src/scoring/api/test_authoring.py: opt-in saved entry inclusion diagnostics only.
- tests/test_authoring_diagrams.py: asserts diagnostic entry state for saved split origin.
- tests/test_model_answer_diagram_reuse.py: accepted diagrams cannot bypass non-included entries.
- frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts: actual Q5 3-child/two-origin workflow and saved state evidence.
- docs/reports/j-ui-12b-fix15d.md: diagnosis, evidence and acquisition instructions.

Production root-cause repair remains outstanding until production origin states can be inspected. Local success is not claimed to reproduce or repair the production transition. J.UI.12c and drag-and-drop remain deferred.

## Read-only snapshot extraction without deploying diagnostics

On the existing authoring page, the browser console can read the already available saved snapshot:

```js
const testId = location.pathname.split("/")[2];
const {revision} = await (await fetch(`/api/v1/tests/${testId}/authoring`)).json();
console.table(revision.snapshot.domains.answer.entries
  .filter(e => e.diagram_records?.some(r => r.state === "accepted"))
  .map(e => ({
    entry_id: e.id,
    question_key: e.authoring_question_key,
    disposition_present: Object.hasOwn(e, "disposition"),
    disposition: e.disposition,
    effective_disposition: Object.hasOwn(e, "disposition") ? e.disposition : "include",
    mapping_state: e.mapping_state,
    ignore_reason: e.ignore_reason,
    classification_status: e.semantic_classification?.status,
    source_draft_id: e.source_draft_id,
    accepted_diagram_count: e.diagram_records.filter(r => r.state === "accepted").length
  })));
```

This performs one authenticated GET and does not Save, analyze, change inclusion, or invoke models. The output identifies the exact origin entries from the existing reuse decisions.

## Exact final Git status

```text
 M src/scoring/api/test_authoring.py
 M tests/test_authoring_diagrams.py
 M tests/test_model_answer_diagram_reuse.py
?? docs/reports/j-ui-12b-fix15d.md
?? frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts
```

No inclusion-state repair is claimed. Next step is to inspect production snapshot origin states using the read-only method above, reproduce that specific automatic/teacher state transition, and repair it while retaining explicit exclusions.
