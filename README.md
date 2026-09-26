# llm-grader：ローカルLLMによる答案採点

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

## Python adapter（Phase A）

既存CLIを壊さずworker等から同じ処理を呼ぶため、
`scoring.adapters.LegacyCliAdapter`を提供しています。`StageRequest`に
assignment、run、configを指定し、`run_ricoh_phase()`、
`run_math_ocr_phase()`、`run_ornith_phase()`を順に呼び出します。内部では既存の
`scoring.cli.run_exam`へ委譲するため、checkpoint、hash、reuse、保存形式はCLIと
共通です。`RunArtifactAdapter`は既存`runs/<run>/`のJSONとresult hashを読み取る
互換境界です。

### 一覧と答案PDFの出力

採点済みrunから次のコマンドで出力します。

```bash
.venv/bin/python -m scoring export-reports --run runs/<run名>
```

学籍番号と氏名はRicohのページOCRに追加した専用フィールドから記録します。旧形式のOCR結果や判読不能な場合は推測せず `要確認` とし、一覧の備考にも再OCRが必要であることを記録します。PDFの赤字部分はFreeText注釈なので、対応するPDFエディタで後から修正できます。元画像は背景として保持されます。

[処理構成案](docs/architecture.md)には将来の拡張も含みます。現実装の範囲と制約は[サンプル説明](docs/BasicMathSmallExam1.md)を参照してください。

実機での数式単体の成功と、ページ全体での上限到達は[変更・検証記録](docs/dual-ocr-validation.md)に記載しています。

## Ricoh結果に基づく領域分割

全体OCRのあと、Ricohに元画像・OCR・設問IDとラベルを渡し、領域指定を別リクエストで取得します。問題の正解や配点は渡しません。新規artifactの`bbox`は`coordinate_space: "normalized"`を伴う左上原点の0.0〜1.0座標、`bbox_pixels`は余白を含む元画像上の画素座標です。旧artifactの`normalized_1000`は明示された互換境界でのみ0.0〜1.0へ変換します。元画像を変更・縮小せず、各領域の周囲に12ピクセルの余白を付けます。

`math` の領域だけUni-MuMERへ送信します。グラフ・文章はOrnithが元画像で評価します。全設問について `located`・`blank`・`no_math`・`unreadable` を明示し、検出できなかった領域を空答案や0点へ変換しません。Ornithには対象設問の領域だけを渡します。

画像外・逆転・重複ID・設問対応の欠落や矛盾、ページの半分を超える数式領域を拒否します。ただし、数値として正しい座標でも、符号や枠外の計算を取りこぼす可能性があります。`*.layout.json` と切り出し画像で確認できます。領域の自動再分割・座標編集UIは未実装です。失敗時にページ全体をUni-MuMERへ送り直すことはしません。

## contentが空の場合の扱い

Uni-MuMERはJSONを強制せずLaTeXの転写を依頼します。`content` が空白・空文字・nullなら `reasoning_content` を参照し、LaTeX/TeXコードブロック、`$$...$$`、`\[...\]`、`\(...\)`、`$...$`、数式環境、数式だけの行を抽出します。説明文はOrnithへ渡しません。`eval_handwrite.py` と同様、reasoning全体が同じ行列を2回繰り返した場合のみ重複を除きます。

抽出結果は `latex` 配列と `text`、取得元は `source` に保存します。`content` が空でない場合はそれを優先し、不適切なcontentをreasoningで置き換えることはしません。抽出不能や生成打ち切りは失敗として停止します。RicohはJSON形式を維持し、contentが空ならreasoningが正しいJSONである場合だけ受け付けます。採点結果にはこのフォールバックを適用しません。

数式抽出は形式上の候補抽出であり、推論中の仮の式と画像の転写を完全には区別できません。位置・設問対応はRicohの推定なので、Uni-MuMERの結果は要確認情報を伴い、Ornithが元画像で設問との対応と実際の記載を照合します。自由文を含む生レスポンスはローカルの `*.raw.json` にだけ保持します。

## 検証

## Production operations (I.6)

