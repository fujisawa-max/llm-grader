import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_FORMULA_CONSISTENCY_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated formula confirmation API is not configured");

test("individual confirmation, mixed merge, embedded formula confirmation and bulk confirmation persist", async ({ page, baseURL }) => {
  if (!reviewId || !email || !password || !baseURL) throw new Error("Isolated review environment required");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード").fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const path = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${path}`)).json());
  const initial = await read();
  const node = initial.snapshot.nodes[0];
  const formulaIds = node.ordered_content.filter((item: { type: string }) => item.type === "formula_region")
    .map((item: { region_id: string }) => item.region_id);
  expect(formulaIds).toHaveLength(3);
  expect(initial.summary).toMatchObject({ formula_reviewed: 0, formula_unreviewed: 3 });

  await page.goto(`/question-import-reviews/${reviewId}`);
  await expect(page.getByRole("button", { name: /数式 確認済み 0 \/ 3 · 未確認 3/ })).toBeVisible();
  await page.getByLabel("数式 1の確認").selectOption("confirmed");
  const firstSave = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await firstSave).status()).toBe(200);
  await page.reload();
  let saved = await read();
  expect(saved.summary).toMatchObject({ formula_reviewed: 1, formula_unreviewed: 2 });

  const failedMark = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  const markResponse = await failedMark;
  expect(markResponse.status()).toBe(422);
  expect((await markResponse.json()).error.code).toBe("formula_review_required");
  await expect(page.locator("p.error[role='alert']")).toContainText("未確認の数式が残っています");

  // Text, Formula, Text, Formula, Text are combined in original order.
  await page.getByRole("button", { name: "内容をまとめて結合" }).click();
  for (const label of ["問題文 1", "数式 1", "問題文 2", "数式 2", "問題文 3"]) {
    await page.getByLabel(`まとめて結合する ${label}`).check();
  }
  const merge = page.getByRole("button", { name: "選択した5件の内容を結合" });
  await expect(merge).toBeEnabled();
  await merge.click();
  await expect(page.getByLabel("問題文 1", { exact: true })).toHaveValue("次の式$x^2$について、$y=1$結果を求めます。");
  await expect(page.locator('[data-content-type="text"]').first().locator(".katex")).toHaveCount(2);
  await expect(page.getByLabel("結合済み数式 1")).toHaveValue("confirmed");
  await expect(page.getByLabel("結合済み数式 2")).toHaveValue("unreviewed");

  const mergeSave = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await mergeSave).status()).toBe(200);
  await page.reload();
  saved = await read();
  expect(saved.snapshot.nodes[0].ordered_content.map((item: { type: string }) => item.type)).toEqual(["text", "formula_region"]);
  const mergedText = saved.snapshot.nodes[0].ordered_content[0];
  expect(mergedText.text).toBe("次の式$x^2$について、$y=1$結果を求めます。");
  expect(mergedText.merged_source_segments.filter((segment: { type?: string }) => segment.type === "formula_region")
    .map((segment: { region_id: string }) => segment.region_id)).toEqual(formulaIds.slice(0, 2));
  expect(saved.snapshot.nodes[0].formula_decisions[formulaIds[0]]).toMatchObject({
    decision: "merged_into_text", confirmation_status: "confirmed",
  });
  expect(saved.snapshot.nodes[0].formula_decisions[formulaIds[1]]).toMatchObject({
    decision: "merged_into_text", confirmation_status: "unreviewed",
  });
  expect(saved.summary).toMatchObject({ formula_reviewed: 1, formula_unreviewed: 2 });
  expect(saved.source_pdf_sha256).toBe(initial.source_pdf_sha256);
  expect(saved.regions).toEqual(initial.regions);

  const bulkDialog = page.waitForEvent("dialog").then(async dialog => {
    const message = dialog.message();
    await dialog.accept();
    return message;
  });
  await page.getByRole("button", { name: /未確認の数式を一括確認（2件）/ }).click();
  const bulkDialogMessage = await bulkDialog;
  expect(bulkDialogMessage).toContain("未確認の数式が2件");
  expect(bulkDialogMessage).toContain("すべて確認済みとして扱いますか");
  await expect(page.getByLabel("結合済み数式 2")).toHaveValue("confirmed");
  await expect(page.getByLabel("数式 1の確認")).toHaveValue("confirmed");
  await expect(page.getByText(/数式 確認済み 3 \/ 3 · 未確認 0/)).toBeVisible();

  const bulkSave = page.waitForResponse(response => response.url().includes(`${path}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await bulkSave).status()).toBe(200);
  await page.reload();
  saved = await read();
  expect(saved.summary).toMatchObject({ formula_reviewed: 3, formula_unreviewed: 0 });
  expect(saved.snapshot.nodes[0].formula_decisions[formulaIds[1]]).toMatchObject({
    confirmation_status: "confirmed", confirmation_method: "bulk",
  });
  expect(saved.snapshot.nodes[0].formula_decisions[formulaIds[2]]).toMatchObject({
    decision: "unreviewed", confirmation_status: "confirmed", confirmation_method: "bulk",
  });
  expect(saved.source_pdf_sha256).toBe(initial.source_pdf_sha256);
  expect(saved.regions).toEqual(initial.regions);

  const complete = page.waitForResponse(response => response.url().includes(`${path}/mark-reviewed`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await complete).status()).toBe(200);
  await page.reload();
  saved = await read();
  expect(saved.state).toBe("reviewed");
  expect(saved.summary).toMatchObject({ formula_reviewed: 3, formula_unreviewed: 0 });
});
