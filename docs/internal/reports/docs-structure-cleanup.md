# Documentation structure cleanup

## Result

Completed, documentation only. Previously product, operations, design and historical engineering records shared the same entry points. Documents were inspected by purpose; no application behavior changed.

## Structure / moves

- `docs/README.md`: concise entry point for four audiences.
- `docs/user/`: existing CLI sample (`BasicMathSmallExam1.md`) and index.
- `docs/admin/`: six deployment/runtime/backup/incident/cutover documents and index.
- `docs/architecture/`: initial architecture, coordinate contract, extraction and LaTeX API/diagnostic references, plus index.
- `docs/internal/reports/`: all 53 former report-directory records, other historical phase records, OCR validation and server investigation. Reports remain independent and tracked; historical conclusions were not rewritten.
- `docs/internal/README.md`: internal-record warning and exception explanation.
- Total existing tracked documents moved with `git mv`: **90**.
- `docs/phase-h3c1-teacher-review-package.md` remains unchanged because its generating script fixes this output path. The script is unchanged; changing that output is out of scope.
- Existing ignored local specification and Codex-only development documentation remain untouched and untracked by Git.

## References / gaps

Repository README and document path references/relative Markdown links were updated for moves. Operational commands were not redesigned. No executable dependency on the moved paths was found; the only identified fixed-output dependency is the preserved exception above.

A comprehensive current teacher Web workflow manual is missing. Existing CLI sample and initial architecture retain their dated limitations; historical reports were not converted into a guessed manual. Operational runbooks and setup references remain surfaced through the admin index.

## Validation

- Old report-directory references: none in repository documentation (the exact-status appendix records old rename paths as historical Git metadata, not links).
- Relative Markdown file/directory links checked in tracked documentation and repository README: no missing targets before or after moves. External URLs and anchor IDs were not network-validated.
- All 90 moved source documents preserved; only path/link references updated. Generated exception unchanged.
- Application/source, tests, migrations, configuration, dependencies, CI and scripts unchanged. No DB or production operations; no expensive test suites run.
- `git diff --check` and `git diff --cached --check`: pass.
- No commit/push. Git moves are staged by `git mv`; subsequent documentation link edits and new indexes/report remain unstaged/untracked.

## Exact git status