運用時の起動停止、Teacher/Adminの境界、学生ポータルのfeature flag、
バックアップ・復旧、障害対応、監視、Playwright環境は
[production runbook](docs/operations/production-runbook.md)を参照してください。
バックアップ検証は[backup-restore.md](docs/operations/backup-restore.md)、
リリース前確認は[deployment-checklist.md](docs/operations/deployment-checklist.md)、
障害対応は[incident-response.md](docs/operations/incident-response.md)にまとめています。
本番serverでは`STUDENT_PORTAL_ENABLED=false`が既定で、結果はTeacher/Adminが
PDF/CSVで授業システムへ配布します。Student向け実装はflagで再有効化できます。

### Instructor Web UI

Phase H の UI は `frontend/` に独立した Next.js App Router アプリとして配置しています。
`frontend/.env.example` を `.env.local` にコピーし、FastAPI の `/api/v1` URL を設定してから、次を実行してください。通常のUIは開発用ユーザーIDを使わず、ログイン時に発行されたHttpOnlyセッションを使います。

```bash
npm install
npm run typecheck
npm run lint
npm run build
```

採点処理と runtime 操作はブラウザでは実行せず、既存 API と別プロセスの worker に委譲します。

### Authentication and administration (J.UI.Admin.1)

ブラウザのTeacher/Admin UIは`/api/v1/auth/login`が発行するHttpOnly
セッションCookieを使用します。既存ユーザーはmigrationで保持されますが、password
hashがないユーザーにはpasswordを自動設定しません。初回管理者は次で作成します。

```bash
ADMIN_INITIAL_PASSWORD='change-me-now' \\
  .venv/bin/python -m scoring.admin create-admin \\
  --email admin@example.com --display-name 管理者
```

`ADMIN_INITIAL_PASSWORD`や`--password`はログへ出力しません。Adminは
`/admin/users`からTeacherを作成できます。Teacherが作成したCourseはログイン中の
Teacherに自動的に紐づき、別TeacherのCourseへはBackend authorizationでアクセスできません。

既存DBを保持したまま認証列とセッション表を追加するには、アプリ起動前に対象DBへ
Alembic migrationを適用します（production URLは環境変数から渡してください）。

```bash
.venv/bin/alembic -x sqlalchemy.url="$LLM_GRADER_DATABASE_URL" upgrade head
```

既存ユーザーにpasswordを自動設定することはありません。password hashがない既存ユーザーは
Adminによる明示的なreset/bootstrap後にログインできます。

