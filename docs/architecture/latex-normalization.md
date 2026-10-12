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

## Draft review state and runtime diagnostics

The review separates three sources:

- **登録済み模範解答**: the current formal ModelAnswer version, read-only and collapsed.
- **保存済み下書き模範解答**: the last server draft revision, collapsed; initial extraction counts as a saved revision.
- **編集中の下書き**: the editable browser state with its own live preview.

An unsaved edit changes only the third source. Draft save updates the second and
keeps the formal version unchanged. Registration creates the formal version and
returns to the normal editor. Reopening/reloading the draft reads the persisted
revision. Original semantic groups are separately labeled and are not the live
editor preview.

The API startup entrypoint enables standard logging. Normalization logs request
context/character count, profile, ensure start, ready, inference start and result
status; it does not log the text, model response or tokens. Invalid requests log
only field locations. Runtime errors have separate codes:
`latex_runtime_unavailable`, `latex_runtime_start_failed`,
`latex_runtime_start_timeout`, `latex_inference_timeout`,
`latex_inference_failed`, `latex_invalid_response`. Validation rejection remains
an HTTP 200 proposal with `status=rejected`, and cannot be applied.

If an error happens immediately with no ensure log, first inspect the browser
POST status and response `error.code`: 404 may indicate a stale API deployment,
401/403 authentication, and 422 invalid input (including the 12,000-character
limit). A reachable manager health endpoint does not prove the application POST
was accepted. Stopped is normal for lazy startup; do not manually start a model
just to hide a missing application request.

Default cold-start budgets are unchanged: browser fetch has no explicit abort
limit, Next proxy 900 seconds, API manager ensure 330 seconds, managed profile
startup 300 seconds, and inference 300 seconds. `scoring.api.server` uses
`LLM_GRADER_RUNTIME_START_TIMEOUT_SECONDS` for ensure; the profile controls model
startup and inference limits. API-to-manager ordinary calls use 120 seconds.

## Generic text-tool authorization

Text tools require an authenticated `teacher` or `admin` session (the existing
`STAFF_ROLES`). They do not resolve Test/Question/Course ownership from the URL:
the endpoint formats supplied text and does not load or mutate domain resources.
Their dedicated staff-only dependency retains the standard authenticated user
context. Student and anonymous requests are rejected before the handler/runtime.
Question review/import and other resource APIs retain domain-path authorization.

A prior deployment passed the text-tool URL through `authorize_domain_path`,
which rejects an unrecognized resource path with `RESOURCE_NOT_FOUND` for
teachers. Admin bypasses that resource guard, so admin-only runtime/browser
fixtures failed to detect the problem. Tests now cover actual teacher-owned
review data and student sessions in addition to admin sessions.

The UI prioritizes structured error codes: `RESOURCE_NOT_FOUND` means a missing
resource, not a missing API route. Only a standard `Not Found` response (or the
API's equivalent `http_error`/`Not Found`) is labeled as an absent API. Unexplained
404 responses do not assert that the route is missing.
