import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { ReviewDocument } from "../types/reviews";

// Explicit opt-in: this appends validation revisions to the three sample Reviews.
// It never calls upload, Vision execution, TestQuestion, or grading endpoints.
const auditPath = process.env.REVIEW_AUDIT_PATH;
const audit: { samples: Record<string, { review_id: string; test_id: string }> } = auditPath ? JSON.parse(readFileSync(auditPath, "utf8")) : { samples: {} };
test.skip(!auditPath, "Set REVIEW_AUDIT_PATH to opt into existing sample Review validation");

async function load(page: Page, sample: string) {
  const info = audit.samples[sample];
  await page.goto(`/question-import-reviews/${info.review_id}`);
  await expect(page.getByRole("heading", { name: "教師による確認", exact: true })).toBeVisible();
  const preview = page.getByAltText("原PDF 1ページ");
  await expect(preview).toBeVisible();
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.locator(".teacher-review [role=alert]")).toHaveCount(0);
  return info;
}
async function edit(page: Page) {
  const reopen = page.getByRole("button", { name: "新しい修正版で編集を再開" });
  if (await reopen.isVisible()) await reopen.click();
}
async function save(page: Page) {
  const response = page.waitForResponse(r => r.url().endsWith("/revisions") && r.request().method() === "POST");
  await page.getByRole("button", { name: "変更を保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByText("未保存の変更", { exact: true })).toHaveCount(0);
}
async function reviewed(page: Page) {
  const response = page.waitForResponse(r => r.url().endsWith("/mark-reviewed"));
  await page.getByRole("button", { name: "確認済みにする", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator("header .badge")).toHaveText("確認済み");
}

test("sampleQ1 native-only page, tree, score, save and reviewed", async ({ page }) => {
  const info = await load(page, "sampleQ1");
  await expect(page.getByRole("navigation", { name: "設問構成" }).getByRole("button")).toHaveCount(8);
  await expect(page.getByLabel("確認状況")).toContainText("合計点候補 100");
  await page.getByRole("navigation", { name: "設問構成" }).locator("button[data-source-key=q3]").click();
  await expect(page.locator("rect[data-source-id=q3]")).not.toHaveCount(0);
  await expect(page.getByLabel("配点の扱い")).toHaveValue("each_child");
  await expect(page.getByLabel("配点", { exact: true })).toHaveValue("10");
  await edit(page); await save(page); await reviewed(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ1.png", fullPage: true });
  const result = await page.request.get(`/api/v1/question-import-reviews/${info.review_id}`);
  expect((await result.json() as ReviewDocument).snapshot.vision_pin.results).toHaveLength(0);
  await page.getByRole("link", { name: "← 試験の問題画面に戻る" }).click();
  await expect(page.getByRole("heading", { name: "問題の読み取り確認" })).toBeVisible();
  await expect(page.getByRole("button", { name: "前回の解析結果を編集" })).toBeVisible();
});

test("sampleQ2 formula, warnings, all node operations, reload and real stale-tab conflict", async ({ page, context }) => {
  test.setTimeout(60_000);
  const info = await load(page, "sampleQ2");
  await edit(page);
  await page.getByRole("navigation", { name: "設問構成" }).locator("button[data-source-key=\"q1.1\"]").click();
  await page.locator("button[data-region-id=formula-0001]").last().click();
  await expect(page.locator("rect[data-source-id=formula-0001]")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "PDFから読み取った内容" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "画像解析による候補" })).toBeVisible();
  await expect(page.getByLabel("読み取りに関する確認事項")).toContainText("native_vision_disagreement");
  await expect(page.getByLabel("読み取りに関する確認事項")).toContainText("reasoning_output_requires_review");
  await page.getByText("画像解析の元データ（技術情報）").click();
  await expect(page.getByTestId("raw-vision-output")).toContainText("reasoning_content");
  await page.getByLabel("読み取り内容の採用方法").selectOption("teacher_edit");
  await page.getByLabel("教師が確認した数式", { exact: true }).fill("2x^3 - 21x^2 + 69x - 70 = 0");
  await page.getByLabel("教師メモ", { exact: true }).fill("H.2-D.1 browser teacher_edit validation");
  await page.getByRole("combobox", { name: /の状態$/ }).first().selectOption("resolved");
  await save(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ2-formula.png", fullPage: true });
  await page.getByRole("button", { name: "大問を追加" }).click();
  await page.getByLabel("設問番号・見出し", { exact: true }).fill("Browser validation node");
  await page.getByLabel("問題文 1", { exact: true }).fill("Review node validation only");
  await save(page);
  await page.getByLabel("設問の階層", { exact: true }).selectOption("q1");
  await save(page);
  await page.getByRole("button", { name: "上へ移動", exact: true }).click(); await save(page);
  await page.getByRole("button", { name: "下へ移動", exact: true }).click(); await save(page);
  await page.getByLabel("この設問を含める（チェックを外すと除外）").uncheck(); await save(page);
  await page.reload();
  await expect(page.getByRole("navigation", { name: "設問構成" }).getByRole("button", { name: /Browser validation node.*除外/ })).toBeVisible();
  await page.getByRole("navigation", { name: "設問構成" }).locator("button[data-source-key=q3]").click();
  await page.locator("button[data-region-id=formula-0004]").last().click();
  await expect(page.getByText("元の問題用紙から切り出した範囲です。画像解析の候補はありません。")).toBeVisible();
  const stale = await context.newPage();
  await load(stale, "sampleQ2");
  await page.getByLabel("設問番号・見出し", { exact: true }).fill("問題３ browser check");
  await save(page);
  await stale.getByLabel("設問番号・見出し", { exact: true }).fill("stale tab edit");
  await stale.getByRole("button", { name: "変更を保存", exact: true }).click();
  await expect(stale.locator(".teacher-review [role=alert]")).toContainText("別の画面で新しい修正版が保存されています");
  await stale.screenshot({ path: "test-results/screenshots/h2d1-conflict.png", fullPage: true });
  await stale.close();
  await reviewed(page);
  const final = await (await page.request.get(`/api/v1/question-import-reviews/${info.review_id}`)).json() as ReviewDocument;
  expect(final.snapshot.nodes.find(n => n.source_draft_stable_key === "q1.1")?.formula_decisions["formula-0001"].teacher_transcription).toBe("2x^3 - 21x^2 + 69x - 70 = 0");
});

test("sampleQ3 graph crop, partial Ricoh labels, raw and teacher decision", async ({ page }) => {
  await load(page, "sampleQ3");
  await edit(page);
  await page.getByRole("navigation", { name: "設問構成" }).locator("button[data-source-key=q3]").click();
  await page.locator("button[data-region-id=figure-0001]").last().click();
  await expect(page.getByAltText("図の原文範囲")).toBeVisible();
  await expect(page.locator("rect[data-source-id=figure-0001]")).toHaveCount(1);
  await expect(page.getByText("一部のみ読み取り済み・要確認")).toBeVisible();
  await expect(page.getByTestId("evidence-panel")).toContainText("一部のみ読み取り済み・要確認");
  await expect(page.getByTestId("evidence-panel")).toContainText("-2π");
  await page.getByText("画像解析の技術情報").click();
  await page.getByText("画像解析の元データ（技術情報）").click();
  await expect(page.getByTestId("raw-vision-output")).toContainText('"choices"');
  await page.getByLabel("確認結果").selectOption("needs_correction");
  await page.getByLabel("教師メモ", { exact: true }).fill("Ricoh partial observationを確認。原PDFを参照する（browser検証）。");
  await save(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ3-graph.png", fullPage: true });
  await reviewed(page);
  await page.setViewportSize({ width: 760, height: 1000 });
  await expect(page.getByAltText("原PDF 1ページ")).toBeVisible();
  const preview = await page.getByRole("region", { name: "原PDFプレビュー" }).boundingBox();
  const tree = await page.getByRole("navigation", { name: "設問構成" }).boundingBox();
  expect(tree!.y).toBeGreaterThan(preview!.y);
  await page.screenshot({ path: "test-results/screenshots/h2d1-tablet.png", fullPage: true });
});
