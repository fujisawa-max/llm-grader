# J.GRADING.0 — Immutable Grading Definition Completeness

## Result and authority decision

**COMPLETE.** Local implementation and required automated validation passed previously. Operator deployment was followed by successful isolated production acceptance on 2026-10-12. Production evidence and scope are recorded below. J.GRADING.1 remains outside this phase.

The initial audit reproduced a real disagreement: approved DB levels `[0, 10]` and external assignment levels `[0, 5, 10]` were both accepted for identical Test/Question/criterion identities and points. Development initially stopped rather than selecting an authority. The user's subsequent decision resolves that boundary: **Web authoring Rubric is canonical; filesystem assignment is explicit legacy compatibility only.** No reconciliation UI or legacy-policy import into new Web grading was added.

No remaining information-integrity stop condition was found for the supported new Web contract: positive integer/discrete scoring with sum aggregation, supported Question content, saved text/visual Answers and server-attested image references. CLI `cap`/`unresolved` policies remain legacy and are not silently translated into Web sum policies.

**Important handoff:** this phase supplies the immutable definition adapter, not Submission/job revision binding. New Web editions cannot use the mutable-row selected grading job path or legacy assignment job path. Those operations fail clearly until J.GRADING.1 implements the safe read path. Existing explicit legacy Tests/CLI remain supported. The historical submission/grading activation fail-safe is retained.

Baseline HEAD: `846a1b68e1306fdce31af5e5e1fe63b758cdf065`. At resume, only this audit report was untracked; product/source status was clean.

## Grading-definition completeness matrix

| Semantic field | Before: effective source | Existing confirmed content | New immutable representation |
|---|---|---|---|
| Stable Question identity, parent, order, body | Current TestQuestion / authoring nodes | Mostly present | `grading_definition.questions`: stable key, parent, order, label, supported content |
| Leaf/structural scoring and Test total | Formal Question/max points, Test total | Authoring score state present | Leaf max points, declared/effective score semantics; structural parents excluded from double counting; frozen total |
| Ancestor context and title | EffectiveQuestionContextBuilder / current rows | Title/context identity not guaranteed | Frozen evidence, ancestor chain, context segments, effective text, content/context hashes |
| Text/math/figure/score content schema | Formal content / reviewed source | Projection lacked supported schema | `test-question-content.v1`; explicit resolved formula transcription; figure identity/SHA/reference; ordered score-expression slots |
| Primary/alternative Answers and selection | Current ModelAnswers / authoring entries | Present for authoring, selection varies | Frozen primary/alternatives, included entries and classification/teacher history |
| Criterion identity/order/description/points | Approved RubricVersion / authoring criteria | Present | Frozen canonical criteria with original stable identity and deterministic executable identifier |
| Allowed scores and partial-credit conditions | DB levels or external assignment | Optional, not guaranteed | Teacher-configured `criteria[*].levels`; score and condition required; no inferred levels |
| Aggregation | Test domain requires sum; standalone CLI also supports cap/unresolved | Not an executable guarantee | Explicit `sum`, interpreter `discrete-integer-sum.v1`; incompatible legacy modes not adopted |
| Automatic/manual/reused accepted diagrams | Authoring records / import artifacts | Present for authoring diagrams | All accepted crops, including distinct crops sharing a candidate ID; complete records/provenance retained |
| Visual purpose, source role, page/bbox/normalization | Diagram records / legacy teacher-review references | Workflow-dependent | Explicit question/model-answer role, source role, page, final/expanded bbox, coordinate/renderer contract, acceptance/reuse origin |
| Image identity and bytes | TestQuestionAsset / filesystem roots | SHA/ref partial; MIME not guaranteed | Frozen MIME/type/SHA/owned artifact reference; namespace-relative decoder verifies bytes without current formal lookup |
| Legacy `teacher_review.reference_assets` | Current approved Rubric JSON | Not guaranteed | **Not a policy input to new Web grading.** New Web references derive from accepted authoring diagrams or captured Question assets |
| Correction history | TestQuestionCorrection rows loaded by assembler | Not guaranteed | Captured correction IDs/version/content hashes, matching existing packaged audit fields |
| Source materials/drafts/artifact hashes | Current bindings / authoring domains | Present but not consolidated | Immutable material/source provenance, source bindings and crop identities in the contract/snapshot |
| Model/generation/prompt/runtime settings | Execution/job configuration | Outside authoring | Execution environment, separately sealed by existing jobs; unchanged here. Definition declares the interpretation/schema version |
| GradingPolicy policy text | Rubric generation input / legacy readiness+manifest | Not a direct selected-grader policy input | No new mutable policy lookup; teacher-authored resulting criteria/levels are frozen |
| External assignment levels/conditions | Filesystem JSON copied by legacy `prepare_inputs` | Not sealed by authoring | Explicit legacy-only boundary; rejected for new Web confirmed editions |

