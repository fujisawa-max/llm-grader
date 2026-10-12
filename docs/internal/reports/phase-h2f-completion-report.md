# Phase H.2-F Completion Report

## 1. Starting architecture

H.2-Eのauthoritative TestQuestion hierarchyとimmutable contentを入力とした。Review、Confirm、Vision、PDF parserの変更は行っていない。採点engineはfilesystem assignmentを読み、DB job adapterは従来、関連IDだけをmanifestへ記録していた。

## 2. Existing schema findings

ModelAnswerは`test_id`、nullable `question_id`、`answer_text`、`material_id`、`version`、`is_current`を持つ。更新は既存POSTによる新versionの作成。Rubricは問題ごとの独立tableではなく、Test単位の`RubricVersion.rubric_json.questions[].question_id`で関連付く。criteriaは`id/description/points`を持ち、Test totalとの合計validationが既存contract。

legacy graderのrubricは`criterion_id/max_score/levels`であり、domain rubricと同一schemaではない。この境界で新しい採点条件やlevelsを生成しない。

## 3. Files changed

Backend:

- `src/scoring/grading_context.py`（新規）
- `src/scoring/grading_inputs.py`（新規）
- `src/scoring/domain.py`
- `src/scoring/domain_adapter.py`
- `src/scoring/api/domain.py`
- `src/scoring/api/app.py`
- `src/scoring/adapters/scoring_adapter.py`
- `src/scoring/db/worker.py`
- `src/scoring/orchestration/phased_auto.py`
- `src/scoring/cli.py`

Frontend:

- `frontend/components/GradingPreparation.tsx`（新規）
- `frontend/app/tests/[testId]/page.tsx`

Tests / validation / documentation:

- `tests/test_grading_context.py`（新規）
- `frontend/e2e/grading-readiness-real.spec.ts`（新規）
- `scripts/validate_grading_readiness.py`（新規）
- `artifacts/h2b-verification/h2f-validation.json`
- `README.md`
- 本report

## 4. DB / migration decision

新table/columnは不要。migration追加なし。実PostgreSQLのcurrentは`0009_question_import_confirm`。readinessはDBに固定保存しない。

## 5. ModelAnswer association

既存question_id relationを再利用。gradable questionの本文を既存versioned POSTで保存する。unknown question、別Test question、structural questionを拒否。旧versionは保持する。Test全体に紐付く既存answerは削除しないが、個別問題へ自動割当しない。

## 6. Rubric association

既存Test単位versionを再利用し、questions内のIDをgradable questionsに限定。新version作成と承認によって更新。criteria合計、重複ID、空criteria、非有限/不正配点を検証する。

## 7. Structural-node protection

structural nodeはNOT_GRADABLE。ModelAnswer/Rubricを要求せず、新規associationをservice側で拒否する。historical associationがある場合は削除せず`STRUCTURAL_ASSOCIATION_IGNORED`を返す。

## 8. Legacy manual question compatibility

contentがnullのmanual questionは既存question_textをそのまま使う。root + gradableの動作を維持。QuestionImport provenanceがないことをblockerにしない。弱かった旧Test-level readinessの「模範解答が1件でもあればよい」は意図的に廃止し、各問題の明示associationを要求する。

## 9. EffectiveQuestionContext architecture

`EffectiveQuestionContextBuilder`は、事前取得したquestions/assetsを入力として`effective-question-context.v1`を生成する。resolverはモデル呼び出しもDB mutationも行わない。asset integrityだけfilesystem adapter経由で確認する。

## 10. Ancestor resolution

parent_idを辿りroot→parent→selfに並べる。cycle、missing parent、cross-Test parentを防御的に検出する。question_numberからhierarchyを推測しない。

## 11. Authoritative content resolution

imported questionはcontent.itemsを使用し、content_sha256と照合。未知schema/item、不正shape、欠落formulaをblockerとする。segmentにはsource question ID、stable key、display label、title、ancestor/self role、content hashを保持する。

## 12. Effective text

flat rootはself本文のみ。hierarchical questionでは`[label]`と本文をrootからselfへ連結する。score_expressionはordered slotに保持するがsemantic textへ重複挿入しない。既存text itemに含まれている配点文字をheuristicで削除することもしない。

## 13. Formula handling

