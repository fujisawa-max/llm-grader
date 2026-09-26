# Phase H.3-C Real Sample Grading Readiness Preparation Report

## 1. Environment

PostgreSQL 16.15 / Alembic `0011_student_answer_recon`。read-only transactionで監査。モデル呼出0。Migration・production code・UI変更なし。

## 2. sampleQ1 identity

Test ID: `70a63c23-f1b1-46b7-852c-046148b6f451`

Name: H.2-B verification sampleQ1

Confirmation ID: `1452d9f4-e598-409c-892c-c6538ba79565`

## 3. sampleQ1 hierarchy/readiness matrix

| Question ID | Label/title | Parent | Max | Context SHA | State |
|---|---|---|---:|---|---|
| b9dae2b2-22d2-4241-8978-65cc5bf9b24d | 問題1 / 問題1 | — | None | — | NOT_GRADABLE |
| 3d5d8e20-46b7-42c2-96bd-3e7aeb62963b | (1) / (1) | b9dae2b2-22d2-4241-8978-65cc5bf9b24d | 20.0 | 9bbe33218793c448c7fcde396d85f9830f2d632fed2c2fb5c91b4c12abcaeeba | BLOCKED |
| 9a3ba4aa-8e79-4dda-b15a-807f4364d6c3 | (2) / (2) | b9dae2b2-22d2-4241-8978-65cc5bf9b24d | 20.0 | f88796d526451a69f23947286b51cc0f3a9dc5dc15d5721cc8046b61b1df5e6a | BLOCKED |
| a8f32cd9-1d3d-4242-9ef6-3b45fecb5f74 | 問題2 / 問題2 | — | 30.0 | 5c763e64fc5e2fb6923cb96d179a239d594634ab9f58afba2d4f8b52273132ed | BLOCKED |
| f211ef35-2408-4187-a834-eb68b27f140e | 問題3 / 問題3 | — | None | — | NOT_GRADABLE |
| 8a2a7955-2347-4c67-8581-f800721ec558 | (1) / (1) | f211ef35-2408-4187-a834-eb68b27f140e | 10.0 | 87a0f63103b8159a8e395f5077efdcc6c1d8db84b063f2d7a0663c74c021f8bf | BLOCKED |
| b759cd39-630f-4be6-8d59-85ddefb61293 | (2) / (2) | f211ef35-2408-4187-a834-eb68b27f140e | 10.0 | 0a48b3d637aeb2bd8cffaf99c45d5a8d863d6356f9b7b61eab833a85805f40fa | BLOCKED |
| 6a1543bc-13ea-4ea1-a02a-6669ff147f83 | (3) / (3) | f211ef35-2408-4187-a834-eb68b27f140e | 10.0 | 8793ef3c9bcdc031c3dcae6f261e74e94dad856b3cfd05fc34604223f2885cff | BLOCKED |

全gradable行: ModelAnswer absent（current/historicalとも0）、RubricVersion 0（approved/draftともなし）、Submission 0、Student Answer MISSING、Reconstruction 0・selected IDなし。Mappingは対象submission不在で未評価（READYではない）、Execution BLOCKED。既存Test readiness blockerはMISSING_MODEL_ANSWER / MISSING_RUBRIC。sampleQ2にはMISSING_MAX_POINTSもある。Structural行はNOT_GRADABLEで関連入力を要求しない。全stable key・content・context・status・warningsは[audit.json](../artifacts/h3c-readiness/audit.json)に収録。

Gradable 6、structural 2、配点20/20/30/10/10/10、合計100。全childのancestor_chainと親stem+selfを既存EffectiveQuestionContextBuilderで確認。

## 4. sampleQ1 ModelAnswer audit

6問すべてabsent。exact question_id queryでcurrent/versioned/historicalを含め0件。生成・保存なし。

## 5. sampleQ1 Rubric audit

RubricVersion 0件。approved entryなし。array順序による対応付けなし。

## 6. sampleQ1 Student Answer audit

このTest IDのStudentSubmissionは0件。既存synthetic submissionを混ぜていない。MISSING_STUDENT_ANSWER。source type・ownership・duplicate/orphanの実submission評価は対象なし。

## 7. sampleQ1 Reconstruction audit

対象questionのReconstructionは0件。document答案自体が未登録なので再構成要否は未確定。DIRECT_TEXTなら不要、documentならselected COMPLETEが必要。

