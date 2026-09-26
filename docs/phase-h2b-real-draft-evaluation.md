# H.2-B Real Draft Evaluation

評価対象は既存completed Draft 3件です。PostgreSQLをREAD ONLY transactionで読み取り、DB → Draft artifact → layout → Document IRの順に評価用snapshotを保存し、hash固定後に原PDFの既存全ページ表示と比較しました。新規Draft生成、parser呼出しによる再生成、threshold変更、原PDFからの補正は行っていません。モデル/OCR/Visionや新規region renderingも未実行です。

結論: 階層・配点・provenance・hash整合性は良好です。Q1は軽微な表示整形で教師レビュー可能。Q2/Q3は数式分離後のbody_textが不完全なため、body_text単独をeditable authoritative本文として扱えません。数式/図のregion bboxは今回の3PDFに対して概ね利用可能ですが、数学geometry signalの誤判定と合成figureの扱いを明示する必要があります。

## 1. Environment

- commit: `6aa6ed62ed23ad14add3bff881cac48f4d485468`。H.2-Bは未commitのworkspace実装を含むためcommitだけでは再現できません。評価開始時のsrc/tests/migrations/frontendのfile hashも記録しました。
- DB: 既存PostgreSQL grader（read-only参照）、Alembic `0006_question_import_draft`
- IR: `question-document-ir.v1`
- Draft: `question-import-draft.v1`
- Structure parser: `question-structure-v1.1`
- Config hash: `75577dfc6417f0aafb1b61dbc3ad96c5ce252fe08bcf537c98be2c08d28f0686`
- 3PDFともpage_index=0、1ページ、rotation=0、cropbox=mediabox、約594.96×842.04 PDF points。

## 2. Evaluated Drafts

DBのsource SHAとcompleted stateから選択した最新既存Draftです。過去の試行Draftは変更していません。全件state=completed、review_required=true。
### sampleQ1

- source PDF: `testData/SampleQ/sampleQ1.pdf`
- source SHA-256: `0150d09e60e794b05b7d4bc5bcb6715c585aba06ccfa588de88a0dea8ae36ea3`
- extraction ID: `13edc574-2cdc-4013-89cd-ddda666b8f58`
- source IR SHA-256: `415764a74bfa2fbededc16b5c964dd0c34705634d51c7cfaa0da6e3ef59560f4`
- draft ID: `3cbceec1-0a4c-445a-8d3c-95822f21aecb`
- draft SHA-256: `475767a8c2cadafcbd4e75d92cd3f91900580f62df2da54f34ac805cf3fe10f0`
- layout SHA-256: `0ba2931fd27699033b82da60d0a4761aeaebc96ed61a5a64efdb060168726cd8`

### sampleQ2

- source PDF: `testData/SampleQ/sampleQ2.pdf`
- source SHA-256: `f2246b8ad5311195b6e969a812748080cc3bf2f846fa4e5ba3ab2cf408cd954f`
- extraction ID: `aabd0f8e-9bd0-4c1e-937c-1d2f71938563`
- source IR SHA-256: `c7f9a614d5e08b2e9e1376f39c23ca8e54d07a1076698656a1e5d8b7a53e7d03`
- draft ID: `68dec40b-8a6c-4c55-928d-62e5e94b6110`
- draft SHA-256: `41180e5ef5ef0099b06c77c41fd5bd6c70f445f87279fdb912af3a3dd20e5da7`
- layout SHA-256: `ca92a604ed8c64e15dd4c73391d84a21643055a170d9820fc21b9652145b4dc7`

### sampleQ3

- source PDF: `testData/SampleQ/sampleQ3.pdf`
- source SHA-256: `1da0211a68e1a709c6b61bc08ed84f6d403d1cdafc6e556c8489e5801d883fe1`
- extraction ID: `3d2e1962-3a59-420f-bec2-4ac1cadc121e`
- source IR SHA-256: `4cb48f10edb97b8d4d945d732b13b2687b0315db0b8f1ef5572e62764f5b340e`
- draft ID: `9ebaba7b-466e-45dc-9c8a-d71021e63d0b`
- draft SHA-256: `1fee5a73dccd5aec4a232e6c47631e3edddb7b41989ddf0c94826f3b3391feda`
- layout SHA-256: `7e38045851c9b54c09679ed58394dd684c88c9577cbe89d45aacb7fa29315df0`

## 3. Draft Tree Summary

Automatic Draft Result。effectiveは派生候補、nullは未設定です。

### sampleQ1

```text
q1 問題1 [each_child; points=20.0; effective=None; aggregate=40.0]
  q1.1 (1) [unset; points=None; effective=20.0; aggregate=None]
  q1.2 (2) [unset; points=None; effective=20.0; aggregate=None]
q2 問題2 [direct; points=30.0; effective=30.0; aggregate=None]
q3 問題3 [each_child; points=10.0; effective=None; aggregate=30.0]
  q3.1 (1) [unset; points=None; effective=10.0; aggregate=None]
  q3.2 (2) [unset; points=None; effective=10.0; aggregate=None]
  q3.3 (3) [unset; points=None; effective=10.0; aggregate=None]
```

Total candidate: 100.0

### sampleQ2

```text
q1 問題1 [unset; points=None; effective=None; aggregate=None]
  q1.1 (1) [unset; points=None; effective=None; aggregate=None]
  q1.2 (2) [unset; points=None; effective=None; aggregate=None]
q2 問題2 [unset; points=None; effective=None; aggregate=None]
q3 問題3 [unset; points=None; effective=None; aggregate=None]
```

Total candidate: None

### sampleQ3

```text
q1 問題1 [direct; points=30.0; effective=30.0; aggregate=None]
q2 問題2 [direct; points=30.0; effective=30.0; aggregate=None]
q3 問題3 [direct; points=40.0; effective=40.0; aggregate=None]
```

Total candidate: 100.0

## 4. sampleQ1 — Draft Evaluation

### Tree

Automatic Draft Result: 大問3、小問5。q1のchildrenはq1.1/q1.2、q2はleaf、q3はq3.1/q3.2/q3.3。parent/depth/stable_keyはDB/artifactとも一致。

### Body text quality

q1/q1.1/q1.2/q3.1/q3.2/q3.3はOK。q2/q3はMINOR_ISSUE（「説明しなさ\nい」「説明し\nなさい」の紙面改行を保持）。末尾空白・label重複表示・配点の本文残存は整形課題で、隣の問題やheaderの混入はありません。全nodeのbody_textは付録Aに原文のまま表示します。

### Score semantics

q1はeach_child=20、aggregate=40、child effective=20/20。q2はdirect=30。q3はeach_child=10、aggregate=30、child effective=10/10/10。total=100。子のsemantics=unsetは「子自身には明示配点なし」の意味で、derived_fromを通じて親expressionへ戻れます。UIでunsetだけを表示すると誤解を招くためeffective/derived_fromも表示すべきです。

### Provenance

