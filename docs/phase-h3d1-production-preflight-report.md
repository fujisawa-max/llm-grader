# H.3-D.1 Production Preflight — Teacher Clarification

Status: READY for the selected question only; actual grading NOT EXECUTED.

The two criteria use machine-safe IDs criterion_1 and criterion_2, each with
allowed scores 0 and 5 only. Total: 10. Descriptions and source evidence are
unchanged. TEACHER_EDITED provenance retains each complete original criterion
and the old/new ID mapping.

The existing approval workflow marks version 1 superseded (status only), retaining
its content, approval information and history. Version 2 is APPROVED. No schema
migration was performed. The initial attempt to retain two approved rows was
rolled back by the existing unique-current-approved constraint.

New RubricVersion: `220553e1-d52e-4083-8fb8-cd64f4f14414`
Rubric entry SHA: `95d5ffdb78544568f74a63466bbeeeafa770f07cb0db3cb9e0e5f2a910b8fbd1`
Bundle SHA: `1113ef411508e32abb55e72d3d037a01c764e47345ef2d9f6131f01a906b31ab`

Question, ModelAnswer, selected reconstruction version 2 and source PNG are
unchanged. No GradingJob or runtime was created; all model calls, score and
feedback generation are zero.

GradingInputAssembler.execution_preview now invokes the same validate_bundle and
execution_rubric functions used by the production worker. API preview and
create_execution_job both use this entry point; neither constructs a separate
semantic bundle. Invalid IDs, absent levels, invalid or duplicate allowed scores,
criterion totals and max-point mismatches block execution before job creation.
Mapping-only readiness is distinct from production execution readiness.

The selected PNG path was tested against job snapshot equality using isolated
fixtures; no production job was created. Generation/approval normalization now
uses machine-safe criterion IDs for new drafts.

Current preview: artifacts/h3d1-preflight/preview.json
Audit: artifacts/h3d1-preflight/report.json

Other questions have not been assigned new partial-credit rules and are not
asserted production-ready by this report. A fresh hash check and explicit user
authorization remain required before H.3-D.1 actual grading.

Validation: unittest 245 OK; pytest 263 passed (8955 warnings); Ruff clean.
Frontend unchanged.
