# J.UI.Admin.1a Production DB Migration & Live Authentication Validation Report

## Summary

PostgreSQLへの0013適用、既存データ保全、分離サービスでのAdmin／Teacher実ブラウザ検証はPASS。現行Q5サービスの8000／3001が最終確認時に停止しており、元の認証追加前コードを確認できないため、全体判定はPARTIAL。

今回Q5サービスへの停止命令、接続変更、migrationは行っていない。停止原因は未特定。最後の再起動許可は「元の構成を確認できた場合のみ」であり、この条件を満たさないため再起動していない。

## Environment Separation

| 環境 | Frontend | API | DB |
|---|---|---|---|
| PostgreSQL検証 | http://ai-serv2:3002 | http://ai-serv2:8001/api/v1 | llm-grader-pg / grader / 55432 |
| 現行Q5 | 3001（最終確認時停止） | 8000（最終確認時停止） | /tmp/j1-q5-pilot/pilot.sqlite |

検証Frontendは `/tmp/jui-admin1a/frontend` の分離コピー。build検証も別コピー `/tmp/jui-admin1a/build` で実行。現行Frontendのビルド出力を変更していない。検証APIはheader auth無効、student portal無効。model runtime接続を設定せず、workerを起動していない。

## Pre-Migration State

PostgreSQL revision: `0012_teacher_grading_decision`。既存34テーブルの件数と全行ハッシュを `/tmp/jui-admin1a/before.json` に記録。

## Backup

- ファイル: `/tmp/jui-admin1a/grader-20260925T224102Z.dump`
- サイズ: 523,848 bytes
- 形式: PostgreSQL custom-format pg_dump
- `pg_restore --list`: PASS。目録 `/tmp/jui-admin1a/backup-toc.txt`
- SHA256: `04c0f00699f0d3db1548508a9efeb56345afd0ace6f4234e5d457a25bc1a72cf`
- 実restoreは未実施。保管ディレクトリはmode 0700。長期保管先への転送は未実施。

## Migration Applied

既存Alembicの `upgrade 0013_authentication` をPostgreSQLに実行。upgradeはUser列追加、email index、auth_sessions作成であり既存行の削除なし。downgradeは追加した認証テーブル・列を削除するため実行していない。

## Migration Revision

`0012_teacher_grading_decision` → `0013_authentication`。PASS。

## Schema Verification

`users.role`、`password_hash`、`must_change_password` と `auth_sessions` を確認。既存 `display_name/email/is_active/created_at/updated_at` は保持。session列は `id/token_hash/user_id/created_at/expires_at/revoked_at`。raw token列なし。

## Existing Data Count Comparison

| 実テーブル | migration前 | migration直後 | 検証終了後 |
|---|---:|---:|---:|
| users | 11 | 11 | 13 |
| courses | 12 | 12 | 13 |
| course_offerings | 11 | 11 | 11 |
| tests | 16 | 16 | 16 |
| test_questions | 33 | 33 | 33 |
| test_materials | 32 | 32 | 32 |
| model_answers | 34 | 34 | 34 |
| rubric_versions | 35 | 35 | 35 |
| student_submissions | 14 | 14 | 14 |
| student_answer_reconstructions | 62 | 62 | 62 |
| grading_jobs | 50 | 50 | 50 |
| grading_job_items | 50 | 50 | 50 |
| teacher_grading_decisions | 2 | 2 | 2 |
| domain_events | 320 | 320 | 328 |
| auth_sessions | 未作成 | 0 | 6 |

このschemaに独立した `grading_results` / `reconstruction_artifacts` テーブルはない。採点値・結果artifact参照は `grading_job_items`、読み取りartifact参照は `student_answer_reconstructions` 等を検証した。migrationだけでは既存テーブル件数の増減なし。

## Existing User Migration

既存11 UserはID・氏名・email・is_active・日時を含む旧列全体がハッシュ一致。既存Userはrole=teacher、password_hash=NULL。固定パスワード付与、既存UserのAdmin昇格なし。元のCourseとownershipの全行ハッシュも一致。

## Admin Bootstrap

既存CLI実装を利用し専用Adminを1名追加。

- 名称: JUI Admin1a Validation Admin
- email: jui-admin1a-admin@example.invalid
- ID: 82d2a4b1-ffc6-48fe-a7cd-0d75ed237f50

パスワードはランダム生成、DBはscrypt hashのみ。秘密値は報告・ログへ出していない。操作者用の資格情報ファイルは `/tmp/jui-admin1a/credentials.json`（0600、親0700）。既存Userを置換していない。

