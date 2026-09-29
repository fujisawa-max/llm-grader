import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_SPLIT_PARTIAL_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated review API is not configured");

test("ambiguous candidates are excluded while safe candidates split through the real API", async ({ page, baseURL }) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const apiPath = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${apiPath}`)).json());
  const before = await read();
  await page.goto(`/question-import-reviews/${reviewId}`);
  const firstText = page.getByLabel("問題文 1");
  const secondText = page.getByLabel("問題文 2");
  const ambiguousFirst = "導入文です。\n1. 新しい境界の指示\n2. 新しい領域の指示\n";
  const ambiguousSecond = "3. 新しい点の指示";
  await firstText.fill(ambiguousFirst);
  await secondText.fill(ambiguousSecond);
  await page.getByRole("button", { name: "小問に分割" }).click();

  const splitButton = page.getByRole("button", { name: "この内容で分割" });
  const choices = page.getByLabel("この候補を小問にする");
  await expect(choices).toHaveCount(3);
  await expect(page.getByText("元資料との対応: 要対応")).toHaveCount(3);
  await expect(choices.nth(0)).toBeDisabled();
  await expect(choices.nth(1)).toBeDisabled();
  await expect(choices.nth(2)).toBeDisabled();
  await expect(splitButton).toBeDisabled();
  const noSafeMapping = page.locator(".review-split-preview").getByText(/自動で対応を確認できない候補があります/);
  await expect(noSafeMapping).toHaveCount(1);
  await expect(noSafeMapping).toBeVisible();
  await page.getByRole("button", { name: "キャンセル" }).click();
  await expect(firstText).toHaveValue(ambiguousFirst);
  await expect(secondText).toHaveValue(ambiguousSecond);

  const partiallyEdited = "導入文です。\n1. 新しい境界の指示\n2. クラス1の領域を示しなさい。\n";
  const originalThird = "3. 点Aのクラスを答えなさい。";
  await firstText.fill(partiallyEdited);
  await secondText.fill(originalThird);
  await page.getByRole("button", { name: "小問に分割" }).click();
  await expect(choices).toHaveCount(3);
  await expect(page.locator(".review-split-preview").getByText(/3件中2件は自動で対応を確認できました/)).toBeVisible();
  await expect(page.getByText("元資料との対応: 要対応")).toHaveCount(1);
  await expect(page.getByText("元資料との対応: 自動確認済み")).toHaveCount(2);
  await expect(choices.nth(0)).toBeDisabled();
  await expect(choices.nth(0)).not.toBeChecked();
  await expect(choices.nth(1)).toBeEnabled();
  await expect(choices.nth(2)).toBeEnabled();
  await expect(splitButton).toBeEnabled();
  await choices.nth(1).uncheck();
  await expect(choices.nth(1)).not.toBeChecked();
  await expect(splitButton).toBeEnabled();
  await splitButton.click();

  const tree = page.getByRole("navigation", { name: "設問構成" });
  await expect(tree.getByRole("button")).toHaveCount(2);
  await expect(tree.getByRole("button", { name: /\(3\)/ })).toBeVisible();
  const saveResponse = page.waitForResponse(response => response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();

  const saved = await read();
  expect(saved.current_revision).toBe(before.current_revision + 1);
  expect(saved.snapshot.nodes).toHaveLength(2);
  const [parent, child3] = saved.snapshot.nodes;
  expect(saved.snapshot.nodes.slice(1).map((node: { parent_key: string }) => node.parent_key))
    .toEqual([parent.stable_key]);
  expect(child3.label.normalized).toBe("(3)");
  expect(parent.ordered_content.map((item: { text?: string }) => item.text).filter(Boolean).join("\n"))
    .toContain("1. 新しい境界の指示");
  const retainedAmbiguous = parent.ordered_content.find((item: { text?: string }) => item.text?.includes("新しい境界"));
  expect(retainedAmbiguous).toBeTruthy();
  expect(retainedAmbiguous.source_slice).toBeUndefined();
  const retainedSafe = parent.ordered_content.find((item: { text?: string }) => item.text?.includes("2. クラス1の領域を示しなさい。"));
  expect(retainedSafe).toBeTruthy();
  expect(retainedSafe.source_slice).toHaveLength(3);
  expect(child3.ordered_content[0].source_slice).toHaveLength(3);
  expect(saved.source_pdf_sha256).toBe(before.source_pdf_sha256);
  expect(saved.regions).toEqual(before.regions);
});
