import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_SCORE_SUM_ID;
const email = process.env.REVIEW_SCORE_SUM_EMAIL;
const password = process.env.REVIEW_SCORE_SUM_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated child-score-sum API is not configured");

test("recursively derives parent totals, surfaces unset descendants, and persists the repair", async ({ page, baseURL }) => {
  if (!reviewId || !email || !password || !baseURL) throw new Error("Isolated score-sum environment required");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const path = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => {
    const response = await page.request.get(`${baseURL}${path}`);
    expect(response.status()).toBe(200);
    return response.json();
  };
  const initial = await read();
  expect(initial.snapshot.nodes.map((node: { score_semantics: string }) => node.score_semantics)).toEqual([
    "sum_children", "direct", "sum_children", "direct", "direct", "direct",
  ]);

  await page.goto(`/question-import-reviews/${reviewId}`);
  const tree = page.getByRole("navigation", { name: "設問構成" });
  await expect(page.locator(".derived-score").first()).toContainText("配点: 40点");
  await tree.getByRole("button", { name: /\(2\)/ }).click();
  await expect(page.locator(".derived-score").first()).toContainText("配点: 30点");

  await tree.getByRole("button", { name: /3\./ }).click();
  await page.getByLabel("配点の扱い").selectOption("unset");
  const missingSave = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await missingSave).status()).toBe(200);
  let saved = await read();
  expect(saved.current_revision).toBe(initial.current_revision + 1);
  expect(saved.summary.total_points_candidate).toBeNull();

  await page.reload();
  await tree.getByRole("button", { name: /問題2/ }).click();
  await expect(page.locator(".derived-score").first()).toContainText("未確定");
  await expect(page.locator(".derived-score").first()).toContainText("小問合計（設定済み分）: 30点");
  await expect(page.locator(".derived-score").first()).toContainText("未設定または要確認: 3.");

  const missingReview = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await missingReview).status()).toBe(200);
  const missingPlan = page.waitForResponse(response => response.url().includes(`${path}/import-plan`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "問題登録前の最終確認へ", exact: true }).click();
  expect((await missingPlan).status()).toBe(200);
  const finalCheck = page.getByRole("region", { name: "問題登録前の最終確認" });
  await expect(finalCheck.getByRole("heading", { name: "配点未設定: 問題2 > (2) > 3." })).toBeVisible();
  await expect(finalCheck).toContainText("の配点は未設定です。");
  page.once("dialog", dialog => dialog.accept());
  await finalCheck.getByRole("button", { name: "確認を解除して編集" }).click();

  await tree.getByRole("button", { name: /3\./ }).click();
  await page.getByLabel("配点の扱い").selectOption("direct");
  await page.locator(".review-fields input[type='number']").fill("10");
  const repairSave = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await repairSave).status()).toBe(200);
  await page.reload();
  await expect(page.locator(".derived-score").first()).toContainText("配点: 40点");

  const reviewResponse = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await reviewResponse).status()).toBe(200);
  const planResponse = page.waitForResponse(response => response.url().includes(`${path}/import-plan`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "問題登録前の最終確認へ", exact: true }).click();
  expect((await planResponse).status()).toBe(200);
  await expect(page.getByRole("region", { name: "問題登録前の最終確認" })).toContainText("合計点 40");
  saved = await read();
  expect(saved.summary.total_points_candidate).toBe(40);
  const plan = await (await page.request.post(`${baseURL}${path}/import-plan`)).json();
  expect(plan.blockers).toEqual([]);
  expect(plan.total_points).toBe(40);
  expect(plan.nodes.filter((node: { is_gradable: boolean }) => !node.is_gradable).map((node: { max_points: number | null }) => node.max_points))
    .toEqual([null, null]);
  expect(plan.nodes.filter((node: { is_gradable: boolean }) => node.is_gradable).map((node: { max_points: number }) => node.max_points))
    .toEqual([10, 10, 10, 10]);
  page.once("dialog", dialog => dialog.accept());
  const importResponse = page.waitForResponse(response => response.url().includes(`${path}/confirm`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認した問題を登録", exact: true }).click();
  expect((await importResponse).status()).toBe(200);
  const confirmation = await (await page.request.get(`${baseURL}${path}/confirmation`)).json();
  expect(confirmation.total_points).toBe(40);
  expect(confirmation.structural_count).toBe(2);
  expect(confirmation.gradable_count).toBe(4);
});
