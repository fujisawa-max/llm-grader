# J.UI.12b-fix13 — Answer/Rubric Draft Separation & Question Split Modal

## Status
`READY_FOR_PRODUCTION_VALIDATION`. No deployment, production access, formal publication, or grading action was performed.

## Baseline
- HEAD: `ab06b43134de415b401c5f2a1a7670df708f18ac` (`Refine authoring save flow and enforce role isolation`); fix12 is committed.
- Initial working tree: clean.
- Migrations: 17 files under `migrations/versions`.
- Test inventory: 69 backend test modules, 63 frontend Playwright spec files. Most recent fix12 result: 928 passed / 1 skipped backend; 61/61 normal production-like Chromium tests.
- Authoring storage currently has one `TestAuthoringRevision.snapshot` JSON document with `nodes`, `answers`, `rubrics`, `rubric_histories`, and `domains`. `domains.answer.entries` is a shared source-import/editor candidate collection; rows may contain both Answer fields and nested `rubric_edits`/`rubric_merge_history`. `domains.answer.sources` holds role-tagged bindings and `analysis_results`. `ModelAnswerImportDraft` is one table/model for imports from both Answer and Rubric material bindings.

## Historical coupling audit
- Schema: the same `ModelAnswerImportDraft` table/model stores both role types, distinguished by `TestMaterial.material_type`; there is no separate Answer-vs-Rubric import table. A single authoring revision JSON stores both domains.
- Import JSON: each import has one `entries` array. Current validation/edit APIs include `rubric_edits` on those entries, including Answer-role entries. Thus a shared candidate row can own Answer text/diagrams and Rubric criteria/history.
- Authoring JSON/projection: `snapshot.rubrics` is a separate projection, but `domains.answer.entries[*].rubric_edits` is also used as persisted Rubric working state. `source_projection` combines Answer and Rubric import entries under `domains.answer.entries`, then derives both Answer and Rubric maps from that collection.
- UI: `AuthoringCandidates` receives one entry collection and mutates it for both domains. The lower workspace conditionally renders an outer “解答・採点基準” section and mounts Answer and Rubric operations inside that shared boundary.
- Analysis: role checks in the latest fix12 prevent some cross-role projection, but `merge_answer_analysis`/`merge_rubric_analysis` and saved source drafts still share entry-shaped structures. This remains a structural ownership hole, not only a visual issue.
- Resume: source imports are selected per role after fix12, but the returned collection is recombined and the top-level rubric projection is reconstructed from entries. There is no independent persisted Rubric candidate/import collection in the authoring revision.
- Question split proposal is rendered inline under its target Question; each candidate divider is currently placed after the candidate name, inside that candidate.

## Historical ownership findings
- **Schema:** one `ModelAnswerImportDraft` table stores both import roles. This is compatible with separation because each draft references a distinct `TestMaterial` binding; the physical artifact/SHA can be shared without sharing analysis rows.
- **JSON:** the defect was structural in old revisions: `domains.answer.entries[*]` could contain nested `rubric_edits` and operation history, while `snapshot.rubrics` was only a projection. Role-specific import results could also be retained in a shared `analysis_results` map.
- **Source/import:** the legacy projection combined entries from Answer and Rubric role drafts. Rubric was selected by role in a few paths but still merged into the Answer collection; recovery candidates and teacher edits therefore had no independent Rubric owner.
- **Projection/resume:** resume returned one authoring revision, but its shared candidate collection was used to reconstruct both role views. `latest_by_role` is now explicit in source projection, with a separate `domains.rubric` and role-filtered source registries.
- **UI:** the prior combined editor exposed Answer and Rubric controls under one candidate component. The page now mounts three peer sections and writes each candidate adapter back only to its owning domain. Rubric recovery candidates are stored separately and require explicit promotion.
- **Compatibility:** no database migration is needed. On read and save, an idempotent JSON adapter separates nested legacy Rubric edits/history from Answer entries, preserves both role bindings when the old root points at Rubric, and deduplicates duplicate projected criterion IDs. Flattened `rubrics` writes from old clients are translated into RubricDraft only when the separated Rubric domain itself is unchanged.

## Resulting ownership model
- `TestAuthoringRevision` remains one revision row with one JSON snapshot; this is the authoring transaction boundary, not a mixed domain collection.
- `domains.question` owns Question structure, hierarchy, score and source provenance. `nodes` remains the compatibility projection.
- `domains.answer` owns Answer entries, alternatives, classification, diagrams and Answer source bindings. `answers` remains a compatibility projection.
- `domains.rubric` owns Rubric entries, criteria, points, operation history, Rubric source bindings and role-local analysis result. `rubrics` and `rubric_histories` are compatibility projections only.
- `domains.recovery.rubric_candidates` is separate from accepted Rubric criteria. Entries retain origin role, source draft/binding, SHA, source candidate/segment and provenance. Promotion changes RubricDraft only after explicit teacher action.
- `ModelAnswerImportDraft` remains a shared storage type, but each row is tied to one `TestMaterial` binding. The PDF/artifact/SHA can be shared across two bindings; analysis/import rows and authoring domain state do not share ownership.
- Analysis endpoints route by selected material role. Answer and Rubric merge functions reject mismatched roles. Question merge preserves both Answer and Rubric domains. Resume adapts old mixed snapshots deterministically instead of resolving one role from the globally latest import.
- Lower editor sections are peer sections `問題`, `模範解答`, and `採点基準`; UI edits write only their owning domain. The Question split proposal reuses `AuthoringDialog`; candidate dividers now sit between candidate blocks.