authoritative transcriptionを文字列のまま使用し、Native/Vision/teacherを選び直さない。

**既存データの問題を発見した。** sampleQ3のformula-0001/0002/0003は、H.2-Eの保存時にLaTeXコマンド前のバックスラッシュが2文字になっている。これはJSON表示だけのescapeではなく、decode後の実文字数を確認した。ユーザーが入力した1文字のバックスラッシュと一致しない。前phaseの「入力どおり保存済み」という報告を訂正する。

H.2-Fでは既存authoritative contentとReviewを変更せず、余分なescapeも含めて同じ文字列をcontextへ渡した。正式なauthoritative correction workflowによる修正が実採点前に必要。formula-0001/0002はq1、formula-0003はq2に属する。q3自体のformulaはnative由来の`𝑥`であり、教師の3式をq3へ複製しない。

## 14. Figure asset handling

self/ancestorのfigure itemからTestQuestionAssetを解決する。asset所有question、artifact存在、SHAを検証する。orderとsource segmentを保持し、text表現では`[図]`、画像は独立したasset refとする。Ricoh observationで代用しない。

## 15. Grader multimodal capability audit

現在の`core.LocalClient.chat`はimage contentを送信可能。`cli.run_exam`のgrading呼び出しは`images + question asset_paths`を渡し、health contractもvisionを要求する。このため現在のadapter capabilityは画像対応。モデル起動・推論・live capability probeは行っていない。

画像非対応adapter条件では、asset integrityが正常でも`GRADER_ASSET_UNSUPPORTED`となることをunit testで確認した。

## 16. Context hash

canonical JSONのSHA-256を付与する。ancestor identity、順序、authoritative item、asset ID/SHA、score metadataを含む。request時刻、作成時刻、runtime生成UUID、filesystem pathは含まない。同一stateで一致することを検証した。

## 17. Per-question Grading Readiness

READY / BLOCKED / NOT_GRADABLE。score、answer、approved rubric、context、assetの状態を個別に返す。複数current ModelAnswerの曖昧な状態も自動選択せずblockする。

## 18. Readiness reason codes

主なcodes:

`MISSING_MAX_POINTS`, `INVALID_MAX_POINTS`, `MISSING_MODEL_ANSWER`, `EMPTY_MODEL_ANSWER`, `AMBIGUOUS_MODEL_ANSWER`, `MISSING_RUBRIC`, `INVALID_RUBRIC`, `RUBRIC_SCORE_MISMATCH`, `CONTENT_HASH_MISMATCH`, `EFFECTIVE_CONTEXT_UNRESOLVABLE`, `PARENT_CYCLE`, `PARENT_MISSING`, `CROSS_TEST_PARENT`, `ASSET_MISSING`, `ASSET_HASH_MISMATCH`, `UNSUPPORTED_CONTENT_ITEM`, `UNSUPPORTED_CONTENT_SCHEMA`, `GRADER_ASSET_UNSUPPORTED`, `NO_GRADABLE_QUESTIONS`。

## 19. Score readiness

nullはMISSING_MAX_POINTS。0点へ変換しない。現行core rubric validatorが正の整数scoreを要求するため、非正数・小数・非有限値はINVALID_MAX_POINTS。このphaseでscore correctionは追加していない。

## 20. ModelAnswer readiness

当該questionのcurrent answerの非空本文が必要。material-only answerを自動OCRしたり、Test全体のanswerを各leafへ配ったりしない。current associationの解除は履歴rowを削除せずis_current=falseにする。

## 21. Rubric readiness

approved Test rubric内に当該questionの非空criteriaが必要。既存validatorを再利用し、question.max_pointsとも比較する。承認解除はversionをsupersededにして履歴を残す。

## 22. Asset readiness

source question ownership、asset row、safe artifact lookup、file SHAを検証。missing/tampered assetはblocker。正常なancestor assetもleaf contextへ含む。

## 23. Test-level readiness

total/structural/gradable、ready/blocked gradable、score/answer/rubric/asset ready数を返す。gradable=0ではcan_start_grading=false。question readinessは全gradableがREADYのときtrue。

既存の`/readiness`と新規job APIは、これに従来のgrading policy・student submissions条件を組み合わせる。Question readinessとjob実行に必要なassignment/runtime設定は区別する。