Title and correction metadata are frozen context/audit identity, not asserted to independently change today's prompt. Automatic classification history is retained. Working UI-only expansion/focus state is not executable policy. Material/artifact references carry provenance; no arbitrary client paths become grading inputs.

## Canonical contract and compilation boundary

`src/scoring/grading_definition.py` owns compilation and consumption:

- `compile_definition(snapshot, evidence)` is pure/deterministic, with no DB, assignment, model, OCR, renderer or network access.
- `freeze_definition` writes `domains.grading_definition` during draft creation/Save/analysis persistence, before hashing.
- `executable_definition` verifies schema, completeness and exact recomputation from the snapshot and returns a detached definition.
- `confirmed_definition` additionally verifies the persisted snapshot's canonical hash against its stored SHA.
- `executable_rubric` produces a rubric accepted by the existing discrete scoring validator using only snapshot data.
- `read_reference_asset` uses frozen namespace/path/SHA plus configured artifact roots; traversal, missing files and changed bytes fail closed. It does not query current material/draft/formal configuration or regenerate a crop.

Envelope: `schema_version=web-grading-definition.v1`, `authority=web_authoring`, `interpreter_version=discrete-integer-sum.v1`, completeness, total, Questions/context/Answers/criteria/visual refs, material/source provenance and captured evidence. Existing authoring domains remain the editable inputs; the derived envelope is server-owned. Client attempts to forge it are discarded/recomputed; frozen evidence cannot be replaced through ordinary Save.

Initial capture may read owned formal Question context/assets/correction audit metadata once. Later Save/Confirm uses the captured evidence. A legacy confirmed fork remains an exact copy initially; completion derives from its own saved evidence instead of borrowing newer formal context. Missing legacy evidence is not fabricated.

Original criterion IDs remain in the definition. IDs containing characters unsupported by the existing executable rubric protocol receive a deterministic SHA-based executable alias, with the original identity retained in the adapter. Both original and executable identity collisions block completeness. This changes identification representation, not score rules or descriptions.

Question content is converted deliberately into the supported schema. Native formula fallback matches existing authoring display; explicit native/vision/teacher choices use frozen evidence. Excluded/merged formula decisions are respected. Context contains ancestor/self segments, effective text, hashes and immutable asset references, without querying current TestQuestion content.

## Teacher workflow, Save and Final Review

The existing criterion editor now has **得点段階と部分点の条件**. Each row has an explicit score and condition; adding a row initializes **blank score/condition**, never `[0,max]`. Teachers add/remove/edit rows. Supported aggregation is explained as the sum of criterion scores.

Approved **Web** rubric levels already in authoring are preserved and editable. Missing rules must be configured explicitly. External assignment policy is not read, offered or reconciled.

Incomplete drafts remain savable, including no levels and pending blank rows. Malformed/non-finite level field types are structural Save errors; semantic incompleteness is a Confirm/readiness issue. Validation covers positive integral criterion maxima, stable/unique identity, nonempty descriptions/levels/conditions, finite integral scores within bounds, unique scores, maximum-level equality, sums and hierarchy/content/reference validity. Zero is not silently added or newly mandated as a stage.

Readiness distinguishes missing/invalid levels, missing criterion body, invalid points, identity problems and visual-reference problems. Actions target the criterion body/points/level editor or diagram area. Level navigation scrolls/highlights the actual level section and focuses an actionable control below sticky controls. Existing issue overlay, per-Question `*`, unsaved state and Final Review use the same server issue source. Independent source-warning identities remain independent; only duplicate representations of the single Question-body requirement are coalesced.

Final Review and edition history display stored scores/conditions as teacher-facing text, not raw JSON. Historical revisions without a definition show that limitation and remain readable; new grading-definition requirements are not imposed as unresolvable editing actions on already-confirmed legacy content.

## Confirmation, source references and integrity

