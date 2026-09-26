# Phase H.2-B Completion Report

本実装の成果物は教師確認前のcandidate-only Draftです。H.2-Bの完了条件を満たしました。TestQuestionへの登録・編集・確定は実装していません。

## 1. Existing architecture findings

`src/scoring/pdf_native.py`のDocumentIRはdataclassとdictによる`question-document-ir.v1`で、native evidenceはJSON artifactに保存されています。`QuestionImportExtraction`はDBの状態・parser/config参照、`TestMaterial`はPDF参照です。`api/app.py`がupload/status/documentを公開し、`RunArtifactAdapter.path()`にはroot外へのresolve拒否があります。既存DBはSQLAlchemyのString UUID、JSON、文字列stateを使用。調査時のAlembic headは`0005_question_import_extraction`でした。

## 2. Files changed / added

- 追加: `src/scoring/question_structure.py`
- 追加: `src/scoring/question_drafts.py`
- 追加: `src/scoring/api/question_drafts.py`
- 追加: `migrations/versions/0006_question_import_draft.py`
- 追加: `tests/test_question_structure.py`
- 追加: 本報告書
- 変更: `src/scoring/db/models.py`（専用2modelの追加）
- 変更: `src/scoring/api/app.py`（router登録のみ）

H.2-A/A.1、既存manual CRUD、grading、frontend、internal docs/.gitignoreは変更していません。既存の多数の未commit変更は維持しています。

## 3. DB migration

`0005_question_import_extraction → 0006_question_import_draft`。

`question_import_drafts.extraction_id → question_import_extractions.id`、`question_import_draft_nodes.draft_id → question_import_drafts.id`、nodeの`parent_id → question_import_draft_nodes.id`。

入力のunique constraintは`(extraction_id, source_ir_sha256, parser_version, parser_config_hash)`、nodeは`(draft_id, stable_key)`。既存migrationが現行metadata.create_allを呼ぶ事情に合わせ、fresh DBで既に作成済みのテーブルは重複作成しません。downgradeは新2テーブルのみ削除。既存DBのresetは行っていません。

## 4. H.2-B architecture

Document IR → LayoutProjector → QuestionStructureParser.build → QuestionDraftService → DB/artifact。

同期API処理です。grading jobやworkerには接続していません。DB/node保存はtransaction内で行い、途中失敗時はnodeをrollbackし、安全なerror codeを持つfailed recordを残します。artifactとDBは分散transactionではないため、書込み失敗時に非公開の部分artifactが残り得ます。

## 5. PyMuPDF independence

structure coreには`fitz` / `pymupdf` import、source PDF読込み、render、OCR、モデル呼出しはありません。既存のcanonical JSON hash関数だけを再利用しています。入力はIR dictです。新dependencyはありません。

## 6. Geometric ordering

font sizeの大きいspanをline anchor候補として優先し、vertical overlapまたは下端位置の近接でlineへ集約。派生lineをpage/y/x順、line内をx/y/source ID順に並べます。分数の小さな分子だけを先頭anchorにして本文の前へ分離する問題を避けます。

native reading_orderは上書きせず、各fragmentにnative_orderとbboxを保持。大きなline内horizontal gapは`ambiguous_geometric_order`。multi-column/table/複雑な数式の完全な順序保証はありません。

## 7. Major question detection

NFKCによるdetection textに対して行頭の`問題 N` / `問N` / `第N問`を確認します。番号後の境界を要求し、本文中のsubstringや`問題1について説明する`は大問化しません。表示・source本文はNFKCで上書きしません。patternはconfig/hash対象です。

## 8. Subquestion detection

行頭の`(N)`を候補とし、同一line内labelが1つ、後続内容あり、既存parentありの場合だけchild化します。inline複数label、内容のない番号欄は`inline_subquestion_label`としてreviewへ送ります。改行だけで意味が一意になるとは保証しません。

## 9. Hierarchy

major/subquestionの2階層。nodeにはparent_key、DBにはparent_id。stable keyは検出順からq1/q1.1等を生成するため、番号重複でも衝突しません。重複labelはreview。page breakだけではcurrent nodeを変更しません。

## 10. Question body grouping