## 24. Import-ready vs grading-ready distinction

登録済みでも採点可能とは限らない。unset配点、解答・Rubric欠落などはgrading blocker。sampleQ2のConfirm可否やReview判断には介入しない。

## 25. Effective Context API

`GET /api/v1/test-questions/{question_id}/effective-grading-context`

question、ancestor chain、segments、effective text、asset refs、context SHAを返す。

safe media endpoint:

`GET /api/v1/tests/{test_id}/test-question-assets/{asset_id}`

## 26. Readiness API

`GET /api/v1/tests/{test_id}/grading-readiness`

既存`GET /tests/{id}/readiness`もadditiveにquestion readinessを統合した。既存fieldは削除していない。

## 27. Grading-start server guard

`POST /tests/{id}/grading-jobs`はBLOCKED時に409と`GRADING_NOT_READY`、詳細reasonsを返す。frontend guardだけに依存しない。READY時にadapter境界まで通ることをmock HTTP testで確認した。

新規domain jobのinput preparationでは、legacy assignment IDsがgradable domain ID、question_number、stable key、source draft keyのいずれかへ一意に解決すること、approved rubricのcriterion ID/points/descriptionとlegacy rubricの対応を検証する。不一致なら`GRADING_INPUT_CONTRACT_MISMATCH`として拒否。学生答案mappingや採点levelsを生成・推測しない。

## 28. Existing job/resume compatibility

新規domain jobはcontext、answer、検証済みlegacy rubricをmetadata snapshotへ保存する。figureはjob inputsへSHA検証付きcopy。StageRequest経由で既存CLIのquestion input preparationへ渡す。

既存jobはdomain_inputsがなければ従来経路。resume時にlive ModelAnswer/Rubricへ差し替えたりreadinessを再判定したりしない。mock workerで、association解除後もsnapshotを使うことを検証した。採点prompt、採点計算、response parser、RuntimeManager semanticsは変更していない。

## 29. Answers UI

Test Workspace内で階層・score・answer/rubric status・readinessを表示する。gradable node選択時だけeditorを表示し、新version保存・current association解除が可能。

## 30. Rubric UI

同じhierarchyを表示し、structural editorを抑止。selected question criteriaを既存Test rubricに組み込む新version保存と、全questions JSON入力を提供する。既存Test total validationを維持するため、初回に複数問題を登録する場合は全questions JSONを利用する。generated/draftの承認、approvedの解除に対応。AI生成はない。

## 31. Effective Context preview UI

selected gradable nodeについてancestor/self labels、effective text、asset count、context SHA短縮値をread-only表示する。画像はTest所有権を検証するasset linkから確認可能。

## 32. Grading Readiness UI

Grading sectionでsummaryと問題別reason code/messageを表示。question readinessがBLOCKEDならStartボタンはdisabled。従来どおり実行設定付きStart UIは後続実装であり、今回モデル起動操作は追加しない。server guardは実装・検証済み。

## 33. sampleQ1 context validation

| Node | Context |
|---|---|
| q1 | structural / NOT_GRADABLE |
| q1.1 | q1 + self |
| q1.2 | q1 + self |
| q2 | selfのみ |
| q3 | structural / NOT_GRADABLE |
| q3.1 | q3 + self |
| q3.2 | q3 + self |
| q3.3 | q3 + self |

child DB本文へのancestor複製はない。

## 34. sampleQ1 readiness

| Question | Score | Context | ModelAnswer | Rubric | State | Blockers |
|---|---:|---|---|---|---|---|
| q1.1 | 20 | OK | Missing | Missing | BLOCKED | MISSING_MODEL_ANSWER, MISSING_RUBRIC |
| q1.2 | 20 | OK | Missing | Missing | BLOCKED | 同上 |
| q2 | 30 | OK | Missing | Missing | BLOCKED | 同上 |
| q3.1 | 10 | OK | Missing | Missing | BLOCKED | 同上 |
| q3.2 | 10 | OK | Missing | Missing | BLOCKED | 同上 |
| q3.3 | 10 | OK | Missing | Missing | BLOCKED | 同上 |

8 nodes、2 structural、6 gradable、score-ready 6/6、ready 0/6。実問題へanswer/rubricは追加していない。

## 35. sampleQ2 status

