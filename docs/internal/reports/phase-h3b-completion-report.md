# Phase H.3-B Actual Grading Execution Validation Report

## 1. Starting architecture

H.2-G assemblerはbundleを生成済みでしたが、従来workerはOCR→再構成→採点を実行し、selected reconstructionを固定したStage 2実行は未接続でした。

## 2. Existing grading execution path

create_execution_job → GradingJob / GradingJobItem → JobWorker → GradingExecutionRunner → RuntimeManager grader → LocalClient → parse_response / validate_grade → JobRepository.sync_item_from_artifacts → PostgreSQL。従来CLIのOCR/reconstruction経路は維持し、H.3-Bはinput_stage=selected_reconstructionで明示します。

## 3. Files changed

src/scoring/grading_execution.py（新規）、grading_mapping.py、db/worker.py、db/repository.py、api/domain.py、tests/test_grading_execution.py（新規）、scripts/validate_h3b_grading.py（新規）、この報告書。frontend・RuntimeManager・座標変換コードは未変更。

## 4. Migration decision

なし。既存job/itemのmetadata JSON、runtime snapshot、artifactを使用。PostgreSQL headは0011_student_answer_recon。

## 5. Synthetic fixture

既存H.3-A.2 runtime validationの1問を再利用。Question:「計算した結果と考えを書いてください。」。Selected answer:「私は次のように計算しました。
2 + 2 = 5
これが私の答えです。」。ModelAnswer: 2 + 2 = 4。Rubric: 最終回答4なら1点、それ以外0点、部分点なし。max_points=1。grading前のfixture準備としてこのsynthetic questionの配点10→1とtest total10→1を設定し、模範解答/Rubricを新versionとして作成・承認しました。既存reconstructionや原画像は変更していません。

## 6. Identity mapping

- test_id: `930bf71c-f9cf-42d6-8d10-ec3a65633bc7`
- question_id: `80a8f584-7e61-40a2-aecf-0ccc5502ce88`
- submission_id: `20bc7950-f3de-48db-985f-8163ab810f31`
- reconstruction_id: `f624b7e6-1e81-4040-981f-e22eb019f401`
- model_answer_id: `b2c3a819-05e4-4776-b78e-4b7867c0b798`
- model_answer_version: `2`
- rubric_id: `810cff0f-ef72-4485-9c93-b67468829d11`
- stable_question_key: h3a2-q1
- rubric entry question_id: 80a8f584-7e61-40a2-aecf-0ccc5502ce88

## 7. Pre-grading readiness

Test-side、mapping-side、selected reconstruction COMPLETE、execution READYを検証。1問だけをsnapshot。未選択/REVIEW_REQUIRED/破損reconstruction、missing answer、未設定配点ではjob作成前に拒否します。

## 8. GradingInputBundle

- bundle: `43137b6dd121f815afbe7bc6c48b7a9dfddd42fd80021e739a4975ca5617d06a`
- context: `d003487404ab2bf69ee5f9e07266ab6e7c6e6a3dfb017ef373332c5f7263bf09`
- reconstruction: `7f32cb4f646ce8e0dcb338e1f664321c6b83443836762b3568c2fa7ac52d00f8`
- model_answer: `02dec8d8f6634da7cd0b33365d5eda3f4cfc0d5293f61e7171eb3a192107c71f`
- rubric_entry: `510dc67a461175b6d53bd5f06a64f927087747cc1ae5a85164f3250b76c0ecf4`
- source_answer: `b5582f062f578af64b15b2db3cb0e282639b1dac9a565976c7b5bd028b505f95`
- max_points: 1

## 9. Preview / Snapshot equivalence

実job作成直前のpreview bundleとsnapshot.bundleを全体比較し一致。question/context、reconstruction、ModelAnswer、Rubric entry、配点、assets（本fixtureは0件）が一致。

## 10. Job snapshot

Job: `ea07dea3-a1e1-4844-b5f1-985db5d7575c`

Item: `f49d5bd5-d644-4eb3-87be-5ed36ad86d1f`

Snapshot: `a3cb44472cf720b147b5713aaa62a464ce20e3b5c511d5db1925cda35e39a792`

job開始後はdomain current情報を再resolveせずsnapshotだけを使用。時刻/job ID/absolute asset pathsはsemantic snapshot hash対象外。

## 11. RuntimeManager

role=grader、model=ornith15-35b-q8（既存registryのOrnith-1.5-35B Q8_0）。dynamic port 18080。owned managed runtime。startup約32秒、health成功、推論約3.61秒、shutdown完了。RuntimeManagerのみがllama-serverを起動。既存workerへ構成済みmanagerを注入して実行しました。

## 12. Actual grading request