次のlabelまで同じnodeへsource lineを関連付けます。math候補はbodyの平文化から外しformula fragmentsへ保持。配点は原文から破壊的削除しません。前文はdocument_preamble、ページ最下部はfooter_candidate、大きな画像内textはfigure_annotationとしてdocument_contextへ保持します。

## 11. Score extraction

`(30点)` / `(30 点)` / `(各20点)`等をNFKC比較で検出。direct、each_child、unset、ambiguousを使用。競合する複数score expressionはambiguous。raw evidenceはsource line、正規化expressionは一致部分として保持し、bbox精度はsource_lineと明示します。

## 12. Derived score candidates

each_childは明確なimmediate childrenがあり、inline/重複/親割当/geometric曖昧性やchildの別scoreがない場合のみ展開します。childは自身の明示scoreがないためsemantics=unsetを維持し、effective_points_candidateとderived_fromで親由来を明示します。

親aggregateは各点×child数。すべてのleaf candidateが明示または安全派生で解決した場合のみtotal_points_candidateを計算します。

## 13. Score safety

問題数やTest.total_pointsから推測しません。direct parentにchildrenがある場合は`direct_score_with_children`で子への分配を禁止します。前文のscoreは`unassigned_score_expression`として保持。authoritative max_pointsの書換えはありません。

## 14. Formula region grouping

math_like_candidate（旧IRのreview flagも対応）、bbox間の水平/垂直距離からconnected componentを生成します。regionにnative fragments、fonts、signal理由、source IDs、bboxを保持。同じcontent ownerが一つなら関連付け、複数ownerなら未割当。ownerがない場合はquestion開始位置と次nodeとの交差を確認します。LaTeXや式のlinearizeは生成しません。

## 15. Figure region grouping

page面積1%以上かつ短辺25pt以上の画像placementをseedにし、画像同士の重なり/包含/近接componentをまとめます。小さな記号画像をそれぞれ独立figureにしません。vector集約値だけからfigureを生成せず`unresolved_vector_evidence`を残します。画像の意味解釈は行いません。

## 16. Provenance

nodeのsource_regions: page_index、bbox、geometric_order、source_element_ids、native_orders。layoutにはnative fragmentsとfont/math evidenceも保持。regionはsource IDsとnative画像hash/refまたはtext fragmentsを保持します。native IRは変更しません。

## 17. Review flags

- ambiguous_geometric_order: line内の大きなgapなど順序が曖昧
- inline_subquestion_label: 独立childと決められない番号表記
- ambiguous_parent_assignment / duplicate_question_label: hierarchy候補の衝突
- score_scope_ambiguous: 複数score evidenceの競合
- each_child_without_clear_children: 各点を安全展開できない
- direct_score_with_children: 親配点を子へ分配しない
- unassigned_score_expression: nodeに属さない配点表記
- unassigned_formula_region / unassigned_figure_region: region割当が不明
- unresolved_vector_evidence: page-level vectorだけでは図と判断できない
- unassigned_content: bbox不足等で配置できない
- no_question_candidates: 大問候補なし

review_requiredは抽出失敗とは別です。現在の3PDFはすべてreview_required=trueです。

## 18. QuestionImportDraft schema

`question-import-draft.v1`: parser metadata、source_ir_sha256、nodes、document_context、formula_regions、figure_regions、unassigned_score_expressions、unassigned_content、total_points_candidate、review_flags/review_required。

node: stable_key、parent_key、node_type、depth、sort_order、raw/normalized label、body_text、source_regions、score、region IDs、leaf_candidate、review情報。通常APIはdocument_context/full layout/full region fragmentsを埋め込みません。

## 19. Draft DB model

Draftにはlifecycle、parser/version/config、source/draft hash、artifact ref、review、total、error、日時。nodeにはquery可能なlabel/body/score/parent/reviewとsource evidence JSON。UUIDや日時はdeterministic draft JSONのhashへ含めません。

## 20. Artifact structure

```
question-imports/<extraction-id>/
  native/ ...                         # 既存IRは不変
  structured/<draft-id>/
    layout-projection.json
    question-draft.json
    manifest.json
    diagnostics.json
```

parser/configの異なる実行が過去artifactを上書きしないようdraft ID単位に分離します。

## 21. Reproducibility

最終parser version: `question-structure-v1.1`（実装途中の検証版と区別）。configにはpattern/line/formula/figure閾値を保存。共通config hash:

