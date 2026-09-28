import { test, expect } from "@playwright/test";

const reviewId = process.env.REVIEW_SOURCE_MAPPING_ID;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!reviewId || !email || !password, "isolated source mapping API is not configured");

test("text merge and formula merge retain source slices through split and real API save", async ({ page, baseURL }) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const apiPath = `/api/v1/question-import-reviews/${reviewId}`;
  const read = async () => (await (await page.request.get(`${baseURL}${apiPath}`)).json());
  const before = await read();
  const originalPdf = before.source_pdf_sha256;
  const originalRegions = before.regions;
  await page.goto(`/question-import-reviews/${reviewId}`);

  const formula = page.locator('[data-content-type="formula"]');
  await formula.getByRole("button", { name: "上の問題文とマージ" }).click();
  const text = page.locator('[data-content-type="text"]');
  await text.nth(1).getByRole("button", { name: "上の問題文とマージ" }).click();
  await page.getByRole("button", { name: "小問に分割" }).click();
  await expect(page.getByLabel("小問名")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "この内容で分割" })).toBeEnabled();
  await page.getByRole("button", { name: "この内容で分割" }).click();
  await page.getByLabel("問題文 1").fill("決定境界を描きなさい。（教師が分割後に修正）");

  const saveResponse = page.waitForResponse(response =>
    response.url().includes(`${apiPath}/revisions`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await saveResponse).status()).toBe(200);
  await page.reload();

  const saved = await read();
  const [parent, ...children] = saved.snapshot.nodes;
  expect(children).toHaveLength(3);
  expect(children.map((node: { parent_key: string }) => node.parent_key)).toEqual(Array(3).fill(parent.stable_key));
  expect(children[0].ordered_content[0].text).toBe("決定境界を描きなさい。（教師が分割後に修正）");
  expect(children[1].ordered_content.some((item: { merged_source_segments?: { type?: string }[] }) =>
    item.merged_source_segments?.some(segment => segment.type === "formula_region"))).toBe(true);
  expect(children[2].ordered_content.map((item: { text?: string }) => item.text?.trim()).join(" "))
    .toContain("点Aのクラスを答えなさい。");

  const sourceRanges = new Map<string, [number, number, number][]>();
  for (const node of saved.snapshot.nodes) for (const item of node.ordered_content) {
    if (item.type !== "text") continue;
    if (item.source_slice && item.source_element_ids?.length) {
      const id = item.source_element_ids[0];
      sourceRanges.set(id, [...(sourceRanges.get(id) || []), item.source_slice]);
    }
    for (const segment of item.merged_source_segments || []) {
      if (segment.source_slice && segment.source_element_ids?.length) {
        const id = segment.source_element_ids[0] as string;
        sourceRanges.set(id, [...(sourceRanges.get(id) || []), segment.source_slice as [number, number, number]]);
      }
    }
  }
  for (const ranges of sourceRanges.values()) {
    const ordered = [...ranges].sort((a, b) => a[0] - b[0]);
    expect(ordered.every(range => range[0] >= 0 && range[0] < range[1] && range[1] <= range[2])).toBe(true);
    expect(ordered.slice(1).every((range, index) => ordered[index][1] <= range[0])).toBe(true);
  }
  expect(saved.source_pdf_sha256).toBe(originalPdf);
  expect(saved.regions).toEqual(originalRegions);
});
