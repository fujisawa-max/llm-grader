# Authoring Save blocker — diagnosis only

## Result / evidence boundary

Question-only authoring Save is structurally supported. Actual Sample Q5 with no Answer source and no Rubric source saved successfully both before edits and after Question text/label edits. The observed generic rejection was reproduced for incomplete direct-score state (`direct` with `score_points=null`), returning **HTTP 409 / `score_type_mismatch`**. This is an identified Save/confirmation boundary defect, not evidence that missing Answer/Rubric blocks Save.

The exact failed production request/error code and edited snapshot were not supplied or accessed. Therefore the production instance's root cause cannot be uniquely established from its generic message: several distinct validation failures share that message. Do not treat the local score reproduction as proof of the original production predicate. No production connection or mutation occurred.

HEAD: `5a0748257cc64a9e9aa6a701539607f8a4997983`. Initial working tree was clean; the previous documentation cleanup is already committed at this HEAD. This task adds only this diagnosis report; no product fix or new service test was written.

## Local reproduction

Used real `testData/SampleQ/sampleQ5.pdf`, unchanged, with a fresh disposable Test, temporary SQLite/artifact root, authenticated FastAPI TestClient and actual native PDF extraction/Question review services. No ModelAnswer or Rubric upload/analysis. Five extracted nodes; Answer domain absent; normalized Rubric domain exists only as an empty container (**entries=0, sources=0**), not registered grading criteria.

Request sequence:

1. POST `/api/v1/tests/{fresh_test_id}/authoring/revisions` → 200.
2. POST `/api/v1/tests/{fresh_test_id}/question-materials`, real PDF bytes → 201.
3. POST `/api/v1/question-imports/{extraction_id}/draft` → 201.
4. POST `/api/v1/question-import-drafts/{draft_id}/reviews` → 201.
5. POST `/api/v1/tests/{fresh_test_id}/authoring/source-import` with matching Question material and edit version → 200.
6. PUT `/api/v1/tests/{fresh_test_id}/authoring`, JSON `{expected_edit_version, snapshot}`.

The frontend's actual `authoringBuffers()` / `prepareAuthoringSave()` were executed through a temporary TypeScript loader for the prepared cases. No production browser was used; this is local API reproduction with the real frontend payload-building logic, not a full mouse/keyboard Chromium reproduction.

| Submitted edit | HTTP | Backend error |
|---|---:|---|
| untouched | 200 | none |
| prepared_unchanged | 200 | none |
| body_edit | 200 | none |
| score_unset_with_number | 409 | score_type_mismatch |
| direct_score_missing | 409 | score_type_mismatch |
| label_edit | 200 | none |
| edit_source_text | 200 | none |
| included_parent_false | 409 | orphan_node |
| empty_label | 409 | label_required |
| prepared_body_edit | 200 | none |

`prepared_unchanged` uses actual frontend Save preparation. `body_edit` retains validated anchors with exact raw text buffers; `edit_source_text` changes a source text item's editable text; `prepared_body_edit` uses actual frontend text-edit reconciliation. `included_parent_false` excludes a parent while retaining an included child. All rejected requests left the persisted edit version unchanged.

A second fresh disposable Test specifically tested **editing before the first post-analysis PUT**: `prepared_body_edit` → 200. A later `direct`/null score on that Test → 409. Thus ordinary text editing before first Save is not by itself the trigger.

After successful Question-only Save, GET `/authoring/review` returned `can_confirm=false` with missing Answer, Rubric points, score, source-review/Question and Test-total issues. They did not prevent the Save. Temporary fixtures asserted grading jobs=0 and were disposed. Initial exploratory probes encountered local helper errors (wrong material-field location and absence of prepopulated formula decisions); these were helper errors, not product Save failures. The completed cases above ran successfully; no unsupported empty-formula reproduction is counted.

## Exact validation path and status

`src/scoring/api/test_authoring.py:287` PUT handler:

1. ownership/auth, editable state and expected edit version;
2. external legacy source-review token conflict;
3. `validate_materials()` verifies same Test / SHA / role;
4. `test_authoring.validate_snapshot(submitted, saved)` checks snapshot/domain schemas, immutable evidence, hierarchy, types and bounded text;
5. when **Question domain exists**, `AuthoringQuestionReview.validate_working(current.snapshot)`;
6. when **Answer domain exists**, `AuthoringAnswers.validate()`;
7. `save_draft()` revalidates schema/material replacements and persists using CAS, increments edit version, commits.

Step 5 is executed regardless of Answer/Rubric registration. `authoring_question.py:33` constructs review snapshots, restores prior anchored body when ordered content is unchanged, verifies vision pin, then calls `review_document.validate_snapshot(..., mark=False)`.