## 8. H.3-D candidate

Question ID: `8a2a7955-2347-4c67-8581-f800721ec558`

Stable key: `review-48e6195a-5d0-q3.1`

Label: (1) / title: (1)

max_points: 10.0

Context SHA: `87a0f63103b8159a8e395f5077efdcc6c1d8db84b063f2d7a0663c74c021f8bf`

Effective Context（current DBをそのまま使用）:

```text
[問題3]
問題３ 
人工知能における教師付き学習、教師なし学習、強化学習とはそれぞれどのようなものか説明し
なさい。（各10 点） 

[(1)]
（１）
教師付き学習 
```

問題3 (1) 教師付き学習。gradable leaf、配点済み、parent context正常、figure/formulaなし。ただし答案sourceがないため暫定candidate。

## 9. H.3-D candidate blockers

教師の模範解答・承認用採点基準（合計10点）と、利用許可された対応実答案が必要。documentならその後selected COMPLETE Reconstructionが必要。

## 10. H.3-D teacher input required

上記Question ID/context/max_pointsに対して、次を別々に入力してください。

- ModelAnswer: 【教師記入】
- Rubric: criterion ID / 内容 / 最大点 / 許容得点levels・各条件【教師記入】（合計10点）
- Student Answer: 対応する実答案sourceとvalidation利用可否【User指定】

保存は入力後に既存version/approval workflowを使う。教師入力なしで進まない。

## 11. sampleQ2 identity

Test ID: `9fc4f834-a50e-423f-b0cf-31a977c1f891`

Name: H.2-B verification sampleQ2

Confirmation ID: `8b559ac5-0565-4d71-bcb5-93f277f72185`

## 12. sampleQ2 readiness matrix

| Question ID | Label/title | Parent | Max | Context SHA | State |
|---|---|---|---:|---|---|
| 24a42587-a730-408c-8565-1221cba11453 | (1) / (1) | 70dad1da-b4b3-4a37-8588-31e1a7b88136 | None | fc0231ffb17c062acc97164f42c391dad7f3b9d4c870b60bc848731d8ee1ed78 | BLOCKED |
| 70dad1da-b4b3-4a37-8588-31e1a7b88136 | 問題1 / 問題1 | — | None | — | NOT_GRADABLE |
| 5928d0e3-ea16-48e4-b9ff-a96209e4eb37 | 問題2 / 問題2 | — | None | 7b34c29792907f6ae67dd74a9845176cc0d0d59916a2e2bcd7ab7c9bd0a5576e | BLOCKED |
| dbd8a6e7-8fdd-475c-adb7-652db377ab8a | (2) / (2) | 70dad1da-b4b3-4a37-8588-31e1a7b88136 | None | 5ecde0a0fea414bcb0046669a7a47595178b618936e0995f9c54dbc1d2fc55b3 | BLOCKED |
| 8c8c578c-1635-4f13-91e8-4b40dbe3e258 | 問題３ / 問題３ | — | None | e9eaf3ecc515cf8a190782f42dfc50236b7c9ba17dc18166c667f1eed90f59fb | BLOCKED |

全gradable行: ModelAnswer absent（current/historicalとも0）、RubricVersion 0（approved/draftともなし）、Submission 0、Student Answer MISSING、Reconstruction 0・selected IDなし。Mappingは対象submission不在で未評価（READYではない）、Execution BLOCKED。既存Test readiness blockerはMISSING_MODEL_ANSWER / MISSING_RUBRIC。sampleQ2にはMISSING_MAX_POINTSもある。Structural行はNOT_GRADABLEで関連入力を要求しない。全stable key・content・context・status・warningsは[audit.json](../artifacts/h3c-readiness/audit.json)に収録。

## 13. sampleQ2 score state

全4 gradable max_points=NULL。問題別配点合計は未解決。ただしactual Test.total_pointsは100.0でありNULLではない。既知期待の「total unresolved」は計算・承認状態としてのみ成立し、DB totalフィールドunsetとは異なる。この既存値を変更せず、配点の根拠として使用しない。

## 14. sampleQ2 blockers

MISSING_MAX_POINTS / MISSING_MODEL_ANSWER / MISSING_RUBRIC、対応Submission/Answerなし。全問BLOCKED。

## 15. sampleQ2 protection

