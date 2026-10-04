# Teacher text LaTeX formatting

The answer/rubric review and normal editor offer **LLMでLaTeX化**. Nothing runs on
load, resume, save, registration or classification rerun. A proposal never saves
content: teachers inspect the source, proposed text and Markdown/KaTeX preview,
then apply or cancel. Draft save and formal registration retain their existing
meanings. Rubric points are not changed.

`POST /api/v1/text-tools/latex-normalize` is staff-authenticated and accepts
`text` (1–12,000 characters), `context_type` (`model_answer`, `rubric`, `question`,
`sample_answer`, `generic`) and an optional context label (up to 500 characters).
The shared `LatexNormalizationControl` and `textTools` client can be reused in
other teacher editors; Question editing is not enabled by this change.

The service reuses the configured semantic-classification manager/profile
(default `ornith_rubric_draft`), model, trusted LocalClient transport and timeouts.
It lazily starts and reuses the runtime; it never stops a runtime after a request.
No extra model server or fixed model name is introduced.

Responses have `safe`, `ambiguous`, `no_change` or `rejected` status, original and
normalized text, warnings, changes, confidence and model/profile identifiers.
Strict JSON validation rejects malformed output. Ordered content tokens retain
numeric spelling, signs, percentages, identifiers and prose/punctuation;
division counts and explicit parenthesized arithmetic are checked separately.
Missing or added content rejects a proposal. Ambiguous precedence, unclear
multiline structure and low-confidence proposals require explicit teacher
acknowledgment. Failed KaTeX rendering or stale source text disables apply.

These conservative checks are not a mathematical equivalence proof. Unsupported
LaTeX command conversions may be rejected. A native PDF fragment missing part of
a formula must be corrected by the teacher, rather than completed by the model.
For example, `0.800` is not silently changed to `0.8`, and `24 / 30 = 0.7` must
not be corrected to `0.8`.

Review applications retain original PDF provenance and record normalization
metadata in teacher corrections/rubric edit provenance. Normal editors use their
existing versioned save paths. The output is plain text; existing Markdown HTML
filtering and KaTeX `trust: false` rendering remain in place. Runtime, parse and
validation failures preserve the editor contents and allow retry.
