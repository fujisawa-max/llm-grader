# J.UI.12b-fix15c — Saved Diagram Reuse Production-State Diagnosis

## Result
PARTIAL

The reported deployed failure was not reproduced in the normal fresh workflow. Its exact root cause remains unidentified. No speculative reuse fix was applied and no filter was relaxed. Added opt-in diagnostic visibility and stronger real-PDF regression evidence.

## Baseline
- HEAD: 68fdfafa65135e4c2ea12c5d2b171f487bb66679
- Initial git status: clean; fix15b committed.
- Read docs/auto-grading-system-spec-v4.md before changes.
- No production access/data mutation, commit, push or deployment.

## Reproduction
Used testData/SampleQ/sampleQ5.pdf and testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf with a fresh Test, real FastAPI, standard disposable DB harness, production Next build, Chromium, real RuntimeManager and managed model stubs.
Uploaded/analyzed Question PDF, split Q3 into three children, saved, uploaded/analyzed Answer PDF, discovered/corrected/accepted Q3(1), inspected Q3(2) before Save, saved, then inspected API and UI after Save.
Before changing product code, this exact positive workflow passed. Therefore the existing test pass was not presented as a deployed repair.
After adding diagnostics, normal and truncated-geometry variants also passed, including manual crop parity and reload/Back/resume.

## Persisted state transition evidence
The following is one actual disposable run; these are not production identifiers. Working acceptance was verified by the accept UI and working-copy guidance; persistence was read through GET authoring, not inferred from frontend state.

| Stage | edit_version | Working new accepted | Persisted origin accepted records | Persisted reuse count | Outcome |
|---|---:|---|---:|---:|---|
| automatic-before-save | 6 | yes | 0 | 0 | automatic absent; unsaved guidance visible |
| automatic-after-save | 7 | yes | 1 | 1 | automatic present; guidance absent; reuse succeeds |
| manual-before-save | 10 | yes | 1 | 1 | new manual absent; prior saved automatic present |
| manual-after-save | 11 | yes | 2 | 2 | automatic + manual present; guidance absent |
| manual-after-resume | 11 | yes | 2 | 2 | both still present |

Full persisted evidence is attached to the Sample Q5 Playwright report as saved-reuse-* JSON attachments. Relevant fields are retained below so this report does not depend on ephemeral harness files.

## Q3 identities / canonical roots
| Field | Q3(1) | Q3(2) |
|---|---|---|
| stable key | teacher-bfed7b7f-9f6d-4311-a6c1-11ae883802a6 | teacher-29a11ad7-ec22-40cb-8a4a-1664ab6eb9e6 |
| parent key | q3 | q3 |
| canonical root | q3 | q3 |
| Answer entry ID | 8466591a-4468-4e2b-9519-1322cc920cd4 | b8909264-f25d-4a3f-b652-713ebde2a155 |
| source draft | 9eb5e2d6-7bc5-49a6-88eb-0bf1d49822e8 | 9eb5e2d6-7bc5-49a6-88eb-0bf1d49822e8 |

Explicit assertion: root(Q3(1)) == root(Q3(2)) == q3. Backend diagnostic target_root is also q3. The automatic diagram source_question_id is q3; assigned_question_id is the child stable key. Canonical parent links, not labels or filenames, govern scope.

## Save snapshot / source evidence
- Test ID: 426cb505-aabd-447b-bfbd-68292a7b020e
- Automatic saved revision: bbead6bb-111b-49ff-9772-67ae187576c3; edit_version 7.
- Manual saved revision: 692cae4d-6f9c-429a-b554-34f78042e0ca; edit_version 11.
- Exact record path: domains.answer.entries[id=8466591a-4468-4e2b-9519-1322cc920cd4].diagram_records
- Automatic after Save: one accepted record. Manual after Save: two accepted records.
- Origin disposition was absent in the ordinary fixture; the existing server default is include. It was not null, ignored or unassigned.
- Answer material ID: 5c573c55-190d-4513-b29d-2b7e0980b9f6
- Answer source draft ID: 9eb5e2d6-7bc5-49a6-88eb-0bf1d49822e8
- Answer source SHA: 6ce6cc39071755205e905e60b2a70feaaf8d63456113c77ff4c529c9c9b1c420
- Answer source artifact: model-answer-imports/9eb5e2d6-7bc5-49a6-88eb-0bf1d49822e8/native/document-ir.json
- Save retained record IDs, source binding, acceptance, crop hash/bounds and assignment. No normalization/drop was observed.

