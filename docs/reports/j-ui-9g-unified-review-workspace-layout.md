# J.UI.9g Unified Review Workspace Layout Report

Phase result: **READY_FOR_PRODUCTION_VALIDATION**

## 変更前後

| 項目 | 変更前 | 変更後 |
| --- | --- | --- |
| Question | 左に画像プレビュー、右にeditor。操作とselectorのsticky管理が別々 | 共通のsticky操作バー、左source、右selector＋editor |
| 解答・採点基準 | 全幅の操作＋selector、左editor／右PDF | 操作だけが全幅、左PDF／右selector＋editor |
| 列幅 | ドメインごとに異なる | desktopはsource約40%／editor約60% |
| PDF高さ | 画面ごとに固定offset等で管理 | 操作バーの実測高さから残りviewportを計算 |

タイトル・説明・解析状態・未確認summary等は通常フローのintroに残し、スクロールで画面外へ移動します。

## 共通layout

`ReviewWorkspaceLayout` を追加しました。受け取るのは操作、source、selector、editor body、必要ならworkspace前の内容です。Questionの登録前最終確認はその追加slotを使用します。選択state・内容編集・provenance・保存・登録・OCR・model処理は各ドメインに残しています。

共通構造は次のとおりです。

```text
domain intro（通常フロー）
共通sticky操作バー
必要な登録前確認（通常フロー）
左：sticky source/PDF       右：sticky selector
                           右：domain editor body
```

Questionの変更履歴・技術情報も右body末尾に配置し、レビュー内容を見ている間は左右ペインのsticky境界を揃えます。content-dependent keyは追加していません。

## Question

既存の操作、対象設問select、unified問題文、split preview、NodeEditor、WarningPanel、確認・最終登録を共通layoutへ移しました。既存の選択handler・per-node buffer・DOM識別子・保存条件は保持しています。

`PdfPreview` は既存の認可済みPNG・metadata・SVGハイライト・前後ページ操作を再利用します。画像領域に内部scroll用wrapperを追加し、固定されたペイン内でtoolbarと補足を除く高さを利用します。source ID、SHA、bbox、reading order、figure情報、crop生成は変更していません。

## 解答・採点基準

PDFを左に移し、既存のselectorを右editorの先頭へ配置しました。selectorは1つだけです。独立した全幅selector行はありません。登録済み／保存済み／編集中、candidate、Rubric等の右側内容を保持しました。

下書き保存、模範解答登録、採点基準登録、意味分類再実行、戻るの既存handler・有効条件は維持しています。J.UI.9fのページ専用高さ測定とsticky配置を、共通layoutの測定に置き換えました。

`PdfPaneViewer` / `SourcePdfPreview` の実装は変更していません。zoom・fit width・fit page・reset・ページ移動・panを既存viewerで利用します。

## Stickyと高さ

global headerと操作バーを `ResizeObserver` で測定し、CSS変数へ反映します。

- 操作バー：headerの実測高さから開始、z-index 55。
- 左sourceと右selector：header＋操作バーの実測高さ＋12pxから開始。
- selector：z-index 35。sourceと左右に分かれ、PDF toolbarを覆いません。
- global header：既存のz-index 80を保持。
- 左ペイン高さ：`100dvh - ペイン開始位置 - 44px`。`100vh` fallbackも指定。
- 下端44px：外側mainの32px余白と12pxの間隔。ページ末尾で親境界に押されて上部へ重ならないための余白。
- PDF body：flexでtoolbar等の残り高さを使用。

測定はCSSだけを更新し、editor stringの再構築・revision作成・API呼び出しを行いません。

900px以下では1列に戻し、PDFを通常フローの480px表示にします。画面高さ560px以下でもPDF stickyを解除します。操作バーと、右editorまでスクロールした後のselectorは維持します。

## 自動検証

共通のブラウザassertionをQuestionと解答レビューで使用し、次を確認しました。

