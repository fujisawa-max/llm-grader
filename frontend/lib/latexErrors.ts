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
