import { test, expect } from "@playwright/test";

const testId = process.env.MODEL_ANSWER_VISUAL_TEST_ID;
const materialId = process.env.MODEL_ANSWER_VISUAL_MATERIAL_ID;
const answerText = process.env.MODEL_ANSWER_VISUAL_TEXT;
const email = process.env.MODEL_ANSWER_VISUAL_EMAIL;
const password = process.env.MODEL_ANSWER_VISUAL_PASSWORD;
const apiBase = process.env.MODEL_ANSWER_VISUAL_API_URL;
test.skip(!testId || !materialId || !answerText || !email || !password,
  "isolated visual-difference model-answer API is not configured");

test("visual difference extracts added native answer text and persists provenance", async ({ page, baseURL }) => {
  if (!testId || !materialId || !answerText || !email || !password || !baseURL) {
    throw new Error("Isolated visual-difference API is required");
  }
  const apiUrl = apiBase || baseURL;
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  await page.goto(`/tests/${testId}?section=answers`);
  const analyze = page.getByRole("button", {
    name: "visual-model-answer.pdfを解析して模範解答を確認", exact: true,
  });
  const createResponse = page.waitForResponse((response) =>
    response.url().includes(`/tests/${testId}/model-answer-imports`) && response.request().method() === "POST");
  await analyze.click();
  expect((await createResponse).status()).toBe(201);
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);

  const answer = page.getByLabel("模範解答本文 1");
  await expect(answer).toHaveValue(answerText);
  await expect(page.getByText("本文抽出: 問題PDFとの差分から追加領域を特定")).toBeVisible();
  await expect(page.getByText("抽出方法: 問題PDFとの差分")).toBeVisible();
  const saveResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "変更を保存" }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();
  await expect(answer).toHaveValue(answerText);

  const confirmResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.url().endsWith("/confirm"));
  await page.getByRole("button", { name: "確認した模範解答を登録" }).click();
  expect((await confirmResponse).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers`));

  const answersResponse = await page.request.get(`${apiUrl}/api/v1/tests/${testId}/model-answers`);
  expect(answersResponse.ok()).toBeTruthy();
  const answers = await answersResponse.json();
  const saved = answers.find((item: { is_current: boolean; material_id: string }) =>
    item.is_current && item.material_id === materialId);
  expect(saved).toBeTruthy();
  expect(saved.answer_text).toBe(answerText);
  expect(saved.provenance_json.extraction_method).toBe("visual_difference_guided_native_text");
  expect(saved.provenance_json.extraction.method).toBe("visual_difference_guided_native_text");
  expect(saved.provenance_json.extraction.regions.length).toBeGreaterThan(0);
  expect(saved.provenance_json.segments.length).toBeGreaterThan(0);
});
