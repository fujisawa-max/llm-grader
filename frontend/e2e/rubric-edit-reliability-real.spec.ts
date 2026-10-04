import { test, expect, type Page } from "@playwright/test";

const testId = process.env.RUBRIC_SPLIT_TEST_ID;
const questionId = process.env.RUBRIC_SPLIT_QUESTION_ID;
test.skip(!testId || !questionId, "requires isolated real API and managed runtime stub");
const descriptions = (page: Page) => page.getByLabel(/^採点基準候補 .* 本文$/);
const points = (page: Page) => page.getByLabel(/^採点基準候補 .* の配点$/);
const cards = (page: Page) => page.locator(".rubric-candidate-edit");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name: "ログイン"}).click();
  await expect(page).not.toHaveURL(/\/login/);
  if (process.env.RUBRIC_INSECURE_ORIGIN === "1") {
    expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
    expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe("undefined");
  }
}
async function open(page: Page, draftId?: string) {
  if (!draftId) {
    const materials = await (await page.request.get(`/api/v1/tests/${testId}/materials`)).json();
    const created = await page.request.post(`/api/v1/tests/${testId}/model-answer-imports`, {data: {material_id: materials[0].id}});
    expect(created.ok()).toBeTruthy(); draftId = (await created.json()).id;
  }
  await page.goto(`/model-answer-import-reviews/${draftId}`);
  await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  await expect(descriptions(page)).toHaveCount(1);
  return draftId!;
}
async function snapshot(page: Page) {
  return cards(page).evaluateAll(elements => elements.map(element => ({
    id: element.getAttribute("data-candidate-id"),
    text: (element.querySelector("textarea") as HTMLTextAreaElement).value,
    points: (element.querySelector('input[type="number"]') as HTMLInputElement).value,
  })));
}
async function save(page: Page, draftId: string) {
  const result = page.waitForResponse(response => response.request().method() === "PUT" && response.url().endsWith(draftId));
  await page.getByRole("button", {name: "下書き保存"}).click();
  const response = await result; expect(response.status()).toBe(200); return response.json();
}
async function cursor(page: Page, offset: number) {
  await descriptions(page).first().evaluate((element, position) => {
    const control = element as HTMLTextAreaElement; control.focus(); control.setSelectionRange(position, position);
  }, offset);
}