question_id、effective question text、selected answer transcript/ID/hash、reference_answer、対象rubric、bundle hash。legacy schema互換のocr fieldはpage ID→空objectだけで、Ricoh/UniのOCR本文を含みません。原答案を再解釈するmodel callはありません。temperature=0、seed=42、top_k=40、top_p=0.95、min_p=0.05、repeat_penalty=1、max_output_tokens=4096、context=8192、input=570 tokens、output=151 tokens、finish_reason=stop。

## 13. Prompt injection protection

system promptでstudent answerをuntrusted dataと明示。student contentはJSONの値としてuser messageにシリアライズ。引用符等でstructureが壊れないことをテスト。攻撃文に対するactual追加model smokeは実施していません。

## 14. Raw Ornith output

criteria=[{criterion_id: final-answer, score:0, max_score:1, evidence:[{page_id:answer-page,quote:2 + 2 = 5}], reason:最終回答が5であり、4ではないため0点。}]。needs_review=false、review_reasons=[]。raw response SHA: c2dfbbae27ebfd84b5dca8fd8df49720a19dbf89d98e065fb26163589c7e0628。raw保持、reasoning要求なし。

## 15. Parsed grading result

score=0、max_points=1、criterion final-answer=0/1、feedback=「最終回答が5であり、4ではないため0点。」、warnings/review_reasons=[]、schema=grading-result.v1。合計は既存validatorがcriterionの合計として計算。

## 16. Expected score comparison

Expected 0/1、Actual 0/1。PASS。モデルのscoreを書き換えたりclampしたりしていません。

## 17. Score validation

既存integer/discrete-level contractを維持。負値、overflow、NaN、Infinity、bool、model満点変更、明示totalとcriterion合計の不一致を拒否。小数配点を丸める処理はなし。

## 18. Rubric criterion validation

承認済みentryのID/points/levelsを使用。unknown/duplicate/missing criterion、許容点数外、根拠page不一致を拒否。levelsを生成・補完しません。

## 19. Persistence

PostgreSQL job/item completed。reconstruction hash、bundle/snapshot hash、result hash、feedback、model identity、runtime snapshot、prompt versionを保持。normalized file SHA: `b6a99c5bfab0f43e1ab7ef2584091482d7c72bab11b7792b16dbbaaf5f814796`。input/request/raw/normalizedのfile SHAをmanifestへ保存、manifest hashをitem metadataへ保存。

## 20. Score sync

既存JobRepository.sync_item_from_artifactsへselected-answer結果の厳格検証分岐を追加。通常workerが同じrepository入口からDB score/max/feedbackへ投影します。実DB score/max、read-only HTTP result、normalized artifactが0/1で一致。

## 21. Input immutability

grading前後のreconstruction全row、ModelAnswer、Rubric、原答案JSON SHAは一致。Question行も不変（監査helperのstr(1)対str(1.0)だけを同じ数値表現にして確認）。source page SHA=e1f26db12e18d87c7bc2f942cbaac2eb9bd2b19b588781f75694d0e0ca9d0e56。不変hash比較はartifacts/h3b-validation/report.json。fixture準備前の配点変更とgrading開始後の不変比較を区別しています。

## 22. Retry / Resume

失敗→retryは同じmetadata snapshot。完了jobはclaim不可。実completed runnerを空RuntimeManagerで再検証し、保存済みmanifest/resultを検証してmodel callなしで終了。repository再投影一致もrollback transactionで確認。

## 23. Snapshot immutability

unit testでjob作成後にQuestion本文、current ModelAnswer、Rubric、selected reconstructionを変更してもworker入力は元snapshotのままであることを確認。historical jobを書き換える処理なし。

## 24. Reproducibility

sampling/config/prompt/hashを固定。追加actual replayは未実施（要求どおりactual gradingは1回）。同一snapshot hashと完了checkpoint再利用をテスト。GPU再推論のbyte-identical性は未検証。

## 25. Failure-path validation

Runtime start failure、timeout、invalid/truncated JSON、invalid total/max、unknown/duplicate/missing criterion、criterion範囲外、bundle/reconstruction/result/asset tamper、wrong test/submission、未選択/REVIEW_REQUIREDをテスト。runtime例外時cleanup、borrowed runtime非停止も確認。

## 26. sampleQ1 audit

70a63c23-f1b1-46b7-852c-046148b6f451: structural 2、gradable 6。context resolved。MISSING_MODEL_ANSWER / MISSING_RUBRICでBLOCKED。実採点なし。

## 27. sampleQ2 audit

