# J.UI.12b-fix15e — Teacher diagram acceptance and automatic exclusion

## Result

**COMPLETE.** Local implementation and automated validation were completed earlier. Production acceptance is now completed on a newly created, dedicated validation course/offering/Test, with user authorization for the prerequisite course/offering creation. Real production automatic non-answer exclusions were observed before acceptance, both origins became included after teacher acceptance and Save, candidate_count=2, both reuse actions and reload/Back/resume passed, and explicit teacher-ignore safety passed. Earlier blocked attempts below are historical.

## Baseline and confirmed root cause

HEAD: `a1c066c64815b4d38762ce0aa374446d7386fcf0`; initial Git status clean. fix15d was committed in this baseline. No commit/push during this phase.

User-provided production evidence: both origins had disposition/effective_disposition excluded, mapping_state automatic, ignore_reason classified_as_non_answer, classification status classified, and one saved accepted diagram each. Saved accepted count=2 but candidate_count=0; both origins excluded as entry_not_included; target same_target, root q3.

The classifier's question/note-only branch marks such entries excluded. Previously `AuthoringCandidates` only updated diagram_records on acceptance. Entry exclusion survived Save and was correctly rejected by `ConfirmedDiagramReuse.available()`.

## Exact state transition

A new, explicit diagram acceptance promotes the entry to include only when all hold:

- current disposition is excluded;
- mapping_state is automatic;
- ignore_reason is classified_as_non_answer;
- semantic classification status is classified;
- target is a valid gradable authoring Question;
- existing teacher_correction.disposition is not ignored/excluded/unassigned;
- a newly accepted non-hard-invalid diagram exists, rather than merely redisplaying an already accepted saved record.

The frontend applies this transition to its working copy through the shared automatic/manual diagram onChange path. The backend independently applies the same rule after source/crop validation and before projecting saved Answer state. No reuse predicate changed.

The resulting existing metadata is teacher_correction.disposition=include and teacher_confirmed=true. Original semantic classification, classified_as_non_answer reason, diagram source/crop/provenance and artifacts remain. Explicit candidate handling choices now write the existing teacher_correction metadata, so even an automatic-mapped entry with the old classifier reason can retain a subsequent explicit teacher exclusion. No parallel flag, schema migration or inference was added.

Ignored, unassigned, unresolved, invalid targets, unrelated automatic reasons and already-saved accepted records do not trigger promotion. Historical bad entries are not silently mass-normalized on Save: a new explicit teacher acceptance is required.

## Local Sample Q5 reproduction and evidence

Actual PDFs: `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`.

The natural managed extraction fixture still produced mapped entries with omitted disposition (effective include). This was not rewritten or represented as a natural reproduction of the production classifier. A separate, clearly labelled controlled saved-state case uses the exact supplied production exclusion metadata, while keeping the real PDFs, real source/artifacts, actual split dialog, real FastAPI/disposable DB/RuntimeManager and browser workflow.

The controlled case confirms before accept: excluded / automatic / classified_as_non_answer / classified. Q3(1) accepts an automatically discovered diagram; Q3(2) accepts a separate PDF-drag manual crop. Both become include on acceptance and Save.

| Saved entry | mapping | disposition after acceptance | original ignore_reason | accepted origin diagrams | canonical root |
|---|---|---|---|---:|---|
| Q3(1) | automatic | include | classified_as_non_answer retained | 1 automatic | q3 |
| Q3(2) | automatic | include | classified_as_non_answer retained | 1 manual_pdf_crop | q3 |
| Q3(3) | automatic | default/effective include | native result | 0 before reuse | q3 |

Before origin Save: working accepted=yes, persisted accepted=no, persisted reuse absent. After both Saves: saved origin accepted count=2, diagnostics candidate_count=2, both origins included, target same_target. Both cards are visible and reusable. Reload/Back/resume keeps origins, accepted records and reuse. Existing source provenance and crop artifacts remain server-validated.

Explicit teacher-ignore of origin1 then Save excludes it with entry_not_included; origin2 remains offered. Backend tests additionally cover explicit teacher exclusion metadata on an otherwise identical excluded/automatic/non-answer entry.

Acceptance, Save, reuse and resume require no additional model calls. The new helpers are deterministic; the actual browser scenario asserts model call counts around reuse/Save/resume remain unchanged.

## Verification

- Focused backend/domain/manual/reuse: **70 passed**, 2 existing warnings, 33.29s.
- Full backend: **963 passed, 1 skipped, 22 warnings**, 211.40s. Warnings are existing dependency deprecation/model-class collection warnings.
- Focused browser: **10 passed**, 28.6s (2 actual-PDF browser scenarios + 8 helper tests), grading jobs=0.
- Full normal production-like Chromium harness: **64 passed**, 2.7m, grading jobs=0. Includes existing Sample Q5 discovery/crop/reuse, source-backed state, rubric split dialog, section ownership, notifications/recovery, materials, OCR, Save/resume/endurance and stale-state protections.
- Critical truncated diagram group: **9 passed**, 31.2s (Sample Q5 + authoring reuse + legacy reuse + 6 hierarchy/review helper tests), grading jobs=0.
- TypeScript passed.
- ESLint: 0 errors, 19 existing warnings.
- Ruff changed Python/tests: passed.
- Next production build: passed in each browser harness.
- git diff --check: passed.

