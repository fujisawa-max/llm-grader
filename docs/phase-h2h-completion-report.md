# Phase H.2-H Completion Report

Track A COMPLETE / Track B COMPLETE。Phase H.2-H COMPLETE。H.3-C.1へ進むQuestion-side準備が完了。

## 1. Environment

PostgreSQL16.15 / Alembic0011_student_answer_recon。今回Uni-MuMER2 calls、他モデル0。migrationなし。

## 2. sampleQ1 current identity

Test70a63c23-f1b1-46b7-852c-046148b6f451 / Confirmation1452d9f4-e598-409c-892c-c6538ba79565。8 node IDはq1-correction.jsonのbefore/afterに収録。

## 3. sampleQ1 corrected source

sampleQ1.pdf / SHA bd7cc3fa1e665af61d28ecd2776252624f5853d54938724b55545edd6bb8f0e9 / material a6a79d68-07db-4e59-ad6f-70e6842b1e40。旧sourceと別登録。

## 4. sampleQ1 H.2-A result

1 page、native text十分。新immutable source/native IR/comparison Draft/Reviewあり。Vision不要。

## 5. sampleQ1 structure comparison

新旧8 nodes・structural2・gradable6。hierarchy/label/order/type/gradability/20,20,30,10,10,10全一致。total100。全条件照合後のhierarchical path comparisonでありgrading mappingではない。

## 6. sampleQ1 actual diff

1箇所TEXT_ONLY: 問題1(1)「反表型」→「汎用型」。他text segment、formula、asset、score、hierarchy変更なし。

## 7. Teacher approval

YES。UserがQuestion ID・stable key・old/new・reason・source SHAを明示。承認前に停止済み。

## 8. sampleQ1 Correction

ID `d7f1f7aa-a6e4-48a0-a262-5abea9aba93d` / version1 / type set_text_segment / reason question_source_typo_correction。source material/extraction ID/SHAをnoteに保存。既存plan→apply、row lock、expected content hash・exact old text・plan hash検証、append-only correction artifact/recordを使用。text segment操作だけ既存service/APIに最小追加。

## 9. sampleQ1 before/after hashes

content_sha256:

Before `667807d054a5076adc259fe142534d292a166342aa703f083248434e4664149a`

After `21f670e0b3d04c92a8717485900a3a478354a0e9ab3aa0b1c2c117ad67ca5ad8`

context_sha256:

Before `9bbe33218793c448c7fcde396d85f9830f2d632fed2c2fb5c91b4c12abcaeeba`

After `e5d986c04795cf8a37306f21c0760788062f4f0e8c6bd50c8e10b50cfc01916a`

対象はleafでdescendantなし。他7 nodeのcontent/context SHA不変。

## 10. sampleQ1 identity preservation

Test/Question ID、stable key、parent、sort order、node type、gradability、max_points不変。TestQuestion件数8のまま。H.3-D候補8a2a7955-2347-4c67-8581-f800721ec558不変。

## 11. sampleQ1 historical immutability

既存Confirmation/ReviewRevision/Correction/Asset全rowと全既存historical artifactのbefore fingerprintを照合。変更なし（新Correctionの追加のみ）。current text: （１）汎用型AI、特化型AI とは何か説明しなさい。元segment末尾spaceも保持。

## 12. sampleQ4 source

testData/SampleQ/sampleQ4.pdf / SHA c3be971d251e67d0f66b994b0e2afe68ef781721efc0666fe972e12955ae6966。Question PDFのみ。模範解答PDFは開いていない。

## 13. sampleQ4 H.2-A

Test `e14aeeb5-924c-4c72-b2a2-583f1be9f48e` / material `eb5bc74c-3446-4e31-8d52-1d8082090edc` / extraction `3ccb7e32-14ac-485b-b7c9-f507d6a51baf`。1 page。native text・page geometry・vectors保存。

## 14. sampleQ4 H.2-B structure