通常のproductionでは`X-Role`/`X-User-ID`ヘッダー認証は無効です。既存の内部workerや
auth proxyとの互換が必要な隔離環境だけ、`LLM_GRADER_ALLOW_HEADER_AUTH=true`を明示して
有効化してください。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
```

テストにはモデル起動・実答案・ネットワーク接続は不要です。実際の認識精度と採点精度は、別途実モデルで確認します。
# Hierarchical grading preparation (H.2-F)

`src/scoring/grading_context.py` resolves root-to-leaf authoritative content and
derives question/test grading readiness. `GET /api/v1/tests/{id}/grading-readiness`
and `GET /api/v1/test-questions/{id}/effective-grading-context` are read-only.
Answers and Rubric sections in Test Workspace use the existing versioned
associations; structural nodes need neither. Removing an association retires its
current version, preserving historical records.

New domain grading jobs require per-question readiness plus the existing policy
and submission preconditions. `src/scoring/grading_inputs.py` snapshots context,
model answers, the validated legacy rubric and figure assets before execution.
Assignment question IDs must exactly match gradable compatibility question
numbers; no student-answer mapping or rubric levels are inferred. Old jobs and
CLI runs without domain snapshots retain the existing input path.

Validation: `.venv/bin/python -m unittest`, `.venv/bin/python -m pytest -q`,
`.venv/bin/ruff check`; in `frontend`, use the existing `typecheck`, `lint`,
`build` and `e2e` npm scripts. See `docs/phase-h2f-completion-report.md` for the
real PostgreSQL and browser evidence, including the existing sampleQ3 literal
LaTeX discrepancy that requires a separate authoritative correction workflow.

## Final grading review (I.1)

The read-only teacher review surface is available at
`/tests/{testId}/grading` and `/tests/{testId}/grading/{submissionId}`. It uses
`GradingReviewService`, which delegates final-result selection to
`grading_audit.resolve_authoritative_result`; the browser never implements
precedence or creates a job. The corresponding API endpoints are
`GET /api/v1/tests/{testId}/grading` and
`GET /api/v1/tests/{testId}/grading/{submissionId}`. They expose current
authoritative scores, teacher decisions, historical model results, immutable
input evidence, visual asset roles, and warning codes without exposing local
filesystem paths. Teacher actions are handled by the append-only endpoints
described below.

## Teacher review actions (I.2)

The detail page keeps the same resolver-backed read model and adds append-only
teacher actions. `POST .../questions/{questionId}/teacher-decision` validates
criterion IDs, allowed rubric levels, totals, and the immutable grading-input
snapshot before creating a `TeacherGradingDecision`. `POST
.../questions/{questionId}/regrade-request` records a `REGRADING_REQUESTED`
domain event without starting a model job. Submission and test finalization use
the corresponding `/finalize` endpoints and store references to authoritative
results rather than copying scores. `GET .../grading/export.csv` emits a UTF-8
BOM CSV with dynamic question columns and the authoritative Test total (so a
110-point test remains 110 points). Domain events provide the audit timeline;
no migration is required because these actions use the existing append-only
event table.

## Review workspace and regrade queue (I.3)

`/tests/{testId}/grading/review` filters unresolved warnings, pending regrades,
teacher decisions, reconstruction history, visual answers, and score bands in
one side-by-side workspace. `J`/`K` (or arrow keys) move between targets while
the focused action form keeps shortcuts inactive. `/tests/{testId}/grading/regrade-queue`
shows pending and approved requests; only the explicit approve endpoint may
seal a new current grading-input snapshot and enqueue one production
`GradingJob`. Rejecting writes a reasoned domain event and creates no job.
Worker completion/failure events close or retain the request for review, and
the existing TeacherDecision precedence remains authoritative over any new
model result.

## Student feedback and result publishing (I.4)

`ResultPublicationService` stores `results_published` and
`results_unpublished` as append-only domain events containing immutable result
references rather than copied scores. Publishing requires finalization,
complete authoritative results, no review flags, and no unresolved regrade
request. Teacher feedback overrides are separate append-only events and take
precedence only for the student-facing feedback projection.

Teacher controls are exposed below the grading overview and the student-safe
read-only projection is available at `/results/{submissionId}` through
`GET /api/v1/student/results/{submissionId}`. The student endpoint requires
`X-Student-ID` (or the equivalent `student_id` query value), exposes only the
published snapshot, and uses opaque visual-asset URLs. A changed authoritative
result is reported as `RESULT_CHANGED_AFTER_PUBLICATION` until the teacher
republishes. Result PDFs use the same sanitized projection and omit model,
rubric, audit, path, hash, and teacher-note data.

## Production readiness checks (I.5)

The review, publication, and legacy job/runtime APIs enforce a service-level
authorization boundary. Teacher routes require `X-Role: teacher`, `X-User-ID`,
and ownership of the Test's Course (unlinked legacy jobs still require an
active teacher identity); student result routes require `X-Role: student` plus
the student identity. Student visual URLs use opaque capabilities and are
resolved against the requesting student's published submissions.

For a non-destructive artifact backup manifest, run:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_backup_manifest.py artifacts \
  --output /tmp/llm-scoring-artifacts-manifest.json
```

The production logical backup command is `pg_dump --format=custom --file
backup.dump "$DATABASE_URL"`. Restore validation is a dry run: restore into
a disposable PostgreSQL database, run the manifest verifier with `--verify`,
and compare the database dump checksum and artifact manifest checksum before
switching any production pointer. No production restore is performed by the
test suite.
# Docker deployment

Docker Engine and the Docker Compose plugin are the only host dependencies for
the deployment path. From a fresh checkout:

```bash
cp .env.example .env
# Edit POSTGRES_PASSWORD and any site-specific ports in .env.
docker compose up -d --build
```

The first start waits for PostgreSQL, runs the Alembic migrations once, and
then starts the API and frontend. Open `http://localhost:${FRONTEND_PORT:-3000}`
and complete `/setup` to create the first administrator. Logs are available
with `docker compose logs -f`; stop the stack with `docker compose down`.

The named PostgreSQL and artifact volumes are retained by `down` and container
recreation. `docker compose down -v` removes those volumes and is a destructive
development reset, never a normal update procedure. For an update, pull the
new checkout, rebuild, and run `docker compose up -d --build`; the migration
service applies pending migrations before the API starts.
