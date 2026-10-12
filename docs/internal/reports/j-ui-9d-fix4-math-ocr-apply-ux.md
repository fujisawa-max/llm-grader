# J.UI.9d-fix4 Math OCR Apply UX Simplification

## Phase result

**COMPLETE.** This phase changes only the final proposal interaction. Real production-model acceptance is not required for this UI-only phase; browser verification uses production frontend, real FastAPI, isolated SQLite, actual RuntimeManager and managed runtime stubs on a non-loopback HTTP origin.

## UI before / after

Previously an `ambiguous` proposal required a separate checkbox labelled 「数式構造に曖昧さがあります。変換案を確認しました。」 before Apply became enabled. The checkbox, `confirmed` state, reset, change handler and confirmation gating are removed from the shared `LatexNormalizationControl`. No confirmation-specific API field exists, so API types and backend semantics need no change.

A valid proposal can now be applied directly using 「この変換を適用」. The secondary helper note 「適用後も数式は編集できます。」 appears immediately above the action buttons. Explicit Apply and Cancel remain; nothing applies automatically. The shared control also consistently simplifies the existing plain-text LaTeX proposal interaction.

## Apply enabling rule / safety

Apply is enabled only for an existing `safe` or `ambiguous` proposal when the parent control is enabled, no request is busy, the original proposal text still equals the editing text, and the existing KaTeX/delimiter syntax gate passes. Rejected, no-change, stale, invalid-math or unexpected statuses cannot apply. While a request is pending the previous proposal is cleared, the request button is disabled, spinner/status and `aria-busy` remain, and no Apply action is available.

Backend validation, source provenance, authorization, runtime lifecycle, Ricoh/Uni-MuMER/Ornith behavior and grading logic are unchanged. Crop, KaTeX, grouping, candidate, raw OCR, deterministic/Ornith and rejection diagnostics remain unchanged. Removing the checkbox does not remove backend warnings or validation. Explicit Apply is the teacher's acceptance action.

## Editing / save / register

Apply still invokes the existing local-edit callback only. Browser tests apply via keyboard Enter, then manually edit the actual inserted LaTeX (`Precision=` to `\mathrm{Precision}=`) and add a teacher note. The editor remains editable, while the server draft still contains the original text and the formal ModelAnswer still contains the existing formal answer.

Only 「下書き保存」 changes the saved draft; reload retains the manually edited LaTeX, and the formal answer remains unchanged. Only the separate register action updates the formal ModelAnswer. Cancel discards only the proposal and leaves editing text unchanged; Apply/Cancel use native accessible buttons, including keyboard activation.

## Tests

- Production-build non-localhost Chromium regression suite: **27 passed**. Covers direct Apply, checkbox absence/helper note, KaTeX, Cancel, stale/rejected/invalid-math blocking, loading, draft/formal isolation, answer/rubric workflows and existing editing regressions.
- Dedicated formatting-only fallback browser scenario: **1 passed**. Confirms direct Apply without checkbox, post-Apply manual LaTeX edit, unchanged saved/formal states until explicit actions and warm runtime reuse.
- Focused source-math browser rerun after refining the manual-LaTeX edit assertion: **2 passed**. Confirms keyboard Apply, Cancel, local edit/save/register separation, failure/retry and diagnostics.
- TypeScript and production builds: pass. ESLint: **0 errors**, 19 pre-existing warnings. `git diff --check`: pass.
- Unexpected page/console errors: none in monitored scenarios. Tests assert real editor values, API persistence and reload behavior rather than only button existence. Grading jobs: **0**.

Backend code is untouched, so no redundant backend test rerun was needed. Test runtime calls use managed stubs only; production/Q5 data, PostgreSQL and OpenWebUI were not accessed or changed.

## Files changed / Git status

- `frontend/components/LatexNormalizationControl.tsx`
- `frontend/e2e/latex-normalization-real.spec.ts`
- `frontend/e2e/source-math-ocr-real.spec.ts`
- `frontend/e2e/source-math-formatting-real.spec.ts`
- This service-facing report.

Git: four modified frontend files and this new untracked report; nothing staged, committed or pushed. No local databases, logs, credentials or test artifacts were added to tracking.

## Remaining issues

None for this phase. Existing lint warnings are unchanged. This result does not retroactively claim a new real-model production acceptance for earlier OCR phases.

## Final decision

**Phase J.UI.9d-fix4: COMPLETE.** Valid proposals apply directly, remain editable, and retain all validation and local/saved/formal state boundaries.
