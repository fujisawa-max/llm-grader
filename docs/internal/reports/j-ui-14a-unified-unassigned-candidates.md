# J.UI.14a — Unified unassigned Answer/Rubric candidate queue

Status: **READY_FOR_PRODUCTION_VALIDATION**. No production writes, deployment, commit or push.

## Design and persistence

Previously Answer unassigned entries lived under the special Question selector, while Rubric recovery candidates appeared in an inline disclosure even for an ordinary selected Question. The selector now opens one compact queue projecting `domains.answer.entries`, `domains.rubric.entries`, and `domains.recovery.rubric_candidates`. Storage, stable IDs, source roles, source evidence and operation histories stay separate. The inline recovery disclosure is removed. Normal selected-Question content retains the existing editors.

The selector and filters count unresolved actionable candidates: Answer/Rubric entries without a valid Question assignment excluding ignored/excluded dispositions; recovery rows excluding promoted/dismissed state. Recovery `question_key` is a suggested target, not promotion into accepted Rubric content. Excluded rows remain inspectable/restorable and are not counted or selected by Select All. Filters are All / ModelAnswer / Rubric; selection persists by domain-qualified candidate identity across filters. Select All adds only currently shown actionable candidates; Clear Selection clears the whole selection.

Assignment uses the existing `manualClassificationPatch` routing confirmation for Answer/Rubric entries and the existing `promoteRecovery` operation for recovered criteria. Answer/criterion projections update with their owning domain. Individual exclusion and bulk exclusion use ignored disposition or recovery dismissed state, never deletion. Source files/SHAs/geometry are not changed or duplicated. Supported restoration uses the same disposition/recovery state fields.

Mixed bulk exclusion has a titled confirmation dialog with domain breakdown. One synchronous working-snapshot update changes every selected candidate; global Save is still the only durable boundary. There are no per-candidate network operations, so partial network success cannot occur within this operation. No all-success persistence claim is made: feedback explicitly says Save records the decision. A failed atomic Save leaves working decisions visible and the existing failure feedback/dirty state intact; server state is unchanged. Both affected domains are marked dirty for mixed selection.

Final Review and domain issue counts still use existing server readiness. Hidden/excluded candidates are not silently approved. Existing per-Question markers are unchanged. Recovery issue navigation selects the unified queue even if the issue carries a suggested Question key, retains exact candidate IDs, and scrolls/highlights its row. Source/PDF pane, global Save and Final Review remain available; no Question editor is rendered for the special queue selection. Checkboxes, pressed filter buttons and selection count have accessible labels; confirmation reuses `AuthoringDialog` focus/Escape behavior.

## Read-only production provenance audit

Inspected dedicated Test `Repro - review`, Course `Codex Debug - 20261013`, Test ID `a7bc4d5a-014d-4067-a2ac-6672c3de28f6`. Authentication plus GET only; no warning acknowledgment, Save, analysis, content edit or grading.

Working revision `8ce264e0-e43e-493c-9479-4f7ef247638a`, edit_version 22, hash `fb63f92508667f8c6707409c122d16a9fa9faa6b10e79aca2c2b65eaa36ce4c5` was identical before/after both probes.

The observed candidate is `teacher-entry-e6025784-32de-4348-8da4-493d94742f23` in **Answer**, with `material_role=model_answer_source`, `source.kind=teacher_manual`, source material/SHA null, source segments empty, `authoring_question_key=null`, `question_id=null`, `disposition=unassigned`, `mapping_state=needs_review`. No candidate created_at/updated_at, teacher_correction, semantic classification, separate provenance or loaded_model_answer reference is exposed on this row; answer_kind is primary. Its actual source metadata, rather than polished appearance, supports the UI label 教員作成. No extraction/normalization origin or previous owner can be inferred from its text alone.

Its Accuracy formula and answer 0.825 exactly match the current flattened `answers[teacher-fdb9f204-3f93-4876-8510-d1a44a2824dd].primary`. That Question currently exists under q2.2 with null imported source key. This establishes duplicated content across the compatibility projection and the unassigned domain entry; it does **not** establish that the candidate was previously accepted, the previous binding, or which historical operation removed it. The history API returned no confirmed editions. Mutable prior Save snapshots/edit events are not exposed by this API, so the exact production transition remains unavailable. No automatic reassign/dedup/exclusion was performed.