`review_document.py:296` rejects:

```python
(semantics in {'unset', 'sum_children'} and points is not None
 or semantics in {'direct', 'each_child'} and points is None)
```

It raises `ReviewError('score_type_mismatch', 422, node_key=..., field_key='score')`. The authoring Save wrapper at `api/test_authoring.py:310` replaces this with `AuthoringError(code, generic_message)`; `error()` rolls back and converts **all AuthoringError failures to HTTP 409**. Therefore the observed HTTP response is 409, although the underlying validator's intended status was 422:

```json
{"error":{"code":"score_type_mismatch","message":"保存できませんでした。設問構造または出典情報が無効です。編集内容は画面に保持されています。"}}
```

No failure persistence, formal publication or inference occurs in that path.

## Cause classification / editing paths

- **Missing ModelAnswer:** not Save-blocking; empty maps/absent Answer domain accepted. Missing content is checked by `preflight()` for Confirm.
- **Missing Rubric:** not Save-blocking; empty independent Rubric container/maps accepted. Missing criteria/points checked for Confirm.
- **Hierarchy:** genuinely malformed cycles/orphans/duplicate keys/orders/parent-type contradictions remain Save blockers. Included child of excluded parent reproduces `orphan_node`; this is not missing Answer.
- **Question source/provenance:** immutable evidence/pin, automatic source node retention, source-anchor identities, slices, math edit references and diagram attestation are Save integrity checks. They can independently produce the same generic message; no tampered source was required for the score reproduction.
- **Raw text buffers:** allowed explicitly. Ordinary edits and unresolved raw text can be persisted, with source-review work deferred. The adapter restores verified body before strict anchored validation, then reapplies raw buffers. This did not cause the reproduced rejection.
- **Review basis mismatch:** external saved legacy review token change is a distinct `AUTHORING_EXTERNAL_REVIEW_CHANGED` conflict. Formal baseline drift is principally readiness/Confirm protection, not the reproduced score condition.
- **Material role/binding:** checked separately and correctly immutable/owned; no role collision or missing binding in this reproduction.
- **Other incomplete fields:** empty included labels also reproduce `label_required`. The current identity is a stable key, so an unfinished display label is a candidate for deferred confirmation readiness; whether to allow it on Save requires an explicit narrow policy decision.

The UI can produce direct/null without corrupting provenance: `NodeEditor.tsx:64-84` retains null when changing to direct and represents a cleared numeric input as null. The default new authoring node is also direct/null (`page.tsx:42`). Missing numeric input is therefore a normal unfinished editing state that the generic outer schema already permits, but the source-backed review validator refuses.

Registering Answer before editing cannot bypass the Question validator: the Question branch is unconditional on Answer existence, and Answer validation adds another branch. A workflow may appear to work by completing/changing scores or changing the source snapshot while doing Answer setup; no evidence supports Answer registration as a required workaround. No unnecessary Answer model inference was run merely to test this claim; it follows directly from the executed handler control flow.

## Save versus Confirm coupling

Both Save and Confirm use `AuthoringQuestionReview.validate_working()`. `mark=False` already avoids final-review-only requirements for nonempty content, complete formula/figure review and blocking warning acknowledgements. However several required-value checks remain unconditional.

Save needs: safe data representation, owned source/artifacts, preserved evidence, valid references, hierarchy suitable for persistence, valid finite numeric values when supplied, bounds and CAS. It should not require complete authoring or resolved teacher-review decisions.

Confirm additionally needs: exact saved identity/hash, immutable snapshot invariant, complete scores/totals, Answer text or accepted diagram, criteria/points equality, classification decisions, unassigned candidate processing, required source review, no genuine stale binding/formal basis, and historical grading activation safety. These come from preflight/source checks and atomic formal projection; incomplete working state must remain distinct.

### Current readiness issues: no evidence they are all Save blockers

The complete preflight issue groups inspected are: no included Questions; empty Question body; missing/invalid leaf score; missing Answer text/diagram; Rubric integration/points review; absent/mismatched criteria; unreviewed formula/figure; blocking Question source warnings; unresolved raw text/source review; unavailable source diagnostics; unassigned Answer; multiple primary Answers; unconfirmed Answer classification; unassigned Rubric; unresolved Rubric recovery; Test total mismatch. Review additionally appends invalid source, formal drift and historical grading publication safety issues.

**Save does not call `preflight()` or gate on this issue list.** Missing Answer, missing Rubric, total mismatch, classification confirmation, recovery processing and normal unreviewed sources are not globally promoted to Save blockers. They must not all be relaxed or reclassified as an emergency fix.

Save-time required-value overlaps requiring focused policy review:

