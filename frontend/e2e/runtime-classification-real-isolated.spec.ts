import { test, expect } from "@playwright/test";

const testId = process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID;
const email = process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL;
const password = process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD;
test.skip(process.env.RUNTIME_MANAGER_E2E !== "1" || !testId || !email || !password,
  "requires isolated real API + RuntimeManager + managed stub process");

test("normal API bootstrap uses RuntimeManager for semantic classification", async ({ page }) => {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  const statuses = await page.request.get("/api/v1/system/runtimes");
  expect(statuses.ok()).toBeTruthy();
  const classifierProfile = (await statuses.json()).find(
    (row: { runtime_id: string }) => row.runtime_id === "ornith_rubric_draft");
  expect(classifierProfile.runtime_type).toBe("managed");
  expect(classifierProfile.availability).toBe("available");

  await page.goto(`/tests/${testId}?section=answers`);
  await page.getByRole("button", { name: "semantic-model-answer.pdfを解析して模範解答を確認", exact: true }).click();
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  const response = page.waitForResponse((res) => res.url().endsWith("/classify") && res.request().method() === "POST");
  await page.getByRole("button", { name: "意味分類を実行" }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  const classification = (await result.json()).entries[0].semantic_classification;
  expect(classification.status).toBe("classified");
  expect(classification.method).toBe("llm_source_segment_classification");
  expect(classification.reason).not.toBe("classifier_unavailable");
  await expect(page.getByText("分類済み", { exact: true })).toBeVisible();
  await expect(page.getByLabel("模範解答本文 1")).toHaveValue(/The model memorizes/);
  await expect(page.getByLabel("模範解答本文 1")).not.toHaveValue(/Explain/);
  await page.getByRole("button", { name: "変更を保存" }).click();
  await expect(page.getByText(/変更を保存しました/)).toBeVisible();
  await page.reload();
  await expect(page.getByText("教師確認済み", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "確認した模範解答を登録" }).click();
  await expect(page.getByText("登録済み", { exact: true })).toBeVisible();
});
