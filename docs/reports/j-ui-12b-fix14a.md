# J.UI.12b-fix14a — Real Sample Q5 Diagram Discovery & Selection Repair

## Result

**READY_FOR_PRODUCTION_VALIDATION** — real Sample Q5 reproduced before product edits, repaired, and automated checks passed. Deployed acceptance is not performed.

## Baseline

- HEAD: `e74395d4f125ad9625255b0e96ed99936cd4bfbf`
- Initial git status: clean. fix14 is committed in this baseline.
- Input PDFs: `testData/SampleQ/sampleQ5.pdf` and `testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf`.
- Production and production Q5 are untouched; browser fixtures use the existing disposable DB / real FastAPI / RuntimeManager harness with managed inference stubs.
- No commit, push, deployment, or schema migration is planned.

## Reproduction

The unmodified baseline reproduced the reported workflow in Chromium with both actual PDFs (no synthetic PDF or mocked extraction response). The discovery POST failed HTTP 422 with `diagram_source_boundary`. The UI could not display a candidate. Only test/report code was added before reproduction.

## Root cause and source chain

- Saved Q3 parent key/source alias: `q3`; split child stable key is a generated `teacher-…` ID with `parent_key=q3`. No formal Question exists in this fresh workflow. The API receives the saved child stable key. The source chain survives Save.
- The Answer analysis derives matching Question-PDF heading regions: parent Q3 `[35.9200, 613.9120, 594.9600, 842.0400]`; child (1) `[54.6640, 715.6288, 594.9600, 730.9888]`. Coordinates are page-0 crop-local PDF points. The source material and immutable import IR are Answer-role owned.
- Real Q3 diagram frame: `page-0001-drawing-0078`, bbox `[343.7000, 614.7760, 533.0500, 774.6760]`. Answer source SHA: `6ce6cc39071755205e905e60b2a70feaaf8d63456113c77ff4c529c9c9b1c420`.
- The diagram spans split-child text bands. Parent discovery incorrectly excluded its frame because the 4-point proximity test considered it near the preceding Q2 region, even though it is wholly inside Q3. Its top is only 0.864 points below the Q3 boundary.
- A Q2 annotation rectangle (`page-0001-drawing-0111`, bbox `[318.5000, 523.5200, 567.7000, 621.8199]`) crosses the heading boundary. It is not fully owned by Q2 or Q3, but the exclusion list treated it as competing sibling diagram evidence; the grouping guard then rejected the entire Q3 discovery.
- Exact-child label collection could also add image IDs from source segments outside the child bounds, putting an image into both ownership and exclusion lists. Labels are now text-only.
- Even after discovery, the default 6-point crop margin would enter Q2. Optional renderer padding is now reduced at verified source boundaries; the native candidate bbox and source ranges remain unchanged.

## Repair

Discovery still requires full containment within the exact child or proven parent range. Competing-region checks use actual overlap. Only fully sibling-owned visuals are treated as competing evidence; boundary-crossing annotation paths stay out of candidate source IDs. Crop validation still rejects native/manual bboxes outside the permitted Question/parent range and retains sibling blockers.

Unified Authoring follows the server-proven parent fallback during an explicit discovery click, so the candidate immediately appears. It does not follow PDF-wide fallback automatically and never auto-accepts. Legacy standalone review retains its existing explicit parent action. Manual range correction remains expected and supported; no advanced crop interpretation was added.

## Verification

- Reproduction: failed as expected on the unmodified baseline, then the real PDF candidate was visible after the repair.
- Initial targeted diagram/reuse/scopes backend group: 103 passed (before adding the three actual-PDF regressions).
- Actual Sample Q5 backend tests: 3 passed; child image scope, safe parent crop, and cross-major crop rejection covered.
- Expanded actual-PDF workflow plus saved split regression: 5 passed (21.0 seconds), grading jobs 0.
- Full backend: 935 passed, 1 skipped, 22 warnings (204.15 seconds).
- TypeScript passed; ESLint has 0 errors and 19 existing warnings; Ruff passed; production Next build passed; `git diff --check` passed.
- First full Chromium run: 62 passed, 2 failed. One existing endurance test timed out at initial login; trace contains no auth POST and no authoring actions. No product/login change was made. The new test also caught the expected anonymous `/auth/me` 401 during login; its console observer now begins after successful login, matching existing authoring observers. Actual diagram workflow assertions passed. Full rerun is in progress; no assertion of diagram safety was weakened.

The next full rerun passed the existing 10-cycle endurance test; its new Sample Q5 spec was loaded before the console observer change, so the anonymous-login console assertion still failed. A `--skip-build` attempt was stopped: Next rewrites embed the previous harness API port and cannot be reused with a fresh disposable port. Final verification rebuilds against its own API. These attempts changed no product semantics.

## Real-data workflow result