未Confirm、authoritative TestQuestion 0件。H.2-Fのauthoritative grading targetではない。can_start_grading=false。Confirmしていない。将来Confirmしてもunset scoreはgrading blockerとなる。

## 36. sampleQ3 context validation

q1/q2/q3はroot gradableでancestorなし。5 formulaのauthoritative文字列を保持。教師3式の所属と余分なescapeについてsection 13参照。

q3のasset:

- ID: `9b9ca4cc-6332-4f02-8254-f63b7773cbfa`
- SHA: `3a5a7a8df0cea793905c1fe178999bafd24fd2dd4b93414bd0cc606131683958`
- q3 context SHA: `ee342244c42e99871937816a8e598abe075e03fbe027ce1fce2d42ddc277f974`

HTTPで取得したasset bytesとSHAも一致した。Ricoh labels/raw observationはcontextへ挿入していない。

## 37. sampleQ3 readiness

| Question | Score | ModelAnswer | Rubric | Asset capability | State |
|---|---:|---|---|---|---|
| q1 | 30 | Missing | Missing | 不要 | BLOCKED |
| q2 | 30 | Missing | Missing | 不要 | BLOCKED |
| q3 | 40 | Missing | Missing | 対応・SHA OK | BLOCKED |

3 gradable、score-ready 3/3、asset-ready 3/3、ready 0/3。blockerは各問題のMISSING_MODEL_ANSWERとMISSING_RUBRIC。

## 38. Figure grading limitation

現行adapterに画像転送能力はあるためQ3へGRADER_ASSET_UNSUPPORTEDは付かない。モデルがその図を正しく解釈・採点できることは未実証。今回はmodel executionを一切行っていない。

## 39. READY validation Test

専用synthetic Test `47b5ad17-ecfc-4604-a8c8-cb3453084111`をDomainServiceで作成。structural parent + gradable child、score 10、fixture-only answer/rubric、assetなし。associationのcreate/approve/retire/restoreは実HTTP経路。

parentはNOT_GRADABLE、childはREADY、question-level can_start_grading=trueを確認。flat READYもunit fixtureで検証。無関係な既存Testには書き込んでいない。

## 40. BLOCKED transitions

実DB: answer解除→BLOCKED、復元→READY、rubric解除→BLOCKED、再版承認→READY。Playwrightでもanswer解除・新version保存・reload後READYを確認。

unit: null/zero score、empty answer、rubric mismatch/invalid、cycle/parent missing、unknown content、content/asset tamper、asset ownership、text-only capabilityを検証。

## 41. PostgreSQL validation

- Existing container: `llm-grader-pg`, host port 55432
- PostgreSQL 16.15
- DB: `grader`
- Alembic: `0009_question_import_confirm`
- DB reset、migration追加、既存data削除なし

既存TestQuestion/ModelAnswer/Rubric/Draft/DraftNode/Extraction/VisionRun/VisionResult/ReviewRevisionをID→record hashで前後照合。既存レコード不変。source artifact filesも前後SHA一致。詳細JSONは`artifacts/h2b-verification/h2f-validation.json`。

## 42. Backend tests

最終コード:

- `.venv/bin/python -m unittest`: **184 tests OK**
- `.venv/bin/python -m pytest -q`: **195 passed**
- `.venv/bin/ruff check`: **All checks passed**

既存resume/checkpoint testsを含む。DeprecationWarning等の既存環境warningは残る。標準PATHにpythonがないためproject venvを使用。

## 43. Frontend validation

- `/tmp/node-v22.14.0-linux-x64/bin/node`: v22.14.0
- npm: 10.9.2
- `npm run typecheck`: PASS
- `npm run lint`: PASS、既存refresh dependency warning 1件
- `npm run build`: PASS

dependency upgrade、system Node/npm installなし。

## 44. Playwright validation

Playwright 1.51.1 / bundled Chromium 134.0.6998.35。既存Ubuntu workaround:

```text
PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64
PLAYWRIGHT_BROWSERS_PATH=/tmp/h2d1-playwright-browsers
LD_LIBRARY_PATH=/tmp/h2d1-browser-libs/usr/lib/x86_64-linux-gnu
FONTCONFIG_FILE=/tmp/h2d1-fonts.conf
```