全source element IDをIRに解決でき、page/bbox/native orderも保持。配点はsource_line bboxのため「各20点」だけでなく直前本文まで含みます。q1 line4、q2 line8、q3 line10が配点source。完全なID/evidenceは付録Aに掲載。

### Review flags

Draft-level unresolved_vector_evidenceのみ。node-levelは全件なし。座席欄等の24 drawingsというnative集計に対する注意で、Q1問題内容の不備を意味しません。

### Unassigned content

unassigned content/formula/figure=0/0/0。document_preamble 4lineにタイトル、学籍番号、名前、座席番号、注意書きを保持。q1 bodyへ混入なし。

### Ground truth comparison

原PDFと大問3・小問2+3・本文境界・各20/30/各10の位置が一致。native抽出本文は評価時に書換えていません。原文の用語の妥当性・教師の作問意図は今回の判定対象外です。

### Teacher review readiness

ほぼそのまま原PDFと照合可能。構造/点数の修正は必要と見られず、紙面折返し/空白など軽微な表示整形が望ましいです。confirm処理は未実装・未実行。

## 5. sampleQ2 — Draft Evaluation

### Tree

Automatic Draft Result: q1→q1.1/q1.2、q2、q3。問題2はchildなし。

### Problem 1 child nodes

q1.1: label（１）、page0、bbox [55.92,196.50,252.15,212.54]、geometric line6、native orders 18/19/20/22/23/25。
q1.2: label（２）、bbox [55.92,303.81,142.08,319.85]、line7、native orders 27/28/29/31。
両者とも左端約55.9ptに独立配置、parent=q1。式はそれぞれformula-0001/0002として保持。

### Problem 2 inline-label handling

q2にinline_subquestion_label。line8、bbox [55.92,412.28,476.98,424.28]、source IDs `page-0001-span-0009-0000-0000` / `page-0001-span-0009-0000-0001`（native33/34）。後者raw textは「次の関数について、（１）式を因数分解しなさい（２）式を平方完成に変形しなさい」。line12の番号のみの答案欄「（１） （２）」も独立childにはしません。source IDは`page-0001-span-0012-0000-0000`、bbox [55.92,495.63,460.96,505.59]。review flag自体に専用evidence IDはないため、node.source_regionsから辿ります。

### Body text quality

q1=MINOR_ISSUE（折返し）。q1.1/q1.2=REVIEW_NEEDED（body_textは番号だけで、式が別region）。q2=REVIEW_NEEDED（式が抜けて空改行3つと答案欄labelが残る）。q3=REVIEW_NEEDED（「−1」が分離され「問題３ という三重根…」になる）。body_text単独の読み物としては不十分です。原PDF＋formulaを併記すれば情報自体は失われていません。

### Geometric order

native0〜6の二次関数はheaderより前でしたが、derived line9〜11となり問題2の後へ移動。native order値はすべて維持。関数内部は3つのlineに分かれ、「1 −2x −5」「y = − 3 x 2」「3」という順で、正しい数式reading orderではありません。formula-0003は全体を1bboxへまとめています。

### Score unset verification

5nodeすべてsemantics=unset、points/effective/aggregate=null、total=null。架空配点なし。

### Formula regions / Formula-to-question assignment

4regionを全件監査（第7節）。三次式→q1.1、x³=-8→q1.2、分数入り二次関数→q2、−1→q3。assignmentはいずれも原PDFと整合。−1はnative sufficientでVision不要です。

### Review flags / Unassigned content

Draft: inline_subquestion_label / unresolved_vector_evidence。node: q2のみinline_subquestion_label。region-levelは全件[]。unassigned=0/0/0、preamble4line。数式内部line分割やbodyの−1欠落は現在flagされていません。

### Ground truth comparison

問題1の小問2件は妥当。問題2は2操作を指示するが、inlineのため確定child化しない保守的判断は妥当。原PDFの指数2はIRでsubscript候補になっており、native math signal方向を信頼できない箇所があります。

## 6. sampleQ3 — Draft Evaluation

### Tree / Score 30/30/40

Automatic Draft Result: q1/q2/q3、childなし、direct/effective=30/30/40、total100。3箇所ともsource lineとIR elementへ辿れます。

### Body text quality

q1=REVIEW_NEEDED: 「問題１ の値を、 の関係式を利用して…」と2式が抜け、分母lineに対応する空行が残る。
q2=REVIEW_NEEDED: 「問題２ の値を、 の関係式を利用して…」と2式が抜ける。
q3=REVIEW_NEEDED: 「x軸」のxがformula-0005に分離され、bodyは「軸方向…」。次問/header混入はありません。

### Formula regions

5region。sin式→q1、加法定理→q1、cos(π/12)→q2、cos差の式→q2、本文x→q3。CambriaMath evidenceあり。4つのvisibleな式に対応するgroupは過剰merge/splitなし。5番目は本文inline変数で、Vision投入候補としては過剰です。

### Graph figure region / Figure-to-question assignment

figure-0001→q3。page0 bbox [56.407,660.101,330.927,777.431]。既知referenceと一致し、graph本体・画像化された軸ラベル・native数値textを幾何的に包含。本文は含まれません。
16 image placementsを1regionへ集約。主画像762×325pxには数値/πラベルが欠けています。図の正しい見た目を得るには、このbboxで原PDFの全レイヤーを合成renderする必要があります。画像1枚だけをVisionへ渡すことは不適切です。

### Review flags

Draft: ambiguous_geometric_order / unresolved_vector_evidence。q1: ambiguous_geometric_order（離れた4分母を同じline6に集めた結果、水平gap約179.2ptが閾値90ptを超える）。figure regionは[]。document_contextのgraph注釈line15にもambiguous_geometric_orderがありますが、その詳細はAPI summaryでは公開されません。

### Ground truth comparison

大問、配点、graph位置は一致。原PDFに見える軸ラベルはregion内ですが、figure.image_evidenceだけではnative text/vectorを明示的にリンクしていません。図の意味認識は未実行。

## 7. Formula Region Audit

全9region、page_index=0、font=CambriaMath、region.review_flags=[]。F=math_font_candidate、M=math_like_candidate、T=math_text_candidate、U=superscript_candidate、D=subscript_candidate。U/Dは指数・添字の確定意味ではありません。bboxはPDF point。完全なsource IDs/native fragmentsは付録B。

