# J.UI.9e-fix1 Unified Question Review UI & Source Provenance after Split Report

## Phase result

**READY_FOR_PRODUCTION_VALIDATION**

実装と対象自動テストは完了。実NVIDIA環境でのsplit/unsplit受入確認は未実施。managed stubの成功を実モデルの成功として扱っていない。

## Root cause

コードと再現テストで確認した原因:

1. `questionMathSource()` と `question_math_source()` が `source_slice` の存在だけでOCRを拒否していた。splitが正しい非重複sliceを保存しても、slice内に完全に含まれる独立native segmentを利用できなかった。
2. sibling判定がsliceの所有範囲ではなく、元text itemの全`source_element_ids`を比較していた。disjointなsplit結果も同一出典のコピーとして拒否していた。
3. `merged_source_segments` 内のformula anchorには、top-level formulaに存在した`region_id`からnative IDを解決する処理がなかった。
4. ownershipが現在の「最寄りautomatic ancestor」だけに依存していた。reviewで親を変更すると、出典の所属も別の元ノードへ変わり得た。
5. split候補の行対応がglobal uniquenessに依存していた。完全な元blockを順序付きで対応できる場合も、繰り返す短い内容を曖昧としていた。
6. 新規childは保存前のserver revisionには存在しない。これは維持すべき認可・revision境界であり、現在は「構成の変更を保存すると…」と理由を表示する。

実機の認証情報・cookie・tokenは取得していない。上記は実装上の原因の確認であり、新しい実機ログによる検証ではない。

## Question review architecture / navigation

従来は`ReviewWorkspace`の長い設問button一覧と、`NodeEditor`の個別text/formula cardだった。現在はcanonical hierarchy順のsticky「対象設問」dropdownと、一つの「問題文」textarea/live previewを使う。

設問名・階層・配点・小問分割・警告対応・PDF照合・変更履歴・明示的保存／確認／登録は維持。selector変更は全nodeを保持するlocal snapshot内の選択変更で、未保存編集を破棄しない。選択したstable keyはreview別のsessionStorageに保持し、存在しなくなったkeyは安全にfallbackする。

ModelAnswer/Rubricと同じdropdown・breadcrumbの操作を使用し、既存`buildQuestionPath()`を再利用。QuestionのeditorをModelAnswer editorへ置換していない。

## Unified Question content

`questionContent()`は内部`ordered_content`を読み順に投影する。native formulaは元の文字列を保持し、教師編集／OCR適用後のMarkdown/LaTeXは同じ問題文に入る。画面に「問題文1」「数式1」の別editorを出さない。

`editQuestionContent()`は局所編集を元itemへ戻す。複数text itemにまたがる編集は既存の出典保持merge contractを使用し、変更していないformula anchorは保持する。数式を書き換えた際には`merged_into_text`とimmutable formula anchorを保持し、内部transcription/confirmationも更新する。

図・配点表現はinternal itemとして保持。図の確認cardも残す。図の位置をまたぐbulk rewriteは、出典位置を推測せず説明付きで拒否する。Markdown/LaTeXの一時的に不完全な入力は編集可能で、source formulaの対応が不完全な間はconfirmationを解除し、保存／review時の厳格な検証を維持する。

## Confirmation

個別のsource typeごとの確認UIを「問題文を確認」にまとめた。内部formula decisions、native evidence identity、confirmation status/methodは保持する。この明示操作で選択Questionのformula evidenceを照合済みにする。編集後は再確認が必要。

OCR proposalのApplyには追加checkboxを要求しない。既存のbackend検証・KaTeX gate・stale gateを通る提案だけApply可能。helperは「適用後も数式は編集できます。」。

## Split provenance / ambiguous evidence

既存の`source_slice=[start,end,total]`はimmutable automatic textのUnicode code-point範囲として維持する。完全blockの順序対応が証明できる場合は、その位置からsplitを導出し、繰り返し文字列をglobal equalityだけで判断しない。教師追加の番号は、変更していない本文を独立に対応できる場合にのみ出典へ結び付ける。

新しい`question_source_ownership.py`は検証済みanchorとsliceから、native reading orderに沿って元text内の各native elementの位置を解決する。sliceに全体が含まれるelementだけをそのnodeのOCR evidenceにする。Unicode mathematical Latinは元のまま保持し、同じ`24`の異なるnative IDも保持する。

境界をまたぐatomic element、位置を証明できないelementは`unresolved_source_ids`として保持し、使用しない。exclusive sourceを別Questionへコピーしない。unresolved/sibling elementのbboxはcrop exclusionに残るため、近隣Questionを借りるcropも拒否される。安全なnative atomが一つもなければ`math_question_source_boundary`または`math_question_source_missing`でfail closed。

textのfull anchor／sliceの重複・overlap禁止、source SHA・native ID・bboxの検証は維持。merge後も元anchor/sliceを保持して再検証する。

## Transformation-aware ownership

serverがteacher nodeの`source_review_owner`を検証済みoriginから導出してrevision JSONへ保存する。既存nodeでは以前のrevisionのoriginを保持し、clientによる別originへの変更は`source_identity_changed`で拒否する。

これによりhierarchyの親変更とPDF originを分離する。実際に使用できるnative IDsは、origin全体ではなく現在のreviewed anchor/sliceから導出する。既存revisionは従来のancestor fallbackで読み込み可能。DB migrationは不要。

## Math OCR / PDF context

Question単位の安定したendpointを追加:

`POST /api/v1/question-import-reviews/{review_id}/nodes/{node_key}/math-ocr`

`expected_revision`と全ordered-contentのimmutable referenceを検証する。旧`items/{item_index}/math-ocr`も維持。frontendからpath/page/bboxを自由指定できない。

