# J.UI.9d Source-aware Math OCR & LaTeX Reconstruction Report

## Summary

source付きModelAnswer候補に、局所PDF crop → math OCR → 決定論的部分置換 → 教師確認の経路を追加した。ソフトウェア経路とmanaged stubの検証はPASS。実Uni-MuMERによる対象PDFの認識精度は未検証のため、最終判定はPARTIAL。

## Existing Source Geometry Audit

`model_answer_geometry.native_segments`のstable ID、original_text、page_index、bbox、reading_order、SHA、source spansを再利用する。PDFはdraft.material_idからTestMaterialを取得する。編集中の本文はrequestから受け取るが、座標・pathは受け取らない。Question用vision adapterはowned runtimeを終了時に停止するため、そのacquireは使用しない。

## Math Region Detection

数式記号・変数・数値を持つ原文行を、編集中の本文の完全一致行と照合する。同一ページで近接し、horizontal overlapがあり、間にproseを挟まない行を局所領域へまとめる。重複原文や編集によって位置を一意に決められない行は置換しない。画像のみの数式検出や教師による領域選択は今回追加していない。

## PDF Crop Strategy

PyMuPDFで保存済みbboxを6pt拡張し、2倍解像度PNGを生成する。1要求8領域以下、各領域はページ面積35%以下かつ4百万pixel以下。ページ範囲外・空・非有限座標は拒否する。temporary cropは要求終了時に削除する。

## Uni-MuMER Runtime Integration

既存model purpose `math_ocr`、既定model ID `unimumer-q4`を利用する。deployment configへ既存Uni-MuMER用model/mmproj assignmentを追加し、環境変数でpathを指定できる。新規モデルのdownloadは行わない。実際のbackendはRuntimeManagerのauto判定を利用する。検証はmanaged synthetic-math-model、CPUおよびCUDA hardware fixtureであり、実GPU inferenceではない。

## Math OCR Output

既存math OCR prompt、画像payload、LocalClient、response_text（reasoning fallback含む）を再利用する。旧Question parserはTP/Precision等の複数文字identifierを除外するため、sourceに現れるidentifierだけを許す専用validationを適用する。raw_response、raw_latex、source_fieldを保持し、数式を計算・訂正しない。confidence値は取得していないためnullとし、すべて教師確認を要求する。

## Deterministic Reconstruction

原文の一意なstart/endから、reading order順に`$$`付きOCR LaTeXを部分挿入する。他のproseを変更しない。抽出原文に残った数値がOCR結果から消失・変更された場合は拒否する。native extractionにない追加数値は、missing numerator等の可能性があるためPDF照合warningを表示する。画像に存在するかの最終判断は教師がcropを確認する。

## Optional Ornith Post-normalization

crop経路ではOrnithを呼ばない。source原文と対応しない編集本文・manual candidate・Rubricは既存text-only normalizationを利用する。その数値・identifier・意味の保持ルールは維持する。

## Spinner / Processing UX

共通buttonを「数式をLaTeX化」へ変更。request中はspinner、aria-busy、disabled button、「数式を解析中…」を表示する。成功・失敗後に解除する。詳細なbackend progress streamingは追加していない。

## Preview / Apply / Cancel

元の本文、変換案、Markdown/KaTeX preview、ページ番号、crop画像、raw OCRを表示する。source OCRは確認checkboxが必要。KaTeXエラー・stale本文では適用できない。cancelはproposalのみ破棄する。crop画像bytesは保存metadataから除外する。

## Draft State Semantics

applyはlocal編集stateのみ更新する。下書き保存はserver draft revisionを更新し、正式登録は既存DomainServiceのModelAnswer versionを作成する。formal A / saved B / editing Cの分離、save/reload、register/reloadをブラウザで確認した。

## Authorization / Source Safety

POST `/api/v1/model-answer-import-drafts/{draft_id}/entries/{entry_id}/math-ocr`を追加。既存staff + domain-path authorizationとowned_draft/owned_testを利用する。entryは保存済みsnapshotから取得し、PDFはallowed artifact root内のみ参照する。material SHAとdraft作成時SHAを検証する。任意path等の余分なrequest fieldは422。generic `/text-tools/latex-normalize`のstaff-only guardは変更していない。

## Error Handling

no_mathは既存proposal contractのno_changeへ対応させる。数式OCR unavailable、startup failed/timeout、inference failed/timeout、invalid response、numeric mismatchをstructured codeで返す。元本文を変更せず再試行できる。frontend failure検証では503を明示的にsimulateした。

