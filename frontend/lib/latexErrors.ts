import { ApiRequestError } from "./api/client";
export function latexErrorMessage(error: unknown): string {
  const retained = "元の本文は保持されています。再試行してください。";
  if (error instanceof ApiRequestError) {
    const messages: Record<string, string> = {
      math_ocr_numeric_mismatch: "数式OCRの数値が抽出原文と一致しません。PDFを確認してください。",
      math_runtime_start_failed: "数式OCRを起動できませんでした。",
      math_runtime_start_timeout: "数式OCRの起動に時間がかかりすぎています。",
      math_inference_timeout: "数式の認識に時間がかかりすぎています。",
      math_inference_failed: "数式OCRから認識結果を取得できませんでした。",
      math_runtime_unavailable: "数式OCRを起動・実行できませんでした。",
      math_ocr_invalid_response: "数式OCRから有効な数式を取得できませんでした。",
      math_source_invalid: "PDFの数式位置を確認できませんでした。",
      math_question_source_missing: "この問題文に対応する元PDFの位置情報がありません。",
      math_question_source_stale: "問題文の構成が変更されています。保存してから数式変換をやり直してください。",
      math_question_source_boundary: "元資料の範囲が別の設問と重なるため、数式OCRを実行できません。",
      math_source_boundary: "数式の切り出し範囲に別の設問が含まれるため、数式OCRを実行できません。",
      math_question_target_not_found: "対象の設問が見つかりません。最新のレビューを読み込んでください。",
      revision_conflict: "新しい修正版が保存されています。未保存内容を控えてから再読み込みしてください。",
      math_crop_too_large: "数式領域が広すぎます。局所的な候補を選んでください。",
      RESOURCE_NOT_FOUND: "対象リソースが見つかりません。",
      COURSE_ACCESS_DENIED: "対象リソースへのアクセス権がありません。",
      latex_runtime_unavailable: "LLMのprofileまたは接続設定を利用できません。",
      latex_runtime_start_failed: "LLMを起動できませんでした。",
      latex_runtime_start_timeout: "LLMの起動に時間がかかりすぎています。",
      latex_inference_timeout: "LaTeX変換に時間がかかりすぎています。",
      latex_inference_failed: "LLMから変換結果を取得できませんでした。",
      latex_invalid_response: "LLMから有効な変換結果を取得できませんでした。",
    };
    if (error.code && messages[error.code]) return messages[error.code] + retained;
    if (error.code?.startsWith("math_")) return mathOcrReasonMessage(error.code) + retained;
    if (error.status === 401 || error.status === 403) return "LaTeX変換には教師としてのログインが必要です。" + retained;
    if (error.status === 404) return (error.routeNotFound
      ? "LaTeX変換APIが見つかりません。APIの更新状態を確認してください。"
      : "LaTeX変換の対象が見つかりません。応答のエラー内容を確認してください。") + retained;
    if (error.status === 422) return "LaTeX変換の入力が不正です。本文は12,000文字以内で指定してください。" + retained;
    if (error.status === 504) return "LaTeX変換に時間がかかりすぎています。" + retained;
    return "LaTeX変換APIでエラーが発生しました。" + retained;
  }
  return "LaTeX変換APIに接続できませんでした。" + retained;
}

export function mathOcrReasonMessage(code: string): string {
  const messages: Record<string, string> = {
    math_region_limit: "数式候補が多すぎます。小さな候補を選んでください。",
    math_crop_too_large: "数式cropが広すぎます。局所的な候補を選んでください。",
    math_source_invalid: "原文の座標を確認できません。",
    math_no_region: "原文と対応する数式領域が見つかりません。",
    math_geometry_ambiguous: "数式領域の所属が曖昧です。",
    math_ricoh_unavailable: "数式領域を確認する画像モデルを利用できません。",
    math_ricoh_grouping_rejected: "画像モデルの所属判定を検証できませんでした。",
    math_ricoh_output_truncated: "数式領域の画像確認が途中で切れました。位置情報と診断を確認してください。",
    math_crop_invalid: "数式cropの座標を確認できません。",
    math_runtime_unavailable: "数式OCR runtimeを利用できません。",
    math_runtime_start_failed: "数式OCRを起動できません。",
    math_runtime_start_timeout: "数式OCRの起動がtimeoutしました。",
    math_inference_timeout: "数式OCRの推論がtimeoutしました。",
    math_inference_failed: "数式OCRの推論が失敗しました。",
    math_ocr_empty_response: "数式OCRの応答本文が空でした。",
    math_response_unsupported: "数式OCRの応答形式を読み取れません。",
    math_formula_not_found: "応答に有効な数式が見つかりません。",
    math_identifier_invalid: "原文にない変数・説明が応答に含まれています。",
    math_identifier_missing: "原文の変数・識別子がOCR候補から欠けています。",
    math_ocr_numeric_mismatch: "原文の数値がOCR結果と一致しません。",
    math_wrapper_invalid: "数式の区切り・出力形式を確認できません。",
    math_detokenization_unresolved: "原文と照合できない文字・数値の分割があります。",
    math_latex_syntax_invalid: "数式のLaTeX構文を確認できません。",
    math_formatting_fallback_unavailable: "数式の書式補助を利用できません。元の本文は保持されています。",
    math_formatting_fallback_timeout: "数式の書式補助がtimeoutしました。再試行してください。",
    math_formatting_fallback_invalid_output: "数式の書式補助から有効な結果を取得できませんでした。",
    math_formatting_semantic_change: "書式補助が数値・変数・演算子・数式構造を変更したため適用できません。",
    math_formatting_validation_failed: "書式補助の結果が原文・構文の検証を通りませんでした。",
  };
  return messages[code] || "数式OCRの結果を確認してください。";
}
