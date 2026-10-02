import { test, expect } from "@playwright/test";

const testId = process.env.GEOMETRY_TEST_ID;
const questionIds: string[] = JSON.parse(process.env.GEOMETRY_QUESTION_IDS || "[]");
test.skip(!testId, "requires isolated geometry fixture, real API and managed classifier stub");

test("PDF analysis automatically classifies spatial Q1/Q2/Q3 regions and persists source evidence", async ({ page }) => {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto(`/tests/${testId}?section=answers`);
  const response = page.waitForResponse((res) => res.url().endsWith("/model-answer-imports") && res.request().method() === "POST");
  await page.getByRole("button", { name: "geometry-model_answer_source.pdfを解析して模範解答を確認", exact: true }).click();
  const created = await response;
  expect(created.status()).toBe(201);
  const draft = await created.json();
  expect(draft.pipeline.semantic_classification_used).toBe(true);
  expect(draft.entries.map((entry: { question_id: string }) => entry.question_id)).toEqual(questionIds);
  await expect(page).toHaveURL(/\/model-answer-import-reviews\//);
  await expect(page.getByText(/意味分類: 完了/)).toBeVisible();
  await expect(page.getByRole("button", { name: "意味分類を実行", exact: true })).toHaveCount(0);
  for (let i = 1; i <= 3; i++) {
    await page.getByLabel("編集対象").selectOption(`question:${questionIds[i - 1]}`);
    await expect(page.getByLabel(`模範解答本文 ${i}`)).toHaveValue(new RegExp(`^Source answer ${i}\\.\\s*$`));
    await expect(page.getByLabel(`模範解答 ${i} の対応先`)).toHaveValue(questionIds[i - 1]);
  }
  await page.getByLabel("編集対象").selectOption(`question:${questionIds[0]}`);
  await page.getByText(/位置判定:/).first().click();
  await expect(page.getByText(/位置根拠:/).first()).toBeVisible();
  await page.getByLabel("模範解答本文 1").fill("Teacher corrected answer 1.");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect(page.getByText(/変更を保存しました/)).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("模範解答本文 1")).toHaveValue("Teacher corrected answer 1.");
  const confirm = page.waitForResponse((res) => res.url().endsWith("/confirm"));
  await page.getByRole("button", { name: "確認した模範解答を登録" }).click();
  expect((await confirm).status()).toBe(200);
  const stored = await (await page.request.get(`/api/v1/tests/${testId}/model-answers`)).json();
  expect(stored).toHaveLength(3);
  for (const answer of stored) {
    expect(answer.provenance_json.pipeline.geometry_first).toBe(true);
    expect(answer.provenance_json.geometry.question_id).toBe(answer.question_id);
    expect(answer.provenance_json.segments[0].bbox).toHaveLength(4);
    expect(answer.provenance_json.segments[0].text_sha256).toHaveLength(64);
    expect(answer.provenance_json.semantic_classification.segments[0].id).toMatch(/^pdf-/);
  }
});
