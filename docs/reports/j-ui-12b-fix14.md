# J.UI.12b-fix14 — Recovery Noise & Split-Child Diagram Scope

## Baseline

- HEAD: `7a04d73365cc8ee8f1bcaaa32290762526e4578f` (fix13)
- Initial working tree: clean
- Production database, deployed Q5, and formal production data were not accessed.
- No schema migration is planned.

## Findings and changes

### Unassigned Rubric recovery candidates

Before this change, the same global recovery list was rendered inside the currently selected Question's Rubric section. Switching Questions therefore repeated a long list of unassigned candidate text even though those candidates were not accepted for any Question. A second inline candidate projection also surfaced Rubric-like classifier segments alongside each Answer entry.

The full recovery list now appears once in a collapsed, target-independent recovery panel. It remains in `domains.recovery.rubric_candidates`; this change does not delete, assign, promote, or dismiss candidates. Regular Question Rubric sections show only entries with accepted Rubric rows. Explicit target selection, promotion, and ignore actions remain available in the recovery panel. The analysis completion notification reports the count of active unassigned Rubric candidates for the analyzed role and source binding; Question switching does not create additional notifications.

### Split-child diagram scope

The diagram adapter used only the selected region as an allowed crop boundary. A child-owned candidate whose rendered crop padding extended slightly beyond the child's source range was rejected, even when the expanded crop remained within its parent major Question. The parent fallback also treated descendants as sibling blockers, which could hide a valid major-level diagram after a split.

Candidate discovery remains limited to the requested Question's own source region. Crop validation now accepts the selected region or its ancestors as a boundary, and the parent fallback excludes descendants of that parent from its sibling blockers. Unrelated major Question branches remain blocked. The UI's assignment guard accepts either the selected stable authoring key or its formal source alias, while still rejecting a candidate that matches neither. No Test-wide scope was added.

## Verification progress

- Targeted backend: `tests/test_diagram_regions.py` and `tests/test_authoring_diagrams.py` — 61 passed, 1 existing Starlette deprecation warning.
- Full backend: `python -m pytest -q` — 932 passed, 1 skipped, 22 existing warnings.
- Focused production-like Chromium: 10 passed across Rubric split/recovery, Question split/diagram discovery/reuse, and legacy Rubric registration. The browser harness reported grading jobs = 0.
- Full production-like Chromium: 63 passed. This included the 24-candidate recovery regression, Q3 split discovery and sibling reuse, Save/reload/Back/resume endurance, OCR, diagrams, and the legacy suites. The browser harness reported grading jobs = 0.
- TypeScript: `npm run typecheck` — passed.
- ESLint: `npm run lint` — 0 errors, 19 existing warnings.
- Ruff: `ruff check src/scoring/diagram_sources.py tests/test_diagram_regions.py tests/run_runtime_browser_e2e.py` — passed.
- Production Next build: passed through the full browser harness. Existing Autoprefixer/Next warnings remain.
- `git diff --check` — passed.
- No database migration was added. Production acceptance was not run.

### Browser fixture correction

The first full run passed 62/63: the additional formal recovery targets made a separate legacy registration scenario correctly reject its incomplete fixture (HTTP 422). The focused rerun also showed the recovery test needed to avoid introducing gradable formal Questions without matching Rubrics. The fixture now uses non-gradable extra targets; the legacy flow retains its original gradable Question. The focused 10-case group and the full 63-case suite then passed. This was test-fixture isolation, not a product behavior change.

## Safety and scope

- No formal Question, ModelAnswer, or approved Rubric was published or intentionally modified by the application changes.
- Browser harness grading-job invariant: 0 at the end of both focused and full runs.
- No commit, push, or deployment was performed.
- J.UI.12c publication and Question drag-and-drop remain out of scope.

## Final status

**READY_FOR_PRODUCTION_VALIDATION** — both requested fixes and automated verification are complete; deployed teacher acceptance remains outstanding.