Confirm requires a complete saved definition and exact recomputation before publication. Existing CAS, permissions, atomic projection, immutable row/hash checks and idempotency remain. No compiler writes occur during Confirm; validators still receive detached copies.

Accepted crops preserve source type/material/draft/SHA, page/geometry, acceptance state, teacher confirmation, origin/reuse metadata and revision. The contract freezes source roles and immutable artifact identity; two different crops with the same candidate ID are not collapsed into one. Source files are referenced, not physically copied.

An explicit request-scoped read-only crop guard prevents Save-oriented validators from rendering missing crops during Confirm. Missing cached evidence fails the transaction with actionable Save/review guidance. Artifact byte verification and source ownership checks happen before formal projection. No diagram revision increment, normalization after hashing, or post-confirm snapshot rewrite is introduced.

Proven invariants in diagram-free and automatic/manual/reused/multiple-diagram cases:

```text
confirmed.snapshot == saved.snapshot
canonical_hash(confirmed.snapshot) == confirmed.snapshot_sha256
canonical_hash(saved.snapshot) == canonical_hash(confirmed.snapshot)
diagram record revisions unchanged by Confirm/fork
failed Confirm: working snapshot/edit version and active basis unchanged
same Confirm repeated: same immutable revision, no new projection
```

Policy counterexample after the authority decision: first edition retains `[0,10]` regardless of external file changes; an explicitly edited Web revised draft produces second edition `[0,5,10]`; first edition remains unchanged. Reconstruction reads the confirmed snapshot alone, not current approved policy.

## Explicit legacy boundary and deferred binding

`prepare_inputs` and `DomainGradingJobAdapter` reject new Web editions with `LEGACY_ASSIGNMENT_NOT_ALLOWED_FOR_WEB_TEST`. The selected execution path rejects them with `WEB_GRADING_REVISION_BINDING_REQUIRED` rather than reading current formal rows. API responses provide Japanese guidance and create no job. Active snapshot hash corruption also fails closed.

Standalone CLI/filesystem grading and existing explicit legacy Test paths are retained. No Submission/job pin implementation, backfill, migration, scoring prompt/model change, runtime orchestration change, regrading, activation-guard removal or production operation was made. **J.GRADING.1 must consume this contract and implement binding before new Web editions can start grading.**

Schema head remains **0018_revision_lineage**. No new Alembic revision, reset, stamp or old snapshot rewrite. Future contract changes require a new schema/interpreter version and retained decoding support; they must not silently reinterpret published v1 content with latest policy.

## Validation

Final-state results:

| Check | Result |
|---|---|
| New definition/actual-field guidance tests | 21 cases passed in the full suite |
| Definition + diagram focused tests | 53 passed before the final metadata/navigation additions; all retained in the final full suite |
| Full backend | **1023 passed, 2 skipped, 23 existing warnings** (256.61 seconds) |
| Full normal production-like Chromium | **74 passed** (4.4 minutes); all required Final Review/Source/Rubric/revision/diagram/Sample Q5 regressions included |
| TypeScript | Passed |
| ESLint | Passed: 0 errors, 19 existing warnings |
| Ruff, all changed Python | Passed |
| Next production build | Passed in the final Chromium harness; production `next start` used |
| git diff --check | Passed |
| Schema/migration | No migration; head remains `0018_revision_lineage` |

The full-suite log paths are local-only `/tmp/j-grading-0-backend-release.log` and `/tmp/j-grading-0-browser-release.log`. They are not deployed artifacts or tracked service files.

Coverage includes missing-policy Save/Confirm separation; invalid levels; actual-field guidance; exact snapshots/hashes; forged projection rejection; policy independence from assignment files; intentional second-edition policy adoption; legacy read/fork/completion; executable identifier handling; artifact drift/traversal; job-path isolation; diagram provenance/bytes; no rendering on Confirm, including missing-cache negative; rollback/CAS/idempotency/permissions/history safety.

Actual PDFs used by Chromium:

- `testData/SampleQ/sampleQ5.pdf`
- `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`

The production-like harness uses real Chromium/Next production server/FastAPI/RuntimeManager with managed deterministic model stubs. These are local automated acceptance results, not deployed production or real-model quality validation. Teacher fixture levels are explicit test choices, not hidden product defaults. Initial regression failures were diagnosed and corrected (native formula conversion, identifier adaptation, independent-warning preservation, new policy fixture requirements and login hydration synchronization); no assertion weakening, sleeps or broad retries.

