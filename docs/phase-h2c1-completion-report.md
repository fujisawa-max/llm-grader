# Phase H.2-C.1 Completion Report

## 1. Existing H.2-C output findings

既存PostgreSQLとartifactを確認した。Q2の3数式、Q3の3数式・1図が対象。
Uni-MuMER 6件はcontentが空で、`choices[0].message.reasoning_content`に同じ式が2回保存されていた。
Ricohはreasoning内に指示文・空のJSON見本・観察文を出力し、`finish_reason=length`で終了していた。
したがって「JSON objectが見つかった」だけで成功扱いすると、空の見本を結果として誤採用する。
実装・raw形式・DB JSON・migration 0007・既存API・LocalClientを確認し、モデル実行経路は変更しなかった。

## 2. Files changed

- `src/scoring/vision_output.py`: role別parserとdeterministicな派生view。
- `src/scoring/adapters/question_vision.py`:既存normalize入口からparserへ委譲。
- `src/scoring/question_vision.py`:新規出力のparser利用、model不要の`reparse(run_id)`。
- `tests/test_vision_output.py`:15件のparser tests。
- `tests/test_question_vision.py`:replay、旧evidence保持、API、改ざん検知の2件追加。
- 本レポート。

実データ監査結果: `artifacts/h2b-verification/h2c1-parser-replay-audit.json`。
未追跡ファイルを含む既存worktreeの変更は保持した。

## 3. DB / migration decision

migrationなし。既存result.evidence JSONへ`parsed_view`と`parsed_views`を追加。
PostgreSQL headは`0007_question_import_vision`。run/resultの削除、DB resetなし。

## 4. Parser architecture

`VisionOutputParser` Protocolを、`UniMuMerOutputParser` / `RicohVisionOutputParser`が満たす。
`parse_output`がraw fieldの選択、role別処理、provenance、警告、hashをまとめる。
PDF、runtime、network、推論はparserの依存に含まれない。

## 5. Parser versions

- `unimumer-output-parser-v1`
- `ricoh-output-parser-v1`

prompt versionとは独立。parser-only replayで既存run.snapshot/input hashを変更しない。
H.2-Cの`normalization_version` identity markerは既存runの再利用のため保持し、実際のparser versionは派生viewに記録する。

## 6. Raw output preservation

API response全体を保存済みのraw.jsonから読む。raw/crop/旧normalizedの参照・hash・内容は変更しない。
新しいviewは`vision/<run>/parsed/<region>/<parser-version>/<content-hash>.json`に保存する。
旧viewも`parsed_views`に保持し、既存のartifactを上書きしない。

## 7. Uni-MuMER parser

非空文字列についてcontent → final → answer → reasoning_content → reasoningの順で採用する。
contentが存在するときreasoningを連結しない。raw自体が文字列の場合はraw_textとして扱う。
fence行を除き、保守的な字句判定で数式候補行を抽出する。採用文字列の元fieldと文字offsetを保存する。
trim後の完全一致行のみ重複除去する。異なる文字列・内部空白の異なる式は統合しない。
LaTeX environment内の反復行は行列等を壊さないため重複除去しない。

## 8. Uni-MuMER normalization safety

`2 1`、`6 9`、`1 2`はそのまま保持。token間space、符号、変数、分数を修正しない。
`transcription_raw_candidate`には重複を含む抽出列を、`transcription_normalized`には重複除去後を保存。
既存`output.recognized_expression`も維持する。
native比較は従来どおりwhitespace除去後の文字列比較で、数学的同値判定ではない。
replay時には既存`native_vision_disagreement`も保持する。

## 9. Ricoh parser