- introが画面外へ移動し、操作バーとselectorがviewport内に残る。
- selectorが右editor内にあり、重複しない。
- 左source／右editorの位置と、約40/60の列幅。
- 操作バーがheaderと重ならず、PDFとselectorが操作バーの下にある。
- 1920×1080でsourceペインがviewport高さの60%以上、PDF bodyが50%以上。
- 画面末尾でもPDF下端がviewport内に収まり、selectorから対象変更可能。
- 1000×900の操作折返しと700×900の縦積み配置。

Questionの旧テストは内側 `.review-question-selector` のsticky指定を直接検査していたため、新しくstickyを担う `.review-workspace-selector` の検査へ更新しました。実際の可視位置・重なりも共通assertionで検査します。

| 検証 | 結果 |
| --- | --- |
| production-build非loopback HTTP既存＋layout browser suite | **35 passed**（browser 22シナリオ＋error helper 13件） |
| hard formatting fallback browser fixture | **1 passed** |
| Question content/editing/split/validation/issues helper | **37 passed** |
| TypeScript | PASS |
| ESLint | エラー0件、既存警告19件 |
| production Next.js build | PASS、既存CSS/autoprefixer警告あり |
| `git diff --check` | PASS |
| 両production-like runnerのgrading jobs | **0** |

Questionのcaret、newline join、selection、paste、IME、native Undo/Redo、editor DOM identity、per-node buffer、split/save/reload、source OCR、登録を検証しました。解答・Rubricのcandidate切替、merge/split/edit、保存・登録、未確認項目への移動、continuation/reanalysis、PDF全操作、source math OCRも通りました。hard formatting fixtureではOrnithの構造維持・cold/warm再利用・local/saved/formal分離を確認しました。

環境は実FastAPI、隔離SQLiteとsource artifact、production Next.js、非loopback HTTP (`172.19.0.2`)、Chromium、実RuntimeManagerと管理下model stubです。production DB/Q5にはアクセス・変更していません。バックエンド、認可、model/runtime、保存・登録semanticsの変更はありません。

再現コマンド（repository root）：

```sh
python -m tests.run_runtime_browser_e2e --insecure-origin
LLM_GRADER_STUB_MATH_RESPONSE_MODE=formatting_hard python -m tests.run_runtime_browser_e2e --insecure-origin --spec e2e/source-math-formatting-real.spec.ts
git diff --check
```

```sh
cd frontend
npm run typecheck
npm run lint
npx playwright test e2e/question-content.spec.ts e2e/question-editing.spec.ts e2e/question-split.spec.ts e2e/review-validation.spec.ts e2e/review-issues.spec.ts --reporter=list
```

## 変更ファイルとGit状態

既存変更7件：

- `frontend/app/globals.css`
- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`
- `frontend/components/reviews/ReviewWorkspace.tsx`
- `frontend/components/reviews/PdfPreview.tsx`
- `frontend/e2e/model-answer-review-ux-real-isolated.spec.ts`
- `frontend/e2e/question-editor-caret-real.spec.ts`
- `frontend/e2e/question-math-ocr-real.spec.ts`

追加3件：

- `frontend/components/reviews/ReviewWorkspaceLayout.tsx`
- `frontend/e2e/review-layout-assertions.ts`
- `docs/reports/j-ui-9g-unified-review-workspace-layout.md`

開始時clean。終了時は上記の未ステージ変更7件、新規未追跡3件。commit/push未実施です。

## Production受入・残件

実deploymentでの両画面のvisual/UX確認は未実施です。既知の実装・自動テスト不具合はありません。

両画面でintroがスクロールし、操作が残り、左PDFと右selectorが重ならず追従すること、長いPDF・対象切替・編集・issue navigation・再開・保存／登録の既存操作を確認してください。狭い画面の配置とPDF操作も確認対象です。

実画面確認前のため、結果は **READY_FOR_PRODUCTION_VALIDATION** です。