配点・total・contentを更新していない。問題3のtitle/display_labelはともに「問題３」。

## 16. sampleQ3 identity

Test ID: `8df4ed72-9297-4082-bb21-1fdb6c500557`

Name: H.2-B verification sampleQ3

Confirmation ID: `8aef8358-9c74-4cc0-80eb-429d28b31a44`

## 17. sampleQ3 readiness matrix

| Question ID | Label/title | Parent | Max | Context SHA | State |
|---|---|---|---:|---|---|
| ad991321-ce7b-4f67-a4a3-1f23b89e29e2 | 問題1 / 問題1 | — | 30.0 | 62a7c655d9ffff29a80a7336da4e034cf61fc657cb81ec085e5d908f5cc8e853 | BLOCKED |
| 7b81a7ce-e028-4e9c-ba51-e57e4913ffae | 問題2 / 問題2 | — | 30.0 | 6dfb6bcbbae54446b5a7910bfc652e6ceae0d5e66aebaf35ce563c3e940ceb29 | BLOCKED |
| 7fcbd8ee-1eee-4d93-a195-59ea995a0385 | 問題3 / 問題3 | — | 40.0 | ee342244c42e99871937816a8e598abe075e03fbe027ce1fce2d42ddc277f974 | BLOCKED |

全gradable行: ModelAnswer absent（current/historicalとも0）、RubricVersion 0（approved/draftともなし）、Submission 0、Student Answer MISSING、Reconstruction 0・selected IDなし。Mappingは対象submission不在で未評価（READYではない）、Execution BLOCKED。既存Test readiness blockerはMISSING_MODEL_ANSWER / MISSING_RUBRIC。sampleQ2にはMISSING_MAX_POINTSもある。Structural行はNOT_GRADABLEで関連入力を要求しない。全stable key・content・context・status・warningsは[audit.json](../artifacts/h3c-readiness/audit.json)に収録。

## 18. sampleQ3 corrected formulas

current contentから次を確認。historical Reviewは入力に使用しない。

```latex
\sin \frac{5}{12}\pi + \sin \frac{1}{12}\pi
\sin x + \sin y = 2 \sin \frac{x+y}{2} \cos \frac{x-y}{2}
\cos \frac{1}{12}\pi
```

JSON escapingと実文字列を区別。実文字列は単一backslash。

## 19. sampleQ3 figure asset

ID `9b9ca4cc-6332-4f02-8254-f63b7773cbfa` / SHA `3a5a7a8df0cea793905c1fe178999bafd24fd2dd4b93414bd0cc606131683958`。既存asset_pathによるfile存在・actual SHA検証成功。owner `7fcbd8ee-1eee-4d93-a195-59ea995a0385`。q1/q2 contextにはassetなし。既存grading adapterはimages転送対応、registry ornith15-35b-q8にはmmproj設定あり。これは静的capability確認であり実図採点の品質検証ではない。

## 20. H.3-E figure candidate

Question ID: `7fcbd8ee-1eee-4d93-a195-59ea995a0385`

Stable key: `review-352e741e-298-q3`

Label: 問題3 / title: 問題3

max_points: 40.0

Context SHA: `ee342244c42e99871937816a8e598abe075e03fbe027ce1fce2d42ddc277f974`

Effective Context（current DBをそのまま使用）:

```text
問題３
以下のグラフとなる関数の式を特定しなさい（cos で表しなさい。なお、
𝑥
軸方向の移動については、絶対値が最小となるように表記しなさい）。（40 点） 
[図]
```

Asset `9b9ca4cc-6332-4f02-8254-f63b7773cbfa` SHA `3a5a7a8df0cea793905c1fe178999bafd24fd2dd4b93414bd0cc606131683958`。ownershipから特定。

## 21. H.3-E candidate blockers

ModelAnswer / approved Rubric（合計40点）/ 利用許可された実答案が必要。documentの場合selected COMPLETE Reconstructionも必要。教師入力欄: ModelAnswer【空欄】、Rubric criterion ID・内容・最大点・levels【空欄】、答案source/利用許可【空欄】。

## 22. Teacher data created

なし。ModelAnswer/Rubric/配点/答案の生成・保存0。

## 23. Execution readiness