test("rubric buttons update IDs, order, points and persisted state on non-loopback HTTP", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  let splitCalls = 0;
  page.on("request", request => { if (request.url().endsWith("/split-suggest")) splitCalls++; });
  await page.setViewportSize({width: 1100, height: 850});
  await login(page); errors.length = 0; const draftId = await open(page);
  const initial = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draftId}`)).json();
  const preview = page.getByRole("region", {name: "採点基準の分割案"});
  await descriptions(page).first().fill("First criterion. Second criterion.");
  const before = await snapshot(page);
  for (const offset of [0, before[0].text.length]) {
    await cursor(page, offset); await page.getByRole("button", {name: "カーソルの位置で分割"}).click();
    await expect(cards(page).first().getByRole("alert")).toContainText("先頭・末尾");
    await expect(preview).toHaveCount(0); expect(await snapshot(page)).toEqual(before);
  }
  await descriptions(page).first().fill("   Meaningful text.");
  await cursor(page, 3); await page.getByRole("button", {name: "カーソルの位置で分割"}).click();
  await expect(preview).toHaveCount(0);
  await descriptions(page).first().fill(before[0].text);
  await cursor(page, 17); await page.getByRole("button", {name: "カーソルの位置で分割"}).click();
  await expect(cards(page).first().getByRole("region", {name: "採点基準の分割案"})).toBeVisible();
  await expect(preview).toHaveCount(1);
  await page.getByRole("button", {name: "キャンセル", exact: true}).click();
  expect(await snapshot(page)).toEqual(before);
  await cursor(page, 17); await page.getByRole("button", {name: "カーソルの位置で分割"}).click();
  await page.getByRole("button", {name: "この分割案を適用"}).click();
  expect(errors).toEqual([]); await expect(descriptions(page)).toHaveCount(2);
  const split = await snapshot(page);
  expect(split.map(item => item.text)).toEqual(["First criterion.", "Second criterion."]);
  expect(new Set(split.map(item => item.id)).size).toBe(2); expect(split.map(item => item.id)).not.toContain(before[0].id);
  await expect(descriptions(page).first()).toBeFocused();
  expect(splitCalls).toBe(0);
  const saved = await save(page, draftId); expect(saved.revision).toBeGreaterThan(initial.revision);
  await page.reload(); await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  expect(await snapshot(page)).toEqual(split);
  await page.getByRole("button", {name: "分割・追加を元に戻す"}).click();
  expect(await snapshot(page)).toEqual(before);

  await page.getByRole("button", {name: "下に採点基準を追加"}).first().click();
  await expect(descriptions(page)).toHaveCount(2); await expect(descriptions(page).nth(1)).toBeFocused();
  const added = await snapshot(page); expect(added[1].text).toBe(""); expect(added[1].points).toBe("");
  expect(added[0]).toEqual(before[0]); expect(added[1].id).not.toBe(before[0].id);
  await descriptions(page).nth(1).fill("Added criterion."); await points(page).nth(1).fill("3");
  const addedState = await snapshot(page); const addSaved = await save(page, draftId);
  const manual = addSaved.entries.flatMap((entry: {rubric_edits?: Array<{id: string; provenance: {manual_add?: boolean}}>}) => entry.rubric_edits || []).find((item: {id: string}) => item.id === added[1].id);
  expect(manual.provenance.manual_add).toBe(true);
  await page.reload(); await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  expect(await snapshot(page)).toEqual(addedState);
  await page.getByRole("button", {name: "分割・追加を元に戻す"}).click(); expect(await snapshot(page)).toEqual(before);

  await page.getByRole("button", {name: "複製して下に追加"}).first().click();
  await expect(descriptions(page)).toHaveCount(2); await expect(descriptions(page).nth(1)).toBeFocused();
  const copy = await snapshot(page); expect(copy[1].text).toBe(before[0].text); expect(copy[1].points).toBe(before[0].points);
  expect(copy[1].id).not.toBe(before[0].id);
  await descriptions(page).nth(1).fill("Edited duplicate."); const copyState = await snapshot(page);
  const copySaved = await save(page, draftId);
  const duplicate = copySaved.entries.flatMap((entry: {rubric_edits?: Array<{id: string; provenance: {manual_duplicate_from?: string}}>}) => entry.rubric_edits || []).find((item: {id: string}) => item.id === copy[1].id);
  expect(duplicate.provenance.manual_duplicate_from).toBe(before[0].id);
  await page.reload(); await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  expect(await snapshot(page)).toEqual(copyState);
  await page.getByRole("button", {name: "分割・追加を元に戻す"}).click(); expect(await snapshot(page)).toEqual(before);
  expect(splitCalls).toBe(0);

  await descriptions(page).first().fill("5 points: First criterion. 5 points: Second criterion.");
  // Delay transport only; request still goes through the actual API and managed runtime.
  await page.route("**/split-suggest", async route => { await new Promise(resolve => setTimeout(resolve, 300)); await route.continue(); });
  const proposedResponse = page.waitForResponse(response => response.url().endsWith("/split-suggest"));
  await page.getByRole("button", {name: "LLMで分割を試す"}).click();
  await expect(cards(page).first().getByRole("status")).toContainText("分割案を作成しています");
  await expect(cards(page).first()).toHaveAttribute("aria-busy", "true");
  expect((await proposedResponse).status()).toBe(200);
  await expect(cards(page).first().getByRole("region", {name: "採点基準の分割案"})).toBeVisible();
  await page.getByRole("button", {name: "この分割案を適用"}).click();
  await expect(descriptions(page)).toHaveCount(2); const llmSplit = await snapshot(page);
  expect(llmSplit.map(item => item.points)).toEqual(["5", "5"]); expect(splitCalls).toBe(1);
  await save(page, draftId); await page.reload(); await page.getByLabel("編集対象").selectOption(`question:${questionId}`);
  expect(await snapshot(page)).toEqual(llmSplit); expect(errors).toEqual([]);
});

test("legacy saved candidates normalize fields before split; failed runtime can retry inline", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error" && !/503|Failed to load resource/.test(message.text())) errors.push(message.text()); });
  await login(page); const draftId = await open(page, process.env.RUBRIC_LEGACY_DRAFT_ID);
  const before = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draftId}`)).json();
  const legacyItem = before.entries.flatMap((entry: {rubric_edits?: Array<{id: string; source_text?: string}>}) => entry.rubric_edits || []).find((item: {id: string}) => item.id === "legacy-rubric-item");
  expect(legacyItem).not.toHaveProperty("source_text");
  const savedResponse = page.waitForResponse(response => response.request().method() === "PUT" && response.url().endsWith(draftId));
  await page.getByRole("button", {name: "LLMで分割を試す"}).click();
  const normalized = await (await savedResponse).json();
  expect(normalized.entries.flatMap((entry: {rubric_edits?: Array<{id: string; source_text?: string}>}) => entry.rubric_edits || []).find((item: {id: string}) => item.id === "legacy-rubric-item").source_text).toBeNull();
  await expect(cards(page).first().getByRole("region", {name: "採点基準の分割案"})).toBeVisible();
  await page.getByRole("button", {name: "この分割案を適用"}).click();
  await expect(descriptions(page)).toHaveCount(2);
  await page.getByRole("button", {name: "分割・追加を元に戻す"}).click();
  await descriptions(page).first().fill("[split_failure] 5 points: First. 5 points: Second.");
  const failing = page.waitForResponse(response => response.url().endsWith("/split-suggest"));
  await page.getByRole("button", {name: "LLMで分割を試す"}).click();
  expect((await failing).status()).toBe(503);
  await expect(cards(page).first().getByRole("alert")).toContainText("元の候補を保持");
  await expect(descriptions(page)).toHaveCount(1); await expect(cards(page).first()).toHaveAttribute("aria-busy", "false");
  await descriptions(page).first().fill("5 points: First. 5 points: Second.");
  await page.getByRole("button", {name: "LLMで分割を試す"}).click();
  await expect(cards(page).first().getByRole("region", {name: "採点基準の分割案"})).toBeVisible();
  await page.getByRole("button", {name: "この分割案を適用"}).click(); await expect(descriptions(page)).toHaveCount(2);
  expect(errors).toEqual([]);
});
