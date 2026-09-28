import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_VALIDATION_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated review API is not configured");

test("save errors show full question paths and focus the fields before real API save", async ({ page, baseURL }) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  const apiPath = `/api/v1/question-import-reviews/${reviewId}`;
  const saveRequest = () => page.waitForResponse(response => response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.goto(`/question-import-reviews/${reviewId}`);
  await page.getByRole("button", { name: "小問に分割" }).click();
  await page.getByRole("button", { name: "この内容で分割" }).click();
  let response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);

  await page.getByRole("button", { name: "大問を追加" }).click();
  let editor = page.getByRole("article", { name: "選択問題エディタ" });
  await editor.getByRole("textbox", { name: /設問番号・見出し/ }).fill("問題2");
  await editor.getByLabel("問題文 1").fill("共通の導入文。");
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);

  await page.getByRole("button", { name: "小問を追加" }).click();
  editor = page.getByRole("article", { name: "選択問題エディタ" });
  await editor.getByRole("textbox", { name: /設問番号・見出し/ }).fill("(1)");
  await editor.getByLabel("問題文 1").fill("次の値を求めよ。");
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);

  const tree = page.getByRole("navigation", { name: "設問構成" });
  await tree.getByRole("button").nth(2).click();
  await page.getByLabel("問題文 1").fill("");
  await tree.getByRole("button").nth(5).click();
  await page.getByLabel("問題文 1").fill("");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  const summary = page.locator(".review-save-errors");
  await expect(summary).toContainText("2件の項目");
  await expect(summary.getByRole("button", { name: "問題1 > (2) > 問題文1" })).toBeVisible();
  await expect(summary.getByRole("button", { name: "問題2 > (1) > 問題文1" })).toBeVisible();
  await summary.getByRole("button", { name: "問題1 > (2) > 問題文1" }).click();
  await expect(page.getByLabel("問題文 1")).toBeFocused();
  await expect(page.locator('[data-content-type="text"]').first()).toHaveClass(/has-error/);
  await expect(page.locator('[data-content-type="text"]').first()).toContainText("問題文が空です");
  await page.getByLabel("問題文 1").fill("境界を説明しなさい。");
  await expect(summary).toContainText("1件の項目");
  await tree.getByRole("button").nth(5).click();
  await page.getByLabel("問題文 1").fill("点Aの値を求めなさい。");
  await expect(summary).toHaveCount(0);
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await page.reload();
  await expect(page.locator(".review-save-errors")).toHaveCount(0);
  await page.getByRole("navigation", { name: "設問構成" }).getByRole("button").nth(5).click();
  await expect(page.getByLabel("問題文 1")).toHaveValue("点Aの値を求めなさい。");

  editor = page.getByRole("article", { name: "選択問題エディタ" });
  await editor.getByLabel("配点の扱い").selectOption("direct");
  const points = editor.locator('input[type="number"]');
  await points.fill("1000000001");
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(422);
  await expect(page.locator(".review-save-errors")).toContainText("問題2 > (1) > 配点");
  await page.locator(".review-save-errors").getByRole("button", { name: "問題2 > (1) > 配点" }).click();
  await expect(points).toBeFocused();
  await expect(points).toHaveAttribute("aria-invalid", "true");
  await points.fill("1");
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator(".review-save-errors")).toHaveCount(0);

  const saved = await (await page.request.get(`${baseURL}${apiPath}`)).json();
  const invalid = structuredClone(saved.snapshot);
  invalid.nodes[0].score_semantics = "direct";
  invalid.nodes[0].score_points = null;
  const rejected = await page.request.post(`${baseURL}${apiPath}/revisions`, {
    data: { base_revision: saved.current_revision, snapshot: invalid },
  });
  expect(rejected.status()).toBe(422);
  expect((await rejected.json()).error).toMatchObject({
    code: "score_type_mismatch", details: { node_key: invalid.nodes[0].stable_key, field_key: "score" },
  });

  const navigation = page.getByRole("navigation", { name: "設問構成" });
  await navigation.getByRole("button").nth(0).click();
  const originalValue = await page.getByLabel("問題文 1").inputValue();
  await page.getByLabel("問題文 1").fill("未保存編集を保持する確認用テキスト");
  await page.route(`**${apiPath}/revisions`, async route => {
    const body = route.request().postDataJSON();
    const sourceNode = body.snapshot.nodes.find((candidate: { stable_key: string }) => candidate.stable_key === saved.snapshot.nodes[0].stable_key);
    const sourceItem = sourceNode.ordered_content.find((item: { source_slice?: number[] }) => item.source_slice);
    const total = sourceItem.source_slice[2];
    sourceItem.source_slice = [0, total + 1, total];
    await route.continue({ postData: JSON.stringify(body) });
  }, { times: 1 });
  response = saveRequest();
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  const internalResponse = await response;
  expect(internalResponse.status()).toBe(422);
  expect((await internalResponse.json()).error.details).toMatchObject({
    category: "internal_consistency", node_key: saved.snapshot.nodes[0].stable_key,
    field_key: "source_mapping", recoverable: false, recovery_action: "reload_latest",
  });
  const internal = page.locator(".review-internal-error");
  await expect(internal).toContainText("問題1 > 元資料との対応情報");
  await expect(internal).toContainText("直接修正しても解消しない");
  await expect(internal).toContainText("技術情報");
  await expect(page.locator(".review-save-errors")).toHaveCount(0);
  await expect(page.getByLabel("問題文 1")).toHaveValue("未保存編集を保持する確認用テキスト");
  page.once("dialog", async dialog => {
    expect(dialog.message()).toContain("未保存編集は失われます");
    await dialog.dismiss();
  });
  await internal.getByRole("button", { name: "最新の内容を再読み込み" }).click();
  await expect(page.getByLabel("問題文 1")).toHaveValue("未保存編集を保持する確認用テキスト");
  page.once("dialog", dialog => dialog.accept());
  await internal.getByRole("button", { name: "最新の内容を再読み込み" }).click();
  await expect(page.getByLabel("問題文 1")).toHaveValue(originalValue);
});