## Reproduction and implementation log
- Focused backend tests before the latest JSX layout adjustment: `44 passed, 1 warning` across source projection, diagrams, and shared-source bindings. Python compilation and Ruff passed.
- TypeScript passed after introducing the separate Rubric/recovery types.
- First browser run caught a JSX syntax error in the separator relocation before any browser scenario executed. Fixed the component closure.
- Question split proposal now uses the existing `AuthoringDialog`, with target question label, original content, candidate controls, Escape cancellation, focus containment, and no inline proposal. Divider elements are siblings between candidate blocks; the browser assertion checks they are not nested inside a candidate and there is no trailing divider.
- Role-specific backend merge functions now reject the wrong role; Answer analysis writes only AnswerDraft and separate recovery candidates, while Rubric analysis writes only RubricDraft and its recovery candidates. Deep snapshot regression coverage checks unaffected domains byte-for-byte/logically equal across each role analysis.
- Existing diagrams are source-context-sensitive. The misleading saved-structure warning came from `staleAnswerSourceDraftIds`: old mixed `domains.answer.sources` included Rubric bindings, and the Answer UI marked every non-Answer source draft stale. This stale-source guard is independent of the local dirty flag; saving could not clear a role-classification error. Role-separated source registries now contain only Answer bindings, so a Rubric binding cannot block Answer diagram discovery. The split→Save→diagram discovery browser flow passes.
- Full backend regression initially reported six failures. Root causes were compatibility edges exposed by the split: rubric split tests still used Answer IDs, top-level legacy Rubric writes were normalized away before migration, and legacy mixed revisions with a Rubric root did not reliably recover earlier Answer bindings. The route fixtures now use Rubric-owned targets, the save adapter translates legacy flattened Rubric writes into RubricDraft, and normalization separates the older Answer binding from the current Rubric binding. Focused rerun: `54 passed, 1 warning` (`test_authoring_rubric_split.py`, `test_authoring_sources.py`, `test_test_authoring.py`).
- The first `--skip-build` browser attempt was invalid because the cached Next manifest pointed to a previous disposable FastAPI port. A clean production build corrected the environment; after correcting the server-snapshot cancellation assertion and enabling the Answer section/edit mode in the diagram readiness check, the focused production-like browser group passed `4/4` (source-backed, split/analysis/isolation/diagram-readiness, split permutations, unresolved mapping).
- Broad regression initially found stale browser assertions tied to the old combined layout/domain shape and a source-backed Rubric split test that tried to edit nested Answer rubric state. Tests now assert independent role domains, three peer sections, and explicit recovery promotion before split; product behavior was not weakened.
- The source-backed Rubric test promotes an extracted Answer-role recovery candidate explicitly, saves it into `domains.rubric`, splits it, assigns points to each criterion, and verifies segment provenance and resume. Arbitrary client-added recovery rows remain rejected.
- No schema migration was added. Formal API fixtures remain empty in isolation E2Es; the browser harness checks disposable grading-job count at start and end.

## Verification

### Backend
- Full backend suite: `930 passed, 1 skipped, 22 warnings` in 199.52s.
- Focused source/diagram/shared-binding/Rubric split/save tests: `54 passed, 1 warning`.
- Ruff and Python compilation passed for changed Python modules.

### Browser
- Focused production-like authoring group passed `4/4` for source-backed, split/analysis/domain isolation/diagram readiness, split permutations and unresolved mapping.
- A targeted group passed Answer/Rubric analysis in both source orders and explicit recovery promotion/split/Save/resume. Earlier failures were stale assertions against the former shared domain and preview label; tests were updated to the separated domains and new section boundary.
- Final full production-like Chromium suite: `61 passed` in 2.2m. The runner used real FastAPI, RuntimeManager and managed stub; it reported grading jobs `0` at completion.

### Static
- ESLint: 0 errors, 19 existing warnings.
- TypeScript: `npx tsc --noEmit` passed after the Next build completed. The first concurrent attempt raced with generated `.next/types` cleanup and was discarded.
- Production Next build: passed in the production-like browser runner (`next build`, static generation completed).
- Ruff passed.
- `git diff --check`: passed after final edits.

## Production acceptance checklist for manual validation
1. On a fresh Test, analyze Question, split Q3 into children, Save, then open Q3(1) and discover its Answer diagram candidates.
2. Accept a Q3(1) diagram, then verify Q3(2) offers it under “この大問ですでに使用している図”; repeat after Rubric analysis and after Back/resume.
3. Register the same PDF as Answer and Rubric, analyze/reanalyze each role, and confirm the other domain and teacher edits remain unchanged.
4. Analyze a Rubric source with unresolved content; confirm candidates are visibly identified and only enter accepted Rubric after explicit promotion.
5. Confirm the lower editor presents three independent sections: 問題 / 模範解答 / 採点基準.
6. Save, Back, resume and reload; compare the exact split tree, Answer diagrams and Rubric criteria.

## Final repository state
- Files changed: 16 tracked source/test files plus this report (17 paths total).
- Working tree contains only the listed uncommitted changes; no commit or push was made.
- Formal Questions, ModelAnswers and Rubrics remained unchanged in the isolated browser checks; grading jobs finished at zero.

## Remaining issues
- Real deployed acceptance remains unperformed; phase cannot be marked `COMPLETE`.
- J.UI.12c final publication and Question drag-and-drop remain deferred.
