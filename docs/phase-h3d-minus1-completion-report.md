# Phase H.3-D.-1 Completion Report

## 1. Scope and environment

The eight supplied PNGs were registered as immutable real student-answer
source images in PostgreSQL `grader`. The registration path is
`StudentSubmissionImportService`; no migration was required. Source metadata
not represented by the existing `TestMaterial` columns is retained in
append-only `DomainEvent` provenance records.

No OCR, answer extraction, reconstruction, grading, or runtime was started.

## 2. Authoritative Tests

| Sample | Test ID |
|---|---|
| sampleQ1 | `70a63c23-f1b1-46b7-852c-046148b6f451` |
| sampleQ2 | `9fc4f834-a50e-423f-b0cf-31a977c1f891` |
| sampleQ3 | `8df4ed72-9297-4082-bb21-1fdb6c500557` |
| sampleQ4 | `e14aeeb5-924c-4c72-b2a2-583f1be9f48e` |

## 3. Student identity

Two Student records were created in the common authoritative course offering:

- `s1` → `35da0999-dcd9-44f3-be04-240e4fb10007`
- `s2` → `b304225c-88bf-4c5a-8b79-87997ce3e7a9`

Each identity is reused across all four Tests. No duplicate Student was created
on the second import.

## 4. Source registration

All eight files were readable PNGs, decoded successfully, and stored with the
following source SHA-256 values:

| File | Test | Student | SHA-256 | Dimensions | Bytes |
|---|---|---|---|---:|---:|
| `sampleQ1_answerSheet_s1.png` | Q1 | s1 | `aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba` | 4868×6926 | 566060 |
| `sampleQ1_answerSheet_s2.png` | Q1 | s2 | `afe9071af34b9a63fb878300307106009c2e7765d5d76461d57dea9a0060522c` | 4868×6926 | 408674 |
| `sampleQ2_answerSheet_s1.png` | Q2 | s1 | `cb611c52c19cb5e8cd2ee62d30bbee33309df9a665371717b60a545e1c882aa1` | 4875×6901 | 231910 |
| `sampleQ2_answerSheet_s2.png` | Q2 | s2 | `368924c9c885641c6e7dc73388a65f17f6f84acaefcaadd5751b3618b87d7fef` | 4859×6877 | 175158 |
| `sampleQ3_answerSheet_s1.png` | Q3 | s1 | `dbc61ce815682a1095bfcbd1966b7da76a56dff6ee4bdf036c8fd7512e8a07be` | 4826×6867 | 279774 |
| `sampleQ3_answerSheet_s2.png` | Q3 | s2 | `da78ae44ae3cdeea655ccc8fcd2a55a973ed3c3d437519c5370c1b815de93003` | 4810×6843 | 270483 |
| `sampleQ4_answerSheet_s1.png` | Q4 | s1 | `2885b04b93af4415dbbdfa3554ea85e707c9325892b166ee75427dcbab15900e` | 4833×6892 | 258598 |
| `sampleQ4_answerSheet_s2.png` | Q4 | s2 | `dd89f67075824aff671081c57916f25e21093b92cbf9e66d3d46fe5bd823c9f8` | 4825×6817 | 251250 |

Original bytes and registered artifact copies have matching SHA-256 values.
The API-facing storage references are relative artifact references; absolute
filesystem paths are not exposed.

## 5. Submission registration

| Sample | s1 Submission ID | s2 Submission ID | Count |
|---|---|---|---:|
| sampleQ1 | `fcf9d128-4dbb-4aee-b49b-1c715fdcfd16` | `086dbff3-2bd0-4da2-8220-75ef8c64db32` | 2 |
| sampleQ2 | `cf796992-140d-4379-8b3d-9e304a9d9e7a` | `58b55168-2750-45b1-8cc4-91ebc86da5dd` | 2 |
| sampleQ3 | `9a98190f-e5cf-4704-81d3-1cfc03658e7c` | `2406f098-a6fe-472d-bd53-a21586db3e8d` | 2 |
| sampleQ4 | `82355f70-b0f3-4534-8ec2-d66802722776` | `a3f18d80-78a7-41b1-9b07-9db3fe3056e6` | 2 |

All eight submissions have status `REGISTERED_SOURCE`, classification
`REAL`, and source type `image/png`. A second identical import reused all
eight materials and submissions: zero new Students and zero new
StudentSubmissions.

## 6. H.3-D.0 candidate recheck

Target question:

- Question ID: `8a2a7955-2347-4c67-8581-f800721ec558`
- Stable key: `review-48e6195a-5d0-q3.1`
- max_points: `10`

| Candidate | Submission ID | Classification | Mapping | Reconstruction | Blocker |
|---|---|---|---|---|---|
| s1 | `fcf9d128-4dbb-4aee-b49b-1c715fdcfd16` | REAL | NOT_YET_EXTRACTED | NOT_STARTED | `ANSWER_EXTRACTION_NOT_STARTED` |
| s2 | `086dbff3-2bd0-4da2-8220-75ef8c64db32` | REAL | NOT_YET_EXTRACTED | NOT_STARTED | `ANSWER_EXTRACTION_NOT_STARTED` |

The two candidates are visible without fabricating question-level answers.
Neither was selected automatically.

## 7. Safety and mutation audit

- Question-side readiness remained unchanged: Q1 6/6, Q2 4/4, Q3 3/3, Q4 4/4.
- TestQuestion, Confirmation, Correction, ModelAnswer, RubricVersion, and question assets are unchanged.
- Question-level StudentAnswer extraction: 0.
- Reconstruction records for the eight submissions: 0.
- Ricoh calls: 0.
- Uni-MuMER calls: 0.
- Ornith Reconstruction calls: 0.
- Ornith Grading calls: 0.
- RuntimeManager starts: 0.
- New GradingJob records: 0.
- Target sample Tests have no GradingJob records.

Machine-readable audit: [completion-audit.json](/opt/llm-scoring/artifacts/h3d-minus1/completion-audit.json).

## 8. Validation

- `python -m unittest`: 242 tests, OK.
- `python -m pytest -q`: 260 passed.
- `ruff check`: passed.
- Registration-specific tests: 2 passed.

## 9. Final status

**Phase H.3-D.-1: COMPLETE**

The next step is H.3-D.0 candidate selection. Teacher/User must explicitly
choose `s1` or `s2`; no extraction, reconstruction, preview, or grading is
started by this phase.