One test-only TypeScript fixture cast was corrected during preparation; no assertions were weakened or sleeps/retries added. Backend save-transition parametrization proves source-backed acceptance becomes included even without relying on the frontend transition.

## Earlier production access and deployment probes (historical)

URL: configured. Username: configured. Password: configured. Values are not recorded.

Inspected `docs/operations/production-runbook.md` and `deployment-checklist.md`. Their release process requires deployment-host access, backups and managed worker/service operations. The supplied Teacher HTTP credentials are not a deployment mechanism; no remote deployment channel was established or invented.

A standalone, artifact-free Chromium probe attempted real UI login navigation. No traces, screenshots, HAR, saved cookies or token files were enabled. DNS failed before username/password entry. After the user's account-initialization message, login navigation was retried and failed with the same net::ERR_NAME_NOT_RESOLVED. OS DNS resolution also failed. The login API was not reached.

Production version: undetermined. Deployment: not performed. Dedicated validation Test: not created. Production pre-accept, post-accept, candidate_count, reuse, reload/resume and negative acceptance: not executed. The pre-accept state quoted above is user-provided production evidence, not a newly collected server result.

Production mutations=0 and grading requests=0 for this session. Existing production Sample Q5, other Tests, grades, users and runtime configuration were not changed.

After DNS/network access and deployment are available, use a newly named `Codex Validation - J.UI.12b-fix15e` Test only; verify the real automatic exclusion becomes include after teacher acceptance, Q3(3) candidate_count=2, both reuse actions, reload/resume and explicit-origin exclusion safety. No COMPLETE claim until that succeeds.

## Credential audit

No production credentials are embedded in source, reports or shell literals. The probe reads environment variables at runtime and emits only configured-state/status/error-category facts. No production login screenshot or browser artifact was created. Changed files and local phase logs were scanned for actual configured credential values without printing them; final audit result is recorded below.

## Files changed

- frontend/lib/authoringAnswerInclusion.ts: narrow working-copy promotion rule.
- frontend/components/reviews/AuthoringCandidates.tsx: shared diagram accept integration; existing teacher correction metadata on explicit handling choices.
- src/scoring/authoring_answer_inclusion.py: deterministic domain rule.
- src/scoring/authoring_answers.py: validated save-time state transition before Answer projection.
- tests/test_authoring_answer_inclusion.py: automatic/manual parity, metadata preservation, explicit-exclusion and invalid/no-new-action negatives.
- tests/test_authoring_diagrams.py: source-backed split-origin Save/reuse integration for the production exclusion state.
- frontend/e2e/authoring-answer-inclusion.spec.ts: frontend transition safety matrix.
- frontend/e2e/authoring-sample-q5-three-child-reuse-real.spec.ts: separate natural and controlled production-state scenarios; exact before/after disposition assertions.
- docs/reports/j-ui-12b-fix15e.md: implementation, validation and production blocker report.

## Remaining issues

No remaining fix15e acceptance failure. No application code or production deployment was changed during the acceptance-only run. Prior failed probes are documented below for transparency, but DNS/access and prerequisite setup blockers are resolved. The exact deployed build SHA was not exposed; the actual production state transition and server-attested saved reuse prove the required behavior is active. J.UI.12c and drag-and-drop remain deferred.

## Exact final Git status

```text
 M docs/reports/j-ui-12b-fix15e.md
```

No commit or push; acceptance-only repository modification is this report.

## Earlier single production retry after hosts correction (historical)

At the user's request, performed one additional connection/login probe, without automatic retries. Real UI login succeeded. The served authoring route's JavaScript bundle was found, but lacked the `classified_as_non_answer` acceptance rule present in the locally built fix15e authoring bundle. The fixed frontend is therefore not confirmed deployed; backend build identity was not inferred from frontend evidence.

Stopped before validation Test creation or analysis because the required fixed-version precondition was unmet. Production mutations=0, grading requests=0. No screenshot, trace, HAR, token/cookie export or credential literal was saved. Dedicated production validation Test remains not created. Next step: deploy the locally verified fix through the established release process, then run dedicated-Test acceptance in a separately authorized attempt. No further connection attempt was made during this turn.

## Earlier prerequisite-blocked production acceptance attempt (historical)

At the user's explicit request, attempted the actual workflow rather than stopping on the earlier bundle signature probe. Login succeeded through the browser. Authenticated course/offering metadata lookup found no accessible offering. The dedicated validation Test therefore could not be created.

One initial login attempt did not issue the expected login response before timeout; no Test mutation occurred. The runner then waited for login-page network initialization before interacting, with no arbitrary sleep, and authentication succeeded.