| Diagram field | Automatic | Manual |
|---|---|---|
| id | "diagram-cbb55faae2b179777a2f8fd2" | "diagram-ced7551c0a916f58755f3ad5" |
| state | "accepted" | "accepted" |
| scope | "parent" | "manual" |
| source_type | "<absent>" | "manual_pdf_crop" |
| material_id | "5c573c55-190d-4513-b29d-2b7e0980b9f6" | "5c573c55-190d-4513-b29d-2b7e0980b9f6" |
| source_sha256 | "6ce6cc39071755205e905e60b2a70feaaf8d63456113c77ff4c529c9c9b1c420" | "6ce6cc39071755205e905e60b2a70feaaf8d63456113c77ff4c529c9c9b1c420" |
| artifact_ref | "diagrams/c5bc8a074876effdc1fbac3b6ecab09e0435db3193bceba4ad7cbf32856c42c3.png" | "diagrams/967f39e5078dbc46b12091f5db74ba03c92c6b88b717be98b7ad382229cba53e.png" |
| crop_sha256 | "9515c45096516208b13f6c03c76ef81166911c678fcc2734c41ee8017f971042" | "d2f7d5cfc5e62759850893d573f98469865a8d5068c02eba2f94e4b397b39b8c" |
| page_index | 0 | 0 |
| automatic_bbox | [343.70001220703125, 614.7760009765625, 533.050048828125, 774.6759643554688] | [343.00002843670717, 619.999973878838, 510.000018701804, 770.0000314547174] |
| final_bbox | [345.70001220703125, 616.7760009765625, 531.050048828125, 772.6759643554688] | [343.00002843670717, 619.999973878838, 510.000018701804, 770.0000314547174] |
| crop_bbox | [342.83599853515625, 613.9119873046875, 533.9140625, 775.5399780273438] | [343.00002843670717, 619.999973878838, 510.000018701804, 770.0000314547174] |
| teacher_confirmed | false | true |
| trust_state | "trusted" | "trusted" |
| reason_code | "<absent>" | "<absent>" |
| source_question_id | "q3" | "teacher-bfed7b7f-9f6d-4311-a6c1-11ae883802a6" |
| assigned_question_id | "teacher-bfed7b7f-9f6d-4311-a6c1-11ae883802a6" | "teacher-bfed7b7f-9f6d-4311-a6c1-11ae883802a6" |

Automatic source_type is absent in this existing record format; its automatic_bbox, parent scope and native source artifact establish discovery provenance. No synthetic source_type was added. Page_index 0 means PDF page 1. Manual source_type is explicitly manual_pdf_crop. Both crop previews were accessible and reused with unchanged crop SHA.

## Reuse API request / response
Actual automatic post-Save request (direct diagnostic request adds &reuse_diagnostics=true):

```text
GET /api/v1/tests/426cb505-aabd-447b-bfbd-68292a7b020e/authoring/entries/b8909264-f25d-4a3f-b652-713ebde2a155/diagrams?question_id=teacher-29a11ad7-ec22-40cb-8a4a-1664ab6eb9e6&scope=reuse
```

- Requested after the awaited successful Save and persisted revision read; edit_version 7 was confirmed by the diagnostic response.
- API receives the Test ID, target Answer entry ID and target Question stable key above; no client-supplied source/material/draft selector overrides resolution.
- Backend resolves that target entry to the Answer draft/material/SHA above, rather than the selected PDF pane or latest Rubric import.
- Before filtering: 9 saved entries, 9 compatible-source entries, 1 saved diagram, 1 accepted diagram.
- After filtering: 1 reusable automatic candidate. Origin decision: included. UI preview visible and reuse succeeded.
- Manual post-Save: 3 saved accepted assignments across origin and target; 2 reusable origin artifacts. Target assignments excluded as same_target.
- After reload/Back/resume: 2 reusable artifacts.

## Exact filter diagnosis / controlled empty case
Code audit follows these layers: owned Test and source draft/material validation → source-compatible saved entries → different sibling target → included Answer entry → known Question → same root → accepted and non-hard-invalid record → native/manual provenance and artifact validation → reuse attestation → API response → frontend list.
The opt-in diagnostic records included/excluded decisions, reasons, saved counts, source identity, target/root and persisted revision. Existing valid source/crop checks still run.

We reproduced the same visible empty message under one deliberate additional condition:

- Origin Answer entry 8466591a-4468-4e2b-9519-1322cc920cd4 explicitly changed to ignored through the existing candidate-handling UI and saved.
- edit_version 13; both original diagrams still persisted as accepted; both child roots still q3.
- Reuse API returned 0. Exact exclusion point: entry disposition predicate in ConfirmedDiagramReuse.available; reason entry_not_included.
- Restoring include and saving at edit_version 14 returned 2 candidates again.