Authoring/definition acceptance grading jobs: **0**. Compiler/Confirm real model calls: **0**; renderer calls on Confirm: **0**. Existing backend grading suites exercise isolated/mock jobs, not production grading. Existing model analysis tests retain their normal stub calls; no new inference is added by compilation, policy edits, Save or Confirm.

## Production handoff

Operator deployment/revalidation is required. Deploy backend/frontend together; **no migration**. Use a new dedicated Test. Verify incomplete levels Save successfully and block Confirm; configure explicit conditions; inspect the saved/confirmed definition and exact hash/diagram equality; verify external assignment changes have no effect; explicitly configure a second edition; inspect both independent policies. Do not launch grading as part of J.GRADING.0 acceptance. Actual Web grading remains gated on J.GRADING.1.

No remaining authority/completeness stop condition for this implemented contract. Production acceptance and future revision-bound execution are separate pending steps. No deploy, commit or push was performed.

## Repository

Changed files and exact status follow. This lists the complete source/test/UI/report change set. Parent UI reports and the J.GRADING.1 report are unchanged. No credentials/configuration/dependencies/DB models/migrations were added.


```text
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/AuthoringRevisionHistory.tsx
 M frontend/e2e/authoring-correction-ux-real.spec.ts
 M frontend/e2e/authoring-final-confirmation-real.spec.ts
 M frontend/e2e/authoring-final-review-issues-real.spec.ts
 M frontend/e2e/authoring-revision-history-real.spec.ts
 M frontend/e2e/authoring-rubric-reliability-real.spec.ts
 M frontend/e2e/authoring-sample-q5-confirmation-real.spec.ts
 M frontend/e2e/test-authoring-foundation-real.spec.ts
 M frontend/lib/api/modelAnswerImports.ts
 M frontend/lib/api/testAuthoring.ts
 M src/scoring/api/domain.py
 M src/scoring/api/test_authoring.py
 M src/scoring/authoring_issue_guidance.py
 M src/scoring/authoring_sources.py
 M src/scoring/diagram_regions.py
 M src/scoring/domain_adapter.py
 M src/scoring/grading_execution.py
 M src/scoring/grading_inputs.py
 M src/scoring/test_authoring.py
 M tests/run_runtime_browser_e2e.py
 M tests/test_authoring_diagrams.py
 M tests/test_authoring_question_issues.py
 M tests/test_test_authoring.py
?? docs/internal/reports/j-grading-0-immutable-grading-definition.md
?? frontend/components/reviews/ExecutableRubricLevels.tsx
?? src/scoring/grading_definition.py
?? tests/test_grading_definition.py
```


## Production acceptance — 2026-10-12

**COMPLETE for J.GRADING.0 Web grading-definition completeness.** Operator deployed the feature; acceptance verified the live levels editor, grading-definition readiness, immutable contract and two editions. No deployment or migration was executed during acceptance. Submission/job revision binding was neither implemented nor exercised. The expected `WEB_GRADING_REVISION_BINDING_REQUIRED` boundary remains in place; no grading endpoint was invoked.

### Isolation and normal Web workflow

Dedicated Course, Offering and Test were created through authorized service APIs. Only those new records were mutated. Test name:

`Codex Validation - J.GRADING.0 2026-10-12T15-18-28-047Z`

Question, ModelAnswer and Rubric were entered through the normal Web editor, with one 10-point Question (`x + 1 = 2`), answer `x = 1`, and one teacher-written criterion. This focused acceptance used manual authoring rather than PDF extraction; no source analysis/model request was needed. Existing production Tests, Submissions, grading history, runtime settings and external assignments were untouched. Dedicated records remain available for operator inspection.

### Incomplete policy: Save succeeds, Confirm fails safely

- Explicitly created criterion had **no levels**. Draft Save returned **200**, retaining an empty levels array; no hidden score levels or conditions were synthesized.
- Final Review emitted `grading_levels_incomplete`: 「採点基準の得点段階が未設定または不完全です。部分点の条件を確認してください。」
- Confirm button was disabled. An authenticated direct confirmation of that same saved revision returned **409**; no confirmed revision was created.
- 「得点段階を設定」 navigated to the criterion's policy editor. Each 「得点段階を追加」 initially showed blank score and condition fields. Teacher explicitly entered the policy below.

### Explicit policy and teacher review