No production snapshot was altered or controlled exclusion fixture injected. No Question/Answer model call, diagram discovery, crop, Save, grading or formal publication was started. Dedicated Test name: not created. Current production code acceptance: not determined by this blocked workflow.

Asked for permission to create a separate validation-only course/offering, or for an existing accessible offering to be provided. This permission is required by the original user instruction restricting mutation to the dedicated Test. No course/offering was created without that approval. Production mutation count=0 and grading requests=0.

## Completed production acceptance

User explicitly authorized a dedicated validation course and offering. Created only the dedicated course, its 2026 full-year offering, and Test below; no existing course/Test/grade/user/runtime configuration was changed.

- Test: **Codex Validation - J.UI.12b-fix15e 2026-10-09T16-14-04-731Z**
- Course: same name followed by ` Course`
- Offering: **J.UI.12b-fix15e validation only**

The dedicated records remain available for inspection and were not deleted or archived.

### Actual workflow and state evidence

Real browser login succeeded. Uploaded the actual Sample Q5 Question PDF, analyzed it, split Q3 into three children via the dialog, and saved. Uploaded and analyzed the actual Sample Q5 ModelAnswer PDF. No production snapshot was injected or forced to reproduce classification; the real classifier produced the relevant excluded entries naturally.

| Stage | Q3(1) saved state / accepted diagrams | Q3(2) saved state / accepted diagrams | Q3(3) reuse count |
|---|---|---|---:|
| Before origin accept/Save | excluded / 0 | excluded / 0 | 0 |
| Q3(1) automatic diagram accepted, before Save | excluded / 0 persisted | excluded / 0 | 0 |
| After Q3(1) Save | include / 1 | excluded / 0 | 1 |
| Q3(2) manual crop accepted, before Save | include / 1 | excluded / 0 persisted | 1 |
| After Q3(2) Save | include / 1 | include / 1 | **2** |
| After both reuse actions and reload/Back/resume | include / 1 | include / 1 | **2** |
| Explicit Q3(1) teacher-ignore + Save | ignored / 1 | include / 1 | **1** |
| Explicit Q3(1) restoration to use + Save | include / 1 | include / 1 | **2** |

The pre-accept states of both origins were exactly excluded / automatic / classified_as_non_answer / classified. Both retained mapping_state=automatic, original ignore_reason and classification evidence after becoming included. All three canonical roots were q3. Diagnostics before target reuse contained saved_diagram_count=2, saved_accepted_diagram_count=2, candidate_count=2, both origin decisions included and target same_target. Source SHA in both origin records matches the actual uploaded Sample Q5 ModelAnswer PDF. Origin records, crop artifact identity, page/bbox and source provenance were deep-compared across reload/Back/resume and remained unchanged.

Q3(1) automatic discovery used the exact-child-to-parent fallback, returned HTTP 200 with one candidate, and was explicitly accepted. Q3(2) used the normal PDF drag/preview/manual-confirmation workflow, not a direct snapshot crop injection. Both saved reuse cards were visible; both reuse actions succeeded on Q3(3). No unsaved guidance remained after Save.

The explicit safety negative preserved the accepted Q3(1) record but excluded its origin as entry_not_included; Q3(2) remained offered. Restored the explicit handling choice to include afterward, leaving the dedicated Test in the normal two-origin state.

### Timing and harness corrections

Initial discovery display assertion used the local harness's 30-second DOM timeout and expired while the real production discovery was pending. Continued on the same dedicated Test, waiting for its specific terminal discovery API response with the production analysis budget instead of sleeping or creating another fixture. A resume-runner string-transformation error was corrected locally before continuing; no production Test reset/reanalysis was performed for that runner error.

The final audit initially requested GET tests/{id}/grading-jobs, which this API does not implement (HTTP 405). Corrected the audit to use existing scoped read endpoints and the request ledger; no application route or product behavior was changed. Existing scoped formal Question/ModelAnswer/Rubric and submissions endpoints each returned HTTP 200 with empty arrays. No grading requests were made, so grading jobs launched by this session=0. Global production job/database counts were intentionally not queried.

### Production safety and credential audit

Only the explicitly authorized validation course/offering/Test were mutated. Existing production Q5 and unrelated data were not read or changed. No formal publication, student grading, student submission creation, account/admin operation or runtime configuration change occurred. Save/reuse/resume/final restoration caused no additional analysis/OCR/discovery endpoint calls in the acceptance request ledger. Provider-level global inference logs were not accessed.

No screenshots, traces, HAR, cookies or authentication tokens were exported. Credentials were read only from the configured environment; no literal value was written into code, commands or this report. Final credential scan result is recorded below.

Application implementation/tests were not changed in this acceptance-only turn. Repository change: this report only. No commit or push.

Final production credential-value audit: **PASS**, zero matches in this report and production acceptance/probe scripts, summaries and logs.
