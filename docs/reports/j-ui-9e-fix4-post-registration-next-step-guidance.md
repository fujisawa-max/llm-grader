# J.UI.9e-fix4 Post-registration Next-step Guidance Report

Phase result: **READY_FOR_PRODUCTION_VALIDATION**

## 実装結果

Question登録後は確認画面に留まり、タイトル・確認状態の直下に次の案内を表示します。

> 次に行う作業
>
> 問題の登録が完了しました。次は解答・採点基準を確認・登録してください。
>
> 解答・採点基準へ進む ›

従来は「問題登録済み」と既存操作だけが表示され、次の推奨操作がありませんでした。戻るリンク、「新しい修正版で編集を再開」「最新の内容を再読み込み」は維持しました。自動リダイレクトはありません。

## Test画面との共通化

既存Test画面にはローカルの `NextAction` があり、`.next-action` / `.next-action.compact` と `.button` で案内を表示していました。表示部分だけを小さな `NextActionPanel` に抽出しました。Test画面は従来どおりボタンと `go()` を使用し、Question確認画面は通常のリンクを使用します。CSS、Testの次操作判定、作業進捗の完了条件は変更していません。

既存 `go()` のURL生成を `testWorkflowHref()` に抽出し、両画面で使用します。採点確認画面の経路と `rubric` → `answers` の既存別名も保持します。

## 登録完了の判定と移動先

既存の確認結果APIは、正式登録完了時に `state="completed"` と `test_id` を返します。Question確認画面が既に読み込んでいるその結果について、状態が `completed` で現在のTestと一致するときだけ案内を表示します。登録API成功時の応答と、再読み込み時の保存済み確認結果の両方を利用します。

ローカルの「確認済み」や保存成功だけでは表示しません。未確認数式が残る初期状態、下書き保存後、確認済みだが未登録の状態、登録失敗後に表示しないことを検証しました。バックエンド・登録処理・永続化の変更はありません。

移動先は同じTestの `/tests/{test_id}?section=answers` です。解答・採点基準の既存入口に移動し、その画面が資料登録、解析、保存済み解析の再開、登録済み内容を扱います。Question画面に解答解析の状態機械を追加していません。

未着手のケースでは資料登録欄を表示します。保存済み解析があるケースでは「前回の解析結果を編集」が利用でき、同じ解析ID・修正版・教師編集内容を保持して再開します。Question登録で設問選択肢が増えることと、保存済み解答候補が変わることは区別して検証しました。

## ブラウザ検証

新規の2シナリオは、実FastAPI、隔離SQLite、production `next build` / `next start`、非loopback HTTP (`172.19.0.2`)、Chromium、実RuntimeManagerと管理下stubを使用します。

- 実際のQuestion保存・確認・正式登録を行い、登録後も同じ確認ページに留まることを確認。
- 登録前の各状態と、意図した実APIの409登録拒否では案内なし。
- 登録成功後、再読み込み後、入口から確認ページに戻った後に案内を表示。
- 戻るリンク・修正版再開・再読み込み操作を保持。
- キーボードのEnterで同じTestの解答・採点基準へ移動。
- 未着手の資料登録欄と、既存解析の再開の両方を確認。
- Testの既存compact案内、従来の推奨ボタン、問題ステップの「完了」を確認。
- 移動・解析再開中のPOST/PUT/PATCH/DELETEは **0件**。
- 両シナリオの全4runtimeのPID・起動時刻・推論呼び出し数は前後で不変。ネイティブPDFによる準備からモデル推論の追加なし。
- 認証後の予期しないconsole/page/networkエラーなし。ログイン前の既存 `/auth/me` 検査と、意図した409は区別。

テストハーネス全体の既存初期fixture作成やOCR回帰は管理下stubを使用します。このPhaseの移動自体はモデルを呼びません。production DB、Q5、採点結果は変更していません。

## 検証結果

| 検証 | 結果 |
| --- | --- |
| 関連バックエンド7モジュール | **129 passed**、既存警告5件 |
| Question content/editing/split/validation/issues helper | **37 passed** |
| production-build 非loopback Chromium既存＋新規suite | **35 passed**（ブラウザシナリオ22件＋エラー表示helper13件） |
| 新規登録完了・入口/解析再開シナリオ | **2 passed**、上記35件に含む |
| TypeScript | PASS |
| ESLint | エラー0件、既存警告19件 |
| production Next.js build | PASS、既存CSS/autoprefixer警告あり |
| Ruff（変更したPythonハーネス） | PASS |
| `git diff --check` | PASS |
| 隔離DBのgrading jobs | **0** |

Question保存・登録・分割provenance、カーソル/IME/選択/貼り付け/Undo・Redo、未確認項目への移動、Question解析再開、ModelAnswer/Rubric解析再開・分割/結合/登録、source-aware OCR、LaTeX化、runtime再利用の回帰が通りました。既存のdomain認可およびgeneric text-tool認可は変更していません。

再現コマンド（repository root、frontendコマンドのみそのdirectory）：

```sh
python -m pytest -q tests/test_question_reviews.py tests/test_question_import.py tests/test_question_math_ocr.py tests/test_review_document_text_editing.py tests/test_source_math_ocr.py tests/test_model_answer_import_api.py tests/test_text_tool_authorization.py
python -m tests.run_runtime_browser_e2e --insecure-origin
python -m ruff check tests/run_runtime_browser_e2e.py
git diff --check
```

```sh
cd frontend
npm run typecheck
npm run lint
npx playwright test e2e/question-content.spec.ts e2e/question-editing.spec.ts e2e/question-split.spec.ts e2e/review-validation.spec.ts e2e/review-issues.spec.ts --reporter=list
```

## 変更ファイルとGit状態

既存変更3ファイル：

- `frontend/app/tests/[testId]/page.tsx`
- `frontend/components/reviews/ReviewWorkspace.tsx`
- `tests/run_runtime_browser_e2e.py`

追加4ファイル：

- `frontend/components/NextActionPanel.tsx`
- `frontend/lib/testWorkflowNavigation.ts`
- `frontend/e2e/question-completion-real.spec.ts`
- `docs/reports/j-ui-9e-fix4-post-registration-next-step-guidance.md`

作業開始時はclean。終了時は上記の未ステージ変更3件と未追跡追加4件。commit/pushは実行していません。追加ファイルはサービスUI・テスト・サービス向け報告のみです。

## Production受入と残件

実deploymentの確認は未実施です。既知の実装・自動テスト不具合はなく、残件は次の実画面確認です。

1. Question正式登録後に確認ページが維持され、上部の案内が表示される。
2. 「解答・採点基準へ進む」で同じ試験の入口に移動できる。
3. 保存済み解析がある場合、再解析せず「前回の解析結果を編集」が利用できる。
4. Question確認ページへ戻り、再読み込みしても案内と既存修正版操作が残る。

この確認には正式な解答・採点基準の登録は不要です。実画面確認が終わるまでは **COMPLETE** と判定しません。
