# Model answer PDF extraction

The Teacher action **解析して模範解答を確認** now runs native PDF extraction,
spatial assignment, semantic classification and deterministic reconstruction
before opening review. No OCR, question creation or rubric approval occurs.

## Assignment and source evidence

Each native line keeps its original text, native span references, stable source
ID, SHA-256, page, PDF-point rectangle, center and reading order. Question
headings in the unique question-sheet PDF define regions ending at the next
sibling heading, parent boundary or page bottom. Compatible page sizes are
required. Native model-answer headings provide fallback anchors. Existing
question source element references can also provide anchors. Children are
clipped to their parent's region. Separate columns and competing anchors are
handled independently; ambiguous assignments require Teacher mapping.

An unknown heading ends the previous region. Text above the first heading,
missing geometry and unsupported page continuation never default to the last
question. Repeated headings on the next page establish continuation; an open
question on the previous page alone is insufficient evidence. Significant
layout changes may therefore need manual mapping.

## Classification and fallback

The existing `ornith_rubric_draft` profile assigns only source IDs, categories
and confidence. It cannot move a segment to another question or generate saved
answer prose. Requests include rectangles, relative positions, question/parent
context, spatial assignment and visual difference evidence. Small batches keep
structured output within the profile's 512-token limit. Thinking remains disabled
and the runtime stays resident for reuse. Automatic classification shares a
ten-minute request budget across entries; remaining HTTP inference time is
bounded by that budget. Entries beyond the budget retain mechanical review.

Only `model_answer` segments enter the primary reconstructed text. Alternatives,
rubric candidates, notes, excluded question text and uncertain segments remain
separate in review metadata. Rubrics are never automatically approved.
Unknown/duplicate/omitted IDs, invalid JSON, timeout and unavailable runtimes
fall back to geometry plus the existing visual-difference/text-removal pipeline.
Original source segments remain available, including when the primary text is
empty. Low-confidence classification requires Teacher review before registration.

Review shows classification status and spatial evidence. **意味分類を再実行**
is a secondary action near the top. Teacher mapping, text and acknowledged
category edits take precedence over automatic results. Source text and initial
geometry remain in metadata for audit; editable text is recorded separately.
Existing ModelAnswer versioning and revision conflict checks are unchanged.

## Validation

Run isolated integration (production frontend, FastAPI, SQLite, managed test
process and Chromium; no actual LLM inference):

```sh
PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers python -m tests.run_runtime_browser_e2e
```

On the NVIDIA server, use a synthetic test, not formal Q5:

1. Register matching-layout question and model-answer PDFs containing Q1/Q2/Q3.
2. Click analysis once. Review should show completed classification without a
   separate classification action. Inspect the import POST response (201).
3. Check answers near each heading map to that question, with original PDF text.
4. Check alternatives/rubric/notes are separate; inspect spatial source details.
5. Record the runtime PID and VRAM usage through the runtime API and `nvidia-smi`.
6. Analyze again and verify the same runtime PID, without another model load.
7. Edit, save, reload and register; check retained source and classification metadata.

Actual Ornith classification quality and GPU behavior require this follow-up;
synthetic tests verify wiring and invariants rather than real model accuracy.
