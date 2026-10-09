# J.UI.12b-fix15a — Same-Major Unsaved Diagram Guidance

## Result
READY_FOR_PRODUCTION_VALIDATION

## Baseline
- HEAD: e9ecb2a269762d7061b05a13006f19eecf15c0bc
- Initial git status: clean; fix15 committed.
- No production access, deployment, commit or push.

## Root cause / visibility before and after
Before: each DiagramReview compared only its currently displayed Answer entry's diagram records with that entry's saved baseline. An unsaved accepted diagram in Q3(1) could not trigger guidance in Q3(2).

After: the current Question and Answer targets resolve through stable parent keys to the top parent, matching the same-major traversal used by saved sibling reuse. All Answer entries in that tree are examined. Guidance appears when an accepted working record is missing from or differs from the corresponding saved record. New accepted automatic and manual crops are treated equally. Unaccepted records and unrelated text edits do not trigger guidance; other major Questions are excluded. Missing/cyclic ancestry fails closed.

The shared canonical Question hierarchy module exposes the root resolution; no label/prefix/filename grouping is introduced. The UI receives existing Question parent keys from the authoring snapshot. Backend reuse scope and discovery are unchanged.

Exact text remains:
> 他の小問で図を再利用するには、図を選択した後に保存してください。

Save synchronizes the existing saved baseline, so guidance disappears immediately; saved diagrams then appear through the existing sibling reuse list.

## Browser verification
Real Sample Q5 PDFs:
- testData/SampleQ/sampleQ5.pdf
- testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf

The focused Sample Q5 scenario passed twice, each covering:
- automatic discovery/correction/accept in Q3(1);
- switch to Q3(2) without Save, guidance visible;
- Save, guidance absent and saved diagram available for reuse;
- equivalent unsaved sibling guidance for manual PDF crop;
- manual crop provenance/zoom checks and saved reuse;
- Rubric analysis interaction, reload, Back/resume;
- existing no-extra-inference assertions.

Relevant diagram trust/reuse and canonical hierarchy group: **9 passed** (3 real API/browser scenarios + 6 helper tests). The new root scope test includes siblings, grandchildren, unrelated majors, missing ancestry and cycles.

Split/merge production-like group in its own fresh disposable harness: **4 passed**. This includes saved split-child discovery and sibling reuse.

Two combined Sample Q5 + split runs each returned 4 passed / 1 failed. Both failures were the first split test's login URL assertion before authoring: trace had auth/me 401 and no auth/login POST. Sample Q5 passed both times, other split scenarios passed, and the entire split group passed when isolated. No arbitrary sleep, retry setting or assertion weakening was added. This combined-run login submission issue remains a harness verification caveat outside this visibility-only change.

Successful complete harnesses confirmed **grading jobs = 0**.
No full browser/backend suite was required or run for this frontend-only narrow phase.

## Static checks
- TypeScript: passed.
- ESLint: 0 errors, 19 existing warnings.
- Next production build: passed in production-like harnesses.
- git diff --check: passed.
- Python/backend unchanged; Ruff and full backend suite not required.

## Files changed
- frontend/app/tests/[testId]/authoring/page.tsx: pass stable parent keys to candidate UI.
- frontend/components/reviews/AuthoringCandidates.tsx: compare same-major accepted working diagrams against saved baseline.
- frontend/lib/canonicalQuestionPath.ts: shared canonical root resolution with invalid ancestry guards.
- frontend/e2e/authoring-sample-q5-diagram-real.spec.ts: automatic/manual unsaved sibling guidance and Save clearing regressions.
- frontend/e2e/review-issues.spec.ts: hierarchy scope regression.
- docs/reports/j-ui-12b-fix15a.md: this report.

## Final git status
 M frontend/app/tests/[testId]/authoring/page.tsx
 M frontend/components/reviews/AuthoringCandidates.tsx
 M frontend/e2e/authoring-sample-q5-diagram-real.spec.ts
 M frontend/e2e/review-issues.spec.ts
 M frontend/lib/canonicalQuestionPath.ts
?? docs/reports/j-ui-12b-fix15a.md

## Remaining acceptance
Deployed acceptance remains: Q3(1) accept without Save → Q3(2) guidance; Save → guidance disappears and saved diagram reuse appears. Repeat with manual PDF crop.
Discovery, crop, persistence, source/provenance, sibling reuse backend and Save semantics were not changed. J.UI.12c remains deferred.