Original Draft `5b84f9d2-b90d-41d5-babd-709f3af3b2f6` は変更せず保存。教師承認に基づくappend-only refinement Draft `fed87c6d-966f-41b0-ba49-4b04aa3f3472` を作成。5 nodes / major3 / structural1 / gradable4。旧fragment formula-0001/0002と元Draft hashをrefinement_provenanceへ保持。

## 15. sampleQ4 H.2-C

Userの追加承認に従いoriginal PDFからcanonical全行列式formula-0005とquadratic formula-0003をcrop。RuntimeManager→既存RuntimeVisionAdapter→UniMuMerOutputParserを使用し、actual Uni2 calls。旧fragment/artifactはそのまま保持。rawとnormalizedを別保存。これはReview evidenceの実OCRであり、未承認転写のauthoritative確定はしない。

## 16. sampleQ4 formulas

formula-0005: teacher_edit。Userが明示指定した次の文字列を通常JSON serializationでそのまま保存。

```latex
\begin{pmatrix}
1 & 1 \\
0 & 2
\end{pmatrix}
\begin{pmatrix}
3 \\
-1
\end{pmatrix}
+
\begin{pmatrix}
1 & 2 \\
1 & 3
\end{pmatrix}
\begin{pmatrix}
3 \\
-1
\end{pmatrix}
```

formula-0003: teacher_edit、Userの厳密指定値 `y=-\frac{1}{3}x^2-2x-\frac{5}{3}`。ownerはq2 structural parent。

formula-0004: use_native、`3 + √3𝑖`。連続native span、fragmentのsemantic再構築なし。

実保存値検証: begin/end各4 commandは単一backslash、frac2 commandも単一backslash。行区切りだけdouble-backslash4箇所。User指定文字列との完全一致、`repr`確認成功。repr自身とJSON外側のescape表示は実文字数と区別。検証証跡はq4-finalization.jsonのstored_latex_reprとapi-verification.json。

Uni-MuMER raw/normalizedは保持。matrixの不正なOCR出力は採用せず、Userの明示転写で解決。rawを書き換えていない。

## 17. sampleQ4 drawing/formula region verification

### formula-0005 → q1

coordinate_space: normalized / bbox: `[0.1785330060808437, 0.1924625631968378, 0.3846483702774722, 0.21826882506306364]`

source page0 / PDF plane 594.9600219726562×842.0399780273438pt / rotation0。

rendered page [1785, 2527]px / final pixel bbox `[306, 474, 699, 564]` / crop 393×90px。

SHA `3f914ef4f09abd696cae7f7f827cf8aa10451f4d630dc9766682a500d83064aa`。

[実crop](../artifacts/h2h-preflight/q4-canonical/formula-0005.png)。

provenance parent regions: ['formula-0001', 'formula-0002']。

### formula-0003 → q2

coordinate_space: normalized / bbox: `[0.12166196048862182, 0.452084023298666, 0.320741139690136, 0.49257381659574384]`

source page0 / PDF plane 594.9600219726562×842.0399780273438pt / rotation0。

rendered page [1785, 2527]px / final pixel bbox `[204, 1128, 585, 1257]` / crop 381×129px。

SHA `0f895bae24940d85e6b49d6a4f5330198f057e24e1e4a4f4f897134c9299c686`。

[実crop](../artifacts/h2h-preflight/q4-canonical/formula-0003.png)。

provenance parent regions: ['formula-0003']。

### figure-0001 → q2.2

coordinate_space: normalized / bbox: `[0.4622159302203312, 0.457222946708473, 0.9261126456414636, 0.6840530319586505]`

source page0 / PDF plane 594.9600219726562×842.0399780273438pt / rotation0。

rendered page [1190, 1685]px / final pixel bbox `[549, 769, 1103, 1153]` / crop 554×384px。

SHA `38b76fdc5604d461b42eed6d22bbb4acf43610c1053efc46e62672625d64dc0d`。