Production buildをport 13002、検証APIを18052で使用。既存port 3000/3001/8000を停止していない。`grading-readiness-real.spec.ts`: **3 passed**。

確認: Q1 Answers/Rubric hierarchy、structural editor抑止、parent+self preview、Grading summary/reasons/disabled start、Q3 asset ref、専用fixture answer編集/解除/保存/reload/READY。採点ボタンは実行していない。

Screenshots: `frontend/test-results/h2f-q1-readiness.png`, `h2f-q3-context.png`, `h2f-fixture-ready.png`。

## 45. Security

context/answer/rubricはReact textとして表示。trusted HTML扱いなし。asset endpointはTest→Question→Assetの関係とfile hashを検証。context/manifestの公開データにfilesystem pathを含めない。job内部snapshotのasset pathは内部metadataのみ。artifact adapterでpath traversal/symlink escapeを拒否する。既存authentication architectureは変更していない。

## 46. Performance / query behavior

Test readinessはTest、questions、assets、current answers、approved rubricをまとめて取得。ancestor traversalはmemory map上で行う。各ancestorにSQLを発行しない。同一計算内のasset integrity確認を再利用。persistent cacheなし。

## 47. Problems / limitations

1. Q3の3教師式には既存の余分なbackslashがある。今回勝手に修正していない。
2. 実問題のanswer/rubric未設定は教師作業として残る。
3. Domain rubricとlegacy grading rubricは異なるschema。H.2-Fは採点levelsを生成せず、対応する既存assignment/rubricを新規job前に検証する。次phaseで実答案mapping・既存levelsの整合性を検証する必要がある。
4. 模範解答が画像/materialのみの場合、本文化は今回行わない。
5. Question readinessはモデルの正答率・図理解・runtime availabilityの保証ではない。

## 48. Remaining blockers

H.2-Fのassociation/context/readiness実装に残るblockerはない。実問題の採点開始には、教師によるanswer/rubric登録、Q3既存LaTeXの正式修正、対応assignment/student-answer mappingとlegacy rubricの検証が必要。採点方針・学生答案の既存preconditionも必要。

## 49. H.2-F final status

**COMPLETE — association / effective context / readinessの範囲。**

これはsampleQ1/Q3が採点READYという意味ではない。両sampleは正しくBLOCKEDであり、実採点は未実行。

## 50. Next-phase readiness

次phaseのhierarchical grading integration/validationに使えるcontext snapshot、hash、safe asset refs、per-question reasonsが揃った。実行前にsection 48の教材・入力準備を完了すること。ModelAnswer/Rubric自動生成、Q2 Confirm、Review/Question再import、formula correction、Ornith/RuntimeManager実行は行っていない。

## 最後の23問への回答

1. はい。ModelAnswerはgradable questionへ関連付け、structural新規作成を拒否。
2. はい。Rubricのquestionsもgradable IDに限定。
3. はい。structuralにはどちらも要求しない。
4. はい。q1.1はq1 parent stemを含む。
5. はい。q1.2も同じq1 stemを含む。
6. はい。q2はselfのみ。
7. はい。child.question_textへの複製なし。
8. 保存済み文字列は変更せず利用。ただし元の教師入力との余分なbackslash不一致を発見した（section 13）。
9. はい。Q3 graphはdurable TestQuestionAsset参照。
10. はい。Ricoh observationを代替textにしていない。
11. はい。画像非対応capabilityのblockerをunit test済み。現行adapterは画像対応。
12. はい。unsetはMISSING_MAX_POINTS。
13. はい。ModelAnswer欠落はBLOCKED。
14. はい。Rubric欠落はBLOCKED。
15. はい。asset missing/hash mismatchはBLOCKED。
16. はい。全gradableの状態から算出する。
17. はい。新規job APIはserver-side 409で拒否。
18. はい。legacy flat text/selectionと既存job経路を維持。新規readinessは問題ごとの不足を厳密に判定する。
19. はい。structuralをgrading requestへ含めない。
20. はい。Q2は未Confirmのまま。
21. はい。実問題の解答/Rubricを生成・登録していない。
22. H.2-F実装はCOMPLETE。実教材のREADYは別判定。
23. 実採点前にanswer/rubric、Q3既存LaTeX修正、assignment/legacy rubric対応の検証が残る。
