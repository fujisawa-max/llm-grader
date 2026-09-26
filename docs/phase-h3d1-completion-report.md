# Phase H.3-D.1 Completion Report

## Preflight

Current bundle SHA equals authorized SHA: YES.
`1113ef411508e32abb55e72d3d037a01c764e47345ef2d9f6131f01a906b31ab`
Target Test: 70a63c23-f1b1-46b7-852c-046148b6f451
Question: 8a2a7955-2347-4c67-8581-f800721ec558
Submission: fcf9d128-4dbb-4aee-b49b-1c715fdcfd16

## GradingJob and snapshot

Job ID: `c0060e38-f02e-4fd0-a309-a9f051ac0ae2`
Item ID: `053bba04-c030-4a0f-b6df-740d0ae3ced5`
Snapshot SHA: `1d10a77d8cdcb436d497644692edd4b8a6ff3d3b3638e42480aebeaa4a8edba1`
Exactly one item in one job, production JobWorker → GradingExecutionRunner → RuntimeManager → Ornith → production validator → PostgreSQL.
The worker used the sealed snapshot, not current Question/Answer/Rubric resolution.

## Teacher Review

Student Answer:
入力と、その入力に対する正しい答えである教師データをもとに学習を行う機械学習である。学習では誤差が小さくなるように修正を行う。

ModelAnswer:
教師付き学習とは、入力データと正解を示すラベルの組を用いて、未知の入力に対する答えを
予測できるよう学習する方法である。予測と正解の誤差が小さくなるようモデルを調整し、画
像の分類や数値の予測などに利用される。

Approved RubricVersion: 220553e1-d52e-4083-8fb8-cd64f4f14414
Each criterion permits 0 or 5 only; no intermediate points.

### criterion_1: 5 / 5

Rubric: 入力データと対応する正解ラベルがあることを説明できている。

Evidence: 入力と、その入力に対する正しい答えである教師データをもとに学習を行う機械学習である。

Feedback: 入力データと対応する正解ラベル（教師データ）があることを説明できている。

### criterion_2: 5 / 5

Rubric: 予測と正解の誤差が小さくなるようにモデルを学習・調整することを説明できている。

Evidence: 学習では誤差が小さくなるように修正を行う。

Feedback: 予測と正解の誤差が小さくなるようにモデルを学習・調整することを説明できている。

Final score: **10 / 10**.
Production structured validation: PASS. No clamping or score adjustment.
Model needs_review: false. Human Teacher Review: REQUIRED for this first real validation.

## Persistence

Raw response, exact request, immutable input snapshot, normalized grading result and file hashes are stored in:
`artifacts/h3d1-actual/run/submissions/s1-70a63c23-aa04ff31e339ec51/questions/8a2a7955-2347-4c67-8581-f800721ec558`

Raw response SHA: `740ffa785c25a326acc3dd787f4bd531cd0a250252f78f9d68c82cda3ff48f2a`
Normalized result SHA: `176461cb8aa705f04ad6c4a66503ecb015f5e3d1124b2e44c8e1f5987ceb2b7a`
PostgreSQL item score, criterion results, feedback and manifest/provenance persisted.

## Model and runtime audit

Model: ornith15-35b-q4km; prompt: selected-answer-grading.v1.
Generation config: {"temperature": 0, "seed": 42, "top_k": 40, "top_p": 0.95, "min_p": 0.05, "repeat_penalty": 1.0, "max_output_tokens": 4096}
Ricoh: 0; Uni-MuMER: 0; Ornith Reconstruction: 0; Ornith Grading: 1.
Owned runtime stopped; host process check shows no llama-server remains.
Port 3000 was not touched.

## Resume and mutation audit

Completed worker run_once returned None. Completed artifact resume validated and reused existing results; all result file hashes remained identical, one raw response total.
Question, ModelAnswer, Rubric, Reconstruction, StudentSubmission and source-material rows unchanged by before/after table hashes. Source PNG SHA unchanged: `aa04ff31e339ec51e5f4730eda080e6b4c23dcc72cbca60bf30c08c0e508d3ba`.

## Regression

unittest: 245 tests OK.
pytest: 263 passed (warnings remain, no failures).
Ruff: clean.
Frontend unchanged.

## Final status

H.3-D.1: COMPLETE.
Teacher Review: REQUIRED.
No other submission/question was graded.
