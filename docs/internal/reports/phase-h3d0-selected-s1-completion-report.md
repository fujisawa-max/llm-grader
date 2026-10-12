# Phase H.3-D.0 Selected s1 Completion Report

## Target

- Test: `70a63c23-f1b1-46b7-852c-046148b6f451`
- Question: `8a2a7955-2347-4c67-8581-f800721ec558`
- Submission: `fcf9d128-4dbb-4aee-b49b-1c715fdcfd16`
- Source SHA-256: `aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba`

## Teacher edit

The original reconstruction remains version 1 and immutable.  Teacher edit
revision version 2 is selected:

- Reconstruction: `ddc938bd-f4ce-4b67-a99d-2b8b458f30e9`
- Status: `COMPLETE`
- SHA-256: `872b5248746b5a7f51726eab51394f7a76270fa9ea1961d3212bf13cf3b86c2d`
- Provenance: `TEACHER_EDITED`
- Base reconstruction: `4476a8b1-3aa9-454e-833a-8c5bd1c36080`, version 1

The only answer-text edit is `正しい出力` → `正しい答え`.

## H.2-G grading-input preview

- State: `READY`
- Student answer source: `RECONSTRUCTED_FROM_DOCUMENT`
- Effective Context SHA-256: `87a0f63103b8159a8e395f5077efdcc6c1d8db84b063f2d7a0663c74c021f8bf`
- ModelAnswer: `6479d287-0c79-490e-9c4b-4d15adb2589b`
- Approved RubricVersion: `ffbf23b3-80a6-4856-9005-e814752d41e2`
- Max points: `10`
- GradingInputBundle SHA-256: `24bfca68abf14ced700e9a0ef41fca217d9b6cb0f27dc690ccdca5b74316d49c`
- Blockers: none

Preview artifact: `artifacts/h3d0-reconstruction/fcf9d128-4dbb-4aee-b49b-1c715fdcfd16/grading-input-preview.json`.

## Safety and audit

- Original source SHA before/after: unchanged.
- Original reconstruction and raw model response: preserved.
- ModelAnswer/Rubric/max_points were not sent to the reconstruction runtime.
- GradingJob: `0`
- Ornith Grading: `0`
- Score/feedback: not generated.

## Validation

- `python -m unittest`: 242 OK
- `python -m pytest -q`: 260 passed
- `ruff check`: clean

H.3-D.0 is ready for the next phase, H.3-D.1 actual grading, but actual grading
has not been started.
