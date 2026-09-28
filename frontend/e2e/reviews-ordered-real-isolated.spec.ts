import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_VALIDATION_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated API validation environment is not configured");

test("real API preserves ordered content moves, merge evidence, and deletion", async ({ page, baseURL }) => {
  if (!reviewId || !email || !password || !baseURL) throw new Error("Isolated review environment required");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  const path = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${path}`)).json());
  const before = await read();
  const originalItems = before.snapshot.nodes[0].ordered_content;
  expect(originalItems.map((item: { type: string }) => item.type)).toEqual([
    "text", "formula_region", "text", "figure_region",
  ]);
  expect(originalItems[0].source_element_ids).toHaveLength(1);
  expect(originalItems[2].source_element_ids).toHaveLength(1);
  const sourceSha = before.source_pdf_sha256;
  const sourceRegions = before.regions;
  const save = async () => {
    const response = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
    await page.getByRole("button", { name: "変更を保存", exact: true }).click();
    expect((await response).status()).toBe(200);
    await page.reload();
  };
  await page.goto(`/question-import-reviews/${reviewId}`);
  const textCards = page.locator('[data-content-type="text"]');
  const formula = page.locator('[data-content-type="formula"]');
  await expect(textCards.nth(1).getByRole("button", { name: "上へ" })).toBeEnabled();
  await expect(textCards.nth(1).getByRole("button", { name: "下へ" })).toBeEnabled();
  await expect(textCards.nth(1).getByRole("button", { name: /削除/ })).toBeEnabled();
  await expect(formula.getByRole("button", { name: "下へ" })).toBeEnabled();
  await expect(textCards.nth(1).getByRole("button", { name: "上の問題文とマージ" })).toHaveCount(0);

  await textCards.nth(1).getByRole("button", { name: "上へ" }).click();
  await save();
  let result = await read();
  expect(result.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type))
    .toEqual(["text", "text", "formula_region", "figure_region"]);
  await expect(textCards.nth(1).getByRole("button", { name: "上の問題文とマージ" })).toBeEnabled();

  await textCards.nth(0).getByRole("button", { name: "下へ" }).click();
  await save();
  result = await read();
  expect(result.snapshot.nodes[0].ordered_content[0].source_element_ids)
    .toEqual(originalItems[2].source_element_ids);
  await textCards.nth(1).getByRole("button", { name: "上へ" }).click();
  await save();

  await textCards.nth(1).getByRole("button", { name: "上の問題文とマージ" }).click();
  await expect(page.getByLabel("問題文 1")).toHaveValue(
    "問題1 次の式を計算しなさい。補足の説明を確認してください。"
  );
  await expect(page.getByLabel("問題文 2")).toHaveCount(0);
  await save();
  result = await read();
  const merged = result.snapshot.nodes[0].ordered_content[0];
  expect(merged.source_element_ids).toEqual(originalItems[0].source_element_ids);
  expect(merged.merged_source_segments[0].source_element_ids).toEqual(originalItems[2].source_element_ids);
  await expect(page.getByLabel("問題文 1")).toHaveValue(merged.text);

  await expect(formula.getByRole("button", { name: "上へ" })).toBeEnabled();
  await formula.getByRole("button", { name: "上へ" }).click();
  await save();
  result = await read();
  expect(result.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type))
    .toEqual(["formula_region", "text", "figure_region"]);
  await expect(formula.locator(".math-preview .katex")).toBeVisible();
  await formula.getByRole("button", { name: "下へ" }).click();
  await save();
  result = await read();
  expect(result.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type))
    .toEqual(["text", "formula_region", "figure_region"]);

  await page.getByRole("button", { name: "＋ 問題文を追加" }).click();
  await page.getByLabel("問題文 2").fill("削除する追記");
  await save();
  page.once("dialog", dialog => dialog.accept());
  await textCards.nth(1).getByRole("button", { name: "問題文 2を削除" }).click();
  await save();
  await expect(page.getByLabel("問題文 2")).toHaveCount(0);
  result = await read();
  expect(result.source_pdf_sha256).toBe(sourceSha);
  expect(result.regions).toEqual(sourceRegions);
  expect(result.snapshot.nodes[0].ordered_content[0].merged_source_segments[0].source_element_ids)
    .toEqual(originalItems[2].source_element_ids);
  expect(result.current_revision).toBe(before.current_revision + 8);
});