This is a correct safety exclusion, not a proven product defect and not proof that the deployed origin entry is ignored. The diagram state and its containing Answer entry disposition are distinct. We did not bypass this predicate or automatically include teacher-excluded entries.
No wrong canonical root, Save drop, stale frontend list, invalid artifact or source-draft mismatch was observed in the ordinary fixture. The actual deployed exclusion remains unknown.

## Opt-in diagnosis implementation
On an owned authoring Answer diagrams GET, use scope=reuse&reuse_diagnostics=true.
Default requests retain their existing response fields and filtering. The diagnostic option adds reuse_diagnostics with:
- persisted revision_id/edit_version;
- resolved source draft, material, SHA and source artifact;
- target Question identity/root;
- saved/accepted diagram counts and compatible-source entry count;
- per-entry/per-record inclusion/exclusion reasons (same_target, entry_not_included, unknown_question, different_major, not_accepted, hard_invalid, diagram_source_stale, source_draft_mismatch, duplicate_artifact or the existing validation error).

Previously ValueError/KeyError/OSError exclusions inside available() were silently skipped. The opt-in response now makes those visible without changing the skip behavior or adding production logs. Existing source validation failures that abort before filtering still use the existing error response.
No functional root-cause repair was applied: production evidence is insufficient. Frontend product code, crop editor, wording, manual UI, persistence/provenance formats and filtering rules are unchanged.

## Normal versus truncated geometry
Both actual Sample Q5 runs passed.
- Normal automatic record: trusted, teacher_confirmed=false; reusable after Save.
- Truncated managed geometry output: teacher_confirmable, reason diagram_ricoh_output_truncated, teacher_confirmed=true after explicit acceptance; reusable after Save.
- Manual crop: teacher_confirmed=true; same saved-only reuse behavior.
Managed inference cannot prove that deployed candidate classification/source provenance matches these runs. The diagnostic option is intended to expose that difference rather than assume a frontend-only fault.

## Verification
- Focused actual Sample Q5: baseline passed (21.3s), diagnostic run passed (22.5s), final normal scenario including ignored/restored control passed (25.4s), truncated scenario passed (25.4s).
- Relevant production-like Chromium reuse/hierarchy group: 8 passed (7.6s).
- Relevant backend authoring/diagram reuse suites: 42 passed, 2 existing collection warnings (24.41s).
- Backend test confirms diagnostic/default candidate lists are identical, unsaved origin excluded, included origin traced, and current target excluded.
- Existing backend negatives cover unaccepted/excluded, stale/invalid source, missing artifact, unrelated major, forged/foreign draft references.
- One additional E2E negative initially timed out because the candidate-handling label locator used an incorrect exact accessible name. The locator was corrected; no behavior assertion weakened and no arbitrary sleep/retry added.
- TypeScript passed; ESLint 0 errors / 19 existing warnings.
- Ruff passed on changed Python/tests; production Next builds passed; git diff --check passed.
- All successful browser harnesses confirmed grading jobs = 0; existing no-extra-inference assertions passed.
- Full backend/full Chromium not run: changes are opt-in diagnosis only; targeted native and authoring reuse coverage was run.

## Files changed
- src/scoring/model_answer_diagram_reuse.py: optional decision tracing for existing filter outcomes.
- src/scoring/api/test_authoring.py: opt-in owned reuse diagnostics response.
- tests/test_authoring_diagrams.py: default/diagnostic parity and saved-only sibling diagnostics regression.
- frontend/e2e/authoring-sample-q5-diagram-real.spec.ts: persisted source/root/record/API evidence; explicit ignored/restored negative.
- docs/reports/j-ui-12b-fix15c.md: findings and retained evidence.

## Remaining deployed diagnosis
After this diagnostic version is available on the deployed machine, capture the existing Q3(2) reuse GET with &reuse_diagnostics=true immediately after the failing Save, together with the persisted origin Answer entry/diagram.
Compare the returned revision with the Save response. Inspect the origin entry decision and resolved source draft/material against its saved source_draft_id/material_id/crop SHA.
If API candidate_count is 0, the recorded exclusion reason identifies the next predicate to investigate. If API includes the diagram but UI remains empty, investigate frontend response ownership/effect lifecycle using that request.
No deployment was performed. Root cause remains unconfirmed; this phase must not be marked READY or COMPLETE. J.UI.12c remains deferred.

## Git status

```text
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M src/scoring/api/test_authoring.py
 M src/scoring/model_answer_diagram_reuse.py
 M tests/test_authoring_diagrams.py
?? docs/reports/j-ui-12b-fix15c.md

```
