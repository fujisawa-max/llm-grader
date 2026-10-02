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
  await expect(selector.locator("option")).toHaveCount(draft.questions.length +
    draft.entries.filter((entry: { question_id: string | null }) => !entry.question_id).length);
  const questionOptions = await selector.locator("option").allTextContents();
  expect(questionOptions.slice(0, 5)).toEqual(["問題1", "問題2 > (2) > 1.",
    "問題2 > (2) > 2.", "問題2 > (2) > 3.", "問題3 > (1)"]);
  await expect(selector.locator(`option[value="question:${nestedId}"]`)).toHaveText("問題2 > (2) > 2.");
  await selector.selectOption(`question:${nestedId}`);
  await expect(page.getByRole("region", { name: "登録済み問題文" })).toContainText("Recall（再現率）");
  await expect(page.getByRole("region", { name: "登録済み問題文" }).locator(".katex")).toBeVisible();
  await expect(page.getByText("この設問の取り込み候補はありません。" )).toBeVisible();
  const afterNavigation = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json();
  expect(afterNavigation.entries.map((entry: { question_id: string | null }) => entry.question_id))
    .toEqual(draft.entries.map((entry: { question_id: string | null }) => entry.question_id));
  await page.getByRole("button", { name: "問題2 > (2) > 2. に模範解答を追加" }).click();
  const manual = page.locator(".model-answer-import-entry").filter({ hasText: "教師が追加した候補" });
  await manual.getByLabel(/模範解答本文/).fill("Nested teacher answer.");
  await page.getByRole("button", { name: "下書き保存" }).click();
  await expect(page.getByText("下書きを保存しました。")).toBeVisible();
  await page.reload();
  await selector.selectOption(`question:${nestedId}`);
  await expect(page.getByLabel(/模範解答本文/)).toHaveValue("Nested teacher answer.");
  await page.goto(`/tests/${testId}?section=answers&question=${nestedId}`);
  const normalSelector = page.getByLabel("対象設問");
  await expect(normalSelector).toHaveValue(nestedId!);
  await expect(normalSelector.locator(`option[value="${nestedId}"]`)).toHaveText("問題2 > (2) > 2.");
  await expect(page.getByText("準備が必要")).toHaveCount(0);
  await expect(page.locator(".model-answer-normal-layout > .question-selector")).toHaveCount(0);
  await expect(page.getByText("模範解答: 未登録")).toBeVisible();
  await page.getByLabel("模範解答本文", { exact: true }).fill("Normal editor answer.");
  await page.getByRole("button", { name: "模範解答の新しい版を保存" }).click();
  await expect(page.getByText("模範解答: 登録済み")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("模範解答本文", { exact: true })).toHaveValue("Normal editor answer.");
  await normalSelector.selectOption({ label: "問題2 > (2) > 1." });
  await expect(page.getByText("模範解答: 未登録")).toBeVisible();
  await normalSelector.selectOption(process.env.NESTED_REVIEW_PAGE_TWO_QUESTION_ID!);
  await expect(page.getByText("模範解答: 登録済み")).toBeVisible();
  await expect(page.getByRole("region", { name: "模範解答・採点基準PDF" }).getByText("2 / 2")).toBeVisible();
  await page.goto(`/tests/${testId}?section=answers&question=deleted-question`);
  await expect(page.getByLabel("対象設問")).toHaveValue(draft.questions[0].id);
  expect(errors).toEqual([]);
});
