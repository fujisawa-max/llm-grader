import { test, expect } from "@playwright/test";

const testId = process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID;
const materialId = process.env.MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID;
const email = process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL;
const password = process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD;
test.skip(!testId || !materialId || !email || !password,
  "isolated model-answer classification API environment is not configured");

test("source-grounded semantic categories stay editable and persist with the imported answer", async ({ page }) => {
  if (!testId || !materialId || !email || !password) throw new Error("isolated classification API fixture is required");
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  const emailField = page.getByLabel("メールアドレス");
  await emailField.fill(email);
  await expect(emailField).toHaveValue(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  await page.goto(`/tests/${testId}?section=answers`);
  await page.getByRole("button", { name: "semantic-model-answer.pdfを解析して模範解答を確認", exact: true }).click();
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  const answer = page.getByLabel("模範解答本文 1");
  await expect(answer).toHaveValue(/The model memorizes the training examples/);

  await expect(page.getByText(/意味分類: 完了/)).toBeVisible();
  await expect(page.getByRole("button", { name: "意味分類を実行", exact: true })).toHaveCount(0);
  await expect(answer).toHaveValue(/The model memorizes the training examples and generalizes poorly\.\n?/);
  await expect(page.getByText("分類済み", { exact: true })).toBeVisible();
  await expect(page.getByText("別解・複数正答候補", { exact: true })).toBeVisible();
  await expect(page.getByLabel(/^採点基準候補/).first()).toHaveValue("identify overfitting.");
  await expect(page.getByLabel(/採点基準候補 .* の配点/).first()).toHaveValue("5");

  const questionDetails = page.locator("details").filter({ has: page.getByText(/除外された問題文/) });
  await questionDetails.locator("summary").click();
  await expect(questionDetails.getByText("Explain overfitting and state its effect.", { exact: false })).toBeVisible();

  await page.getByText("分類内容を確認・修正", { exact: true }).click();
  const category = page.getByLabel("模範解答 1 抽出箇所 2 の分類");
  await category.selectOption("model_answer");
  await page.getByRole("button", { name: "分類結果を本文へ反映" }).click();
  await expect(answer).toHaveValue(/Explain overfitting and state its effect\.[\s\S]*The model memorizes the training examples/);
  await expect(page.getByText("教師確認済み", { exact: true })).toBeVisible();

  const saveResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "下書き保存" }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();
  await expect(answer).toHaveValue(/Explain overfitting and state its effect\.[\s\S]*The model memorizes the training examples/);

  const confirmResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.url().endsWith("/confirm"));
  await page.getByRole("button", { name: "模範解答として登録" }).click();
  expect((await confirmResponse).status()).toBe(200);
  const answers = await page.request.get(`/api/v1/tests/${testId}/model-answers`);
  expect(answers.ok()).toBeTruthy();
  const stored = (await answers.json()).find((item: { is_current: boolean; provenance_json: Record<string, any> }) => item.is_current);
  expect(stored.provenance_json.semantic_classification.alternative_answers[0].text).toContain("Alternative:");
  expect(stored.provenance_json.semantic_classification.rubric_candidates[0].text).toContain("5 points");
});
