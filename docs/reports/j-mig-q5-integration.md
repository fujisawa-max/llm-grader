# J.MIG.Q5 Legacy Q5 Service Recovery / PostgreSQL Integration Report

## Summary

**Phase J.MIG.Q5: COMPLETE**

Q5の406行をID保持で正式PostgreSQLへ統合。Admin／元所有Teacherの認証下で全画面、18件の既存採点結果、原答案・Q3 visualを実Chromiumで確認した。SQLiteは変更せず保存。再採点・OCR・model callなし。

正式URL: http://ai-serv2:3001/login

API: http://ai-serv2:8000/api/v1/health

## Legacy Service Investigation

開始時、旧SQLiteサービスの3001／8000は停止。旧PID 2298701（API）／2319806（Frontend）は存在せず。停止理由を示す確実なログは得られず、原因は未特定。OpenWebUIコンテナ／PostgreSQLコンテナは稼働。

shell history、既存ログ、repository scripts、service定義、container定義、shell snapshots、Codex session履歴を調査。Codexの関連起動記録41件について秘密値を含めないmetadataを保存した。

## Legacy Code / Startup Reconstruction

旧APIは `uvicorn scoring.api.server:app --host 0.0.0.0 --port 8000`、Frontendは `npm run dev -- --hostname 0.0.0.0 --port 3001`。以前のprocess environmentにSQLite／artifact rootを確認済み。

git HEADと作業ツリーには未commitのWeb実装があり、認証追加前の一式を再現可能な単一code versionは確定できなかった。推測checkout、旧認証への復帰、SQLiteへの認証migrationはしなかった。旧サービスの一時復旧を成功条件とせず、PostgreSQL上でデータ・画面を再現した。

現行コードSHA manifest、git HEAD/status、legacy調査metadataをbackup-setのvalidationに保存。

## SQLite Inventory

read-only接続で全33テーブルを調査。総406行。空テーブルもinventoryに記録。

| Table | Source | Migrated |
|---|---:|---:|
| users | 1 | 1 |
| courses | 1 | 1 |
| domain_events | 40 | 40 |
| course_offerings | 1 | 1 |
| tests | 1 | 1 |
| students | 3 | 3 |
| test_questions | 7 | 7 |
| test_materials | 11 | 11 |
| rubric_versions | 1 | 1 |
| grading_jobs | 33 | 33 |
| question_import_extractions | 1 | 1 |
| model_answers | 6 | 6 |
| student_submissions | 3 | 3 |
| test_question_assets | 1 | 1 |
| grading_job_items | 33 | 33 |
| grading_runtime_snapshots | 33 | 33 |
| student_answer_extraction_runs | 25 | 25 |
| question_import_drafts | 1 | 1 |
| grading_job_events | 135 | 135 |
| student_answer_extraction_results | 25 | 25 |
| question_import_draft_nodes | 5 | 5 |
| student_answer_reconstructions | 25 | 25 |
| question_import_reviews | 1 | 1 |
| question_import_review_revisions | 2 | 2 |
| question_import_confirmations | 1 | 1 |
| question_import_confirmation_items | 8 | 8 |
| test_question_corrections | 2 | 2 |

`grading_results` / `reconstruction_artifacts`という独立テーブルは存在しない。結果はgrading_job_itemsとartifact、読み取りはstudent_answer_reconstructionsとartifactの組として扱う。

## Q5 Entity Inventory

- Owner: `1ab60f19-09c7-4f46-9288-1ab4f0b014de`
- Course: `11262610-d5aa-437a-b821-89e1fcb91602`
- Offering: `a68fea6e-0fb7-4768-9892-9a426acc5634`
- Test: `196893ba-f57f-41a9-974e-8d51b697d672`
- Questions: 7（gradable 6、structural 1）
- Submissions: 3、current authoritative results: 18
- Accepted Q3 visual assets: `cff25c37-2bb0-5e95-bcba-22346417aed3` / `eff9e878-b9a8-5eb6-b92e-43a2ab55ce2a` / `ca7a704f-162d-5c7c-868b-3b620631499d`

全entityのID・parent ID・FK・source SHA・選択状態・historyは `validation/inventory.json` に記録。visual metadataはDomainEventとTestMaterialに保持。Student identityのartifactもコピー対象に含めた。

## Artifact Inventory

artifact単体397ファイル、SQLite本体を加えた従来のSHA確認対象398ファイル。

relative path／size／SHA256のmanifestをbackup-setに保存。元398/398一致、永続artifactコピー397/397一致。元artifactの削除・内容更新なし。

## PostgreSQL Inventory

container `llm-grader-pg`、DB `grader`、port 55432、revision `0013_authentication`。移行前はusers 13、courses 13、tests 16、questions 33、submissions 14、grading_jobs/items各50。

