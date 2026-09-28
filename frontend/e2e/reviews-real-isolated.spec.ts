import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_VALIDATION_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;

test.skip(!reviewId || !email || !password, "isolated API validation environment is not configured");

test("real API persists ordered text and formula edits across revisions", async ({ page, baseURL }) => {
  if (!reviewId || !email || !password || !baseURL) throw new Error("Set isolated review validation environment variables");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const apiPath = `/api/v1/question-import-reviews/${reviewId}`;
  const initialResponse = await page.request.get(`${baseURL}${apiPath}`);
  expect(initialResponse.status()).toBe(200);
  const initial = await initialResponse.json();
  const initialNode = initial.snapshot.nodes[0];
  const initialRevision = initial.current_revision;
  const initialPdfSha = initial.source_pdf_sha256;
  const initialIrSha = initial.source_ir_sha256;
  const initialRegions = initial.regions.map((region: { region_id: string; source_element_ids: string[] }) => ({
    id: region.region_id, source: region.source_element_ids,
  }));
  expect(initialNode.ordered_content.map((item: { type: string }) => item.type)).toEqual([
    "text", "formula_region", "text", "figure_region",
  ]);

  await page.goto(`/question-import-reviews/${reviewId}`);
  await expect(page.getByLabel("問題文 2")).toHaveValue("補足の説明を確認してください。");
  await page.getByRole("button", { name: "＋ 問題文を追加" }).click();
  await page.getByLabel("問題文 3").fill("追加した問題文を保存します。");
  const addRequest = page.waitForRequest(request => request.url().includes(`${apiPath}/revisions`) && request.method() === "POST");
  const addSave = page.waitForResponse(response => response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  await addRequest;
  const addResponse = await addSave;
  expect(addResponse.status(), await addResponse.text()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("問題文 3")).toHaveValue("追加した問題文を保存します。");
  let saved = await (await page.request.get(`${baseURL}${apiPath}`)).json();
  expect(saved.current_revision).toBe(initialRevision + 1);
  expect(saved.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type)).toEqual([
    "text", "formula_region", "text", "figure_region", "text",
  ]);

  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "問題文 3を削除" }).click();
  const deleteSave = page.waitForResponse(response => response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await deleteSave).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("問題文 3")).toHaveCount(0);
  saved = await (await page.request.get(`${baseURL}${apiPath}`)).json();
  expect(saved.current_revision).toBe(initialRevision + 2);
  expect(saved.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type)).toEqual([
    "text", "formula_region", "text", "figure_region",
  ]);

  const formulaEditor = page.getByLabel("数式 1のLaTeX");
  await expect(formulaEditor).toHaveValue(String.raw`\frac{1}{3}`);
  await formulaEditor.fill(String.raw`\frac{1}{6}`);
  await expect(page.locator('[data-region-id="formula-fixture-1"] .math-preview').first().locator(".katex")).toBeVisible();
  const formulaSave = page.waitForResponse(response => response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await formulaSave).status()).toBe(200);
  await page.reload();
  await expect(page.getByLabel("数式 1のLaTeX")).toHaveValue(String.raw`\frac{1}{6}`);
  await expect(page.locator('[data-region-id="formula-fixture-1"] .math-preview').first().locator(".katex")).toBeVisible();

  saved = await (await page.request.get(`${baseURL}${apiPath}`)).json();
  expect(saved.current_revision).toBe(initialRevision + 3);
  expect(saved.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type)).toEqual([
    "text", "formula_region", "text", "figure_region",
  ]);
  expect(saved.snapshot.nodes[0].formula_decisions["formula-fixture-1"].teacher_transcription).toBe(String.raw`\frac{1}{6}`);
  expect(saved.source_pdf_sha256).toBe(initialPdfSha);
  expect(saved.source_ir_sha256).toBe(initialIrSha);
  expect(saved.regions.map((region: { region_id: string; source_element_ids: string[] }) => ({
    id: region.region_id, source: region.source_element_ids,
  }))).toEqual(initialRegions);
});