同じ`SourceMathOCR`、geometry-first grouping、optional Ricoh WHERE、Uni-MuMER WHAT、deterministic candidates、source-guided normalization、guarded Ornith formatting fallbackを使用。OCR engine、prompt、runtime profile/lifecycleは変更していない。

native segmentsはpage/reading_order/IDで安定順序にする。anchorのserialized orderが変わってもgroupingは変わらない。

PDF highlightとsource page情報も現在のreviewed ownershipから導出する。保存後のchildは自分の範囲を表示し、metadataはrevision変更時に再取得し、履歴表示も指定revisionの所有範囲を使う。figureの元geometryは維持する。

## Persistence / registration / authorization

- proposal: 本文・revision・正式Questionを変更しない。
- Apply: browser-local編集だけを更新し、compact OCR provenanceをlocal snapshotへ追加する。
- Save: existing revision保存。structural splitはこの操作で初めてserverへ反映する。
- Review: existing explicit confirmation/warning対応。
- Register: existing import plan/hash確認後に正式Questionを作成する。

hierarchy、stable identity、recursive points、registration semanticsは維持。staff/domain authorization、source artifact integrity、allowed-root/path policyは変更していない。generic text-toolのstaff-only authorizationにも変更なし。

## Tests

| Check | Result |
| --- | --- |
| Question math/source・review・import・shared OCR/grouping/candidates/formatting backend | **197 PASS** |
| うちQuestion math/source tests | 32 tests |
| content projection・split・review validation frontend helper tests | **27 PASS** |
| non-loopback production-build default browser suite | **29 PASS** |
| 最終Question split/unsplit・Save/Register browser suite | **2 PASS** |
| shared ModelAnswer source OCR browser | **2 PASS** |
| hard Ornith formatting fallback browser | **1 PASS** |
| TypeScript | PASS |
| ESLint | 0 errors / 既存19 warnings |
| production Next build / next start | PASS |
| Ruff `src tests` | PASS |
| `git diff --check` | PASS |
| grading jobs（隔離browser harness） | **0** |

browser countsには同じscenarioの再検証が含まれ、合計をunique件数として扱わない。hard fallbackは専用環境で別実行。通常環境でそのspecがskipすることをPASSとして数えていない。

backendはslice内の7 Precision native atom、mathematical italic `𝑇𝑃`、二つの`24`、one-region grouping、sibling exclusion、atomic boundary failure、source順序安定性、split/save/reload、reparent後origin、origin偽装拒否、node endpoint認証を検証した。

ブラウザは実FastAPI、隔離SQLite、production frontend、非loopback HTTP、Chromium、実RuntimeManager＋managed model stubsで実行。split後のformula childはOCR成功、prose siblingはno-math、crop/KaTeX表示、Apply/Cancel、手動編集、保存前server不変、保存後reload、selector内の未保存編集、選択復元を確認した。splitされた親子4 Questionsの明示登録・配点10/0・child provenanceも検証した。

ModelAnswerのformal/saved/editing分離、Rubric split/merge/add/duplicate/登録、generic text tools、cold/warm runtime reuseはdefault suiteで回帰確認。Question testではModelAnswer/Rubric API結果の不変もassertした。認証後のworkspaceでunexpected console/page errorsは0。

## Files modified

Backend:
- `src/scoring/question_source_ownership.py`（追加）
- `src/scoring/question_math_source.py`
- `src/scoring/question_reviews.py`
- `src/scoring/review_document.py`
- `src/scoring/api/question_reviews.py`

Frontend:
- `frontend/lib/questionContent.ts`（追加）
- `frontend/components/reviews/NodeEditor.tsx`
- `frontend/components/reviews/ReviewWorkspace.tsx`
- `frontend/components/reviews/PdfPreview.tsx`
- `frontend/lib/questionMathSource.ts`
- `frontend/lib/questionSplit.ts`
- `frontend/lib/reviewValidation.ts`
- `frontend/lib/api/textTools.ts`
- `frontend/lib/api/reviews.ts`
- `frontend/types/reviews.ts`
- `frontend/app/globals.css`

Tests / report:
- `tests/test_question_math_ocr.py`
- `tests/run_runtime_browser_e2e.py`
- `frontend/e2e/question-content.spec.ts`（追加）
- `frontend/e2e/question-math-ocr-real.spec.ts`
- `frontend/e2e/question-split.spec.ts`
- `frontend/e2e/review-validation.spec.ts`
- 本report（追加）

## Git / safety

開始時working treeはclean。終了時は上記service source/tests/reportの変更のみ。stage/commit/pushは行っていない。production DB、Q5、正式grade、既存artifact、OpenWebUIを操作していない。モデルdownload、unmanaged server起動、GPU hardcoding、diagram extractionも行っていない。

## Production acceptance / remaining work

実モデルのproduction受入のみ未実施。以下を教師側で確認する:

1. source-backedの未分割QuestionでOCR、crop、LaTeX/KaTeX、Cancelを確認。
2. 小問に分割し、構成を明示的に保存。
3. dropdownでformula childを選択し、OCR action、正しいcrop、usable proposal、KaTeX、Applyを確認。
4. Apply後の手動編集と、Save前のserver/formal不変を確認。
5. siblingへ切り替え、数式の借用がないことと未保存編集保持を確認。
6. Save/reloadで内容・出典・選択を確認。
7. 同じprofileのPID/started_at再利用を確認。
8. 正式登録は教師が選ぶ場合だけexisting final actionで行う。

安全に分割できないatomic sourceは意図的にunresolved/fail-closedとする。図は出典保存・既存確認のみで、抽出はJ.UI.10の対象。

**Phase J.UI.9e-fix1: READY_FOR_PRODUCTION_VALIDATION**