## Admin Browser Validation

Chromiumでlogin、auth/me admin確認、reload後のsession維持、管理navigation、User一覧、Teacher作成、logoutの全項目PASS。

## Teacher Browser Validation

専用Teacher `JUI Admin1a Test Teacher` / `jui-admin1a-teacher@example.invalid` をUIから作成。

ID: `0479de92-397b-4195-97f0-4fcff9f7d266`。

login → 初回password変更画面 → password変更 → must_change_password解除 → reload → Course作成 → logout: PASS。Admin navigation非表示、/admin/users直接アクセス時に管理画面を表示しないこともPASS。

## Course Ownership Validation

作成科目: `JUI Admin1a Validation Course`。

ID: `5c503d88-c12a-4347-a4d3-ed7275be3353`。

DBとAPI両方でownerが上記Teacherであることを確認。偽のowner指定による作成は専用一時SQLiteの実APIテストで、指定が無視されlogin Teacherになることを確認（PostgreSQLに余分な科目を作成していない）。

## Authorization Validation

- TeacherのAdmin GET/POST API: 403
- Teacherから他所有者Course／Test: 403または404
- Teacher自身のCourse: 200
- Teacher session＋偽造X-Role/X-User-ID: Admin API拒否
- 未認証＋偽造header: 拒否
- `LLM_GRADER_ALLOW_HEADER_AUTH=false`
- User responseにpassword_hashなし

## Session Validation

cookie tokenのSHA256に一致するDB token_hashが存在し、raw tokenと一致する保存値はないことを実DBで確認。logout後のrevoked_atと同じcookieの再利用拒否を確認。inactive中の既存sessionも拒否。

## Password Reset / Activate / Deactivate Validation

検証Teacherのみ対象。deactivate → login拒否 → reactivate → login成功 → reset → 旧password拒否 → temporary password成功／must_change_password=true → 変更完了: 全PASS。

検証Teacherは有効、must_change_password=falseで保持。既存運用Userへの操作なし。

## Existing Grading Data Integrity

grading_jobs 50、grading_job_items 50、grading_job_events 295、grading_runtime_snapshots 61、teacher_grading_decisions 2の全行ハッシュ一致。score・max・status・artifact参照を含めて不変。新規grading job/model callは0。

## Sample Q5 Integrity

PostgreSQLに指定Q5は存在せず、PostgreSQL上のQ5検証はNot Applicable。SQLiteへのmigration、コピー、統合は行っていない。

## Q5 Environment Integrity

- Q5 service reachable: FAIL（最終確認時8000／3001のlistenerなし）
- Q5 DB changed: NO
- Q5 artifacts changed: NO
- Q5 grading data changed: NO

SQLite本体＋artifactの398ファイルが変更前SHAと完全一致。旧Q5には認証用User列／auth_sessionsがない。認証追加前のコード保存版は探索範囲で見つからず、現行コードの起動や無断migrationで補わなかった。

## Regression

- unittest: 既存Authentication 3件PASS
- pytest: authentication/domain/API/I.5 readiness、25件PASS
- owner spoof専用API unittest: 1件PASS（sandbox TestClient停止待ち後、通常環境で再実行）
- Ruff: auth.py/admin.py/0013/test_authentication.py、PASS
- Frontend typecheck: PASS
- Frontend lint: errors 0、既存warnings 15
- Frontend build: PASS
- 実Chromium smoke: PASS
- 実PostgreSQL/API追加チェック: 25項目PASS

full backend suite／全repository Ruffは今回未実施。実DB検証はlive API、既存自動テストは隔離fixture DBを使用。

## Service Availability

- Validation Frontend 3002: HTTP 200
- Validation API 8001: health HTTP 200、未認証auth/me拒否
- PostgreSQL 55432: 接続正常
- Existing Q5 8000/3001: 停止、原因未特定
- OpenWebUI 3000: listener維持。設定変更・停止操作なし
- llama-server／RuntimeManager: 起動停止・設定変更なし

## Data Mutations

許可されたmigration、専用Admin+Teacherの2 User、検証Course 1件、監査イベント8件、auth_sessions 6件のみ。検証Teacherのpassword変更・reset・active切替を実施。既存User／Course／監査イベントは追加分除外後の全行ハッシュも一致。既存採点データ変更0、model call 0、new grading job 0。DB reset／restoreなし。アプリケーション実装変更なし。

## Remaining Issues

Q5サービスを元の構成で復旧するには認証追加前のコード／デプロイ成果物の確認が必要。この条件未達のため現時点では全体COMPLETEにしない。

