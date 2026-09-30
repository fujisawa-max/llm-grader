import { test, expect } from "@playwright/test";
import { inlineFormulaSource } from "../lib/formulaMerge";

const mergeId = process.env.REVIEW_FORMULA_MERGE_ID;
const deleteId = process.env.REVIEW_FORMULA_DELETE_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!mergeId || !deleteId || !email || !password, "isolated API validation environment is not configured");

test("formula delimiter normalization", () => {
  expect(inlineFormulaSource(String.raw`\frac{1}{3}`)).toBe(String.raw`\frac{1}{3}`);
  expect(inlineFormulaSource("$x_1+x_2$")).toBe("x_1+x_2");
  expect(inlineFormulaSource("$$\nx_1+x_2\n$$")).toBe("x_1+x_2");
  expect(inlineFormulaSource(String.raw`\frac{`)).toBe(String.raw`\frac{`);
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test("formula merges into adjacent text with both PDF sources intact", async ({ page, baseURL }) => {
  await login(page);
  const path = `/api/v1/question-import-reviews/${mergeId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${path}`)).json());
  const before = await read();
  const formulaAnchor = before.snapshot.nodes[0].ordered_content[1];
  const textSource = before.snapshot.nodes[0].ordered_content[0].source_element_ids;
  await page.goto(`/question-import-reviews/${mergeId}`);
  const formula = page.locator('[data-content-type="formula"]');
  await expect(formula.getByRole("button", { name: "上の問題文とマージ" })).toBeEnabled();
  await formula.getByLabel("数式 1の確認").selectOption("unreviewed");
  await page.getByLabel("数式 1のLaTeX").fill("$$x_1 + x_2 = 3$$");
  await formula.getByRole("button", { name: "上の問題文とマージ" }).click();
  await expect(page.getByLabel("問題文 1")).toHaveValue("問題1 次の式を計算しなさい。$x_1 + x_2 = 3$");
  await expect(page.locator('[data-content-type="text"]').first().locator(".katex")).toBeVisible();
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("unreviewed");
  await expect(formula).toHaveCount(0);
  const response = page.waitForResponse(r => r.url().includes(`${path}/revisions`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("問題文 1")).toHaveValue("問題1 次の式を計算しなさい。$x_1 + x_2 = 3$");
  await expect(page.locator('[data-content-type="text"]').first().locator(".katex")).toBeVisible();
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("unreviewed");
  await page.getByLabel("結合済み数式 1").selectOption("confirmed");
  const individualConfirmation = page.waitForResponse(r => r.url().includes(`${path}/revisions`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await individualConfirmation).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("confirmed");
  await page.getByLabel("結合済み数式 1").selectOption("unreviewed");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: /未確認の数式を一括確認（1件）/ }).click();
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("confirmed");
  const bulkConfirmation = page.waitForResponse(r => r.url().includes(`${path}/revisions`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await bulkConfirmation).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("confirmed");
  const saved = await read();
  expect(saved.current_revision).toBe(before.current_revision + 3);
  expect(saved.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type))
    .toEqual(["text", "text", "figure_region"]);
  expect(saved.snapshot.nodes[0].ordered_content[0].source_element_ids).toEqual(textSource);
  const formulaSegment = saved.snapshot.nodes[0].ordered_content[0].merged_source_segments[0];
  expect(formulaSegment).toEqual(Object.fromEntries(Object.entries(formulaAnchor).filter(([key]) => key !== "order")));
  expect(saved.snapshot.nodes[0].formula_decisions["formula-fixture-1"]).toMatchObject({
    decision: "merged_into_text", teacher_transcription: "x_1 + x_2 = 3",
    confirmation_status: "confirmed", confirmation_method: "bulk",
  });
  expect(saved.regions).toEqual(before.regions);
  expect(saved.source_pdf_sha256).toBe(before.source_pdf_sha256);
  await page.locator('[data-content-type="text"]').nth(1).getByRole("button", { name: "上の問題文とマージ" }).click();
  const chain = page.waitForResponse(r => r.url().includes(`${path}/revisions`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await chain).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("問題文 1")).toHaveValue(
    "問題1 次の式を計算しなさい。$x_1 + x_2 = 3$補足の説明を確認してください。"
  );
  const chained = await read();
  expect(chained.snapshot.nodes[0].ordered_content[0].merged_source_segments.some(
    (segment: { region_id?: string }) => segment.region_id === "formula-fixture-1"
  )).toBe(true);
});

test("formula deletion removes only the review item", async ({ page, baseURL }) => {
  await login(page);
  const path = `/api/v1/question-import-reviews/${deleteId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${path}`)).json());
  const before = await read();
  await page.goto(`/question-import-reviews/${deleteId}`);
  page.once("dialog", dialog => dialog.accept());
  await page.locator('[data-content-type="formula"]').getByRole("button", { name: "数式 1を削除" }).click();
  await expect(page.locator('[data-content-type="formula"]')).toHaveCount(0);
  const response = page.waitForResponse(r => r.url().includes(`${path}/revisions`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await page.reload();
  await expect(page.locator('[data-content-type="formula"]')).toHaveCount(0);
  const saved = await read();
  expect(saved.current_revision).toBe(before.current_revision + 1);
  expect(saved.snapshot.nodes[0].formula_decisions["formula-fixture-1"].decision).toBe("excluded");
  expect(saved.regions).toEqual(before.regions);
  expect(saved.source_pdf_sha256).toBe(before.source_pdf_sha256);
  expect(saved.source_ir_sha256).toBe(before.source_ir_sha256);
});
