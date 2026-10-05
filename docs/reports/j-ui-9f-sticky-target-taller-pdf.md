# J.UI.9f Sticky Review Target & Taller PDF Preview Report

Phase result: **READY_FOR_PRODUCTION_VALIDATION**

## 原因と変更前後

「編集対象」の内側コンポーネントには `position:sticky` がありましたが、同じ高さの `#model-answer-target-selector` 親要素に囲まれていました。stickyはその親の境界を越えられず、スクロールするとセレクタが消えていました。また、セレクタは登録阻害項目等の下に置かれていました。

PDF側は固定 `top:130px`、表示領域は `calc(100vh - 245px)` でした。操作バーやPDFツールバーの折返し高さを考慮できず、実際の利用可能な縦領域と一致していませんでした。

変更後は、上部操作と唯一の編集対象セレクタを `model-answer-review-controls` にまとめ、登録阻害項目より上に配置します。ページのスクロール中も操作と現在の対象を表示します。既存のセレクタID、選択値、切替処理は保持しました。

## Sticky配置

- 共通ヘッダの64px下で操作＋セレクタの領域をstickyにします。
- `z-index:55` とし、既存ヘッダの `z-index:80` より下に配置します。
- 内側の操作バーとセレクタの個別sticky指定は、この新しい領域内だけ解除します。
- 下書き保存、模範解答登録、採点基準登録、意味分類再実行、戻るの処理・有効条件は変更していません。
- `ResizeObserver` で操作領域の実寸をCSS変数へ反映します。折返し・画面幅変更・正式登録後の操作バー消失にも追従します。測定でレビュー内容やReact編集stateを変更しません。

## PDF高さと追従

右カラムのsticky位置は `64px + 操作領域の実測高さ + 12px` です。カラム全体の高さは `100dvh` からその位置と下端44pxを差し引き、`100vh` の代替指定も置いています。下端44pxは外側mainの32px余白と12pxの間隔です。初回ブラウザ検証で、これを含めない場合はページ末尾で親要素の境界に押されてPDFが上部操作領域へ重なることを確認し、修正しました。

右カラム、既存PDFビューアを縦flexにし、見出しと折返し可能なツールバーの残りをPDF表示領域へ割り当てます。幅900px以下は従来の1カラム配置と480pxのPDFに戻し、画面高さ560px以下でもPDFのstickyを解除します。

変更は解答レビューのCSSに限定しています。`PdfPaneViewer` / `SourcePdfPreview` の描画・zoom・fit・reset・ページ移動・ドラッグ処理は変更していません。Questionレビュー、Test内のPDF表示等には新しい高さ指定を適用しません。

## 自動検証

既存の実APIブラウザシナリオを拡張しました。

- ページ末尾へスクロール後、編集対象と保存ボタンがviewport内に残る。
- セレクタは1つだけで、sticky状態から問題1→問題2→問題1へ切替可能。
- 操作領域がヘッダより下、PDFが操作領域より下に位置する。
- 1920×1080ではPDF表示領域がviewport高さの50%を超え、カラム下端がviewport内に収まる。
- 1000×900へリサイズしても上部領域とPDFが重ならない。
- 700×900ではPDFがstatic配置へ戻り、セレクタはスクロール中も表示される。
- 拡大、幅fit、ページfit、倍率reset、前後ページ、ドラッグ移動が通る。
- 既存の候補編集、保存・reload、正式登録、未確認項目への移動、解析再開、戻るが通る。

環境はproduction `next build` / `next start`、非loopback HTTP (`172.19.0.2`)、実FastAPI、隔離SQLite、実RuntimeManagerと管理下モデルstubです。

| 検証 | 結果 |
| --- | --- |
| 関連既存＋レイアウト回帰を含むproduction-like suite | **35 passed**（ブラウザ22シナリオ＋既存error helper13件） |
| TypeScript | PASS |
| ESLint | エラー0件、既存警告19件 |
| production Next.js build | PASS、既存CSS/autoprefixer警告あり |
| `git diff --check` | PASS |
| 隔離DBのgrading jobs | **0** |

Questionのsticky選択、caret/IME/貼り付け/Undo・Redo、split provenance、Question/ModelAnswer source math OCR、draft/formal分離、Rubric分割・結合・登録、レビュー継続、未確認項目への移動、runtime再利用も既存suiteで通りました。レイアウト検証シナリオのpage errorはありません。

実行コマンド：

```sh
python -m tests.run_runtime_browser_e2e --insecure-origin
git diff --check
```

```sh
cd frontend
npm run typecheck
npm run lint
```

バックエンド、認可、モデル動作、保存・登録semanticsは変更していません。production DB/Q5/正式採点結果にはアクセス・変更していません。

## 変更ファイルとGit状態

- `frontend/app/model-answer-import-reviews/[draftId]/page.tsx`：sticky領域、セレクタ移動、実寸測定。
- `frontend/app/globals.css`：解答レビューに限定したsticky/flex/viewport高さと小画面の配置。
- `frontend/e2e/model-answer-review-ux-real-isolated.spec.ts`：末尾スクロール、切替、高さ、重なり、小画面の回帰。
- `docs/reports/j-ui-9f-sticky-target-taller-pdf.md`：本報告。

開始時clean。終了時は未ステージ変更3件、新規未追跡報告1件。commit/pushは実行していません。

## 残件

既知の実装・自動テスト不具合はありません。実deploymentで長いレビューをスクロールし、セレクタ切替・縦長PDF・ツールバーの折返し・狭い画面の配置を確認する受入だけが残っています。実機確認前のため **COMPLETE** とは判定しません。