| sample | region ID | assigned question | bbox | source fragment summary（非linearized） | math evidence | review flags | Vision handoff classification | crop recommendation |
|---|---|---|---|---|---|---|---|---|
| Q2 | formula-0001 | q1.1 | [85.94, 196.50, 252.15, 212.54] | 2𝑥 / 3 / −21𝑥 / 2 / + 69x −70 = 0 | F/M/T | [] | EXPAND_MARGIN; Vision recommended | 指数を含む5span。上下2–3pt、左右2pt。小問labelを含めない |
| Q2 | formula-0002 | q1.2 | [90.98, 303.81, 142.08, 319.85] | 𝑥 / 3 / = −8 | F/M | [] | EXPAND_MARGIN; Vision recommended | 3span。上下2–3pt、左右2pt。native geometryで足りるならVision省略 |
| Q2 | formula-0003 | q2 | [72.38, 460.37, 190.83, 494.47] | y = − / 1 / 3 / 𝑥 / 2 / −2x −5 / 3 | F/M/T/D | [] | EXPAND_MARGIN; Vision recommended | 7span・分数全体。上下3pt、左右2pt。下の答案欄まで約1.17ptなので下余白は衝突確認 |
| Q2 | formula-0004 | q3 | [106.10, 649.10, 120.50, 660.15] | −1 | F/M | [] | NOT_NEEDED; Native sufficient | 単独−1。crop不要、本文内参照として保持 |
| Q3 | formula-0001 | q1 | [105.02, 161.22, 206.50, 186.55] | sin / 5 / 12 / 𝜋+ sin / 1 / 12 / 𝜋 | F/M/D/U | [] | EXPAND_MARGIN; Vision recommended | 分子/分母を包含。上下3pt、左右1–2pt。右に約0.28ptで「の値を」が続く |
| Q3 | formula-0002 | q1 | [246.77, 161.22, 432.04, 186.55] | sin 𝑥+ sin 𝑦= 2 sin / 𝑥+𝑦 / 2 / cos / 𝑥−𝑦 / 2 | F/M/T/D/U | [] | EXPAND_MARGIN; Vision recommended | 和積公式全体を包含。上下3pt、左右1–2pt。右の本文との境界確認 |
| Q3 | formula-0003 | q2 | [102.14, 369.81, 146.23, 395.14] | cos / 1 / 12 / 𝜋 | F/M/D/U | [] | EXPAND_MARGIN; Vision recommended | cosと分数/πを包含。上下3pt、左右1–2pt。下の本文との間約2.07pt |
| Q3 | formula-0004 | q2 | [191.57, 376.50, 383.35, 388.51] | cos(𝑥−𝑦) = cos 𝑥 cos 𝑦+ sin 𝑥 sin 𝑦 | F/M/T | [] | NOT_NEEDED; Native sufficient | 1spanのcos差公式。文字列が読め、Visionを無条件実行する理由なし |
| Q3 | formula-0005 | q3 | [56.42, 606.14, 61.72, 616.11] | 𝑥 | F/M | [] | NOT_NEEDED; Native sufficient | 本文「x軸」のx。cropせず本文位置を保持 |

これらはartifact bboxと原PDF全ページ表示の比較による評価で、実crop画質・切断のpixel検証やUni-MuMER精度試験ではありません。主要6式のbboxの取り直しは必要と見られず、margin/周辺衝突確認をH.2-Cで行えます。

## 8. Figure Region Audit

| sample | region ID | assigned | bbox | evidence | flags | handoff | routing |
|---|---|---|---|---|---|---|---|
| Q3 | figure-0001 | q3 | [56.407,660.101,330.927,777.431] | 16placements / 11xref / text+画像+vector合成 | [] | MERGE_WITH_TEXT（元PDF page composition）、bboxはREADY_AS_ISに近い | Vision required（図の意味を自動抽出する場合） |

主画像: `images/embedded/xref-35-2b20fee7e9c6c7ac.png`、762×325px、SHA `2b20fee7e9c6c7ac64f815575caa265d13b44cca8072f42dfb86406c6c70c355`。

図に重なるnative textはnative order66/70/73/76の`2 / 2 / 3 / 3`。document_contextのfigure_annotationとして保存されています。符号・π等は他の画像componentにも存在します。vectorは39drawingsのpage集約（union [86.4,42.4,525.35,762.31]）のみで、graphだけのvectorを区別できません。4textと全image bboxはfigure bbox内。margin拡大で失われた既知ラベルを取り戻す必要はなく、全レイヤー合成が本質です。全placements/hash/refは付録C。

## 9. Geometric Order Audit

- Q1: node順と小問順は良好。preambleではタイトルと右の学籍番号欄を同じlineにmergeしますが、questionへ混入しません。
- Q2: native0〜6がderived line9〜11に移り、問題2へ正しく割当。ただし数式内部が3lineへ分離するためlayout.textを正しい式として連結してはいけません。問題1の指数は同じvisual lineにgroupされています。
- Q3: 分子/基線側と分母側を別lineにgroup。q1の分母4個「12 12 2 2」は同一lineとして跨ってmerge。formula groupingは2式を区別しており、region境界は維持。
- 全件、layout fragmentsのnative_orderとIR.reading_orderは一致。日本語折返しが新Questionになる現象はありません。

## 10. Provenance Audit

16node、9formula、1figure、6score expressionsを全件確認。source IDsは存在し、page一致・region bboxがsource bboxを包含。child派生配点はderived_from→親score evidenceで追跡可能。

node source_regions→geometric_order→layout.fragments→element ID→native IRという経路が成立。figure→画像16placementsは完全。figureの周辺textはdocument_context/IR geometry経由で追えるが、figure.regionに明示的なrelated_text_idsはありません。個別vector provenanceはIRにないため追跡不可で、page集約までです。

## 11. Review Flag Audit

| flag | location | evidence | 人が確認すべき点 / usefulness |
|---|---|---|---|
| unresolved_vector_evidence | 全Draft | Q1=24/Q2=26/Q3=39drawings、page集約のみ | 図か罫線か。消失警告ではない。Q1/Q2ではノイズ寄りでLOW priorityが適切 |
| inline_subquestion_label | Q2 draft / q2 | line8の指示文とline12の答案欄label | 操作2つをchildにすべきか教師判断。有用 |
| ambiguous_geometric_order | Q3 draft / q1 | line6の離れた4分母 | 式内部順序をline textから信用しない。有用だが理由が直接リンクされない |
| ambiguous_geometric_order | Q3 document_context line15 | graphのx軸上の2と2が離れている | graph注釈として自然、通常文章の順序異常ではない |

formula/figure region flagsはすべて空。Q1 node flagsも全件空。大量flagではありませんが、body内の必須数学token分離とQ2内部式line分割に対する注意は不足。H.2-A.1のvertical_offset_candidateは元IRにあり、Draftのreviewへそのままは伝播しません。

## 12. Unassigned Evidence Audit

3PDFともunassigned_content=0、未割当formula=0、未割当figure=0、unassigned_score_expressions=0。これは全文が完成したことを意味しません。Q1/Q2はpreamble各4line、Q3はpreamble5line＋figure_annotation3lineとして別保存。空白だけのnative spanはlayoutへ入らず、元IRに残ります。今回footer候補はありません。

## 13. DB vs Artifact Consistency

DB node count=8/5/3。stable_key、parent_id→parent_key、raw/normalized label、body_text、score semantics/points/effective/aggregate、review flags/required、source_regionsが一致。Draftのreview_requiredとtotalも一致。GET serviceを2回呼び同一内容、stable key不変を確認。新しい生成POSTは行っていません。H.2-B時のHTTP再POST冪等性結果は既存記録として確認。

## 14. Hash / Manifest Verification

