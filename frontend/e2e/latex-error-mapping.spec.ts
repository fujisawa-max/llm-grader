import { test, expect } from "@playwright/test";
import { ApiRequestError } from "../lib/api/client";
import { latexErrorMessage } from "../lib/latexErrors";
for (const [status, code, expected] of [
  [404, "http_error", "APIが見つかりません"],
  [404, "RESOURCE_NOT_FOUND", "対象リソースが見つかりません"],
  [401, "auth_required", "ログインが必要"],
  [403, "TEACHER_ROLE_REQUIRED", "教師としてのログインが必要"],
  [500, "internal_error", "APIでエラー"],
  [422, "validation_error", "入力が不正"],
  [503, "latex_runtime_unavailable", "profileまたは接続設定"],
  [503, "latex_runtime_start_failed", "LLMを起動できません"],
  [504, "latex_runtime_start_timeout", "LLMの起動に時間"],
  [504, "latex_inference_timeout", "LaTeX変換に時間"],
  [503, "latex_invalid_response", "有効な変換結果"],
] as const) {
  test(`normalization error ${code} (${status}) stays actionable`, () => {
    const message = latexErrorMessage(new ApiRequestError(status, {error: {code, message: code === "http_error" ? "Not Found" : "synthetic"}}));
    expect(message).toContain(expected); expect(message).toContain("元の本文は保持");
  });
}
test("network failure is distinct", () => {
  expect(latexErrorMessage(new TypeError("fetch failed"))).toContain("APIに接続できません");
});

test("unstructured FastAPI missing route is distinct from an unexplained 404", () => {
  const route = new ApiRequestError(404, {detail: "Not Found"} as never);
  expect(latexErrorMessage(route)).toContain("APIが見つかりません");
  expect(latexErrorMessage(new ApiRequestError(404, {}))).not.toContain("APIが見つかりません");
});