移行後はusers 14、courses 14、tests 17、questions 40、submissions 17、grading_jobs/items各83。33 Jobの増加は既存Q5履歴のコピーであり、新しい処理Jobの生成ではない。

## SQLite / PostgreSQL Schema Diff

- 共通テーブルで列の差はusers.role/password_hash/must_change_passwordの3列のみ。
- PostgreSQLにはauth_sessions／alembic_versionが追加で存在。
- SQLite Boolean、JSON、日時はSQLAlchemy型で読み、PostgreSQLへ型付きinsert。
- SQLiteのnaive UTC日時はPostgreSQLではUTC timezone表記になる。時刻の意味は保持。
- JSON object／listの内容は保持。採点bundle/snapshotのpathを含むJSONを書き換えない。
- PK、unique、FK、nullable/type/default差を `schema-diff.json` へ保存。FKを全件事前検証し、実insert時もPostgreSQL constraintsで検証。
- ownership構造は既存owner_user_idを保持。

## ID Collision Analysis

既存PostgreSQLとのID衝突0。再採番0。natural uniquenessは事前検査およびstaging／production transactionの制約で確認。source DBが指定1 Testに閉じていることも検証。

## User Mapping

旧所有UserはPostgreSQLにexact ID／同名matchなし、emailはNULL。別Userとの自動統合はしない。旧IDでteacherとしてimport。

その後、ユーザの明示承認「専用ログイン情報を設定して検証」に基づき、この同じ所有者だけに `q5-pilot-owner@example.invalid` とランダムpasswordをAdmin APIで設定。元SQLite Userは変更していない。

## Course Ownership Mapping

owner IDは移行前後同一。Adminや前Phaseの検証Teacherへ付け替えていない。元所有TeacherのloginとCourse／Testアクセス、Adminアクセス、偽造X-RoleでのAdmin API拒否を確認。

## Migration Strategy

全ID／FK／history保持。source read-only、copy first、SHA verify、dry-run、staging copyへのtransaction import、browser gate、production transaction importの順に実施。旧failed15件とcompleted18件を含む33 Jobを保持。pending Jobはない。

## Migration Tool

`scripts/migrate_q5_sqlite_to_postgres.py`

- default dry-run、明示--applyのみinsert
- DB URLは環境変数入力、秘密値非出力
- PK/unique conflict検知、FK事前検証
- identical rowはskip、競合はoverwriteしない
- transactionで全件rollback
- source/destination artifact checksum照合
- 明示的path mapping report

staging／productionとも初回406 insert、直後の再実行0 insert／406 existing。後続の承認済みaccount編集を含む再importではUser差分がconflictになる仕様であり、その変更を上書きしない。

## Backup

Backup set:
`/opt/llm-scoring/data/migration-backups/jmig-q5-20260926T031309Z`

- `pilot.sqlite`: source byteコピー、SHA一致
- `grader.dump`: pg_dump custom format、528,487 bytes、pg_restore --list成功
- `artifacts-manifest.json`: 397 files、relative path／size／SHA
- 永続artifact copy: `/opt/llm-scoring/data/q5-artifacts`
- `validation/`: inventory/schema/collision/dry-run/apply/browser/gate/row-integrity/既存PG保全検証

production restore／resetは未実施。

## Dry-run Result

PASS。insert予定406、already present0、conflict0、unresolved FK0。正式DBへの書き込みなし。user/ownership/path mappingを記録。

## Staging Migration

正式DB dumpを別DB `grader_jmig_q5_stage` へ復元して検証。grader自体をrestoreしていない。

406行insert、FK整合PASS、2回目0行insert。隔離自動テストでもdry-run非変更・同一入力idempotency・conflict非上書き・insert失敗時全rollback・artifact mismatch拒否を検証。

## Staging Browser Validation

API8002／Frontend3003を使用。Admin login、Teacher初回password変更、Course、Test、Questions、ModelAnswer、Rubric、Student Answers、Grading、Resultsの全項目PASS。

原答案3/3、各学生selected reading6/6、Q3 visual3/3。Question／ModelAnswer／Rubric PDF pane表示PASS。6gradable、18completed、誤った準備未完了表示なし。

## Production Migration

staging gate PASS後のみgraderへ適用。単一transaction成功、再実行追加0。

406行を全カラム比較し、明示的file path変換と承認された所有Userのemail/updated_at以外は元SQLiteと一致。認証列は新schemaのteacher/password状態として追加。

移行前から存在したPostgreSQLデータは追加Q5行と認証auditを除外し、全行ハッシュ一致。既存GradingJobs／results／TeacherDecisionは不変。

## Artifact Migration / Mapping

永続先 `/opt/llm-scoring/data/q5-artifacts`。

40件のoperational pathを明示変換:
- TestMaterial.storage_refのabsolute source path
- GradingJobItem.raw_response_path / normalized_result_path