source PDF実体（testDataと保管source.pdf）、IR実file/canonical JSON、layout、Draft、structure configのhashを再計算してDB/manifestと照合し、3件すべて一致。画像artifactのhashも一致。schema/parser metadataも一致。今回のfrozen-index.json/audit.jsonに照合結果を保存。hash mismatch/provenance断絶はありません。

## 15. Draft Schema Review Readiness

stable identity、parent/depth、editable body field、score candidates/semantics、source位置、formula/figure IDs、review flagsは存在し、tree＋PDFを表示する土台はあります。

不足候補: ordered content parts（textとmath/figureの挿入位置）、text offset/anchor、region→注釈textのリンク、flag→evidenceの明示リンク/対象page、編集revision/競合tokenと編集履歴。stable_keyは同一IR/config内で安定しますが、再解析や挿入後のidentity継承は保証しません。これらを今回は追加していません。

## 16. Side-by-Side UI Readiness

source_regionsのpage/bboxで複数highlight可能。node選択→複数region/pageの表現もあります。API GETだけではPDF binary取得URLやcoordinate_space/page rotationを含まないため、extraction/document GETとのjoinと、将来の安全なPDF配信endpointが必要。現在のAPIを変更せず、内部絶対pathを公開する必要もありません。

formula full fragments/理由、document_context、layoutはartifactにはありますが通常Draft GETはsummaryです。既存document?page=0からsource IDをjoinすれば個別font/qualityは参照できます。図注釈の所属・数式の本文内表示順はUIが推測せず参照できる契約が望ましいです。

## 17. H.2-C Selective Vision Readiness

Q2: F1/F2/F3=Vision recommended、F4=Native sufficient。Q3: F1/F2/F3=Vision recommended、F4/F5=Native sufficient。数式regionがあること自体はVision必須を意味しません。native geometryだけで将来認識可能な式も含むため、数式6件についてVision requiredとは断定しません。

Q3 graph: graphの意味・軸情報を自動抽出するにはvisual informationが不可欠なためVision required。ただし教師のPDF確認用途だけならVision不要。region座標は利用可能で、page composition（画像+text+vector）が必要です。回転0の今回3PDFに限るcrop準備度は高いです。

## 18. Proposed Uni-MuMER Routing Conditions

まずmath-font/text evidenceで候補を限定し、複数fragment・基線差・上下に離れたfraction-like配置・native文字列だけでは式が定まらない場合に推奨します。例: Q2 F1〜F3、Q3 F1〜F3。

単独−1、本文x、1spanで読めるcos差式は省略候補。review_flags空でも数式構造が自明とは限りません。superscript/subscript単独を必須/十分条件にしないこと。Q2実指数のfalse negative/誤方向と通常文false positiveが確認されたためです。

## 19. Proposed Ricoh Routing Conditions

imageにgraph/diagram本体があり、native文字列から曲線・相対位置・画像内文字を理解できない場合にpage region合成像を候補とします。Q3 figure-0001が具体例。Q1/Q2のvector_countだけではRicohへ送る根拠になりません。画像中のπや符号、native数値の対応は見た目で統合する必要があります。モデル精度は今回未評価です。

## 20. Region Crop Recommendations

formulaは固定marginだけより、周辺spanとの衝突を抑えるline/font-height基準（例: 上下0.2em程度、左右1〜2pt、page境界でclip）が適切。2〜3ptは今回の初期検討値でありconfigの変更ではありません。

Q2 F3の下は答案欄まで約1.17pt、Q3 F3は下の本文まで約2.07ptしかないため、単純に全方向3〜5pt拡張しないこと。Q3 F1/F2/F3は本文が隣接し、数式専用cropと文脈付きcropを区別して考える必要があります。

graphは全pageレイヤーを含む現bbox＋任意の3〜5pt余白を候補とします。既知ラベルはbbox内にあるので、大幅拡張や本文とのmergeは不要。未実施のrenderによるpixel検証後にmarginを決めてください。

IRにpage、bbox、unit、width/height、cropbox/mediabox、rotationはあります。ただし`rotation: page_rotation`とbasis説明だけではbboxが回転前/回転後のどちらかやpixel変換のcontractが十分明確でありません。今回は全件rotation0/cropbox原点0なので問題は現れていません。任意PDFのrendererを完成扱いにする前に、非zero rotation/offsetの変換を明示・検証する必要があります。

## 21. Problems Found

| ID | category | symptom / sample | likely cause | severity | recommended fix phase |
|---|---|---|---|---|---|
| P1 | H.2-B body / Draft schema | Q2小問が番号だけ、q3の−1脱落、Q3の2式/本文x脱落。該当nodeの多くに注意flagなし | math spanをbodyから除き、再挿入anchorを保存しない | HIGH（teacher review/confirm向け） | H.2-B refinementまたはReview契約整備。ordered content/evidence linkを決めてから編集UI |
| P2 | H.2-A/A.1 quality signal | Q2指数2→subscript。通常日本語37字・空白→superscript。Q3配点文もsubscript | 大きさと近傍bboxだけで別行本文/分数/指数を混同 | HIGH（自動fallback routingの入力として） | H.2-C前のsignal契約refinement、またはH.2-Cで方向未確定として明示除外。今回は変更なし |
| P3 | H.2-B layout | Q2二次関数3line、Q3分母だけ別line、header左右融合 | line groupingが数学/段組の意味を持たない | MEDIUM | 後続consumerはlayout.textを全文と解釈しない。必要に応じH.2-B refinement |
| P4 | H.2-B region / schema | Q3図annotation text IDsがfigureにリンクされず、main embedded image単独だと軸label不足 | imagesだけcluster、textはdocument_contextへ分離 | MEDIUM（main image単独使用はHIGH相当） | H.2-Cで必ずpage composition、将来related evidence refs |
| P5 | Review flag | Q1/Q2でもunresolved_vector_evidenceで常時review | vector summaryしかなく意味判定不能 | LOW | UIで低優先・情報不足理由として表示 |
| P6 | Draft review/API | inline flagの専用evidence ID、原PDF配信、ordered text/math編集APIなし | H.2-Bの生成APIのみという範囲 | MEDIUM / 将来要件 | Teacher Review UI preparation |
| P7 | H.2-C coordinate contract | 非zero rotationやcropbox offsetの座標変換が記述不足 | IRが一般的座標説明のみ | HIGH（任意PDF rendererを出す前） | H.2-C境界設計/追加検証。今回3PDFにbbox障害は未確認 |
| P8 | H.2-B text presentation | Q1/Q2の語中改行、空白、score/label重複 | PDF layoutを保持 | LOW | 表示整形。native evidenceは維持 |

Q2のsuperscript count=3がそのまま3個の指数検出を意味するという前回説明は不十分でした。今回、実体は通常文/空白も含むことを確認しています。問題は修正していません。

## 22. H.2-C Blockers

データ破損・provenance断絶・誤Question割当というBLOCKERはありません。今回3PDFの既存bboxを使う限定的なH.2-C設計検討は可能です。