検証サービスと資格情報・backupは/tmp配下であり、恒久的な運用配置ではない。

## Deferred Work

- Q5 SQLite → PostgreSQL migration / integration
- Unified production DB cutover

上記は別Phase。今回実施していない。

## Checklist

- [x] PostgreSQL backup／目録確認
- [x] 0013 migration／revision／schema確認
- [x] 既存件数・旧User・ownership・採点値保持
- [x] Admin browser login／Teacher作成／logout
- [x] Teacher browser login／初回password変更／Course作成／logout
- [x] Admin API拒否／他所有者データ拒否／header偽装拒否
- [x] session hash／logout失効／inactive拒否
- [x] reset／activate／deactivate
- [x] targeted regression／frontend typecheck・lint・build
- [x] PostgreSQLとQ5環境分離／Q5全ファイル不変
- [ ] 現行Q5 service reachable

## Final Decision

Phase J.UI.Admin.1a: **PARTIAL**

PostgreSQL移行・認証検証は完了。残件はQ5の元構成確認とサービス稼働復旧。


---

## Final Reachability Check / Resume — 2026-09-26T02:36:25.277174+00:00

### Current service state

開始時は3001／8000／3002／8001すべてLISTENなし、Frontend/APIプロセスなし。前回のPASS済み認証・migration・regressionは再実行していない。

| Port | 最終状態 | PID | Command line | Working directory |
|---|---|---|---|---|
| 3001 | NOT LISTENING | — | 稼働プロセスなし | — |
| 8000 | NOT LISTENING | — | 稼働プロセスなし | — |
| 3002 | LISTEN 0.0.0.0 | 2412811 | next-server (v15.5.7); 起動: npm run dev -- --hostname 0.0.0.0 --port 3002 | /tmp/jui-admin1a/frontend |
| 8001 | LISTEN 0.0.0.0 | 2412731 | /opt/llm-scoring/.venv/bin/python /opt/llm-scoring/.venv/bin/uvicorn scoring.api.server:app --host 0.0.0.0 --port 8001 | /opt/llm-scoring |

### Validation service reachability

前回と同じops.py serveと分離Frontendコピーから再起動。

- GET http://127.0.0.1:3002/login: HTTP 200
- GET http://127.0.0.1:8001/api/v1/health: HTTP 200
- 外部向けURL: http://ai-serv2:3002/login / http://ai-serv2:8001/api/v1/health（0.0.0.0で待受、今回のHTTP検証はloopbackから）
- API接続先: PostgreSQL 127.0.0.1:55432/grader。revisionは前回確認済み0013_authentication。今回migrationを実行していない。
- Frontend: NEXT_PUBLIC_API_BASE_URL=/api/v1、API_PROXY_TARGET=http://127.0.0.1:8001
- Header auth=false、検証artifact root=/tmp/jui-admin1a/artifacts。

### Existing Q5 reachability

**UNRESOLVED**。8000／3001は再起動していない。

shell historyにはuvicorn scoring.api.server:app --host 0.0.0.0 --port 8000、およびNEXT_PUBLIC_API_BASE_URL=http://10.206.135.18:8000/api/v1 npm run dev -- --hostname 0.0.0.0 --port 3001を確認した。ただし履歴更新日はQ5稼働より前で、Q5固有のDB/artifact設定と当時のコード版を一組として復元できない。

以前のプロセス情報からSQLite／artifact接続先は既知だが、該当プロセスは消失。既存ログに停止理由の記録はなく、systemd定義・repository scripts・稼働containerにもQ5の元デプロイ定義を確認できなかった。探索範囲のコード保存版とgit HEADにも認証追加前のWeb実装を確認できない。

Q5 SQLiteには認証カラム／auth_sessionsがないため、認証追加後の現コードを同じコマンドで起動するだけでは元構成の再現にならない。推測による構成作成・DB migration・認証迂回は実施していない。停止原因は未特定。

### Data integrity

既存記録の398ファイルをSHA256再照合し、変更／欠損0。Q5 DB、artifact、grading data、reconstruction artifact変更なし。今回はbackup、migration、認証操作、user/course作成、regressionを再実行していない。新規grading job 0、model call 0。OpenWebUI／model runtime変更なし。

### Final Decision

**Phase J.UI.Admin.1a: PARTIAL**

**Authentication / PostgreSQL migration validation itself: COMPLETE**

**Existing Q5 service reachability: UNRESOLVED**

Q5の認証追加前コード／デプロイ成果物の特定と、その構成での再起動が残件。