pure JSON、fenced JSON、前後に説明のあるJSONを`JSONDecoder`で読む。comma・key/valueの補完は行わない。
異なる有効objectが複数ある場合は選ばず警告にする。
説明文中の空のschema見本を除外する。standalone/fencedの空JSONは有効な空結果として扱う。
JSON失敗時は観察文全体を`unparsed_text` / `unstructured_observation`に保持する。
plain text内の`visible_textは[...]`、`labels=[...]`等、明示されたJSON文字列配列のみ部分抽出する。
一般の自然言語記述から図形・関係を推論しない。

## 10. Ricoh structured schema

有効なJSONは`visible_text`、`visual_elements`、`spatial_relations`の文字列配列を要求し、`labels`は存在時に検証・保存する。
fallbackで未取得fieldを推測で補完しない。`structured=false`と`parse_status=partial/unstructured`で区別する。

## 11. Hallucination / answering safeguards

「答えは」「解くと」「the answer is」「solving gives」等は`model_answering_detected`を付け、structured candidateへ採用しない。
互換の`possible_answer_inference`も残す。これは字句上の安全策で、全hallucinationを検出する保証ではない。
reasoningから取得した結果には常に`reasoning_output_requires_review`。
打切りには`vision_output_truncated`。全結果`authoritative=false`。

## 12. Prompt changes

変更なし。既存rawだけで改善可能な範囲を優先した。

## 13. Runtime option changes

変更なし。既存llama.cpp request、generation、reasoning option、RuntimeManager lifecycleを維持。
新たなgrammar/JSON-schema optionや未確認のruntime capabilityは使用していない。

## 14. Parser-only replay

`VisionFallbackService(session, artifact_root).reparse(run_id)`で実行する。
inference adapterは不要。renderを呼ぶと例外になる検証用rendererで実データを確認した。
再parse前にrun snapshot、保存plan/manifest、source Draft/IR/PDF、raw/crop/旧normalizedのhashを確認する。
新しいviewを全件準備してからDBへ反映する。同じraw/parserで再実行しても同じpath/hashとなる。
既存normalizedはそのまま、API consumerは`evidence.parsed_view.result`を優先表示できる。

## 15. Reproducibility

viewにはparser name/version、model role、region ID、source field、raw hash、元文字offsetを保存する。
view内`normalized_sha256`は、そのfield自身を除いたcanonical JSONのhash。
`parsed_view.artifact_sha256`はhash fieldも含むJSONファイル全体のhashで、両者を区別する。
timestamp、DB UUID生成、network、model再実行はparserの結果へ入れない。

今回のnormalized content hash（raw/crop/file hash全値は監査JSONに記録）:

| Region | normalized_sha256 |
|---|---|
| Q2 formula-0001 | `2cfb4b4596b2668d11790ce118ed62f2b3f4b79465324eacbe00d3244bd73181` |
| Q2 formula-0002 | `3e7bf1cc5ad0a24f5f3b6126a9de3084d942e210fdeff2ee82f542f0961ef74f` |
| Q2 formula-0003 | `2b1dbb14506a1a1bf15a38d6db3c7d1e241ebca79e404ae38b465e258f5add19` |
| Q3 formula-0001 | `8e06506c6e27e74481472e24e6b94269a941cbc4fc9033bb31970a5cbf4f1edc` |
| Q3 formula-0002 | `45af938fcc66084ae60675956000d1aa863094cfaa0ffe26fcf796e23baed11c` |
| Q3 formula-0003 | `b1ff045cda5cf9f2cce735b103fdc1cf8a30528391cc151dbfa7674220bf23a9` |
| Q3 figure-0001 | `bb02c9630676a3838d2a1d0b1f63366a0bbe9cdf808828f763b5aaf1589c8bc0` |

## 16. Synthetic tests — Uni-MuMER

clean content、reasoning2形式、空content fallback、content優先、完全一致反復、異なる式の保持、
内部数字spaceの保持、matrix反復行、prose除外とoffset、empty/truncated、解答文の隔離を検証。

## 17. Synthetic tests — Ricoh