HIGHはP2（geometry signalの誤方向/false positives）とP7（一般PDFの座標変換contract）。自動routing/任意PDF rendererへ進む前に修正または明示的な適用制限を決めるべきです。P4に関しては、main embedded imageだけを渡す設計を避ければ既存bboxで進められます。

## 23. Teacher Review / Confirm Blockers

P1はHIGH。body_text単独を完全な問題文として編集・confirmする画面は現在のデータを誤解させます。Q1はレビュー可能ですが、Q2/Q3はPDF＋数式を併記し挿入位置を保持する表現が必要です。read-only tree/highlight prototypeの準備は可能。confirmを実装する前にはrevision/競合/編集履歴と承認境界を別途設計してください。

## 24. TestQuestion Import Readiness

hierarchy、leaf_candidate、score unset/effective/derived_from、stable key、source provenanceは揃っています。しかしparent each_childのpoints=20をそのままparent max_pointsにする、子のunsetを0点にする、body_textだけを確定本文にする等は不適切です。現在flatのTestQuestionへ直接mappingできるとは判定しません。教師確認・構造対応・内容表現の設計が必要で、今回importなし。

## 25. Multi-page Limitations

今回3PDFはいずれも1ページで、multi-pageの実証はありません。node.source_regionsは複数pageを持て、親/childをpageから独立して表現できます。一方、反復header/footerや跨ページ数式/図のassignment品質は今回未検証です。

## 26. Tests

- `.venv/bin/python -m unittest`: 102 tests、OK
- `.venv/bin/python -m pytest -q`: 113 passed
- `.venv/bin/ruff check`: All checks passed

既存DeprecationWarning/SQLite ResourceWarningは残存。src、tests、migration、frontend、parser config、既存IR/Draftへの変更はありません。Alembic headはDBをread-onlyで確認し、upgrade/resetは未実行。追加ファイルは評価script/snapshot/log/reportのみです。

## 27. Final Recommendation

1. sampleQ1: はい、構造/配点はほぼそのままレビュー可能。語中改行等の軽微な表示課題のみ。
2. sampleQ2 inline: はい。q2を無理にchild化せず、原文・位置・flagを保持しています。
3. sampleQ2 4formula: F1〜F3はbboxとして利用可能、衝突を考慮したmargin推奨。F4=−1はVision不要。
4. sampleQ3 5formula: F1〜F3はbboxとして利用可能。F4はnative sufficient、F5=本文xはVision不要。
5. sampleQ3 graph: はい、原PDF全レイヤーをregion renderする前提。main image単独では不十分。
6. provenance: はい、node/score/formula/imageの全参照がIRへ解決。図注釈は間接参照、vectorはpage集約まで。
7. review schema: 基本tree/highlightは可能。編集/confirmへはordered text/math anchors、明示的flag/figure関連、revision契約等が不足します。
8. H.2-C前の修正: データ破損BLOCKERなし。ただしP2/P7はHIGHで、signalの利用条件と座標変換contractを先に明確化することを推奨します。

推奨順は小さなH.2-B/A.1契約refinementの判断 → H.2-Cの限定region rendering/routing準備 → Teacher Review UIの内容表現設計。これは提案のみで、今回新実装は開始していません。

---

# Appendix A — Automatic Draft Result: 全nodeとsource evidence

以下のbody_textはJSON文字列形式で空白/改行を含めてそのまま示します。Ground Truthで補正していません。
## sampleQ1

### q1 — OK

parent_key=None, node_type=major_question, depth=0, leaf_candidate=False

label: {"normalized": "問題1", "raw": "問題１"}

body_text:

```json
"問題１  人工知能の分類について以下に沿って説明しなさい。（各20 点） "
```

score: `{"aggregate_points_candidate": 40.0, "effective_points_candidate": null, "evidence": [{"bbox": [55.91999816894531, 165.7519989013672, 392.1700134277344, 177.7519989013672], "bbox_precision": "source_line", "normalized_expression": "(各20 点)", "numeric_points": 20.0, "page_index": 0, "question_key": "q1", "raw_expression": "問題１ 人工知能の分類について以下に沿って説明しなさい。（各20 点）", "semantics": "each_child", "source_element_ids": ["page-0001-span-0003-0000-0000", "page-0001-span-0003-0000-0001"]}], "points": 20.0, "semantics": "each_child"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 165.75, 392.17, 177.75] | 4 | [7, 8] | page-0001-span-0003-0000-0000, page-0001-span-0003-0000-0001 |

### q1.1 — OK

parent_key=q1, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(1)", "raw": "（１）"}

body_text:

```json
"（１）反表型AI、特化型AI とは何か説明しなさい。 "
```

score: `{"aggregate_points_candidate": null, "derived_from": "q1", "effective_points_candidate": 20.0, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 183.10, 298.43, 193.06] | 5 | [9] | page-0001-span-0004-0000-0000 |

### q1.2 — OK

parent_key=q1, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(2)", "raw": "（２）"}

body_text:

```json
"（２） 強いAI、弱いAI とはなにか汎用型AI、特化型AI と対比しながら説明しなさい。 "
```

score: `{"aggregate_points_candidate": null, "derived_from": "q1", "effective_points_candidate": 20.0, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 286.33, 461.08, 296.29] | 6 | [10] | page-0001-span-0005-0000-0000 |

### q2 — MINOR_ISSUE

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題2", "raw": "問題２"}

body_text:

```json
"問題２  現在の人工知能の基礎となっているニューラルネットワークとはどのようなものか説明しなさ\nい。（30 点） "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": 30.0, "evidence": [{"bbox": [56.42399978637695, 410.6743469238281, 118.8800048828125, 420.63433837890625], "bbox_precision": "source_line", "normalized_expression": "(30 点)", "numeric_points": 30.0, "page_index": 0, "question_key": "q2", "raw_expression": "い。（30 点）", "semantics": "direct", "source_element_ids": ["page-0001-span-0007-0000-0000"]}], "points": 30.0, "semantics": "direct"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 389.94, 517.06, 401.94] | 7 | [11, 12] | page-0001-span-0006-0000-0000, page-0001-span-0006-0000-0001 |
| 0 | [56.42, 410.67, 118.88, 420.63] | 8 | [13] | page-0001-span-0007-0000-0000 |

### q3 — MINOR_ISSUE

parent_key=None, node_type=major_question, depth=0, leaf_candidate=False

label: {"normalized": "問題3", "raw": "問題３"}

body_text:

```json
"問題３  人工知能における教師付き学習、教師なし学習、強化学習とはそれぞれどのようなものか説明し\nなさい。（各10 点） "
```

