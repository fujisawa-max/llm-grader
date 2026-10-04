import { test, expect } from "@playwright/test";
import { ApiRequestError } from "../lib/api/client";
import { latexErrorMessage } from "../lib/latexErrors";
for (const [status, code, expected] of [
  [404, "http_error", "APIが見つかりません"],
  [401, "auth_required", "ログインが必要"],
  [500, "internal_error", "APIでエラー"],
  [422, "validation_error", "入力が不正"],
  [503, "latex_runtime_unavailable", "profileまたは接続設定"],
  [503, "latex_runtime_start_failed", "LLMを起動できません"],
  [504, "latex_runtime_start_timeout", "LLMの起動に時間"],
  [504, "latex_inference_timeout", "LaTeX変換に時間"],
  [503, "latex_invalid_response", "有効な変換結果"],
] as const) {
  test(`normalization error ${code} (${status}) stays actionable`, () => {
    const message = latexErrorMessage(new ApiRequestError(status, {error: {code, message: "synthetic"}}));
    expect(message).toContain(expected); expect(message).toContain("元の本文は保持");
  });
}
test("network failure is distinct", () => {
  expect(latexErrorMessage(new TypeError("fetch failed"))).toContain("APIに接続できません");
});
