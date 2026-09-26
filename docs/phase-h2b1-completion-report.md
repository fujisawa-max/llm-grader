# Phase H.2-B.1 Completion Report

## 1. Existing architecture findings

`DocumentIR`は`src/scoring/pdf_native.py`、Document IRからの構造候補生成は`src/scoring/question_structure.py`、DB/artifact/API永続化は`src/scoring/question_drafts.py`、`src/scoring/db/models.py`、`src/scoring/api/app.py`にあります。Draft nodeの既存JSON evidenceを利用できるため、ordered contentは新しい正規化テーブルなしで保存できます。

## 2. Real Draft Evaluation findings addressed

body_textを維持したまま、本文中のtext、formula、figure、scoreの位置をsource elementとregionへ戻せるanchorを追加しました。PDF-point座標の意味を明示し、rotation/cropboxを扱う純粋な変換utilityを追加しました。mathの上下offsetはsemantic truthではなくrouting evidenceとして扱います。

## 3. Files changed

- `src/scoring/coordinate.py`: coordinate/render contract、bbox expansion、pixel conversion。
- `src/scoring/question_structure.py`: ordered content、coordinate contract fallback、region routing evidence。
- `src/scoring/question_drafts.py`: node evidence、Draft response、manifestへの追加情報。
- `src/scoring/pdf_native.py`: 新規IR生成時の明示的coordinate metadata。
- `src/scoring/api/app.py`: Document endpointへcoordinate metadataを追加。
- `tests/test_question_structure.py`: anchor、routing、rotation、cropbox、clipping、multi-page fixture。

既存のscoring pipeline、worker、RuntimeManager、TestQuestion schemaは変更していません。

## 4. DB / migration decision

Migrationはありません。ordered contentは既存`QuestionImportDraftNode.evidence` JSONへ保存し、Draft artifactにも保存します。実PostgreSQLのAlembic headは`0006_question_import_draft`のままです。既存Draftは削除せず、parser versionを更新したDraftを追加しました。

## 5. Ordered Content design

各nodeに`ordered_content`配列を追加しました。各itemは`order`、`type`、`text`、`region_id`、`page_index`、`bbox`、`source_element_ids`、`geometric_order`、`native_orders`、`coordinate_space_ref`を持ちます。同一layout line内はgeometry orderを優先し、line内はx位置で決定します。

## 6. Content item types

`text`、`formula_region`、`figure_region`、`score_expression`を実装しました。formulaはlinearizeせずregion参照、scoreは既存semanticsを変えずanchorだけ追加しています。

## 7. body_text compatibility

既存`body_text`の生成・field名・score semanticsは維持しました。ordered contentは追加情報です。数式をbodyへ再挿入する処理は行っていません。

## 8. Formula anchors

assigned formula regionをsource bbox、source span IDs、native order、geometric lineへ結び付け、node内の位置に並べます。数式文字列の再構成やLaTeX生成はありません。

## 9. Figure anchors

既存のimage clusteringとgraph region assignmentを維持し、assigned figure regionをordered contentへ追加しました。embedded imageのhash、artifact reference、source IDsは維持されます。

## 10. Score anchors

既存score evidenceのsource IDs/bboxを使い、`score_expression` itemを生成します。`direct`、`each_child`、`unset`、`ambiguous`の意味は変更していません。

## 11. Provenance

node、score、formula、figureのsource element IDsからIR elementへ戻れます。region itemにはnative orderをsource fragmentから集約しています。画像artifactは既存relative referenceを再利用します。

## 12. Multi-page readiness

ordered contentはpage_indexを各itemに持ち、複数ページを同一nodeへ並べられます。multi-pageの実PDFでは未実証です。

## 13. Coordinate contract

coordinate space IDは`pdf-point-unrotated-page`です。unitは`PDF_point`、originはtop-left、xは右、yは下、bboxはmediabox基準のunrotated座標です。cropboxをrender viewportとして使用し、page rotationを時計回りに適用します。IRの既存metadataが古くても、Draft/layout生成時にこのcontractを補完します。

## 14. PDF-point to pixel conversion

source bboxをcropboxへclipし、cropbox左上を原点へ移し、rotationを適用してから`scale = DPI / 72`相当でpixel化します。左上はfloor、右下はceilとし、ページ外はclip情報を返します。

## 15. Rotation handling

0°、90°、180°、270°を純粋な矩形変換で実装しました。90°/270°ではrendered width/heightをswapします。fixtureで各回転の位置とサイズを検証しています。

## 16. Cropbox / mediabox handling

入力bboxはmediaboxのunrotated座標、render対象はcropboxです。cropbox offsetを差し引いてから回転するため、mediaboxとcropboxの原点が異なるケースをテストしています。

## 17. Margin / clipping utility