[実crop](../artifacts/h2h-preflight/q4-canonical/figure-0001.png)。

provenance parent regions: []。

### figure-0002 → q3

coordinate_space: normalized / bbox: `[0.07227376363445179, 0.7208683861092029, 0.6134865982924396, 0.9370101427350266]`

source page0 / PDF plane 594.9600219726562×842.0399780273438pt / rotation0。

rendered page [1190, 1685]px / final pixel bbox `[85, 1213, 731, 1579]` / crop 646×366px。

SHA `75a40b4116b14404eab3313ef7eb59df0112d5e14ced2c137a2b64ec39da8f42`。

[実crop](../artifacts/h2h-preflight/q4-canonical/figure-0002.png)。

provenance parent regions: []。

全formulaと両drawing cropを目視確認。matrix全式・括弧・vector・+を保持。graphは(2)ラベル、x/y axes、交点とblank canvasを保持。complex planeはRe/Im、原点とblank canvasを保持。隣接する別問題本文なし。原PDFから直接既存rendererでcrop、previewから再cropなし。新canonical bboxは0–1、point/pixelは別metadata。PDF point→最終pixelのrounding/expanded bboxもmanifestで追跡。

## 18. sampleQ4 Review

新Review `b0c4f3de-44bb-49a9-b96c-575978fa9f29` / revision3 reviewed。旧Review revision1は不変。数式teacher_editとuse_native、両figure accepted_as_evidenceを保存。OCRのreasoning fallback等warningはUserの正確な転写承認でresolved。crop evidenceは教師承認として明示し、Ricoh出力を捏造していない。

## 19. sampleQ4 Import Plan

nodes5 / structural1 / gradable4 / formula3 / figure2 / total110。blockers=[] / warnings=[] / import_ready=true。Plan SHA `fc61acf9c495d61d1e5e7ae4a7de7a311f869c7fbf4872c17ff389ab95352a46`。親先行のplan配列順に依存せず、review_keyごとに30/20/20/40を照合してConfirm。

## 20. sampleQ4 scoring

問題1=30、問題2(1)=20、問題2(2)=20、問題3=40。total110。structural問題2 max_points=NULL、二重加算なし。Test.total_pointsは独立metadataとしてTest作成時に明示110とし、確定question合計110との一致を検証。100-point normalizationなし。

## 21. sampleQ4 Confirmation

Explicit Confirm成功: `62746ef5-b2df-45b6-abe6-ff3bd8a18918`。既存QuestionImportConfirmationServiceを使用し、Review SHA/Plan SHA・blocker再検証後にtransactionで5 TestQuestionと2 assetを登録。

## 22. sampleQ4 authoritative hierarchy

```text
問題1 [Gradable 30]
問題2 [Structural / max_points unset]
 ├ (1) [Gradable 20]
 └ (2) [Gradable 20]
問題3 [Gradable 40]
```

|Label|Question ID|Parent ID|max_points|
|---|---|---|---|
|問題1|ab3e65c7-7dca-4254-a4d9-757ebf675f28|—|30.0|
|問題2|75f85e0f-1e3e-4b4d-999a-da311e3c87ae|—|None|
|(1)|02669a76-cb99-4ea1-bfd4-c742ff1617a3|75f85e0f-1e3e-4b4d-999a-da311e3c87ae|20.0|
|(2)|705f1d12-4f19-4c33-b197-39212f24b3ca|75f85e0f-1e3e-4b4d-999a-da311e3c87ae|20.0|
|問題3|4c567426-da7a-4aae-bccc-a0026b69f219|—|40.0|

## 23. sampleQ4 assets

