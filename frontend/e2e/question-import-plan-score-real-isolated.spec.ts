import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_SCORE_GUIDANCE_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated score guidance API is not configured");

test("score blocker explains parent and child values and returns to an editable revision", async ({ page, baseURL }) => {
  if (!reviewId || !email || !password || !baseURL) throw new Error("Isolated review environment required");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const path = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${path}`)).json());
  const initial = await read();
  expect(initial.snapshot.nodes.map((node: { label: { raw: string } }) => node.label.raw)).toEqual(["問題2", "(1)", "(2)"]);
  expect(initial.snapshot.nodes.map((node: { score_points: number | null }) => node.score_points)).toEqual([40, 30, null]);

  await page.goto(`/question-import-reviews/${reviewId}`);
  const markReviewed = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await markReviewed).status()).toBe(200);
  await page.getByRole("button", { name: "問題登録前の最終確認へ", exact: true }).click();
  const panel = page.getByRole("region", { name: "問題登録前の最終確認" });
  await expect(panel.getByRole("heading", { name: "問題登録前の最終確認" })).toBeVisible();
  await expect(panel).toContainText("問題登録前に修正が必要な項目が 1 件あります");
  await expect(panel).toContainText("問題2");
  await expect(panel).toContainText("入力済み小問の配点合計: 30点 / 親設問: 40点");
  await expect(panel).toContainText("10点不足");
  await expect(panel).toContainText("問題2 > (2)の配点が未設定です");
  await expect(panel.getByRole("heading", { name: "配点未設定: 問題2 > (2)" })).toHaveCount(0);

  const unconfirmDialog = page.waitForEvent("dialog").then(async dialog => {
    const message = dialog.message();
    await dialog.accept();
    return message;
  });
  await panel.getByRole("button", { name: "確認を解除して編集" }).first().click();
  expect(await unconfirmDialog).toContain("新しい修正版で編集を再開");
  await expect(page.getByLabel("配点の扱い")).toBeEnabled();
  await expect(page.locator(".review-tree").getByRole("button", { name: /問題2/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByLabel("配点の扱い").selectOption("unset");
  await page.locator(".review-tree").getByRole("button").filter({ hasText: "(1)" }).click();
  await page.locator(".review-fields input[type='number']").fill("20");
  await page.locator(".review-tree").getByRole("button").filter({ hasText: "(2)" }).click();
  await page.getByLabel("配点の扱い").selectOption("direct");
  await page.locator(".review-fields input[type='number']").fill("20");

  const save = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await save).status()).toBe(200);
  const saved = await read();
  expect(saved.snapshot.nodes.map((node: { score_points: number | null }) => node.score_points)).toEqual([null, 20, 20]);

  const reReview = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await reReview).status()).toBe(200);
  await page.getByRole("button", { name: "問題登録前の最終確認へ", exact: true }).click();
  await expect(page.getByText("問題を登録できます。登録すると、この試験の問題として確定されます。")).toBeVisible();
  await expect(page.getByText("問題登録前に修正が必要な項目が 1 件あります")).toHaveCount(0);
  const finalPlan = await (await page.request.post(`${baseURL}${path}/import-plan`)).json();
  expect(finalPlan.blockers).toEqual([]);
  expect(finalPlan.total_points).toBe(40);
});