## Runtime Cold Start

停止状態から実RuntimeManagerがmanaged画像stubを起動し、health/model/vision確認後に画像chat requestが到達することを確認した。model/mmproj未配置はサービス全体を停止させず、変換要求を失敗させる。

## Runtime Warm Reuse

2回の画像要求でPIDとstarted_atが一致した。要求後のstopはない。既存grader/Ornith lifecycleとtimeoutを変更していない。

## Representative Fraction Test

2次元分数を描いた合成PDFとflattened native textを用意した。managed画像stubが返す`\frac{TP}{TP+FP}`、`\frac{24}{24+6}`、`\frac{24}{30}`をproposalへ挿入し、末尾の`Answer: 0.800 (80%)`を保持した。これは画像request・再統合の検証であり、実Uni-MuMERの認識精度の証明ではない。

## Tests

対象backend regression: 191 PASS。source geometry、prose/順序保持、重複原文no-op、無効bbox、cold/warm、numeric/identifier拒否、auth、既存classification/geometry/import/Rubric/runtimeを含む。Ruff、TypeScript typecheck、git diff --check PASS。production build PASS（既存CSS/React警告あり）。

## Real Browser E2E

実FastAPI production entrypoint + 隔離SQLite + next build/next start + Chromium + 実RuntimeManager + managed vision stub、非localhost HTTP originで全27件PASS。最終のsource math専用2件も再実行してPASS。spinner、request、crop proposal、cancel/apply、下書き保存/reload、正式登録/reload、PID再利用をassertした。no-math responseと失敗後本文保持・button復帰も確認した。

## Browser Console / Network Audit

認証後の成功scenarioでunexpected console error/pageerrorは0件。source math requestは2回の明示操作に対して2件。既存generic LaTeX・auth・登録・Rubric操作もPASS。ログイン前の想定内401と、failure scenarioの意図的503は成功経路のconsole監査と区別した。

## Real NVIDIA Validation Steps

1. modelと対応mmprojを既存model storageへ配置し、`LLM_GRADER_MATH_MODEL_PATH` / `LLM_GRADER_MATH_MMPROJ_PATH`を設定する。
2. API/frontend/runtime-managerを更新し、合成PDFまたは正式Q5以外の対象draftを開く。
3. 「数式をLaTeX化」でspinner、math_ocr lazy start、画像inference、proposal/crop/KaTeX previewを確認する。
4. Precisionの各分数を元PDFと照合する。数字や項が画像に存在しない場合は適用しない。
5. apply後、saved/formalが未変更であること、save/reloadでsavedが更新すること、register/reloadでformalが更新することを確認する。
6. 2回目要求でmath_ocrのPID/started_atが変わらず、runtimeが停止しないことを確認する。

## Files Modified

- `src/scoring/source_math_ocr.py`、`src/scoring/api/model_answer_imports.py`
- `frontend/components/LatexNormalizationControl.tsx`、Review page、globals.css
- `frontend/lib/api/textTools.ts`、`frontend/lib/latexErrors.ts`
- `config/runtime.deployment.json`、`compose.yaml`
- source math tests、authorization/runtime deployment tests、managed stub/runtime fixture/browser runner
- source math E2E、既存LaTeX E2Eのbutton/loading locator
- README、runtime deployment documentation、本report

## Remaining Issues

実NVIDIA + 実Uni-MuMERでのsource画像認識と対象PDFの精度確認は未実施。一意な行照合を優先するため、重複行、native extractionで全内容が欠落した数式、教師が大きく書き換えた本文ではsource-aware置換を見送る。cropの境界が実PDFの分数・添字を十分に含むかも実サンプルで確認が必要。正式Q5、OpenWebUI、既存DBは変更していない。テストはtemporary DB/artifactsのみで、grading jobsは0件。DB migration、reset、commit/pushは行っていない。

## Final Decision

Phase J.UI.9d: PARTIAL

実装とstubによるproduction経路検証は完了。実Uni-MuMERで対象分数のsource画像復元を確認後、COMPLETEへ移行できる。

## Geometry grouping follow-up

See [J.UI.9d-fix1 report](j-ui-9d-fix1-geometry-vision-math-grouping.md) for visual-expression grouping, optional Ricoh validation and failure-time crop diagnostics. Real deployed Uni-MuMER acceptance remains pending.