The final actual-PDF browser scenario passed with no authoring page/console errors. It verifies fresh Test creation, both real PDF uploads, actual Q3 split/apply/Save, Answer analysis, automatic safe parent discovery for Q3(1), loaded preview, explicit manual crop correction and acceptance, Q3(2) sibling reuse, shared-PDF Rubric binding/analysis, cached rediscovery, Save/reload/Back/resume, independent child assignments sharing the accepted crop SHA, and intact immutable Answer provenance. An attempted Q2 manual range is explicitly rejected HTTP 422. Rubric analysis leaves the saved Answer domain deep-equal.

- Exact child scope returns no complete diagram because the native Q3 frame spans children.
- The server-proven parent Q3 scope supplies the frame; unrelated-major regions remain blocked.
- The source draft is the Answer binding's `model-answer-imports/<draft>/native/document-ir.json`, not the selected PDF pane or globally latest Rubric import.
- Q3 and child identities stay saved authoring keys; no formal-publication dependency was introduced.
- Manual crop adjustment remains expected; the test trims the source candidate through the actual range editor before accepting.
- RuntimeManager chat-completion counters for OCR, math OCR, managed draft inference and grader remain unchanged during crop correction, Save, sibling reuse, cached rediscovery, reload and resume. Explicit analysis keeps its existing inference path.
- Actual fresh fixture formal Questions, ModelAnswers and Rubrics remain empty. No grading jobs are launched.

## Final verification

- Full backend: **935 passed, 1 skipped, 22 warnings**, 204.15 seconds.
- Targeted existing diagram/reuse/scope backend: **103 passed**, 3 warnings, 39.50 seconds; new actual-PDF backend: **3 passed**. Both are included in the full suite.
- Focused actual-PDF + saved split browser: **5 passed**, 21.0 seconds.
- Final full production-like Chromium: **64 passed**, 2.5 minutes, grading jobs **0**. Real FastAPI / RuntimeManager / disposable DB / managed inference stubs; native extraction reads actual PDFs.
- TypeScript: passed. ESLint: **0 errors, 19 existing warnings**. Ruff: passed for changed Python files. Next production build: passed with existing warnings. `git diff --check`: passed.
- Additional truncated-Ricoh diagram trust/override/reuse regression: **3 passed**, 9.5 seconds, grading jobs **0**.

## Files changed

- `src/scoring/diagram_sources.py`: safe native visual ownership, sibling exclusions, text-only labels and source-bound crop padding opt-in.
- `src/scoring/diagram_regions.py`: clamp optional rendering margin to a proven containing Question/parent boundary; retain native bbox and rejection guards.
- `frontend/components/reviews/DiagramReview.tsx`: opt-in automatic server-proven parent fallback for explicit discovery.
- `frontend/components/reviews/AuthoringCandidates.tsx`: enable that fallback for Unified Authoring Answer diagrams.
- `frontend/e2e/authoring-sample-q5-diagram-real.spec.ts`: actual-PDF end-to-end reproduction/regression, negative scope, source snapshots, runtime counters, screenshot and diagnostics attachments.
- `frontend/e2e/authoring-split-merge-real.spec.ts`: assert the new immediate safe parent-discovery flow.
- `tests/test_sample_q5_answer_diagrams.py`: three real native-geometry regressions.
- `tests/run_runtime_browser_e2e.py`: include actual-PDF regression in the default production-like suite.
- This report: reproduction, audit, verification and deployed checklist.

## Production acceptance still required

1. Fresh disposable real-machine Test: register/save/analyze Sample Q5 Question, split Q3 into three children, Save.
2. Register/save/analyze actual Sample Q5 ModelAnswer; Q3(1) → 図候補を確認 must immediately show its parent-scoped candidate.
3. Adjust crop if necessary, accept and Save; Q3(2) must offer that saved same-major diagram.
4. Register the same PDF as Rubric and analyze; Answer discovery and sibling reuse must remain intact.
5. Save/reload/Back/resume must retain assignments and source provenance; unrelated-major diagrams must remain excluded.

Production and production Q5 were not accessed or changed. No schema migration, commit, push or deployment. J.UI.12c and drag-and-drop remain deferred. No additional authoring/recovery/domain redesign was performed.

## Final git status

```text
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/components/reviews/DiagramReview.tsx
 M frontend/e2e/authoring-split-merge-real.spec.ts
 M src/scoring/diagram_regions.py
 M src/scoring/diagram_sources.py
 M tests/run_runtime_browser_e2e.py
?? docs/reports/j-ui-12b-fix14a.md
?? frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
?? tests/test_sample_q5_answer_diagrams.py
```

## Remaining issues

No known reproducible defect remains in the requested actual Sample Q5 workflow. Deployed acceptance is still required. Managed inference stubs make analysis deterministic; real native PDF extraction, geometry, crop rendering, artifact storage, API validation and browser interactions are exercised. Initial pre-hydration login timing remains an unrelated intermittent harness observation; the final fully built suite passed unchanged login tests. Optional auto-crop refinement is intentionally out of scope.