valid JSON、json fence、languageなしfence、prose+JSON、malformed JSON、plain text保持、
schema echo、明示ラベル配列、競合する複数JSON、解答文、empty、hashのdeterminismを検証。
evalや実行可能なtext解釈は使用しない。

## 18. Real parser replay — sampleQ2

既存run: `e8d91c5e-5aec-49e5-b0b5-f736052e099e`。
全件source fieldは`choices[0].message.reasoning_content`、raw candidateは下記と同じ文字列2行。

| Region | normalized candidate | 重複除去 | 判定 |
|---|---|---|---|
| formula-0001 | `2 x ^ { 3 } - 2 1 x ^ { 2 } + 6 9 x - 7 0 = 0` | true | parsed / review |
| formula-0002 | `x ^ { 3 } = - 8` | true | parsed / review |
| formula-0003 | `y = - \frac { 1 } { 3 } x ^ { 2 } - 2 x - \frac { 5 } { 3 }` | true | parsed / review |

全件警告: `exact_duplicate_removed`, `native_vision_disagreement`, `reasoning_output_requires_review`。

## 19. Real parser replay — sampleQ3 formulas

既存run: `3d638755-fd4e-49a9-a316-bcdc175ae6b9`。
全件reasoning_content、raw candidateは同じ式2行。全件重複除去true・parsed、警告はQ2と同じ。

| Region | normalized candidate |
|---|---|
| formula-0001 | `\sin \frac { 5 } { 1 2 } \pi + \sin \frac { 1 } { 1 2 } \pi` |
| formula-0002 | `\sin x + \sin y = 2 \sin \frac { x + y } { 2 } \cos \frac { x - y } { 2 }` |
| formula-0003 | `\cos \frac { 1 } { 1 2 } \pi` |

## 20. Real parser replay — sampleQ3 graph

`figure-0001`: meaningful valid JSONなし、JSON fenceなし。空JSON見本を除外。
`structured=false`, `parse_status=partial`。
raw中の明示配列からvisible_textとlabelsへ`[-2π, -π, π, 2π, 3, -3]`を取得。
visual_elements / spatial_relationsは採用していない。観察文中には点・波形位置について推測や自己訂正があり、rawでのみ閲覧可能。
明示的な解答検出patternには該当しないが、これは推論混入がないという保証ではない。
警告: `json_template_ignored`, `partial_structured_extraction`, `reasoning_output_requires_review`,
`vision_output_parse_failed`, `vision_output_truncated`。

## 21. Old vs New normalized results

数式:旧viewの2行反復から1候補へ。内部spaceは不変。6件ともdisagreementとreasoning警告を維持。
図:旧viewのunparsed textだけの状態から、明示ラベル配列とそのraw内offsetを追加。
rawの正しさ・図の意味をparserが保証するものではない。
元のnormalized.jsonは7件すべて保持しており、新旧を並べて比較可能。

## 22. Uni-MuMER smoke rerun

実行なし。prompt変更なし。既存6rawをモデル再実行なしで評価した。

## 23. Ricoh smoke rerun

実行なし。prompt/runtime変更なし。JSON生成率の改善は主張しない。

## 24. Routing regression

| PDF | Vision | Native sufficient |
|---|---:|---:|
| sampleQ1 | 0 | 0 |
| sampleQ2 | 3 | 1 |
| sampleQ3 | 4 | 2 |

既存GET/plan API経路で確認。routing code/config変更なし。

## 25. Crop regression

Q2で26ファイル、Q3で40ファイルについてsource/native/structuredおよびraw/crop/旧normalizedの前後hashを検証。
crop bbox、image SHA、render DPI、marginは不変。crop再生成0件。

## 26. Overlay compatibility

`question-import-vision-overlay.v1`維持。旧fieldは削除/renameせず、evidenceへparsed viewを追加。
`question-region-vision-evidence.v1`も維持し、parser metadata/status/hashを追加。
既存のraw/ref・normalized_result・attempt・state・anchor associationは保持。