- **Proven incomplete-draft conflict:** direct/each-child with null score (`score_type_mismatch`), even though null is representable and current Confirm readiness should request a score.
- **Additional reproduced completion rule:** included blank label (`label_required`); should be evaluated as editable-draft completeness rather than automatically equated with invalid provenance.
- **Other unconditional source-review checks:** empty `teacher_edit` transcription (`teacher_transcription_required`) is rejected, and `merged_into_text` without matching formula text (`merged_formula_text_missing`) is rejected. The former needs an explicit incomplete-edit representation; the latter may be a real evidence contradiction and must not be weakened blindly. These are code-audit findings, not Sample Q5 empty-formula reproduction results.
- **Not merely unfinished:** unset/sum-children with a non-null score is contradictory representation; malformed anchors/slices, source identity mismatch, invalid diagram provenance and orphan hierarchy are integrity protection. Do not discard them just because their error messages are vague.

## Why the UI is vague

`ReviewError` contains code, status, node_key and field_key. The Save catch retains only code and replaces every Question error message; it drops the concrete node/field and original status. `ApiRequestError` retains a code/details but its Error message uses only backend message; the Save UI catches it as a generic Error and adds another general preservation sentence. Neither layer maps `score_type_mismatch` to the affected score or shows current/expected values. This is separate from whether validation is appropriate.

## Recommended narrow fix — not implemented

Once the original production error code/payload is captured, identify the exact predicate before changing it. For the proven score case, provide a draft-specific validation mode permitting direct/each-child null scores while preserving typed/finite/range checks and all provenance/hierarchy checks. Keep missing-score enforcement at Confirm and make readiness account for score semantics explicitly, including each-child and structural parents; current preflight is not a wholesale substitute for every legacy reviewed-state check.

Do not normalize away teacher input or switch score semantics silently. Pass structured code/question/field/current/expected context through the existing error boundary and give Japanese guidance such as `配点が未入力です` when appropriate. Preserve rollback/CAS and keep malformed contradictory score representations distinct. Add later focused regression for fresh Question-only Save, edited-before-first-Save, null-score draft Save versus Confirm block, genuine orphan/source-tamper negatives, and missing Answer/Rubric Confirm protection.

Production diagnosis still needs the rejected PUT response's `error.code` and the affected node's stable key, score semantics/points and edited fields. No credentials or complete sensitive PDF/request dumps are necessary. This diagnosis run did not access production.

## Follow-up: 保存に必要 / 確定までに必要 / 注意

Related architectural gap: Save exceptions and Confirm readiness are two paths, with inconsistent status/detail and no shared requirement-stage metadata. Introduce a server-owned condition descriptor (code, direct Question owner, domain/field, current/expected, correction action, stage) used by persistence validation, Confirm readiness, selector markers and issue overlay. UI should display stage labels, not independently infer severity from Japanese messages.

- 保存に必要: invalid representation/references, foreign/deleted/tampered evidence where unsafe to persist, CAS/ownership conflicts. Distinguish retry/reload conflicts from data repair.
- 確定までに必要: missing content/points, unresolved classification/assignment/source confirmation, scoring mismatch and activation safety.
- 注意: genuinely informational observations that need no blocking action.

A stale binding may be safely retained as historical evidence but block Confirm/tools; stage depends on whether submitted data is invalid versus unchanged stale provenance. Do not make every source issue Save-blocking. CAS/auth/integrity enforcement remains server authoritative; classification is a focused follow-up design, not implemented here.

## Files inspected / safety

- `src/scoring/api/test_authoring.py`
- `src/scoring/test_authoring.py`
- `src/scoring/authoring_question.py`
- `src/scoring/review_document.py`
- `src/scoring/authoring_answers.py`
- `src/scoring/authoring_sources.py`
- `frontend/app/tests/[testId]/authoring/page.tsx`
- `frontend/lib/authoringState.ts`, `questionContent.ts`, `api/client.ts`
- `frontend/components/reviews/NodeEditor.tsx`
- Existing fixtures/tests: `tests/test_test_authoring.py`, `test_authoring_sources.py`, `test_question_math_ocr.py`, `test_question_reviews.py`, `test_question_vision.py`, `run_runtime_browser_e2e.py`.
- Existing local specification `docs/auto-grading-system-spec-v4.md` Save/Confirm semantics.

Ten completed comparison requests plus two fresh first-Save comparison requests. This is exploratory diagnosis, not a new committed test suite. No expensive regression suite was run. Temporary scripts/data were outside the repository, disposable fixtures cleaned up, grading jobs=0. No application/test/migration/config edits, validation weakening, production changes, follow-on implementation, commit or push.

## Exact git status

This task adds only this report.

```text
?? docs/internal/reports/authoring-save-blocker-diagnosis.md
```