score: `{"aggregate_points_candidate": 30.0, "effective_points_candidate": null, "evidence": [{"bbox": [56.42399978637695, 556.5942993164062, 151.39999389648438, 566.5543212890625], "bbox_precision": "source_line", "normalized_expression": "(各10 点)", "numeric_points": 10.0, "page_index": 0, "question_key": "q3", "raw_expression": "なさい。（各10 点）", "semantics": "each_child", "source_element_ids": ["page-0001-span-0010-0000-0000"]}], "points": 10.0, "semantics": "each_child"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 534.08, 528.10, 546.08] | 9 | [15, 16] | page-0001-span-0009-0000-0000, page-0001-span-0009-0000-0001 |
| 0 | [56.42, 556.59, 151.40, 566.55] | 10 | [17] | page-0001-span-0010-0000-0000 |

### q3.1 — OK

parent_key=q3, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(1)", "raw": "（１）"}

body_text:

```json
"（１） 教師付き学習 "
```

score: `{"aggregate_points_candidate": null, "derived_from": "q3", "effective_points_candidate": 10.0, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [56.66, 577.90, 161.53, 588.94] | 11 | [18, 20] | page-0001-span-0011-0000-0000, page-0001-span-0011-0000-0002 |

### q3.2 — OK

parent_key=q3, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(2)", "raw": "（２）"}

body_text:

```json
"（２） 教師なし学習 "
```

score: `{"aggregate_points_candidate": null, "derived_from": "q3", "effective_points_candidate": 10.0, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [56.66, 635.26, 161.53, 646.30] | 12 | [23, 25] | page-0001-span-0013-0000-0000, page-0001-span-0013-0000-0002 |

### q3.3 — OK

parent_key=q3, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(3)", "raw": "（３）"}

body_text:

```json
"（３） 強化学習 "
```

score: `{"aggregate_points_candidate": null, "derived_from": "q3", "effective_points_candidate": 10.0, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [56.66, 697.66, 139.57, 708.70] | 13 | [28, 30] | page-0001-span-0016-0000-0000, page-0001-span-0016-0000-0002 |

## sampleQ2

### q1 — MINOR_ISSUE

parent_key=None, node_type=major_question, depth=0, leaf_candidate=False

label: {"normalized": "問題1", "raw": "問題１"}

body_text:

```json
"問題１  以下の方程式について、全ての解を求めよ。解が複素数になる場合は、複素数の解まで含めて求\nめること。 また、解答だけでなく、解を求める手順の式の変形を書くこと。  "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": null, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 165.75, 527.14, 177.75] | 4 | [15, 16] | page-0001-span-0005-0000-0000, page-0001-span-0005-0000-0001 |
| 0 | [56.42, 182.74, 411.37, 192.70] | 5 | [17] | page-0001-span-0006-0000-0000 |

### q1.1 — REVIEW_NEEDED

parent_key=q1, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(1)", "raw": "（１）"}

body_text:

```json
"（１）"
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": null, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 196.50, 252.15, 212.54] | 6 | [18, 19, 20, 22, 23, 25] | page-0001-span-0007-0000-0000, page-0001-span-0007-0000-0001, page-0001-span-0007-0000-0002, page-0001-span-0007-0000-0004, page-0001-span-0007-0000-0005, page-0001-span-0007-0000-0007 |

### q1.2 — REVIEW_NEEDED

parent_key=q1, node_type=subquestion, depth=1, leaf_candidate=True

label: {"normalized": "(2)", "raw": "（２）"}

body_text:

```json
"（２） "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": null, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 303.81, 142.08, 319.85] | 7 | [27, 28, 29, 31] | page-0001-span-0008-0000-0000, page-0001-span-0008-0000-0001, page-0001-span-0008-0000-0002, page-0001-span-0008-0000-0004 |

### q2 — REVIEW_NEEDED

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題2", "raw": "問題２"}

body_text:

```json
"問題２  次の関数について、（１）式を因数分解しなさい（２）式を平方完成に変形しなさい\n\n\n\n（１）                                         （２）                         "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": null, "evidence": [], "points": null, "semantics": "unset"}`

review_required=True; review_flags=['inline_subquestion_label']

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 412.28, 476.98, 424.28] | 8 | [33, 34] | page-0001-span-0009-0000-0000, page-0001-span-0009-0000-0001 |
| 0 | [110.42, 460.37, 190.83, 485.11] | 9 | [1, 5] | page-0001-span-0000-0000-0001, page-0001-span-0001-0000-0003 |
| 0 | [72.38, 469.07, 134.55, 494.47] | 10 | [0, 2, 3, 4] | page-0001-span-0000-0000-0000, page-0001-span-0001-0000-0000, page-0001-span-0001-0000-0001, page-0001-span-0001-0000-0002 |
| 0 | [183.05, 480.41, 190.83, 494.47] | 11 | [6] | page-0001-span-0001-0001-0000 |
| 0 | [55.92, 495.63, 460.96, 505.59] | 12 | [39] | page-0001-span-0012-0000-0000 |

### q3 — REVIEW_NEEDED

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題3", "raw": "問題３"}

body_text:

```json
"問題３ という三重根を持つ三次方程式を作りなさい。組み立ての手順を書いた上で、求めた式を答\nえなさい。  "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": null, "evidence": [], "points": null, "semantics": "unset"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 647.39, 530.38, 660.15] | 13 | [41, 43, 44] | page-0001-span-0014-0000-0000, page-0001-span-0014-0000-0002, page-0001-span-0014-0000-0003 |
| 0 | [56.42, 669.90, 116.36, 679.86] | 14 | [45] | page-0001-span-0015-0000-0000 |

## sampleQ3

### q1 — REVIEW_NEEDED

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題1", "raw": "問題１"}

body_text:

```json
"問題１   の値を、  の関係式を利用して\n\n求めなさい。 （30 点）\n    （計算の過程も書くこと）。 "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": 30.0, "evidence": [{"bbox": [106.22000122070312, 194.14431762695312, 213.65000915527344, 204.10430908203125], "bbox_precision": "source_line", "normalized_expression": "(30 点)", "numeric_points": 30.0, "page_index": 0, "question_key": "q1", "raw_expression": "求めなさい。 （30 点）", "semantics": "direct", "source_element_ids": ["page-0001-span-0010-0000-0000"]}], "points": 30.0, "semantics": "direct"}`

review_required=True; review_flags=['ambiguous_geometric_order']

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [56.78, 161.22, 532.06, 180.38] | 5 | [19, 20, 21, 24, 25, 28, 29, 30, 31, 34, 35, 37] | page-0001-span-0004-0000-0000, page-0001-span-0004-0000-0001, page-0001-span-0005-0000-0000, page-0001-span-0006-0000-0002, page-0001-span-0006-0001-0000, page-0001-span-0007-0000-0002, page-0001-span-0007-0000-0003, page-0001-span-0007-0000-0004, page-0001-span-0007-0001-0000, page-0001-span-0008-0000-0002, page-0001-span-0008-0001-0000, page-0001-span-0009-0000-0001 |
| 0 | [125.06, 176.58, 425.15, 186.55] | 6 | [22, 26, 32, 36] | page-0001-span-0006-0000-0000, page-0001-span-0007-0000-0000, page-0001-span-0008-0000-0000, page-0001-span-0009-0000-0000 |
| 0 | [106.22, 194.14, 213.65, 204.10] | 7 | [38] | page-0001-span-0010-0000-0000 |
| 0 | [55.92, 213.58, 220.79, 223.54] | 8 | [40] | page-0001-span-0011-0000-0000 |

### q2 — REVIEW_NEEDED

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題2", "raw": "問題２"}

body_text:

```json
"問題２  の値を、 の関係式を利用して求めなさい \n\n    (計算の過程を書くこと)。 （30 点）"
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": 30.0, "evidence": [{"bbox": [55.91999816894531, 397.21435546875, 263.3299865722656, 407.1743469238281], "bbox_precision": "source_line", "normalized_expression": "(30 点)", "numeric_points": 30.0, "page_index": 0, "question_key": "q2", "raw_expression": "(計算の過程を書くこと)。 （30 点）", "semantics": "direct", "source_element_ids": ["page-0001-span-0015-0000-0000"]}], "points": 30.0, "semantics": "direct"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 369.81, 528.40, 388.97] | 9 | [42, 44, 45, 48, 49, 50, 51] | page-0001-span-0012-0000-0000, page-0001-span-0012-0000-0002, page-0001-span-0013-0000-0000, page-0001-span-0014-0000-0002, page-0001-span-0014-0000-0003, page-0001-span-0014-0000-0004, page-0001-span-0014-0000-0005 |
| 0 | [124.10, 385.17, 135.63, 395.14] | 10 | [46] | page-0001-span-0014-0000-0000 |
| 0 | [55.92, 397.21, 263.33, 407.17] | 11 | [53] | page-0001-span-0015-0000-0000 |

### q3 — REVIEW_NEEDED

parent_key=None, node_type=major_question, depth=0, leaf_candidate=True

label: {"normalized": "問題3", "raw": "問題３"}

body_text:

```json
"問題３ 以下のグラフとなる関数の式を特定しなさい（cos で表しなさい。なお、\n軸方向の移動については、絶対値が最小となるように表記しなさい）。（40 点） "
```

score: `{"aggregate_points_candidate": null, "effective_points_candidate": 40.0, "evidence": [{"bbox": [56.42399978637695, 605.3442993164062, 419.5299987792969, 616.111083984375], "bbox_precision": "source_line", "normalized_expression": "(40 点)", "numeric_points": 40.0, "page_index": 0, "question_key": "q3", "raw_expression": "𝑥 軸方向の移動については、絶対値が最小となるように表記しなさい）。（40 点）", "semantics": "direct", "source_element_ids": ["page-0001-span-0017-0000-0000", "page-0001-span-0017-0000-0001"]}], "points": 40.0, "semantics": "direct"}`

review_required=False; review_flags=[]

| page | bbox | geometric order | native orders | source element IDs |
|---|---|---|---|---|
| 0 | [55.92, 588.23, 433.62, 600.23] | 12 | [55, 57] | page-0001-span-0016-0000-0000, page-0001-span-0016-0000-0002 |
| 0 | [56.42, 605.34, 419.53, 616.11] | 13 | [59, 60] | page-0001-span-0017-0000-0000, page-0001-span-0017-0000-0001 |

# Appendix B — Automatic Formula Evidence: 全9region

## sampleQ2 / formula-0001

assigned=q1.1, page=0, bbox=[85.94, 196.50, 252.15, 212.54]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'math_text_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0007-0000-0001 | 19 | "2𝑥" | [85.94, 198.48, 101.21, 212.54] | False/False |
| page-0001-span-0007-0000-0002 | 20 | "3" | [102.02, 196.50, 107.79, 206.47] | False/False |
| page-0001-span-0007-0000-0004 | 22 | "−21𝑥" | [111.38, 198.48, 148.01, 212.54] | False/False |
| page-0001-span-0007-0000-0005 | 23 | "2" | [148.82, 196.50, 154.59, 206.47] | False/False |
| page-0001-span-0007-0000-0007 | 25 | "+ 69x −70 = 0" | [158.18, 198.48, 252.15, 212.54] | False/False |

## sampleQ2 / formula-0002

assigned=q1.2, page=0, bbox=[90.98, 303.81, 142.08, 319.85]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0008-0000-0001 | 28 | "𝑥" | [90.98, 305.79, 98.45, 319.85] | False/False |
| page-0001-span-0008-0000-0002 | 29 | "3" | [99.26, 303.81, 105.03, 313.78] | False/False |
| page-0001-span-0008-0000-0004 | 31 | "= −8" | [109.46, 305.79, 142.08, 319.85] | False/False |

## sampleQ2 / formula-0003

assigned=q2, page=0, bbox=[72.38, 460.37, 190.83, 494.47]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'math_text_candidate', 'subscript_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0000-0000-0000 | 0 | "y = −" | [72.38, 471.05, 108.19, 485.11] | False/False |
| page-0001-span-0000-0000-0001 | 1 | "1" | [110.42, 460.37, 118.20, 474.43] | False/False |
| page-0001-span-0001-0000-0000 | 2 | "3 " | [110.42, 471.05, 120.50, 494.47] | False/False |
| page-0001-span-0001-0000-0001 | 3 | "𝑥" | [120.50, 471.05, 127.97, 485.11] | False/False |
| page-0001-span-0001-0000-0002 | 4 | "2" | [128.78, 469.07, 134.55, 479.04] | False/True |
| page-0001-span-0001-0000-0003 | 5 | " −2x −5" | [134.55, 460.37, 190.83, 485.11] | False/False |
| page-0001-span-0001-0001-0000 | 6 | "3" | [183.05, 480.41, 190.83, 494.47] | False/False |

## sampleQ2 / formula-0004

assigned=q3, page=0, bbox=[106.10, 649.10, 120.50, 660.15]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0014-0000-0002 | 43 | "−1" | [106.10, 649.10, 120.50, 660.15] | False/False |

## sampleQ3 / formula-0001

assigned=q1, page=0, bbox=[105.02, 161.22, 206.50, 186.55]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'subscript_candidate', 'superscript_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0004-0000-0001 | 20 | "sin" | [105.02, 166.32, 122.79, 180.38] | False/False |
| page-0001-span-0005-0000-0000 | 21 | "5" | [127.94, 161.22, 133.71, 171.19] | True/False |
| page-0001-span-0006-0000-0000 | 22 | "12" | [125.06, 176.58, 136.59, 186.55] | False/True |
| page-0001-span-0006-0000-0002 | 24 | "𝜋+ sin" | [138.98, 166.32, 181.95, 180.38] | False/False |
| page-0001-span-0006-0001-0000 | 25 | "1" | [187.25, 161.22, 193.02, 171.19] | True/False |
| page-0001-span-0007-0000-0000 | 26 | "12" | [184.37, 176.58, 195.90, 186.55] | False/True |
| page-0001-span-0007-0000-0002 | 28 | "𝜋" | [198.17, 166.32, 206.50, 180.38] | False/False |

## sampleQ3 / formula-0002

assigned=q1, page=0, bbox=[246.77, 161.22, 432.04, 186.55]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'math_text_candidate', 'subscript_candidate', 'superscript_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0007-0000-0004 | 30 | "sin 𝑥+ sin 𝑦= 2 sin" | [246.77, 166.32, 365.72, 180.38] | False/False |
| page-0001-span-0007-0001-0000 | 31 | "𝑥+𝑦" | [367.99, 161.22, 387.73, 171.19] | True/False |
| page-0001-span-0008-0000-0000 | 32 | "2" | [375.07, 176.58, 380.84, 186.55] | False/True |
| page-0001-span-0008-0000-0002 | 34 | "cos" | [390.31, 166.32, 410.02, 180.38] | False/False |
| page-0001-span-0008-0001-0000 | 35 | "𝑥−𝑦" | [412.27, 161.22, 432.04, 171.19] | True/False |
| page-0001-span-0009-0000-0000 | 36 | "2" | [419.38, 176.58, 425.15, 186.55] | False/True |

## sampleQ3 / formula-0003

assigned=q2, page=0, bbox=[102.14, 369.81, 146.23, 395.14]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'subscript_candidate', 'superscript_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0012-0000-0002 | 44 | "cos" | [102.14, 374.91, 121.85, 388.97] | False/False |
| page-0001-span-0013-0000-0000 | 45 | "1" | [126.98, 369.81, 132.75, 379.78] | True/False |
| page-0001-span-0014-0000-0000 | 46 | "12" | [124.10, 385.17, 135.63, 395.14] | False/True |
| page-0001-span-0014-0000-0002 | 48 | "𝜋" | [137.90, 374.91, 146.23, 388.97] | False/False |

## sampleQ3 / formula-0004

assigned=q2, page=0, bbox=[191.57, 376.50, 383.35, 388.51]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate', 'math_text_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0014-0000-0004 | 50 | "cos(𝑥−𝑦) = cos 𝑥 cos 𝑦+ sin 𝑥 sin 𝑦" | [191.57, 376.50, 383.35, 388.51] | False/False |

## sampleQ3 / formula-0005

assigned=q3, page=0, bbox=[56.42, 606.14, 61.72, 616.11]

fonts=['CambriaMath']; reasons=['math_font_candidate', 'math_like_candidate']; flags=[]

| source element ID | native order | native text fragment | bbox | superscript / subscript |
|---|---|---|---|---|
| page-0001-span-0017-0000-0000 | 59 | "𝑥" | [56.42, 606.14, 61.72, 616.11] | False/False |

# Appendix C — Automatic Figure Evidence: 全16placements

| source image ID | bbox | dimensions | artifact ref | SHA-256 |
|---|---|---|---|---|
| page-0001-image-0000-00 | [56.41, 660.10, 330.93, 777.43] | 762×325 | images/embedded/xref-35-2b20fee7e9c6c7ac.png | 2b20fee7e9c6c7ac64f815575caa265d13b44cca8072f42dfb86406c6c70c355 |
| page-0001-image-0001-00 | [238.80, 713.52, 248.88, 743.64] | 28×83 | images/embedded/xref-37-5e4e34f70476012a.png | 5e4e34f70476012ac7e2b12636d9920a662b34bc00977da8ce66fba6454542a5 |
| page-0001-image-0002-00 | [150.36, 714.96, 162.24, 741.00] | 32×72 | images/embedded/xref-39-d90264ed1f7669ae.png | d90264ed1f7669ae3b695c2aa37532382c0ec8700d94e8c0bbdc66618233685b |
| page-0001-image-0003-00 | [159.96, 714.96, 168.72, 741.00] | 24×72 | images/embedded/xref-41-866245b380cdacfe.png | 866245b380cdacfe06cd6380e77994a7100103058807b510f0280da5231ed3b2 |
| page-0001-image-0003-01 | [271.20, 715.32, 279.96, 741.48] | 24×72 | images/embedded/xref-41-866245b380cdacfe.png | 866245b380cdacfe06cd6380e77994a7100103058807b510f0280da5231ed3b2 |
| page-0001-image-0004-00 | [264.60, 715.32, 273.24, 741.48] | 23×72 | images/embedded/xref-43-5553c7c52cf177c4.png | 5553c7c52cf177c476446ff3d2fe3e5486118e23ad8106dbd25fa28bca629d36 |
| page-0001-image-0004-01 | [184.32, 669.84, 192.96, 695.88] | 23×72 | images/embedded/xref-43-5553c7c52cf177c4.png | 5553c7c52cf177c476446ff3d2fe3e5486118e23ad8106dbd25fa28bca629d36 |
| page-0001-image-0005-00 | [159.96, 714.96, 168.72, 741.00] | 24×72 | images/embedded/xref-45-866245b380cdacfe.png | 866245b380cdacfe06cd6380e77994a7100103058807b510f0280da5231ed3b2 |
| page-0001-image-0005-01 | [271.20, 715.32, 279.96, 741.48] | 24×72 | images/embedded/xref-45-866245b380cdacfe.png | 866245b380cdacfe06cd6380e77994a7100103058807b510f0280da5231ed3b2 |
| page-0001-image-0006-00 | [86.40, 718.68, 96.48, 740.76] | 27×61 | images/embedded/xref-47-14a37b792927bc74.png | 14a37b792927bc74d9342a001698a658cbc288ac2efbea63c64f9187b83f3f8f |
| page-0001-image-0007-00 | [94.56, 718.68, 101.88, 740.76] | 20×61 | images/embedded/xref-49-48c82f885d1c3bce.png | 48c82f885d1c3bce28e69b339df5c41079df56afc0f11cf059bc8c3c4d95fdfa |
| page-0001-image-0007-01 | [100.44, 718.68, 107.76, 740.76] | 20×61 | images/embedded/xref-49-48c82f885d1c3bce.png | 48c82f885d1c3bce28e69b339df5c41079df56afc0f11cf059bc8c3c4d95fdfa |
| page-0001-image-0008-00 | [264.60, 715.32, 273.24, 741.48] | 23×72 | images/embedded/xref-51-5553c7c52cf177c4.png | 5553c7c52cf177c476446ff3d2fe3e5486118e23ad8106dbd25fa28bca629d36 |
| page-0001-image-0008-01 | [184.32, 669.84, 192.96, 695.88] | 23×72 | images/embedded/xref-51-5553c7c52cf177c4.png | 5553c7c52cf177c476446ff3d2fe3e5486118e23ad8106dbd25fa28bca629d36 |
| page-0001-image-0009-00 | [173.76, 750.96, 184.68, 775.08] | 30×66 | images/embedded/xref-53-36e140effd342ea3.png | 36e140effd342ea307a10b5ec193534d8dc177aa8b7ac6e8620881b7263ef0a1 |
| page-0001-image-0010-00 | [182.64, 750.96, 190.56, 775.08] | 21×66 | images/embedded/xref-55-6412e0cff9867338.png | 6412e0cff9867338f56dce32b03e7fb214b73130f88b841a95884047a58f74ab |

全image SHAは保管artifactと照合済み。元IRのxref別rect列挙には同じhash/bboxの重複placementが含まれます。figure clusterはそれらを別figureにせずまとめています。
