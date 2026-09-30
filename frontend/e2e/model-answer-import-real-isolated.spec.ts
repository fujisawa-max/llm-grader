import { test, expect } from "@playwright/test";

const testId = process.env.MODEL_ANSWER_IMPORT_TEST_ID;
const materialId = process.env.MODEL_ANSWER_IMPORT_MATERIAL_ID;
const manualMaterialId = process.env.MODEL_ANSWER_IMPORT_MANUAL_MATERIAL_ID;
const removalMaterialId = process.env.MODEL_ANSWER_IMPORT_REMOVAL_MATERIAL_ID;
const email = process.env.MODEL_ANSWER_IMPORT_EMAIL;
const password = process.env.MODEL_ANSWER_IMPORT_PASSWORD;
const apiBase = process.env.MODEL_ANSWER_IMPORT_API_URL;
test.skip(!testId || !materialId || !manualMaterialId || !email || !password,
  "isolated model-answer import API environment is not configured");

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test("registered native PDF is mapped, edited, saved, and versioned through the teacher workflow", async ({ page, baseURL }) => {
  if (!testId || !materialId || !baseURL) throw new Error("Isolated model answer API is required");
  const apiUrl = apiBase || baseURL;
  await login(page);
  await page.goto(`/tests/${testId}?section=answers`);
  const analyze = page.getByRole("button", { name: "model-answer.pdfを解析して模範解答を確認", exact: true });
  await expect(analyze).toBeVisible();
  const createResponse = page.waitForResponse((response) =>
    response.url().includes(`/tests/${testId}/model-answer-imports`) && response.request().method() === "POST");
  await analyze.click();
  expect((await createResponse).status()).toBe(201);
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  const textboxes = page.getByLabel(/^模範解答本文 [0-9]+$/);
  const mappings = page.getByLabel(/^模範解答 [0-9]+ の対応先$/);
  await expect(textboxes).toHaveCount(3);
  await expect(mappings).toHaveCount(3);
  await expect(mappings.nth(0).locator("option:checked")).toHaveText("問題1");
  await expect(mappings.nth(1).locator("option:checked")).toHaveText("問題2 > (1)");
  await expect(mappings.nth(2).locator("option:checked")).toHaveText("問題2 > (2)");
  const questionOneId = await mappings.nth(0).inputValue();
  await expect(page.locator(".model-answer-import-entry .katex").first()).toBeVisible();
  await textboxes.nth(0).fill("正答は $x^2 = 1$ です。\n追記しました。");
  const saveResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "変更を保存" }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();
  await expect(textboxes.nth(0)).toHaveValue("正答は $x^2 = 1$ です。\n追記しました。");

  const confirmResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.url().endsWith("/confirm"));
  await page.getByRole("button", { name: "確認した模範解答を登録" }).click();
  expect((await confirmResponse).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers`));
  await expect(page.getByLabel("模範解答本文")).toHaveValue("正答は $x^2 = 1$ です。\n追記しました。");
  const answersResponse = await page.request.get(`${apiUrl}/api/v1/tests/${testId}/model-answers`);
  expect(answersResponse.ok()).toBeTruthy();
  const answers = await answersResponse.json();
  const saved = answers.find((answer: { question_id: string; is_current: boolean }) => answer.question_id === questionOneId && answer.is_current);
  expect(saved.answer_text).toContain("追記しました。");
  expect(saved.material_id).toBe(materialId);
  expect(saved.provenance_json.source_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(saved.provenance_json.segments[0].page_index).toBe(0);
  expect(saved.version).toBe(1);
});

test("ambiguous native answer mapping requires and persists a teacher choice", async ({ page, baseURL }) => {
  if (!testId || !manualMaterialId || !baseURL) throw new Error("Isolated manual mapping API is required");
  const apiUrl = apiBase || baseURL;
  await login(page);
  await page.goto(`/tests/${testId}?section=answers`);
  await page.getByRole("button", { name: "ambiguous-model-answer.pdfを解析して模範解答を確認", exact: true }).click();
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  await expect(page.getByText("対応先を確認")).toBeVisible();
  const mapping = page.getByLabel("模範解答 1 の対応先");
  await expect(mapping).toHaveValue("");
  const confirm = page.getByRole("button", { name: "確認した模範解答を登録" });
  await expect(confirm).toBeDisabled();
  await mapping.selectOption({ label: "問題1" });
  const questionOneId = await mapping.inputValue();
  await expect(page.getByText("教師が対応")).toBeVisible();
  const saveResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.request().method() === "PUT");
  await confirm.click();
  expect((await saveResponse).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers`));
  const response = await page.request.get(`${apiUrl}/api/v1/tests/${testId}/model-answers`);
  const answers = await response.json();
  const q1Versions = answers.filter((answer: { question_id: string }) => answer.question_id === questionOneId);
  expect(q1Versions.some((answer: { version: number; is_current: boolean }) => answer.version === 2 && answer.is_current)).toBe(true);
});

test("repeated question prompt is removed from the native answer draft and provenance records it", async ({ page, baseURL }) => {
  test.skip(!removalMaterialId, "isolated question-text-removal PDF is not configured");
  if (!testId || !baseURL) throw new Error("Isolated model answer API is required");
  const apiUrl = apiBase || baseURL;
  await login(page);
  await page.goto(`/tests/${testId}?section=answers`);
  const analyze = page.getByRole("button", { name: "question-copy.pdfを解析して模範解答を確認", exact: true });
  const createResponse = page.waitForResponse((response) =>
    response.url().includes(`/tests/${testId}/model-answer-imports`) && response.request().method() === "POST");
  await analyze.click();
  expect((await createResponse).status()).toBe(201);
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  const answer = page.getByLabel("模範解答本文 1");
  const extractedAnswer = /The model fits training data too closely, reducing its\s+performance on unseen data\./;
  await expect(answer).toHaveValue(extractedAnswer);
  await expect(page.getByText("重複していた問題文を除去しました。")).toBeVisible();

  const saveResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "変更を保存" }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();
  await expect(answer).toHaveValue(extractedAnswer);

  const confirmResponse = page.waitForResponse((response) =>
    response.url().includes("/model-answer-import-drafts/") && response.url().endsWith("/confirm"));
  await page.getByRole("button", { name: "確認した模範解答を登録" }).click();
  expect((await confirmResponse).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers`));
  const answersResponse = await page.request.get(`${apiUrl}/api/v1/tests/${testId}/model-answers`);
  const answers = await answersResponse.json();
  const saved = answers.find((item: { answer_text: string; is_current: boolean }) =>
    item.is_current && item.answer_text.includes("training data too closely"));
  expect(saved).toBeTruthy();
  expect(saved.provenance_json.question_text_removal.method).toBe("exact");
  expect(saved.provenance_json.question_text_removal.status).toBe("removed");
  expect(saved.provenance_json.segments.length).toBeGreaterThan(0);
});