- `figure-0002` → Question `4c567426-da7a-4aae-bccc-a0026b69f219`
  Asset ID `25a9185d-af5b-4fee-b6ef-7b2d13b3244a`
  SHA `75a40b4116b14404eab3313ef7eb59df0112d5e14ced2c137a2b64ec39da8f42`
  role `student_drawing_area` / coordinate_space `normalized` / bbox `[0.07227376363445179, 0.7208683861092029, 0.6134865982924396, 0.9370101427350266]` / source page 0。MIME image/png。

- `figure-0001` → Question `705f1d12-4f19-4c33-b197-39212f24b3ca`
  Asset ID `003a889e-aa53-4872-ad5d-c656de1beaef`
  SHA `38b76fdc5604d461b42eed6d22bbb4acf43610c1053efc46e62672625d64dc0d`
  role `student_drawing_area` / coordinate_space `normalized` / bbox `[0.4622159302203312, 0.457222946708473, 0.9261126456414636, 0.6840530319586505]` / source page 0。MIME image/png。

Confirm namespaceへcopyしてdurable TestQuestionAsset保存。sha256再検証成功。graphは問題2(2)だけ、complex planeは問題3だけ。教師承認cropはmodel実行とは区別し、vision_run_id/result_idはNULL、evidence_sourceを保持。

## 24. sampleQ4 Effective Context

全4 gradableでH.2-F builder成功。問題2の両childにparent instructionと同一quadratic formulaが入る。問題2(1)にgraphなし、問題2(2)だけgraphあり、問題3だけcomplex planeあり。

- ab3e65c7-7dca-4254-a4d9-757ebf675f28: `d22fa7635708ea157356f1b2aa23519b425c0dc9301441432a483c3cdde40805`
- 02669a76-cb99-4ea1-bfd4-c742ff1617a3: `ade40813e9cd8cc49633431fd5d0115dc6492cacfd990ce4111781bae2c7f897`
- 705f1d12-4f19-4c33-b197-39212f24b3ca: `d82fb622a874d1c8be0405237f96589384823253c0dcea7b5dda13097237fe41`
- 4c567426-da7a-4aae-bccc-a0026b69f219: `351bf4a111f267b36d647ea69fe3303a7b2b34651a6a1584979250f1c4381cbc`

## 25. sampleQ4 Grading Readiness

Question authoritative YES / max_points READY（4/4）/ Effective Context READY（4/4）/ assets integrity READY。全gradable: MISSING_MODEL_ANSWER / MISSING_RUBRIC。StudentSubmission/StudentAnswer未作成。Execution BLOCKEDのまま。

## 26. sampleQ2 protection

全既存row/artifact不変、4問max_points unset。Test.total_points既存100は配点根拠に使用しない。

## 27. sampleQ3 protection

corrected formulas・Confirmation・Correction・graph asset不変。graph SHA 3a5a7a8df0cea793905c1fe178999bafd24fd2dd4b93414bd0cc606131683958。

## 28. H.3-C readiness refresh

既存serviceによるread-only再評価: Q1 corrected authoritative/context正常、ModelAnswer/Rubric/Submission不足。Q2配点unset維持、MISSING_MAX_POINTS。Q3修正済みformula/graph不変。Q4 authoritative・配点・context/asset正常、ModelAnswer/Rubric/Submission不足。新しい採点判定ロジックを作っていない。

## 29. Model-call audit

Ricoh0 / Uni-MuMER2 / Ornith Reconstruction0 / Ornith Grading0 / GradingJob0。role math_ocr、model unimumer-qwen35-4b-q4km、RuntimeManager割当endpoint http://127.0.0.1:18080/v1。owned=true、startup約1.13s、処理約2.81s/1.29s。終了state=stopped、psでllama-server残存0。外部runtime/port3000操作なし。

## 30. PostgreSQL validation

PostgreSQL16.15 / Alembic0011_student_answer_recon。migrationなし。Q1 Correction1件追加、Q4 Test1・material1・native extraction1・automatic Draft1・refinement Draft1・Review2（旧automaticと承認refinement）・Confirmation1・TestQuestion5・Asset2。Domain/source/Review/Confirm servicesを使用しSQL直接UPDATEなし。DB resetなし。全既存保護対象rowとhistorical files不変。ModelAnswer/Rubric/Submission/Reconstruction/GradingJob全row fingerprintもH.3-C監査と一致。