`75577dfc6417f0aafb1b61dbc3ad96c5ce252fe08bcf537c98be2c08d28f0686`

source PDF hash、source IR hash/schema、native parser、structure parser/config、layout hash、draft hash、created_atをmanifestへ保存。created_atはcontent hashの外。同一IRの2回buildでlayout/draft hashとnative不変を確認しました。


実PDF回帰ではH.2-A.1の固定済みIRを使用しました。各hashは次の通りです。

sampleQ1:

- Source IR SHA-256: `d2e2e758ab8ede41d377a748eeeacb91efea23d711331946bfa362a45a54c896`
- Draft SHA-256: `cec6104b7ad58bb50eafe493f766a3cfa4e15309552cfc03567e587e5cee4579`
- Layout SHA-256: `0ba2931fd27699033b82da60d0a4761aeaebc96ed61a5a64efdb060168726cd8`

sampleQ2:

- Source IR SHA-256: `57a605ea76bf91931738ef7f181e9a8c468eb9970531196d39aa962fca03e08b`
- Draft SHA-256: `528d792845f2ba4c9ae100ecc06650822aea762059c9b0b8574f4fb3a1f4d7e1`
- Layout SHA-256: `ca92a604ed8c64e15dd4c73391d84a21643055a170d9820fc21b9652145b4dc7`

sampleQ3:

- Source IR SHA-256: `2ca408a45962fff99b190148994a745192106b177784c804c3ce6c75a3d1c853`
- Draft SHA-256: `74b18f0bc6d844a9a8d0f7c155d90bffa7a316949314901659c13716e9dc666a`
- Layout SHA-256: `7e38045851c9b54c09679ed58394dd684c88c9577cbe89d45aacb7fa29315df0`

実HTTP検証は通常uploadで新しいmaterial IDを採番するため、IR/hashは上記固定IRとは異なります。同一IRの反復処理と同一extractionへの再POSTの再現性をそれぞれ確認しています。

## 22. API

- POST `/api/v1/question-imports/{extraction_id}/draft`: completed extractionから生成（201）。同一入力は既存completed Draftを返す。
- GET `/api/v1/question-imports/{extraction_id}/draft`: 最新Draft（200）
- GET `/api/v1/question-import-drafts/{draft_id}`: metadata/nodes/score/region summaries（200）

404: 対象なし。409: extraction未完了/hash不整合/生成競合。invalid UUIDは422。errorは安全な固定messageとcodeで、stack traceを公開しません。artifact pathはRunArtifactAdapterのresolve検証を経由。source bytes hash、canonical hash、manifest、DBのparser/source metadataを照合し、不一致で処理を停止します。

## 23. Synthetic tests

21件追加（real PDF回帰1件、migration1件を含む）。順序派生とnative不変、each-child tree/total、no score、曖昧な各点、inline label、親direct＋children、formula fragments、image grouping、vector false positive、multi-page/footer、provenance、determinism、重複label/競合score、child explicit score、本文中の大問参照、未割当formula、config hash変更、failure rollback、API/冪等性/hash不一致/symlink、migration往復を検証しました。実PDFfixtureがない環境では当該1件のみskipします。今回は3PDFが存在しskipなしです。

## 24. Real PDF regression — sampleQ1

Automatic H.2-B result:

```
q1 each_child 20 / aggregate 40
  q1.1 effective 20
  q1.2 effective 20
q2 direct/effective 30
q3 each_child 10 / aggregate 30
  q3.1 effective 10
  q3.2 effective 10
  q3.3 effective 10
```

major 3、subquestion 5、total candidate 100。formula 0、figure 0。review: unresolved_vector_evidence。未割当content/regionは0/0（document_contextは別枠）。

## 25. Real PDF regression — sampleQ2

Automatic H.2-B result:

```
q1 unset
  q1.1 unset
  q1.2 unset
q2 unset (inline_subquestion_label)
q3 unset
```

major 3、subquestion 2。totalはnull。native order 0から始まる二次関数はbbox位置に従って問題2へ関連付けました。native orderは保持。

formula 4: 三次式→q1.1、x³=-8のnative fragments→q1.2、分数入り二次関数→q2、単独−1→q3。ここで式表記は読者向け識別であり、parserは数式文字列を再構成していません。figure 0。review: inline_subquestion_label / unresolved_vector_evidence。未割当content/region 0/0。

