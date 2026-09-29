import { test, expect, type Page } from "@playwright/test";

const ids = JSON.parse(process.env.REVIEW_SPLIT_MAPPING_IDS || "{}") as Record<string, string>;
const email = process.env.REVIEW_VALIDATION_EMAIL;
const password = process.env.REVIEW_VALIDATION_PASSWORD;
test.skip(!ids.automatic || !ids.manual || !ids.override || !email || !password,
  "isolated review API is not configured");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function review(page: Page, baseURL: string | undefined, id: string) {
  return (await (await page.request.get(`${baseURL}/api/v1/question-import-reviews/${id}`)).json());
}

async function saveAndReload(page: Page, baseURL: string | undefined, id: string, before: any) {
  const response = page.waitForResponse(value => value.url().includes(`/api/v1/question-import-reviews/${id}/revisions`) &&
    value.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  const saved = await response;
  expect(saved.status(), await saved.text()).toBe(200);
  await page.reload();
  const after = await review(page, baseURL, id);
  expect(after.current_revision).toBe(before.current_revision + 1);
  expect(after.source_pdf_sha256).toBe(before.source_pdf_sha256);
  expect(after.regions).toEqual(before.regions);
  return after;
}

test("fragmented ordered text is detected and automatically split through the real API", async ({ page, baseURL }) => {
  const id = ids.automatic;
  await login(page);
  const before = await review(page, baseURL, id);
  await page.goto(`/question-import-reviews/${id}`);
  await page.getByRole("button", { name: "小問に分割" }).click();
  const preview = page.locator(".review-split-preview");
  await expect(preview.getByRole("heading", { name: "小問への分割候補" })).toBeVisible();
  await expect(preview.getByLabel("小問名")).toHaveCount(3);
  await expect(preview.getByText("元資料との対応: 自動確認済み")).toHaveCount(3);
  const split = preview.getByRole("button", { name: "この内容で分割" });
  await expect(split).toBeEnabled();
  await split.click();
  const after = await saveAndReload(page, baseURL, id, before);
  expect(after.snapshot.nodes).toHaveLength(4);
  expect(after.snapshot.nodes.slice(1).map((node: any) => node.source_mapping_decision))
    .toEqual(["automatic", "automatic", "automatic"]);
  expect(after.snapshot.nodes.slice(1).every((node: any) => Array.isArray(node.ordered_content[0].source_slice))).toBe(true);
  expect(after.snapshot.nodes.slice(1).map((node: any) => node.parent_key))
    .toEqual([after.snapshot.nodes[0].stable_key, after.snapshot.nodes[0].stable_key, after.snapshot.nodes[0].stable_key]);
});

test("ambiguous candidate accepts teacher-selected source elements and persists the mapping", async ({ page, baseURL }) => {
  const id = ids.manual;
  await login(page);
  const before = await review(page, baseURL, id);
  const canonical = before.automatic_nodes[0].ordered_content as { text: string; source_element_ids: string[] }[];
  const expectedSource = canonical.find(item => item.text.includes("元の領域"))!.source_element_ids[0];
  await page.goto(`/question-import-reviews/${id}`);
  await page.getByLabel("問題文 3").fill("（2）クラス1となる領域を斜線で示しなさい。");
  await page.getByRole("button", { name: "小問に分割" }).click();
  const preview = page.locator(".review-split-preview");
  const candidates = preview.locator("section.review-content-item");
  const manualCandidate = candidates.nth(1);
  await expect(manualCandidate.getByText("元資料との対応: 要対応")).toBeVisible();
  await manualCandidate.getByLabel(new RegExp(`\\(2\\)の元読み取り項目.*${expectedSource}.*元の領域`)).check();
  await manualCandidate.getByRole("button", { name: "選択した項目を対応付ける" }).click();
  await expect(manualCandidate.getByText("元資料との対応: 手動確認済み")).toBeVisible();
  const split = preview.getByRole("button", { name: "この内容で分割" });
  await expect(split).toBeEnabled();
  await split.click();
  const after = await saveAndReload(page, baseURL, id, before);
  expect(after.snapshot.nodes[2].source_mapping_decision).toBe("teacher_manual_mapping");
  const refs = after.snapshot.nodes[2].ordered_content.flatMap((item: any) => item.merged_source_segments || []);
  expect(refs.some((item: any) => item.source_element_ids?.includes(expectedSource))).toBe(true);
  expect(refs.every((item: any) => !item.source_slice)).toBe(true);
});

test("ambiguous candidate can be split only after explicit unmapped confirmation", async ({ page, baseURL }) => {
  const id = ids.override;
  await login(page);
  const before = await review(page, baseURL, id);
  await page.goto(`/question-import-reviews/${id}`);
  await page.getByLabel("問題文 4").fill("（3）指定された点のクラスを記入しなさい。");
  await page.getByRole("button", { name: "小問に分割" }).click();
  const preview = page.locator(".review-split-preview");
  const candidate = preview.locator("section.review-content-item").nth(2);
  await expect(candidate.getByText("元資料との対応: 要対応")).toBeVisible();
  await candidate.getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
  const dialog = candidate.getByRole("dialog", { name: "対応情報なしで分割する確認" });
  await expect(dialog).toContainText("元資料上の範囲を自動追跡できません");
  await dialog.getByRole("button", { name: "対応情報なしで分割", exact: true }).click();
  await expect(candidate.getByText("元資料との対応: 対応情報なしで分割")).toBeVisible();
  const split = preview.getByRole("button", { name: "この内容で分割" });
  await expect(split).toBeEnabled();
  await split.click();
  const after = await saveAndReload(page, baseURL, id, before);
  const child = after.snapshot.nodes[3];
  expect(child.source_mapping_decision).toBe("teacher_unmapped_override");
  expect(child.ordered_content.every((item: any) => item.type !== "text" ||
    (!item.source_slice && !item.source_element_ids && !(item.merged_source_segments || []).some(
      (segment: any) => segment.type !== "formula_region")))).toBe(true);
  await page.getByRole("navigation", { name: "設問構成" }).getByRole("button", { name: /\(3\)/ }).click();
  await expect(page.getByText("この小問は元資料との詳細な対応情報なしで作成されています。")).toBeVisible();
});
