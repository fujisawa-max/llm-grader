# ローカルLLMによる答案採点

Ricoh-8Bが答案全体をOCRし、その結果と元画像から数式領域を特定します。指定領域を元画像から切り出してUni-MuMER-4B Q4_K_Mで認識し、Ornith Q8が元画像・Ricoh結果・位置情報付きLaTeXを照合してから採点します。逐次実行するPythonランナーとBasicMathSmallExam1のサンプルを用意しています。

採点は教員確認前の仮採点です。既知の100点・75点は採点モデルへ渡さず、最後に比較します。モデルの自己申告点をそのまま合計せず、許容点数と根拠のページ参照を検証してプログラムで集計します。

## 準備

Python 3.11以上、Linux、ローカルで起動済みのllama.cpp互換サーバーが必要です。リポジトリルートで実行します。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[pdf,dev]'
```

### モデルの取得

モデルファイルはサイズとライセンスの都合でリポジトリに含めません。Hugging Face Hub CLIを用意したうえで、次のスクリプトを実行すると、Ricoh、Uni-MuMER、OrnithのGGUFと必要な画像プロジェクターを`/opt/models`へ取得できます。

```bash
python3 -m pip install -U huggingface_hub
HF_TOKEN=... scripts/download_models.sh
```

`MODEL_DIR`, `RICOH_REPO`, `UNIMUMER_REPO`, `ORNITH_REPO`環境変数で保存先やミラーを変更できます。既定値は公開GGUFリポジトリです。取得後は各ファイルを`llama-server`の起動設定へ割り当て、`python3 -m scoring check`でモデルID、量子化形式、画像入力対応を確認してください。モデルの利用条件は各配布元のライセンスに従ってください。

依存バージョンはpyproject.tomlで固定しています。HTTP推論とテストはPython標準ライブラリ、PDFの取り込み・画像切り出しはPyMuPDF、静的検査はRuffを使います。モデルの起動・停止はランナーから行いません。今回のGPU認識問題と修正設定は[サーバー設定の調査結果](docs/server-settings.md)を参照してください。

## 提供された2答案を採点する

サンプル課題は既に `data/assignments/BasicMathSmallExam1/` に作成済みです。元PDFを更新した場合は[サンプル説明](docs/BasicMathSmallExam1.md)を参照してください。

`config/local.json` の接続先・モデルIDを実際のサーバーに合わせます。Ricohは8081番（`ricoh-qwen3vl-8b-q8`）、Uni-MuMERは8082番（`unimumer-q4`）、Ornithは8080番（`ornith-q8`）です。モデルIDは起動設定によって変わります。`expected_ftype: "Q8_0"` を指定するとQ4等の取り違えを拒否します。

```bash
.venv/bin/python -m scoring validate --assignment data/assignments/BasicMathSmallExam1
.venv/bin/python -m scoring check
.venv/bin/python -m scoring run \
  --assignment data/assignments/BasicMathSmallExam1 \
  --run runs/basic-math-trial-001
.venv/bin/python -m scoring compare \
  --run runs/basic-math-trial-001 \
  --expected data/evaluation/BasicMathSmallExam1-expected.json
```

同じコマンド・同じrunを指定すると、成功した段階を再利用します。入力・設定・プロンプト・コードが変わっていたら上書きせず停止するため、別のrun名を指定してください。失敗したリクエストは自動再試行せず、原因を確認して同じコマンドを再実行します。生レスポンスは試行ごとに保存します。別runで成功したOCRは `--reuse-ocr-from runs/<元run名>` で再利用できます。現在の `--reuse-ocr-from` はRicohの全体OCRのみを取り込みます。画像・Ricohモデル設定・生成設定・OCRプロンプト・結果ハッシュが一致するものが対象です。領域特定とUni-MuMERは新しいrunで実行します。同一runの再開では成功した領域ごとの認識を再利用し、領域指定・切り出し画像・LaTeX抽出コード・結果の整合性を検証します。今回のコード変更後は新しいrun名を指定してください。

3モデルを同時常駐させられない場合や、OCRを先に済ませたい場合は段階を分けられます。`--stage ocr` は既定で全体OCR・領域特定・領域別OCRを実行します。`--ocr-engine ricoh` は全体OCRと領域特定まで、`--ocr-engine unimumer` は保存済みのRicoh結果・領域指定を読み、切り出しと数式認識を実行します。Uni-MuMERだけを先に実行することはできません。採点にはこれらの成功済み結果が必要です。

```bash
.venv/bin/python -m scoring run \
  --assignment data/assignments/BasicMathSmallExam1 \
  --run runs/basic-math-phased-001 --stage ocr --ocr-engine ricoh