`expand_bbox()`は固定marginまたは4方向marginを受け、任意のboundsへclipします。`pdf_bbox_to_pixel()`はsource clippingとpixel clippingを`clipped`で示します。負座標やページ外pixelを返しません。

## 18. Math routing evidence semantics

formula regionに`routing_evidence`を追加しました。math font/text、math-like、superscript/subscript geometryのspan count、reason list、`strength`（strong/supporting/weak）、`semantic_assertion: none`を保持します。最終的なVision routing判定は実装していません。

## 19. Superscript / subscript semantics

上下offsetは「neighbor spanに対するgeometry evidence」です。指数・添字・分子分母を意味するsemantic labelへ変換しません。H.2-Cは単独の上下offsetをroutingの十分条件にしてはいけません。

## 20. Formula-region routing evidence

regionごとにsource span数、math font/text数、math-like数、上下offset数、理由、evidence strengthをdeterministicに集約します。順序はsorted listを使いhashを安定させています。

## 21. Draft schema/version decision

`question-import-draft.v1`を維持しました。ordered content、routing evidence、coordinate metadataはいずれもadditiveです。生成内容が変わるためstructure parserは`question-structure-v1.2.1`へ更新しました。

## 22. Parser/config/hash changes

configへ`ordered_content_version`と`routing_evidence_version`を追加し、parser version/config hashへ反映しました。実DBの最終config hashは`8773d3cd81be5f7306dae3c828dd7ef8edcbc7d192c418ba63accbebb59e7532`です。

## 23. Synthetic tests

text→formula→text、複数ページ、score/figure anchor、determinism、rotation 0/90/180/270、cropbox offset、margin clipping、routing evidence、semantic誤解釈防止を追加しました。

## 24. Real regression — sampleQ1

8 nodes、major 3、subquestion 5、`each_child 20`、`direct 30`、`each_child 10`、total candidate 100、formula 0、figure 0を維持しました。ordered contentとscore anchorが生成され、既存tree/bodyは壊れていません。

## 25. Real regression — sampleQ2

5 nodes、major 3、subquestion 2、score全件unset、formula 4、figure 0を維持しました。問題2のinline label reviewは維持され、formula regionはq1.1/q1.2/q2/q3へordered anchorされます。native fragmentsはlinearizeしていません。

## 26. Real regression — sampleQ3

3 nodes、score 30/30/40、total 100、formula 5、figure 1、graph=q3 assignmentを維持しました。graph bboxとimage hash/artifact referenceは維持され、ordered contentからfigure位置を追跡できます。

## 27. Coordinate readiness for H.2-C

Draftのcoordinate contract、page size、rotation、cropbox、mediabox、region bboxからpixel targetを計算できます。今回の実PDFはrotation 0です。実際のrender/crop画像生成は未実装です。

## 28. Teacher Review readiness

node選択、PDF bbox highlight、本文とformula/figure参照の並列表示に必要な基礎情報があります。編集確定にはordered text offsets、region挿入位置のより細かいanchor、revision/競合管理が次に必要です。

## 29. API compatibility

既存Document GET、Draft GETのfieldは削除・renameしていません。coordinate metadata、ordered content、routing evidenceは追加です。absolute filesystem pathは返しません。

## 30. Reproducibility / hashes

同一IR/configでordered content、routing evidence、layout hash、draft hashがdeterministicです。実DBで最終Draftは3件ともartifact hashを検証し、GET再取得でstable keyと内容が一致しました。

## 31. PostgreSQL validation

既存PostgreSQL `grader`へ3 extractionから最終Draftを生成し、各Draft GETでcoordinate ID、ordered content、node count、formula/figure count、draft hashを確認しました。DB resetは行っていません。

## 32. Tests

- `.venv/bin/python -m unittest`: 106 tests、OK
- `.venv/bin/python -m pytest -q`: 117 passed（既存FastAPI deprecation warning 990件）
- `.venv/bin/ruff check`: All checks passed

## 33. Problems / limitations

body_textは既存互換の便利な文字列であり、数式の本文内挿入位置を表すauthoritative編集表現ではありません。上下offset signalには分数・通常レイアウト由来の誤判定余地があります。vectorはpage summaryのままでsemantic figureではありません。非zero rotationの実PDFrenderは未検証です。

## 34. H.2-C handoff

H.2-Cは、formula/figureのassigned question、page、PDF-point bbox、coordinate_space_ref、source IDs、native/geometric order、routing evidence、image artifact referenceを利用できます。formulaはmath font/textと複数fragmentを主根拠にし、上下offsetだけでVision requiredとしないでください。graphは元PDF全レイヤー合成を前提にregion renderします。

## 35. Intentionally deferred

actual rendering、Ricoh、Uni-MuMER、Vision routing policy、formula reconstruction、teacher edit、confirm/import、TestQuestion migration、gradingは未実装です。