## 27. API compatibility

新REST endpointなし。既存results GETは旧fieldと追加parsed_viewを返す。
実PostgreSQLを利用するTestClientでQ2/Q3とも200、内部absolute path非露出を検証。

## 28. PostgreSQL validation

head `0007_question_import_vision`。既存run ID/state/input snapshotを保持。
TestQuestion全レコードの前後hash一致。Draft/IRファイルhashも一致。
原rawを保持したままresult JSONに派生viewのみ追加した。

## 29. Resume/idempotency regression

同一runをreparse2回して結果一致。mockではreparse後のcompleted run再開でもinference件数が増えない。
completed/failed/pendingの既存resume testを維持。raw/crop改ざんは再parseを拒否。
inference input hashを変えないため、parser-only改善で新しいmodel runを作らない。

## 30. Tests

最終結果: unittest **143 tests OK**、pytest **154 passed**、Ruff **All checks passed**。
Python 3.14 / FastAPI等のdeprecation・resource warningsがあるがfailureなし。
frontend変更なし、buildは実行していない。

## 31. Problems / limitations

数式字句filterは保守的で、複雑なLaTeXやprose混在では候補欠落が起き得る。原rawと警告で追跡する。
行列環境の重複は自動除去しない。単語・数字・式の同値判断はしない。
Ricohの自由文fallbackは明示配列に限定し、一般文からの図形意味抽出は行わない。
解答/hallucination検出は限定的なpatternであり、教師レビューを代替しない。

## 32. Teacher Review readiness

crop_ref、native_fragments、parsed_view.result、raw_ref、警告、source_field/offset、region/ordered anchorが利用可能。
旧normalizedも残るため「旧view / 新view / raw / crop」の比較が可能。
parsed=trueは正解の確定ではなく、機械的抽出の成功を意味する。

## 33. Remaining blockers

今回のparser/view契約についてTeacher Review UI着手を止めるBLOCKERは見つからなかった。
ただしRicohをstructured-onlyで扱うUIには不足するため、unstructured/partial表示と警告表示が必要。

## 34. Intentionally deferred

native/Vision automatic merge、数学的修正、semantic equivalence、Ornith、teacher edit/confirm、
TestQuestion import、grading、prompt/runtime調整、追加のモデル推論は実装・実行していない。

## 最終7問への回答

1. はい。数式6件で完全一致の重複を除去し、数字間space等は保持した。
2. はい。reasoning由来を明示し、review flagと元文字位置を保存した。
3. はい。valid/fenced/prose+JSONのsynthetic testsで確認した。
4. はい。原raw・観察文・警告を保持し、今回6ラベルを部分抽出した。
5. はい。既存7件をモデル・renderなしで再parseした。
6. はい。routing 0/3/4、crop/source hash、provenance、旧normalizedを維持した。
7. BLOCKERは見つからなかった。partial/unstructuredと警告を表示するUIを前提とする。

## Parser-only replay procedure

repository rootから、既存DB URLを環境変数`LLM_GRADER_DATABASE_URL`に設定して実行できる。
`question_import_root`にはsource PDF/extraction artifactが存在するrootを指定する。

```python
import os
from scoring.db import create_session_factory
from scoring.question_vision import VisionFallbackService

engine, sessions = create_session_factory(os.environ["LLM_GRADER_DATABASE_URL"])
with sessions() as session:
    service = VisionFallbackService(session, "artifacts/h2b-verification")
    results = service.reparse("e8d91c5e-5aec-49e5-b0b5-f736052e099e")
    for result in results:
        view = result["evidence"].get("parsed_view")
        if view:
            print(result["region_id"], view["result"]["parse_status"],
                  view["result"]["normalized_sha256"])
engine.dispose()
```

Q3のrun IDは`3d638755-fd4e-49a9-a316-bcdc175ae6b9`。推論adapterやモデル設定は不要。