H.3-D candidate BLOCKED / H.3-E candidate BLOCKED / sampleQ2 BLOCKED。既存GradingReadinessServiceは全問BLOCKED。GradingInputAssemblerは各Testで構築済みだがevaluate対象のSubmissionが0件のため呼び出せない。架空IDでREADYを作らない。H.3-B guardを変更・迂回しない。

## 24. Grading Input Preview

READY candidateなし。preview/bundle/handoff hashを生成していない。ID/context hashを含む準備worksheetは保存済みだが、execution-ready handoffではない。

## 25. Immutability

read-only transaction。Question/Confirmation/Correction/assets/ModelAnswer/Rubric/Submission/Reconstruction/GradingJobの全row fingerprint before=after。確認IDは各identity節、Correction等を含むtable fingerprintはaudit JSONに保存。asset bytesはcontext resolverでSHA確認。

## 26. Model-call audit

Ricoh 0 / Uni-MuMER 0 / Ornith reconstruction 0 / Ornith grading 0 / GradingJob created 0。モデル実行スクリプト・job create APIを呼んでいない。テストはfake/mockでありactual callなし。

## 27. PostgreSQL validation

persistent graderへread-only接続。DB reset/SQL UPDATE/commitなし。schema migrationなし。JSON worksheetにsource IDs/content hashes・before/after fingerprints・report SHAあり。

## 28. Backend tests

unittest: 239 tests OK。pytest: 250 passed（8418既存deprecation warnings）。Ruff: All checks passed。

既存tests/test_grading_context.py・test_grading_mapping.py・test_grading_execution.pyでstructural除外、unset score、missing association/answer/reconstruction、all-ready fake worker、guard rejection no job、asset hash/current correction、snapshotを確認。実sample集計はread-only auditで確認。production変更なしのため重複testは追加しない。

## 29. Frontend validation

Frontend変更なし。既存readiness/Answers/Rubric/Mapping UIを使用する方針。typecheck/lint/buildは変更時のみの指示に従い未実施。新aggregate判定/UIは作成しない。

## 30. Playwright

UI変更なし。今回は未実施。ブラウザ表示確認を実施済みとは扱わない。

## 31. Remaining blockers

両candidateの教師ModelAnswer/approved Rubricと対応する実答案・利用許可。答案種別によりselected Reconstruction。sampleQ2は意図的に配点未設定でBLOCKED維持。sampleQ1問題1(1) current textに「反表型AI」が存在するが、本phaseでは修正しない。candidateはこの問ではない。

## 32. H.3-C final status

COMPLETE（read-only audit）。Teacher Input Requiredが明確になった段階で停止。採点準備がREADYになったという意味ではない。

## 33. H.3-D readiness

NOT READY。上記10節の教師入力・実答案指定が必要。入力後にexistingサービスで再評価。job作成しない。

## 34. H.3-E readiness

NOT READY。40点figure問題の教師ModelAnswer/Rubric・実答案指定、必要なら許可後Reconstruction、再readiness確認が必要。

## 最後の34質問への回答

1. 6問。
2. 20/20/30/10/10/10点。
3. 存在なし。
4. 存在なし。
5. 登録済み対応Submissionなし、存在を確認できる答案なし。
6. なし。
7. 問題3 (1) 教師付き学習（暫定）。
8. 8a2a7955-2347-4c67-8581-f800721ec558。
9. NO、MISSING。
10. NO、MISSING。
11. NO、対応Submissionなし。
12. 未準備。答案種別未確定、documentなら必要。
13. NO、submission不在で未評価。
14. NO、BLOCKED。
15. 10節参照: ModelAnswer、10点Rubric、対応実答案/利用許可。
16. はい、4問ともNULL。
17. 問題別合計は未解決。ただしTest.total_points DB値は100.0。
18. 設定していない。
19. はい、current authoritative content。
20. 一致。
21. 問題3 / 7fcbd8ee-1eee-4d93-a195-59ea995a0385。
22. すべて不足。asset/contextは正常。
23. AI生成なし。
24. AI生成なし。
25. 生成なし。
26. 無断processingなし。
27. 作成0。
28. 実行0。
29. 不変。
30. 不変。
31. auditとしてCOMPLETE。
32. NO。
33. 教師模範解答・採点基準と利用可の実答案指定。documentならその後明示許可で再構成。
34. 40点figure問題の教師入力・実答案・必要な再構成とreadiness再評価。