## 31. Backend tests

最終: unittest242 tests OK / pytest253 passed（8955既存deprecation等warning）/ Ruff All checks passed。Refinement→Review→Confirm→教師crop durable assetのintegration test、source保存、text correction、comparison Confirm拒否、既存座標・階層・履歴回帰を含む。actual PostgreSQLでは5node・110点・context/asset ownership・stored LaTeXをassert。

## 32. Frontend validation

Frontendコード変更なし。typecheck/lint/buildは変更時のみの指示に従い未実施。既存Review UIを使うため、backendのregion metadata/preview変換とpinned crop APIを対応。

## 33. Playwright

今回は未実施。代わりにcurrent backend TestClientで全formula/drawingのReview evidence/crop APIとpage metadata APIが200、normalized metadata・PNG・overlay生成を確認。crop自体は目視済み。実ブラウザで確認済みとは扱わない。

## 34. Problems / limitations

Uni-MuMERのmatrix OCRは不正だったため採用せず、教師の明示LaTeXで解決。教師cropを扱うため既存Review/Confirmへ新evidence sourceを追加し、fake model出力にはしていない。原automatic Draftのfragmentationはそのままhistorical evidenceに残る。広範な自動領域検出の改善や一般OCR精度保証は本phaseの成果には含めない。

## 35. Remaining blockers

Question import/correctionに未解決blockerなし。採点には依然ModelAnswer/approved Rubric/実答案と必要なReconstructionが不足。sampleQ2配点unsetは意図どおり維持。

## 36. H.2-H final status

COMPLETE。Track A:承認後append-only Correction完了。Track B:承認数式/crop・5node・110点・blockers0でExplicit Confirm完了。

## 37. H.3-C.1 readiness

READY（Question-side準備）。次phaseで模範解答PDF処理/Rubric Draft生成へ進める。このphase中は4 sampleの模範解答PDFを一切使用していない。actual grading readyとは別。

## 最後の39質問への回答

1. はい。
2. 使用なし。
3. 作成なし。
4. 一致。
5. 一致。
6. 1箇所。
7. TEXT_ONLYのみ。
8. 停止済み。
9. 明示YES後適用。
10. 不変。
11. 不変。
12. 問題1(1)のみ、9節参照。
13. 対象leafのみ、descendantなし。
14. 不変。
15. Question PDFのみ。
16. 使用なし。
17. major3。
18. はい、structural parent+2 children。
19. 4問。
20. 30/20/20/40。
21. 110。
22. 補正なし。
23. 教師指定のpmatrix全文でresolved。
24. 教師指定式をparentに保存、両childから継承。
25. 保持・durable化済み。
26. 保持・durable化済み。
27. normalized0–1。
28. 目視済み。
29. durable TestQuestionAsset登録済み。
30. graph→q2(2)、complex-plane→q3、exact FK確認。
31. Explicit Confirm済み。
32. 全4問成功。
33. ModelAnswer/Rubric未追加。
34. 不変。
35. 不変。
36. 0。
37. 0。
38. COMPLETE。
39. H.3-C.1 READY（actual gradingは未準備）。

## Files changed / evidence

Backend: question_corrections.py, api/question_reviews.py, api/app.py, question_import.py, question_drafts.py, question_reviews.py, question_refinement.py, vision_policy.py, review_preview.py。Tests: tests/test_question_import.py。Frontend変更なし。

主な証跡: artifacts/h2h-preflight/q1-correction.json / q4-finalization.json / q4-canonical/manifest.json / q4-canonical/runtime-audit.json / api-verification.json / final-audit.json。original-baseline.json・旧source/IR/Draft/Reviewも保持。
