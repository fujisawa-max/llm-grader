import { test, expect } from "@playwright/test";

const testId = process.env.RUBRIC_SPLIT_TEST_ID;
const questionId = process.env.RUBRIC_SPLIT_QUESTION_ID;
test.skip(!testId || !questionId, "requires isolated API and managed split runtime stub");

test("rubric ranges preview, split, insert, undo and registration preserve source and points", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name: "ログイン"}).click();
  await expect(page).not.toHaveURL(/\/login/);
  const materials = await (await page.request.get(`/api/v1/tests/${testId}/materials`)).json();
  const created = await page.request.post(`/api/v1/tests/${testId}/model-answer-imports`, {data: {material_id: materials[0].id}});
  expect(created.ok()).toBeTruthy();
  const draft = await created.json();
  await page.goto(`/model-answer-import-reviews/${draft.id}`);
  await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  const descriptions = () => page.getByLabel(/^採点基準候補 .* 本文$/);
  await expect(descriptions()).toHaveCount(1);
  const original = await descriptions().first().inputValue();
  await page.getByRole("button", {name: "LLMで分割を試す", exact: true}).click();
  const preview = page.getByRole("region", {name: "採点基準の分割案"});
  await expect(preview).toBeVisible();
  await expect(preview.getByText("配点: 5", {exact: true})).toHaveCount(2);
  await expect(descriptions()).toHaveCount(1); // suggestion is non-destructive
  await page.getByRole("button", {name: "この分割案を適用"}).click();
  await expect(descriptions()).toHaveCount(2);
  await expect(descriptions().nth(0)).toHaveValue("explain overfitting.");
  await expect(descriptions().nth(1)).toHaveValue("cite evidence.");
  await page.getByRole("button", {name: "分割・追加を元に戻す"}).click();
  await expect(descriptions()).toHaveCount(1);
  await expect(descriptions().first()).toHaveValue(original);

  // A textarea cursor splits current teacher text; no automatic point allocation.
  const textarea = descriptions().first();
  await textarea.fill("First criterion. Second criterion.");
  await textarea.evaluate((element) => {
    const control = element as HTMLTextAreaElement;
    control.focus(); control.setSelectionRange(17, 17); control.dispatchEvent(new Event("select", {bubbles: true}));
  });
  await page.getByRole("button", {name: "カーソルの位置で分割"}).click();
  await expect(preview).toBeVisible();
  await page.getByRole("button", {name: "この分割案を適用"}).click();
  await expect(descriptions()).toHaveCount(2);
  await expect(descriptions().nth(0)).toHaveValue("First criterion.");
  await expect(descriptions().nth(1)).toHaveValue("Second criterion.");
  const points = () => page.getByLabel(/^採点基準候補 .* の配点$/);
  await points().nth(0).fill("5"); await points().nth(1).fill("5");

  await page.getByRole("button", {name: "複製して下に追加"}).first().click();
  await expect(descriptions()).toHaveCount(3);
  await expect(descriptions().nth(1)).toHaveValue("First criterion.");
  await descriptions().nth(1).fill("Duplicated teacher criterion.");
  await page.getByRole("button", {name: "採点基準を除外"}).nth(1).click();
  await expect(descriptions()).toHaveCount(2);
  await page.getByRole("button", {name: "下に採点基準を追加"}).first().click();
  await expect(descriptions()).toHaveCount(3);
  await descriptions().nth(1).fill("New teacher criterion.");
  await points().nth(1).fill("1");
  await page.getByRole("button", {name: "採点基準を除外"}).nth(1).click();
  await expect(descriptions()).toHaveCount(2);
  await page.getByRole("button", {name: "上とマージ"}).first().click();
  await expect(descriptions()).toHaveCount(1);
  await page.getByRole("button", {name: "マージを解除（元に戻す）"}).click();
  await expect(descriptions()).toHaveCount(2);

  const saved = page.waitForResponse((response) => response.request().method() === "PUT" && response.url().endsWith(draft.id));
  await page.getByRole("button", {name: "下書き保存"}).click();
  expect((await saved).ok()).toBeTruthy();
  await page.reload();
  await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  await expect(descriptions()).toHaveCount(2);
  await expect(descriptions().nth(0)).toHaveValue("First criterion.");
  const registered = page.waitForResponse((response) => response.url().endsWith("/register-rubric"));
  await page.getByRole("button", {name: "採点基準として登録"}).click();
  const result = await registered;
  expect(result.status()).toBe(200);
  const payload = await result.json();
  expect(payload.rubric.status).toBe("generated");
  expect(payload.rubric.rubric_json.questions[0].criteria).toHaveLength(2);
  const sources = payload.rubric.rubric_json.provenance.questions[questionId!];
  expect(sources[0].operation_provenance.split_method).toBe("manual");
  expect(sources[0].segment_ids).toEqual(sources[1].segment_ids);
  const persisted = await (await page.request.get(`/api/v1/tests/${testId}/rubrics`)).json();
  expect(persisted[0].rubric_json.questions[0].criteria).toHaveLength(2);
  // Register accepted manual and duplicate items too, not merely excluded copies.
  await page.getByRole("button", {name: "複製して下に追加"}).first().click();
  await page.getByRole("button", {name: "下に採点基準を追加"}).first().click();
  await expect(descriptions()).toHaveCount(4);
  await descriptions().nth(1).fill("Accepted manual criterion.");
  await descriptions().nth(2).fill("Accepted duplicate criterion.");
  for (const [index, value] of ["3", "2", "2", "3"].entries()) await points().nth(index).fill(value);
  const manualSaved = page.waitForResponse((response) => response.request().method() === "PUT" && response.url().endsWith(draft.id));
  await page.getByRole("button", {name: "下書き保存"}).click();
  expect((await manualSaved).ok()).toBeTruthy();
  await page.reload();
  await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  await expect(descriptions()).toHaveCount(4);
  await expect(descriptions().nth(1)).toHaveValue("Accepted manual criterion.");
  const rerun = page.waitForResponse((response) => response.url().endsWith("/classify"));
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", {name: "意味分類を再実行"}).click();
  expect((await rerun).ok()).toBeTruthy();
  await expect(descriptions().nth(2)).toHaveValue("Accepted duplicate criterion.");
  const insertedRegistration = page.waitForResponse((response) => response.url().endsWith("/register-rubric"));
  await page.getByRole("button", {name: "採点基準として登録"}).click();
  const insertedResponse = await insertedRegistration;
  expect(insertedResponse.status()).toBe(200);
  const inserted = await insertedResponse.json();
  expect(inserted.rubric.version).toBe(2);
  const criteria = inserted.rubric.rubric_json.questions[0].criteria;
  expect(criteria.map((item: {description: string}) => item.description)).toEqual([
    "First criterion.", "Accepted manual criterion.", "Accepted duplicate criterion.", "Second criterion."]);
  const provenance = inserted.rubric.rubric_json.provenance.questions[questionId!];
  expect(provenance[1].operation_provenance.source).toBe("teacher_manual");
  expect(provenance[2].operation_provenance.manual_duplicate_from).toBeTruthy();

});