9fc4f834-a50e-423f-b0cf-31a977c1f891: structural 1、gradable 4。MISSING_MAX_POINTS / MISSING_MODEL_ANSWER / MISSING_RUBRICでBLOCKED。score unset維持。同条件のHTTP job guardテストは409、job rowなし。実採点なし。

## 28. sampleQ3 audit

8df4ed72-9297-4082-bb21-1fdb6c500557: gradable 3。current corrected formulas/contextをread-onlyで解決。q3 asset 9b9ca4cc-6332-4f02-8254-f63b7773cbfa / SHA 3a5a7a8df0cea793905c1fe178999bafd24fd2dd4b93414bd0cc606131683958を検証。MISSING_MODEL_ANSWER / MISSING_RUBRICでBLOCKED。最初のauditはartifact root指定が違いASSET_MISSINGを表示したため、実root artifacts/h2b-verificationで再確認して解消。データ修正なし。

## 29. Model-call audit

Ricoh=0、Uni-MuMER=0、Ornith reconstruction=0、Ornith grading=1。replay=0。runtimeはgraderのみ。

## 30. GradingJob audit

このfixtureでcreated=1、completed=1、failed=0。初回helper Path型エラーはDB更新/model起動前。実jobは成功し、後段のhelper不変監査だけをread-onlyでやり直しました。sampleにはjobを作成していません。

## 31. Runtime orphan audit

owned runtimeはstopped、pid=null。ps -C llama-serverでprocessなし。borrowed/external停止なし、OpenWebUI port3000操作なし。

## 32. PostgreSQL validation

PostgreSQL16.15、head0011_student_answer_recon。DB reset/migrationなし。影響は既存synthetic test/questionの配点設定、模範解答/Rubricの新version、1job/item/events/runtime snapshot。既存reconstructionは不変。

## 33. Backend tests

python -m unittest: 239 tests / OK。python -m pytest -q: 250 passed。Ruff: All checks passed。TestClientのdocument済みsocketpair対応実行環境を使用。deprecation warningsは失敗と区別。

## 34. Frontend validation

production frontend変更なし。今回typecheck/lint/buildは再実行していません。

## 35. Playwright

未実施。代わりに実PostgreSQLを用いたread-only TestClient HTTP result検証でscore/max、snapshot answer、result hash、path非公開を確認。UIによる採点開始は行っていません。

## 36. Security / isolation

Test/Submission/Question/ModelAnswer/Rubricのexact identityを検証。result APIはtest/submission/jobを照合。別submission指定は404。APIにabsolute artifact pathを返さず、local modelのみ使用。既存のlocal applicationの認証方式を維持しており、新規multi-user認証は実装していません。

## 37. Problems / limitations

検証はsynthetic 1問のみ。自動semantic正誤検証一般化・bulk/concurrency・実model replay・browser表示は今回未検証。H.3-B Stage2はinput_stage=selected_reconstructionで選択する専用実行分岐で、従来CLIのOCR込み動作は維持。再構成は以前のquestion context hashを保持し、今回のfixture配点設定はgrading開始前に行いました。

## 38. Remaining blockers

このsynthetic 1問のexecution検証に未解決blockerなし。実sampleはModelAnswer/Rubric不足、sampleQ2は配点不足もあり、そのまま実採点へは進めません。

## 39. H.3-B final status

COMPLETE（synthetic 1問のproduction job/worker→actual grading→厳格validation→PostgreSQL保存→resume検証）。

## 40. Next-phase readiness

実sampleを用いた準備・readiness validationへ進む基盤は整いました。actual grading開始はNO：教師承認済みModelAnswer/Rubric、必要なmax_points、対応するselected reconstruction、全readiness READYを満たしてからです。

## 最終質問への回答

1. はい、GradingInputAssemblerを使用。
2. はい、bundle全体一致。
3. はい、currentの再resolveなし。
4. はい、selected COMPLETEのみ。
5. はい、raw OCR本文を使用しない。
6. はい。
7. はい、question/submission/source artifactを照合。
8. はい。
9. はい。
10. はい、exact ID対応。
11. はい。
12. はい。
13. はい、graderのみ。
14. 0回。
15. 0回。
16. 0回。
17. 1回、replayなし。
18. instruction扱いしないsystem指示とJSON分離を確認。actual攻撃文smokeは未実施。
19. はい。
20. はい。
21. はい。
22. はい。
23. はい。
24. はい、manifestとDB metadata。
25. はい、grading前後不変。fixture配点/参照答案/Rubric設定は採点前。
26. はい。
27. はい。
28. はい、0/1。
29. はい。
30. はい、未採点。
31. はい。
32. 残っていない。
33. はい、1問synthetic範囲でCOMPLETE。
34. 実sampleのModelAnswer/Rubric、sampleQ2の配点、答案再構成/readiness準備が必要。