relative referencesはそのまま。sealed JSON／runtime provenanceに含まれる旧absolute pathは歴史的証跡として保持し、再hashしない。現在の原答案・PDF・cropは永続root／変換済みmaterial参照から表示。

旧pathを含む履歴の再実行は対象外であり実行しない。元artifactはそのまま残す。

## Authentication Integration

既存cookie sessionとDB roleを使用。header auth=false、Student portal=false。AdminとQ5所有Teacher login PASS。TeacherからAdmin APIへのheader偽装は403。passwordはscrypt hash、plaintextをログ／報告へ記載しない。

操作者用資格情報: `/opt/llm-scoring/data/operations/q5/owner-credentials.json` と `admin-credentials.json`（0600、親0700）。Q5 Teacher email: `q5-pilot-owner@example.invalid`。

## Production Browser Validation

正式3001／8000でstagingと同じ全画面確認PASS。実Chromiumで3名の原答案、18 selected reading、Q3 visual、採点済み状態、合計・設問別結果を確認。

`http://ai-serv2:3001/login`、`http://ai-serv2:8000/api/v1/health` はHTTP200。

## Result Integrity

| Student | Total | Status |
|---|---:|---|
| M0A999947 山田工大 | 65/100 | COMPLETE |
| M0A999978 工科太郎 | 90/100 | COMPLETE |
| M0A999987 田中花子 | 100/100 | COMPLETE |

18件のauthoritative result ID／score／max／criterion／feedback／Student Answer／ModelAnswer／Rubric／warning／review flagsが一致。sourceとdestinationのoverview DTOも一致。Question別詳細・監査historyは検証evidenceへ保存。

## No-Reprocessing Verification

Ricoh0、Uni-MuMER0、Ornith Reconstruction0、Ornith Grading0。

新規処理用GradingJob0。移入した既存履歴33件（completed18、failed15）のstate・結果は保持。新規grading実行イベント0。worker／model server起動なし。

## Runtime / OpenWebUI Integrity

OpenWebUI3000変更・停止なし。RuntimeManager／llama-server設定・起動停止・model download/deleteなし。

## Cutover

正式Q5はPostgreSQL＋認証付きAPI8000／Frontend3001へ切替完了。旧SQLiteを使用しない。

- API PID: 2416790
- Frontend PID: 2417533
- API launcher: `scripts/run_q5_postgres.py --database-url-file data/operations/q5/database-url --port 8000`
- Frontend cwd: `/opt/llm-scoring/data/deployments/q5-frontend`
- Frontend: build済みNext.jsを `npm run start -- --hostname 0.0.0.0 --port 3001`
- API_PROXY_TARGET=http://127.0.0.1:8000、browser API=/api/v1
- DB URL保管file0600、PostgreSQL grader55432、revision0013

8001／3002の前Phase検証サービスは保持。8002／3003のstagingサービスも比較用に保持。旧SQLiteサービスは停止状態のまま、削除していない。

## Rollback Plan

`docs/operations/q5-postgres-cutover.md` に切替前から手順を保存。

import失敗はtransaction rollback。切替後の復旧は新しいrecovery DBへbackupをrestoreして検証し、明示的に接続を戻す。graderのreset／無断上書きrestore／DELETEはしない。SQLite source、旧artifact、永続artifactコピー、接続構成を保持。

## Remaining Issues

旧サービス停止原因と認証追加前の再現可能コード版は未確定。ただしPostgreSQLで既存Q5状態を再現できたため本Phaseのblockerではない。

プロセス自動起動のsystemd化、backupの別ホストへの退避、legacy/tmp cleanupは今回実施していない。履歴snapshotの旧pathは改変せず保存し、再処理対象にしない。staging資源の削除も別判断。

## Checklist

- [x] Legacy startup／code／history／logs／process調査（停止原因は未特定）
- [x] SQLite全table／entity／FK／artifact inventory
- [x] PostgreSQL schema diff／ID collision／owner mapping
- [x] dry-run／idempotency／transaction／rollbackテスト
- [x] SQLite／PostgreSQL backup／artifact manifest
- [x] staging migration／FK／browser PASS
- [x] production migration／全406行照合PASS
- [x] 原398/398、copy397/397 SHA PASS
- [x] Admin／元所有Teacher認証／ownership／header偽装拒否
- [x] 全画面／18結果／3 visual／65・90・100 totals
- [x] no model calls／no new execution jobs／runtime不変
- [x] PostgreSQL正式切替／到達性／rollback手順

検証: migration unittest4件PASS、pytest4件PASS、変更scripts/testsのRuff PASS。Frontend production build PASS（type/lintを含む、既存warningあり）。grading core／Reconstruction／UI実装変更なし。

## Final Decision

**Phase J.MIG.Q5: COMPLETE**