Code audit: `AuthoringCandidates.addAnswer` explicitly creates teacher-manual entries with a teacher-entry ID, source role model_answer_source, and question_id null. `merge_question_analysis` in `authoring_sources.py` preserves entries whose Question key disappears, clears only that binding and sets unassigned/needs_review. This is deliberate recoverable preservation, including teacher text/accepted diagrams/history. Answer reanalysis also retains teacher work when an incoming candidate disappears and preserves teacher text against fallback classification. Save alone does not perform that missing-target transition; exact revised-draft fork copies state. The existing pure merge regression passes, including original text, diagram and Rubric-history preservation.

No new lifecycle defect is proven by the available production history. In particular, the production duplicate cannot safely be attributed to reanalysis, split, Save failure, LaTeX conversion or manual reassignment. A separate lifecycle investigation would need previous saved working snapshots/events to establish that event. This phase leaves both records untouched and exposes provenance for teacher decision. Backend lifecycle semantics are unchanged.

## Validation

Focused final suite: **9 passed / 0 skipped / 0 failed** (8 browser scenarios + 1 score-level semantic test), 19.6s. Includes unified mixed queue, Question compact dialog/split, Rubric interaction dialogs, canonical score levels and split/diagram-reuse regressions. New scenario proves Answer assignment, Rubric assignment, mixed 2 Answer + 3 Rubric exclusion, existing excluded row retention, cross-filter selection, cancellation, dirty state, failed Save retention, successful Save/reload, exact source/binding/diagram/criterion/history preservation and restoration. Runtime log completion counts before/after candidate operations are identical; no analysis/grading request is sent.

Initial full suite: 73 passed / 0 skipped / 1 failed: an existing test waited for the removed unassigned Answer Preview/Edit button. Its assignment step now directly uses the unified queue; its persistence/hierarchy/no-inference assertions are retained. Test fixture setup errors (invalid teacher IDs/source binding, duplicate cloned criterion ID, colon-containing CSS ID and ambiguous alert locator) were corrected without changing product validation or weakening preservation assertions. Final fresh full normal production-like Chromium run: **74 passed / 0 skipped / 0 failed**, 4.5 minutes. Both final harness runs report PASS and grading jobs 0.

The fixture has two model_answer_source recovery rows. They remain in the candidate queue but are not blocking rubric_source recovery issues under existing backend rules; their optional readiness semantics were preserved. No synthetic blocker was added to make an issue-navigation assertion pass. The harness uses temporary DB/artifacts, real FastAPI/RuntimeManager, fresh production Next build/server, and managed synthetic stubs. Real model calls and production grading remain prohibited.

Static: TypeScript (`npx tsc --noEmit`) passed; ESLint 0 errors / 19 existing warnings; fresh Next production build passed (focused and full harness); `git diff --check` passed. Ruff and full backend suite are not required: no Python/backend behavior changed.

Grading jobs **0**. Real model calls **0**. Managed synthetic stubs are used by existing analysis/LaTeX/bootstrap regressions; focused candidate operations have model-call delta **0**. No grading operation was launched.

Backend: unchanged. Existing `test_question_analysis_merge_preserves_answer_rubric_and_sources`: **1 passed**, 1 dependency warning; no new backend tests or migration.

## Files changed and handoff

- `frontend/app/tests/[testId]/authoring/page.tsx`: queue projection, owning-domain callbacks, selector count and recovery issue navigation; remove inline queue.
- `frontend/components/reviews/UnassignedCandidateQueue.tsx`: compact mixed queue/filter/selection/confirmation.
- `frontend/e2e/authoring-unassigned-unified-real.spec.ts`: mixed individual/bulk/filter/excluded/Save-failure/provenance/no-inference regression.
- `frontend/e2e/authoring-correction-ux-real.spec.ts`: unified correction destination.
- `frontend/e2e/authoring-rubric-reliability-real.spec.ts`: recovery/split tests use the sole queue entry point.
- `frontend/e2e/authoring-split-merge-real.spec.ts`: unmatched-source assignment directly uses the queue.
- This report.

No backend, migrations, runtime/model configuration or grading semantics changed. Operator acceptance must use a new dedicated Test for assignment/exclusion/bulk/Save/reload; the production audit record must remain untouched. No commit/push.

## Exact repository status

Before J.UI.14a: clean (`git status --short` empty). After implementation/validation:

```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-split-merge-real.spec.ts
?? docs/internal/reports/j-ui-14a-unified-unassigned-candidates.md
?? frontend/components/reviews/UnassignedCandidateQueue.tsx
?? frontend/e2e/authoring-unassigned-unified-real.spec.ts
```