# 必要ならRicohを停止し、Uni-MuMERを起動
.venv/bin/python -m scoring run \
  --assignment data/assignments/BasicMathSmallExam1 \
  --run runs/basic-math-phased-001 --stage ocr --ocr-engine unimumer
# 必要ならOCRモデルを停止し、Ornith Q8を起動。同じ設定ファイルを保持する
.venv/bin/python -m scoring run \
  --assignment data/assignments/BasicMathSmallExam1 \
  --run runs/basic-math-phased-001 --stage grade
```

`--submission s42` で1答案だけ試せます。既定では2答案を処理します。実行中のリクエストは常に1件です。同じリポジトリ内の別ランナーの同時起動もロックで防ぎます。他アプリからのサーバー利用はこのロックの対象外です。

## 配置

| 場所 | 内容 |
|---|---|
| `testData/BasicMathSmallExam1/` | 提供されたPDF2個と答案画像2枚。原本を保持 |
| `data/assignments/BasicMathSmallExam1/` | 作成済み課題。問題・ルーブリック・模範解答・答案・PDFの複製とページ画像 |
| `data/evaluation/BasicMathSmallExam1-expected.json` | 既知の100点・75点。比較コマンドだけが読む |
| `examples/basic-math-small-exam1/` | 今回の問題の教材テンプレート。答案画像は含まない |
| `examples/assignment-template/` | 新しい課題を手で作るための小さな汎用記入例 |
| `src/scoring/` | 入力検証・API接続・採点検証（core.py）、準備・実行・比較（cli.py）、LaTeX抽出（math_ocr.py）、領域検証・切り出し（regions.py） |
| `prompts/` | OCR・読み取り照合・採点の指示 |
| `config/local.json` | 実機設定（Git対象外） |
| `runs/<run名>/` | 入力スナップショット、モデル情報、生レスポンス、OCR、仮採点、比較結果 |
| `tests/` | 小さな人工データとモックを使う単体テスト |

新しい課題は `examples/assignment-template/` を `data/assignments/<課題ID>/` へコピーし、問題文・ルーブリック・任意の模範解答・答案を記入します。答案画像は `submissions/<答案ID>/images/` に置き、submission.jsonで設問とページを対応づけます。複数設問が1ページにある場合、同じページを各設問から参照できます。

実データ・実機設定・生成物はGit対象外です。氏名や学籍番号は答案IDに使いません。

## 結果を見る

- `runs/<run名>/summary.csv`: 小問別の仮点。確定点の列は空欄。
- `totals.json`: 答案別の仮合計。未処理・採点不能があればnull。
- `comparison.json`: compareコマンドによる既知点との比較。
- `reports/roster.csv`: 全答案の学籍番号、氏名、小問別得点、合計、減点理由の一覧。
- `reports/roster.md`: 同じ一覧の確認用Markdown。
- `reports/annotated/<答案ID>.pdf`: 元画像を背景に、赤字の編集可能なFreeText注釈で各小問の `○`（満点）、`△`（部分点）、`×`（0点）、得点、減点理由を重ねたPDF。
- `submissions/s42/ocr/ricoh/page-001.json`: RicohのOCR。
- `submissions/s42/ocr/ricoh/page-001.layout.json`: Ricohが元画像とOCRから推定した領域・設問対応。
- `submissions/s42/ocr/unimumer/regions/page-001/r01.png`: 実際に送信した切り出し画像。
- 同階層の `r01/transcription.json`: 領域の数式認識結果（生レスポンス・状態は隣接ファイル）。
- `submissions/s42/ocr/unimumer/page-001.json`: 領域ID・設問ID・座標・LaTeXを集約した結果。
- `submissions/s42/questions/q01_1/reconstruction.json`: 模範解答を見せずに照合した答案。
- 同ディレクトリの `grading.json`: 観点別得点、画像・文字の根拠、理由。
- `review.json`: 人手確認の必要性と理由。初期試行は全件確認。

### 一覧と答案PDFの出力

採点済みrunから次のコマンドで出力します。

```bash
.venv/bin/python -m scoring export-reports --run runs/<run名>
```

学籍番号と氏名はRicohのページOCRに追加した専用フィールドから記録します。旧形式のOCR結果や判読不能な場合は推測せず `要確認` とし、一覧の備考にも再OCRが必要であることを記録します。PDFの赤字部分はFreeText注釈なので、対応するPDFエディタで後から修正できます。元画像は背景として保持されます。

[処理構成案](docs/architecture.md)には将来の拡張も含みます。現実装の範囲と制約は[サンプル説明](docs/BasicMathSmallExam1.md)を参照してください。

実機での数式単体の成功と、ページ全体での上限到達は[変更・検証記録](docs/dual-ocr-validation.md)に記載しています。

## Ricoh結果に基づく領域分割

全体OCRのあと、Ricohに元画像・OCR・設問IDとラベルを渡し、領域指定を別リクエストで取得します。問題の正解や配点は渡しません。`bbox` は左上原点の0〜1000座標、`bbox_pixels` は余白を含む元画像上の画素座標です。元画像を変更・縮小せず、各領域の周囲に12ピクセルの余白を付けます。

`math` の領域だけUni-MuMERへ送信します。グラフ・文章はOrnithが元画像で評価します。全設問について `located`・`blank`・`no_math`・`unreadable` を明示し、検出できなかった領域を空答案や0点へ変換しません。Ornithには対象設問の領域だけを渡します。

画像外・逆転・重複ID・設問対応の欠落や矛盾、ページの半分を超える数式領域を拒否します。ただし、数値として正しい座標でも、符号や枠外の計算を取りこぼす可能性があります。`*.layout.json` と切り出し画像で確認できます。領域の自動再分割・座標編集UIは未実装です。失敗時にページ全体をUni-MuMERへ送り直すことはしません。

## contentが空の場合の扱い

Uni-MuMERはJSONを強制せずLaTeXの転写を依頼します。`content` が空白・空文字・nullなら `reasoning_content` を参照し、LaTeX/TeXコードブロック、`$$...$$`、`\[...\]`、`\(...\)`、`$...$`、数式環境、数式だけの行を抽出します。説明文はOrnithへ渡しません。`eval_handwrite.py` と同様、reasoning全体が同じ行列を2回繰り返した場合のみ重複を除きます。

抽出結果は `latex` 配列と `text`、取得元は `source` に保存します。`content` が空でない場合はそれを優先し、不適切なcontentをreasoningで置き換えることはしません。抽出不能や生成打ち切りは失敗として停止します。RicohはJSON形式を維持し、contentが空ならreasoningが正しいJSONである場合だけ受け付けます。採点結果にはこのフォールバックを適用しません。

数式抽出は形式上の候補抽出であり、推論中の仮の式と画像の転写を完全には区別できません。位置・設問対応はRicohの推定なので、Uni-MuMERの結果は要確認情報を伴い、Ornithが元画像で設問との対応と実際の記載を照合します。自由文を含む生レスポンスはローカルの `*.raw.json` にだけ保持します。

## 検証

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
```

テストにはモデル起動・実答案・ネットワーク接続は不要です。実際の認識精度と採点精度は、別途実モデルで確認します。
