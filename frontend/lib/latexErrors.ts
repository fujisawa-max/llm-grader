import { ApiRequestError } from "./api/client";
export function latexErrorMessage(error: unknown): string {
  const retained = "元の本文は保持されています。再試行してください。";
  if (error instanceof ApiRequestError) {
    const messages: Record<string, string> = {
      latex_runtime_unavailable: "LLMのprofileまたは接続設定を利用できません。",
      latex_runtime_start_failed: "LLMを起動できませんでした。",
      latex_runtime_start_timeout: "LLMの起動に時間がかかりすぎています。",
      latex_inference_timeout: "LaTeX変換に時間がかかりすぎています。",
      latex_inference_failed: "LLMから変換結果を取得できませんでした。",
      latex_invalid_response: "LLMから有効な変換結果を取得できませんでした。",
    };
    if (error.code && messages[error.code]) return messages[error.code] + retained;
    if (error.status === 401 || error.status === 403) return "LaTeX変換には教師としてのログインが必要です。" + retained;
    if (error.status === 404) return "LaTeX変換APIが見つかりません。APIの更新状態を確認してください。" + retained;
    if (error.status === 422) return "LaTeX変換の入力が不正です。本文は12,000文字以内で指定してください。" + retained;
    if (error.status === 504) return "LaTeX変換に時間がかかりすぎています。" + retained;
    return "LaTeX変換APIでエラーが発生しました。" + retained;
  }
  return "LaTeX変換APIに接続できませんでした。" + retained;
}