| Edition | Score | Explicit teacher condition |
|---|---:|---|
| 第1版 / 第2版 | 0 | 正しい値 x=1 を示していない。 |
| 第1版 / 第2版 | 10 | x=1を示し、元の式に代入して成立を確認している。 |
| 第2版 only | 5 | x=1を示しているが、代入による確認がない。 |

Final Review's 「得点段階と部分点の条件」 displayed the criterion, 10-point maximum, levels and conditions. No unresolved issue remained and Confirm became enabled. Both confirmations were performed through the explicit Web confirmation dialog.

### Exact snapshots, hashes and independent executable definitions

| Check | 第1版 | 第2版 |
|---|---|---|
| Complete recursive saved/confirmed snapshot equality | Passed | Passed |
| `canonical_hash(saved) == canonical_hash(confirmed) == stored snapshot_sha256` | Passed | Passed |
| `grading_definition.complete` and API completeness flag | true | true |
| Authority | `web_authoring` | `web_authoring` |
| Score set | `[0, 10]` | `[0, 5, 10]` |
| Snapshot-only executable rubric reconstruction/validation | Passed | Passed |
| Duplicate Confirm returns same confirmed revision | Passed | Passed |

第2版 retains the explicit UI insertion order `[0, 10, 5]`; its score set is `[0, 5, 10]`. No policy reordering or synthesis was required.

Canonical hashes, recomputed with the service's Python canonical-hash implementation from raw authenticated API JSON:

- 第1版: `8b8c4cc5966ff2cf19a86e0a16b31448b2a99ab3ea678f08186caa18b6a718cc`
- 第2版: `d62206844758edba29c0cecd5405205e30d5ef9dfaf2c6617dd84f8660e9f046`

Opening 第1版 through 「版の履歴」 showed read-only content. 「修正版を作成」 produced an exact snapshot/hash copy with explicit parent lineage and kept 第1版 active. After adding the 5-point level through the Web editor and saving/confirming, 第2版 became active atomically. History retained exactly two independent confirmed snapshots; 第1版's original snapshot/policy/hash remained unchanged.

### Legacy independence: evidence and limits

Both **real production confirmed snapshots** were reconstructed using `executable_definition()` and `executable_rubric()` with external filesystem reads and network connections forbidden. Reconstruction required no DB/current-policy lookup and retained the exact levels/conditions above.

An isolated **local temporary legacy-assignment fixture** was changed from `[0, 10]` to `[0, 5, 10]` with different conditions. Reconstructing production 第1版 before/after that change yielded identical executable Rubrics. Production 第2版 changed only through the explicit Web edit described above. The new dedicated production Test had **0 DB grading-policy rows** at final audit.

No production filesystem assignment was edited or inventoried; live external-assignment mutation is **not claimed**. The independence counterexample used a safe local fixture plus the actual production snapshots, and the snapshot-only reconstruction denied the very external reads that could introduce mutable legacy policy. No unrelated legacy workflow was modified.

### References, navigation and audits

This dedicated manual Test contained **no diagrams/visual references**, so conditional visual SHA/geometry/provenance/revision checks were not applicable to this production run. The earlier automated visual/accepted/manual/reused-diagram integrity coverage remains recorded above; it is not represented as a new production visual test.

- Reload, Back/return and 「版の履歴」 reopened both editions and their saved conditions unchanged.
- History still identified 第2版 as active and 第1版 as historical, with 第2版's parent link to 第1版.
- Final server readiness issues: **0**.
- Dedicated Test Submissions: **0**; grading jobs: **0**; grading endpoint requests: **0**.
- Authoring analysis/inference endpoint requests during acceptance: **0**. No real model grading was performed.
- No migrations, production configuration changes, existing immutable-record repairs, commits or pushes.
- Credential literal audit of acceptance scripts, result/snapshot artifacts and changed repository content: **clean**. No HAR, cookie/token storage, credential screenshots or credential values were recorded in this report.

Production acceptance scope passed. No remaining J.GRADING.0 issue was observed. Future J.GRADING.1 revision-bound grading execution remains separate and was not started.

### Repository after production acceptance

Only this report changed; no application, test, migration or configuration file changed during acceptance. `git diff --check` passed. Previously recorded full local results remain unchanged; expensive local suites were not repeated for this report-only production acceptance.

Exact `git status --short`:

```text
 M docs/internal/reports/j-grading-0-immutable-grading-definition.md
```
