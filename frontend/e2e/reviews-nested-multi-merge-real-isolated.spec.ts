import { test, expect, type Page } from "@playwright/test";

const ids = JSON.parse(process.env.REVIEW_NESTED_MERGE_IDS || "{}") as Record<string, string>;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!ids.nested || !ids.merge || !email || !password,
  "isolated nested review API is not configured");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function read(page: Page, baseURL: string | undefined, id: string) {
  return (await (await page.request.get(String(baseURL) + "/api/v1/question-import-reviews/" + id)).json());
}

async function saveAndReload(page: Page, baseURL: string | undefined, id: string, before: any) {
  const response = page.waitForResponse(value => value.url().includes(
    "/api/v1/question-import-reviews/" + id + "/revisions") && value.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  const saved = await response;
  expect(saved.status(), await saved.text()).toBe(200);
  await page.reload();
  const after = await read(page, baseURL, id);
  expect(after.current_revision).toBe(before.current_revision + 1);
  expect(after.source_pdf_sha256).toBe(before.source_pdf_sha256);
  expect(after.regions).toEqual(before.regions);
  return after;
}

test("nested question split supports automatic, manual, and unmapped children recursively", async ({ page, baseURL }) => {
  const id = ids.nested;
  await login(page);
  const before = await read(page, baseURL, id);
  const sourceItem = before.automatic_nodes[0].ordered_content.find((item: any) => item.text === "2. Precision");
  const sourceId = sourceItem.source_element_ids[0];
  await page.goto("/question-import-reviews/" + id);
  const tree = page.getByRole("navigation", { name: "設問構成" });
  await tree.getByRole("button", { name: /\(2\)/ }).click();
  await expect(page.getByRole("button", { name: "小問に分割" })).toBeVisible();
  await page.getByLabel("問題文 2").fill("2. Precision（教師が修正）");
  await page.getByLabel("問題文 3").fill("3. Recall（対応なしで分割）");
  await page.getByRole("button", { name: "小問に分割" }).click();

  const preview = page.locator(".review-split-preview");
  await expect(preview.getByLabel("小問名")).toHaveCount(3);
  const candidates = preview.locator("section.review-content-item");
  await expect(candidates.nth(0).getByText("元資料との対応: 自動確認済み")).toBeVisible();
  await expect(candidates.nth(1).getByText("元資料との対応: 要対応")).toBeVisible();
  await expect(candidates.nth(2).getByText("元資料との対応: 要対応")).toBeVisible();

  const manual = candidates.nth(1);
  await manual.getByLabel(new RegExp(sourceId)).check();
  await manual.getByRole("button", { name: "選択した項目を対応付ける" }).click();
  await expect(manual.getByText("元資料との対応: 手動確認済み")).toBeVisible();
  const unmapped = candidates.nth(2);
  await unmapped.getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
  const dialog = unmapped.getByRole("dialog", { name: "対応情報なしで分割する確認" });
  await dialog.getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
  await expect(unmapped.getByText("元資料との対応: 対応情報なしで分割")).toBeVisible();
  const split = preview.getByRole("button", { name: "この内容で分割" });
  await expect(split).toBeEnabled();
  await split.click();

  let after = await saveAndReload(page, baseURL, id, before);
  let nodes = after.snapshot.nodes as any[];
  const parent = nodes.find(node => node.label.raw === "(2)");
  const children = nodes.filter(node => node.parent_key === parent.stable_key);
  expect(children.map(node => node.source_mapping_decision))
    .toEqual(["automatic", "teacher_manual_mapping", "teacher_unmapped_override"]);
  expect(children.map(node => node.label.raw)).toEqual(["1.", "2.", "3."]);
  expect(children.every(node => node.depth === 2)).toBe(true);
  expect(parent.ordered_content).toHaveLength(0);
  expect(parent.source_mapping_decision).toBeUndefined();
  const manuallyMapped = children[1].ordered_content.flatMap((item: any) => item.merged_source_segments || []);
  expect(manuallyMapped.some((segment: any) => segment.source_element_ids?.includes(sourceId))).toBe(true);
  expect(manuallyMapped.every((segment: any) => !segment.source_slice)).toBe(true);
  expect(children[2].ordered_content.every((item: any) => item.type !== "text" ||
    (!item.source_slice && !item.source_element_ids && !(item.merged_source_segments || []).some(
      (segment: any) => segment.type !== "formula_region")))).toBe(true);

  // Split the first nested child once more. Its source text was edited, so the
  // teacher explicitly chooses the no-detailed-mapping path for both leaves.
  await page.getByRole("navigation", { name: "設問構成" }).getByRole("button", { name: /^1\./ }).click();
  await page.getByLabel("問題文 1").fill("1. Term A\n2. Term B");
  await page.getByRole("button", { name: "小問に分割" }).click();
  const deeper = page.locator(".review-split-preview");
  await expect(deeper.getByLabel("小問名")).toHaveCount(2);
  for (const candidate of await deeper.locator("section.review-content-item").all()) {
    await candidate.getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
    await candidate.getByRole("dialog", { name: "対応情報なしで分割する確認" })
      .getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
  }
  await expect(deeper.getByRole("button", { name: "この内容で分割" })).toBeEnabled();
  await deeper.getByRole("button", { name: "この内容で分割" }).click();
  after = await saveAndReload(page, baseURL, id, after);
  nodes = after.snapshot.nodes;
  const grandchild = nodes.find(node => node.stable_key === children[0].stable_key);
  const greatGrandchildren = nodes.filter(node => node.parent_key === grandchild.stable_key);
  expect(greatGrandchildren).toHaveLength(2);
  expect(greatGrandchildren.map(node => node.depth)).toEqual([3, 3]);
  expect(greatGrandchildren.every(node => node.source_mapping_decision === "teacher_unmapped_override")).toBe(true);

  // Editing a deepest-level question follows the normal editor and revision flow.
  const deepestQuestions = page.getByRole("navigation", { name: "設問構成" }).locator('button[style*="66px"]');
  await expect(deepestQuestions).toHaveCount(2);
  await deepestQuestions.last().click();
  await page.getByLabel("問題文 1").fill("2. Term Bを修正");
  const edited = await saveAndReload(page, baseURL, id, after);
  expect(edited.snapshot.nodes.some((node: any) => node.depth === 3 &&
    node.ordered_content.some((item: any) => item.type === "text" && item.text.includes("Term Bを修正")))).toBe(true);
});

test("multi-text merge preserves source ranges and cannot cross a formula", async ({ page, baseURL }) => {
  const id = ids.merge;
  await login(page);
  const before = await read(page, baseURL, id);
  const sourceItems = before.snapshot.nodes[0].ordered_content as any[];
  expect(sourceItems.slice(0, 4).every(item => item.type === "text")).toBe(true);
  expect(sourceItems[4].type).toBe("formula_region");
  const expectedText = sourceItems.slice(0, 4).map(item => item.text).join("");
  const expectedSlices = sourceItems.slice(0, 4).map(item => item.source_slice);
  await page.goto("/question-import-reviews/" + id);
  await page.getByRole("button", { name: "内容をまとめて結合" }).click();
  const checkbox = (number: number) => page.getByLabel("まとめて結合する 問題文 " + number);
  await checkbox(2).check();
  await checkbox(5).check();
  const invalidSelection = page.getByRole("button", { name: "選択した2件の内容を結合" });
  await expect(invalidSelection).toBeDisabled();
  await expect(page.getByText(/連続する内容だけを結合できます/)).toBeVisible();
  await checkbox(2).uncheck();
  await checkbox(5).uncheck();

  for (const number of [1, 2, 3, 4]) await checkbox(number).check();
  const merge = page.getByRole("button", { name: "選択した4件の内容を結合" });
  await expect(merge).toBeEnabled();
  await merge.click();
  await expect(page.getByLabel("問題文 1")).toHaveValue(expectedText);
  await expect(page.getByLabel("問題文 2")).toHaveValue(sourceItems[5].text);
  await expect(page.locator('[data-content-type="formula"]')).toHaveCount(1);

  const after = await saveAndReload(page, baseURL, id, before);
  const content = after.snapshot.nodes[0].ordered_content as any[];
  expect(content.map(item => item.type)).toEqual(["text", "formula_region", "text", "figure_region"]);
  expect(content[0].text).toBe(expectedText);
  const mergedSlices = [content[0].source_slice, ...(content[0].merged_source_segments || [])
    .map((segment: any) => segment.source_slice)].filter(Boolean);
  expect(mergedSlices).toEqual(expectedSlices);
});