## 26. Real PDF regression — sampleQ3

Automatic H.2-B result: q1 direct 30、q2 direct 30、q3 direct 40。major 3、subquestion 0、total candidate 100。

formula 5: sin関連2region→q1、cos関連2region→q2、本文中のx→q3。figure 1→q3。graph bbox `[56.407, 660.101, 330.927, 777.431]`。画像placement16個を16図にはせず、main imageを含む1componentにまとめました。

review: ambiguous_geometric_order（q1の大きなspan間gap）/ unresolved_vector_evidence。未割当content/region 0/0。

## 27. Ground truth comparison

上記Automatic resultのartifact/hash固定後に原PDFを比較しました。原PDFの目視結果はparser入力にしていません。

Q1の大問3、小問2+3、各20/30/各10は一致。Q2は問題1の2つの式が独立した小問として配置され、問題2のinline指示と番号のみの答案欄は独立childとして確定しない結果が妥当です。配点はありません。Q3の大問3、30/30/40、問題3のgraph位置は一致しました。

## 28. False positive / false negative analysis

question label: 今回3PDFでは各3問を検出。自由な番号体系や複雑な段組は未保証。

subquestion: Q2問題2のinline表記を保守的にreviewへ送るため、潜在的な2つの課題をchildとしては表現していません。

score: 今回期待値と一致。bboxはtoken単位ではなくsource line単位。複数scopeは自動確定しません。

formula: Q2の−1、Q3本文のxも候補になり得ます。candidateだからといって直ちにVision必須ではありません。数式の分子・分母や指数の意味は確定しません。

figure: Q1/Q2のvectorから図を誤生成しません。Q3のgraphは検出。vector-only図や小さな図の検出は保守的です。

## 29. API / HTTP validation

一時uvicornは127.0.0.1:18086、実PostgreSQLへ接続。専用User/Course/Offering/Testを作成し、Q1/Q2/Q3ともupload 201 → draft POST 201 → GET 200 → 再POSTで同一IDを確認しました。GET最新Draftも成功。no absolute internal pathを確認。

最終HTTP Draft IDs:

- Q1: `3cbceec1-0a4c-445a-8d3c-95822f21aecb`
- Q2: `68dec40b-8a6c-4c55-928d-62e5e94b6110`
- Q3: `9ebaba7b-466e-45dc-9c8a-d71021e63d0b`

既存TestQuestion件数は4→4。専用検証データは明示名で残しています。一時APIは正常終了。既存サービス/port 3000は操作していません。

## 30. PostgreSQL validation

PostgreSQL 16.15、既存grader DBへ`alembic upgrade head`成功。新2table、node保存を確認。既存データ削除なし。SQLiteではupgrade → downgrade(0005) → upgradeを自動検証し、既存test_questionsテーブル維持を確認しました。

## 31. Tests

- `.venv/bin/python -m unittest`: 102 passed
- `.venv/bin/python -m pytest -q`: 113 passed
- `.venv/bin/ruff check`: All checks passed

既存FastAPI/PythonのDeprecationWarningとSQLite ResourceWarningは残っています。実モデル起動なし。frontend変更なしのためfrontend buildは実施していません。

## 32. Problems / limitations

単一段組を中心とする保守的heuristicです。multi-column・table・複雑な数式はreviewが必要です。現IRのvector summaryだけではvector-only図を復元できません。word/token単位のscore bboxはありません。初回source integrityの信頼点は既存native manifestとDB metadataであり、署名付き改ざん証明ではありません。

H.2-Bの完了を妨げる未解決事項はありません。candidateは教師確認前で、正しさを保証するauthoritative dataではありません。

## 33. H.2-C handoff

Q2の指数・分数を含むformula regions、Q3の三角関数/分数regionsをnative geometryのまま渡せます。Q3 graph regionは複数画像/周辺textの合成が必要になり得るため、将来page region renderingの候補です。単独−1や本文xはモデル投入前に必要性を再評価してください。Ricoh/VLMの必要性は現段階で自動決定していません。

## 34. Intentionally deferred

teacher edit、teacher confirm、TestQuestion import、TestQuestion hierarchy migration、Ricoh、Uni-MuMER、Ornith、Vision、formula recognition、grading、background worker、retry/pause/resume、frontendは未実装です。
