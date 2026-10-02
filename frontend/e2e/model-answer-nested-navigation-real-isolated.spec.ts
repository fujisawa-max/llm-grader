import { expect, test } from "@playwright/test";

const testId = process.env.NESTED_REVIEW_TEST_ID;
const nestedId = process.env.NESTED_REVIEW_QUESTION_ID;
test.skip(!testId || !nestedId, "requires isolated real API and production frontend");

test("nested review target selection keeps assignment separate and survives save and reload", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto(`/tests/${testId}?section=answers`);
  const created = page.waitForResponse((response) => response.url().endsWith("/model-answer-imports") && response.request().method() === "POST");
  await page.getByRole("button", { name: "review-ux-nested.pdfを解析して模範解答を確認" }).click();
  const draft = await (await created).json();
  await expect(page).toHaveURL(/model-answer-import-reviews/);
  const selector = page.getByLabel("編集対象");
  await expect(selector.locator(`option[value="question:${nestedId}"]`)).toHaveText("問題2 > (2) > 2.");
  await selector.selectOption(`question:${nestedId}`);
  await expect(page.getByText("この設問の取り込み候補はありません。" )).toBeVisible();
  const afterNavigation = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json();
  expect(afterNavigation.entries.map((entry: { question_id: string | null }) => entry.question_id))
    .toEqual(draft.entries.map((entry: { question_id: string | null }) => entry.question_id));
  await page.getByRole("button", { name: "問題2 > (2) > 2. に模範解答を追加" }).click();
  const manual = page.locator(".model-answer-import-entry").filter({ hasText: "教師が追加した候補" });
  await manual.getByLabel(/模範解答本文/).fill("Nested teacher answer.");
  await page.getByRole("button", { name: "変更を保存" }).click();
  await expect(page.getByText("変更を保存しました。")).toBeVisible();
  await page.reload();
  await selector.selectOption(`question:${nestedId}`);
  await expect(page.getByLabel(/模範解答本文/)).toHaveValue("Nested teacher answer.");
  expect(errors).toEqual([]);
});