```text
 M README.md
R  docs/operations/backup-restore.md -> docs/admin/backup-restore.md
R  docs/operations/deployment-checklist.md -> docs/admin/deployment-checklist.md
R  docs/operations/incident-response.md -> docs/admin/incident-response.md
R  docs/operations/production-runbook.md -> docs/admin/production-runbook.md
R  docs/operations/q5-postgres-cutover.md -> docs/admin/q5-postgres-cutover.md
R  docs/operations/runtime-deployment.md -> docs/admin/runtime-deployment.md
R  docs/architecture.md -> docs/architecture/architecture.md
R  docs/operations/latex-normalization.md -> docs/architecture/latex-normalization.md
R  docs/operations/model-answer-extraction.md -> docs/architecture/model-answer-extraction.md
R  docs/phase-h3a2-coordinate-contract.md -> docs/architecture/phase-h3a2-coordinate-contract.md
R  docs/dual-ocr-validation.md -> docs/internal/reports/dual-ocr-validation.md
R  docs/reports/j-deploy-1-docker-compose-readiness.md -> docs/internal/reports/j-deploy-1-docker-compose-readiness.md
RM docs/reports/j-mig-q5-integration.md -> docs/internal/reports/j-mig-q5-integration.md
R  docs/reports/j-ui-10-diagram-region-extraction-review.md -> docs/internal/reports/j-ui-10-diagram-region-extraction-review.md
RM docs/reports/j-ui-10a-diagram-review-api-persistence-ui.md -> docs/internal/reports/j-ui-10a-diagram-review-api-persistence-ui.md
R  docs/reports/j-ui-10b-diagram-only-manual-model-answers.md -> docs/internal/reports/j-ui-10b-diagram-only-manual-model-answers.md
R  docs/reports/j-ui-10c-parent-shared-diagram-assignment.md -> docs/internal/reports/j-ui-10c-parent-shared-diagram-assignment.md
R  docs/reports/j-ui-10d-teacher-confirmed-diagram-trust.md -> docs/internal/reports/j-ui-10d-teacher-confirmed-diagram-trust.md
R  docs/reports/j-ui-10e-diagram-acceptance-reuse.md -> docs/internal/reports/j-ui-10e-diagram-acceptance-reuse.md
R  docs/reports/j-ui-12-authoring-foundation.md -> docs/internal/reports/j-ui-12-authoring-foundation.md
RM docs/reports/j-ui-12b-fix1-authoring-entry-source-layout.md -> docs/internal/reports/j-ui-12b-fix1-authoring-entry-source-layout.md
R  docs/reports/j-ui-12b-fix10-shared-source-tooltip-diagram-reuse.md -> docs/internal/reports/j-ui-12b-fix10-shared-source-tooltip-diagram-reuse.md
R  docs/reports/j-ui-12b-fix11-proposal-dialog.md -> docs/internal/reports/j-ui-12b-fix11-proposal-dialog.md
R  docs/reports/j-ui-12b-fix11-rubric-split-section-ownership.md -> docs/internal/reports/j-ui-12b-fix11-rubric-split-section-ownership.md
RM docs/reports/j-ui-12b-fix12.md -> docs/internal/reports/j-ui-12b-fix12.md
R  docs/reports/j-ui-12b-fix13.md -> docs/internal/reports/j-ui-12b-fix13.md
R  docs/reports/j-ui-12b-fix14.md -> docs/internal/reports/j-ui-12b-fix14.md
RM docs/reports/j-ui-12b-fix14a.md -> docs/internal/reports/j-ui-12b-fix14a.md
RM docs/reports/j-ui-12b-fix14b.md -> docs/internal/reports/j-ui-12b-fix14b.md
RM docs/reports/j-ui-12b-fix15.md -> docs/internal/reports/j-ui-12b-fix15.md
RM docs/reports/j-ui-12b-fix15a.md -> docs/internal/reports/j-ui-12b-fix15a.md
RM docs/reports/j-ui-12b-fix15b.md -> docs/internal/reports/j-ui-12b-fix15b.md
RM docs/reports/j-ui-12b-fix15c.md -> docs/internal/reports/j-ui-12b-fix15c.md
RM docs/reports/j-ui-12b-fix15d.md -> docs/internal/reports/j-ui-12b-fix15d.md
RM docs/reports/j-ui-12b-fix15e.md -> docs/internal/reports/j-ui-12b-fix15e.md
RM docs/reports/j-ui-12b-fix2-preview-materials.md -> docs/internal/reports/j-ui-12b-fix2-preview-materials.md
RM docs/reports/j-ui-12b-fix3-analysis-access.md -> docs/internal/reports/j-ui-12b-fix3-analysis-access.md
RM docs/reports/j-ui-12b-fix4-authoring-modes-materials.md -> docs/internal/reports/j-ui-12b-fix4-authoring-modes-materials.md
RM docs/reports/j-ui-12b-fix5-question-view-preview.md -> docs/internal/reports/j-ui-12b-fix5-question-view-preview.md
R  docs/reports/j-ui-12b-fix6-split-analysis-merge.md -> docs/internal/reports/j-ui-12b-fix6-split-analysis-merge.md
RM docs/reports/j-ui-12b-fix7-save-resume-readiness.md -> docs/internal/reports/j-ui-12b-fix7-save-resume-readiness.md
R  docs/reports/j-ui-12b-fix8-analysis-messaging-notifications.md -> docs/internal/reports/j-ui-12b-fix8-analysis-messaging-notifications.md
R  docs/reports/j-ui-12b-fix9-quiet-readiness-split-separation.md -> docs/internal/reports/j-ui-12b-fix9-quiet-readiness-split-separation.md
RM docs/reports/j-ui-12b-harden-2.md -> docs/internal/reports/j-ui-12b-harden-2.md
R  docs/reports/j-ui-12b-overnight-authoring-hardening.md -> docs/internal/reports/j-ui-12b-overnight-authoring-hardening.md
RM docs/reports/j-ui-12b-source-backed-authoring.md -> docs/internal/reports/j-ui-12b-source-backed-authoring.md
RM docs/reports/j-ui-12c.md -> docs/internal/reports/j-ui-12c.md
RM docs/reports/j-ui-12d.md -> docs/internal/reports/j-ui-12d.md
RM docs/reports/j-ui-12e-fix1.md -> docs/internal/reports/j-ui-12e-fix1.md
RM docs/reports/j-ui-12e.md -> docs/internal/reports/j-ui-12e.md
RM docs/reports/j-ui-9d-fix1-geometry-vision-math-grouping.md -> docs/internal/reports/j-ui-9d-fix1-geometry-vision-math-grouping.md
R  docs/reports/j-ui-9d-fix2-unimumer-candidate-validation.md -> docs/internal/reports/j-ui-9d-fix2-unimumer-candidate-validation.md
R  docs/reports/j-ui-9d-fix3-deterministic-ornith-formatting.md -> docs/internal/reports/j-ui-9d-fix3-deterministic-ornith-formatting.md
R  docs/reports/j-ui-9d-fix4-math-ocr-apply-ux.md -> docs/internal/reports/j-ui-9d-fix4-math-ocr-apply-ux.md
R  docs/reports/j-ui-9d-source-aware-math-ocr.md -> docs/internal/reports/j-ui-9d-source-aware-math-ocr.md
R  docs/reports/j-ui-9e-fix1-unified-question-review-split-provenance.md -> docs/internal/reports/j-ui-9e-fix1-unified-question-review-split-provenance.md
RM docs/reports/j-ui-9e-fix2-stable-question-text-editing.md -> docs/internal/reports/j-ui-9e-fix2-stable-question-text-editing.md
R  docs/reports/j-ui-9e-fix3-review-continuation-unresolved-navigation.md -> docs/internal/reports/j-ui-9e-fix3-review-continuation-unresolved-navigation.md
RM docs/reports/j-ui-9e-fix4-post-registration-next-step-guidance.md -> docs/internal/reports/j-ui-9e-fix4-post-registration-next-step-guidance.md
R  docs/reports/j-ui-9e-question-source-aware-math-ocr.md -> docs/internal/reports/j-ui-9e-question-source-aware-math-ocr.md
RM docs/reports/j-ui-9f-sticky-target-taller-pdf.md -> docs/internal/reports/j-ui-9f-sticky-target-taller-pdf.md
RM docs/reports/j-ui-9g-unified-review-workspace-layout.md -> docs/internal/reports/j-ui-9g-unified-review-workspace-layout.md
R  docs/reports/j-ui-admin-1a-validation.md -> docs/internal/reports/j-ui-admin-1a-validation.md
R  docs/reports/j-ui-admin-1b-setup-wizard.md -> docs/internal/reports/j-ui-admin-1b-setup-wizard.md
R  docs/phase-h2b-completion-report.md -> docs/internal/reports/phase-h2b-completion-report.md
R  docs/phase-h2b-real-draft-evaluation.md -> docs/internal/reports/phase-h2b-real-draft-evaluation.md
R  docs/phase-h2b1-completion-report.md -> docs/internal/reports/phase-h2b1-completion-report.md
R  docs/phase-h2c1-completion-report.md -> docs/internal/reports/phase-h2c1-completion-report.md
R  docs/phase-h2f-completion-report.md -> docs/internal/reports/phase-h2f-completion-report.md
R  docs/phase-h2g-completion-report.md -> docs/internal/reports/phase-h2g-completion-report.md
R  docs/phase-h2h-checkpoint.md -> docs/internal/reports/phase-h2h-checkpoint.md
RM docs/phase-h2h-completion-report.md -> docs/internal/reports/phase-h2h-completion-report.md
R  docs/phase-h3a-completion-report.md -> docs/internal/reports/phase-h3a-completion-report.md
R  docs/phase-h3a0-coordinate-normalization-report.md -> docs/internal/reports/phase-h3a0-coordinate-normalization-report.md
R  docs/phase-h3a1-runtime-smoke-report.md -> docs/internal/reports/phase-h3a1-runtime-smoke-report.md
R  docs/phase-h3a2-runtime-blocker-fix-report.md -> docs/internal/reports/phase-h3a2-runtime-blocker-fix-report.md
R  docs/phase-h3b-completion-report.md -> docs/internal/reports/phase-h3b-completion-report.md
RM docs/phase-h3c-readiness-report.md -> docs/internal/reports/phase-h3c-readiness-report.md
RM docs/phase-h3c1-completion-report.md -> docs/internal/reports/phase-h3c1-completion-report.md
R  docs/phase-h3c1-teacher-review-approval-completion-report.md -> docs/internal/reports/phase-h3c1-teacher-review-approval-completion-report.md
R  docs/phase-h3d-minus1-completion-report.md -> docs/internal/reports/phase-h3d-minus1-completion-report.md
R  docs/phase-h3d0-selected-s1-completion-report.md -> docs/internal/reports/phase-h3d0-selected-s1-completion-report.md
R  docs/phase-h3d1-completion-report.md -> docs/internal/reports/phase-h3d1-completion-report.md
R  docs/phase-h3d1-production-preflight-report.md -> docs/internal/reports/phase-h3d1-production-preflight-report.md
R  docs/phase-h3e0a-preflight-repair-report.md -> docs/internal/reports/phase-h3e0a-preflight-repair-report.md
R  docs/phase-h3e2-partial-credit-report.md -> docs/internal/reports/phase-h3e2-partial-credit-report.md
R  docs/phase-h3g0b-ricoh-diagnosis.md -> docs/internal/reports/phase-h3g0b-ricoh-diagnosis.md
R  docs/phase-h3h3g-artifact-repair-report.md -> docs/internal/reports/phase-h3h3g-artifact-repair-report.md
R  docs/server-settings.md -> docs/internal/reports/server-settings.md
R  docs/BasicMathSmallExam1.md -> docs/user/BasicMathSmallExam1.md
?? docs/README.md
?? docs/admin/README.md
?? docs/architecture/README.md
?? docs/internal/README.md
?? docs/internal/reports/docs-structure-cleanup.md
?? docs/user/README.md
```
