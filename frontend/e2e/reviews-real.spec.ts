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
  await expect(page.getByRole("heading", { name: "Teacher Review", exact: true })).toBeVisible();
  const preview = page.getByAltText("原PDF 1ページ");
  await expect(preview).toBeVisible();
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.locator(".teacher-review [role=alert]")).toHaveCount(0);
  return info;
}
async function edit(page: Page) {
  const reopen = page.getByRole("button", { name: "新Revisionで編集を再開" });
  if (await reopen.isVisible()) await reopen.click();
}
async function save(page: Page) {
  const response = page.waitForResponse(r => r.url().endsWith("/revisions") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Revisionを保存", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByText("未保存の変更", { exact: true })).toHaveCount(0);
}
async function reviewed(page: Page) {
  const response = page.waitForResponse(r => r.url().endsWith("/mark-reviewed"));
  await page.getByRole("button", { name: "Mark Reviewed", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator("header .badge")).toHaveText("reviewed");
}

test("sampleQ1 native-only page, tree, score, save and reviewed", async ({ page }) => {
  const info = await load(page, "sampleQ1");
  await expect(page.getByRole("navigation", { name: "Question tree" }).getByRole("button")).toHaveCount(8);
  await expect(page.getByLabel("Review summary")).toContainText("Total candidate 100");
  await page.getByRole("navigation", { name: "Question tree" }).getByRole("button", { name: /q3$/, exact: false }).click();
  await expect(page.locator("rect[data-source-id=q3]")).not.toHaveCount(0);
  await expect(page.getByLabel("Score semantics")).toHaveValue("each_child");
  await expect(page.getByLabel("Score points")).toHaveValue("10");
  await edit(page); await save(page); await reviewed(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ1.png", fullPage: true });
  const result = await page.request.get(`/api/v1/question-import-reviews/${info.review_id}`);
  expect((await result.json() as ReviewDocument).snapshot.vision_pin.results).toHaveLength(0);
  await page.getByRole("link", { name: "← Test Workspace / Questions" }).click();
  await expect(page.getByRole("heading", { name: "Question Import Draft / Teacher Review" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reviewを再開" })).toBeVisible();
});

test("sampleQ2 formula, warnings, all node operations, reload and real stale-tab conflict", async ({ page, context }) => {
  test.setTimeout(60_000);
  const info = await load(page, "sampleQ2");
  await edit(page);
  await page.getByRole("navigation", { name: "Question tree" }).getByRole("button", { name: /q1\.1/ }).click();
  await page.getByRole("button", { name: "formula-0001", exact: true }).click();
  await expect(page.locator("rect[data-source-id=formula-0001]")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Native evidence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vision candidate" })).toBeVisible();
  await expect(page.getByLabel("Evidence warnings")).toContainText("native_vision_disagreement");
  await expect(page.getByLabel("Evidence warnings")).toContainText("reasoning_output_requires_review");
  await page.getByText("Raw Vision response（読み取り専用）").click();
  await expect(page.getByTestId("raw-vision-output")).toContainText("reasoning_content");
  await page.getByLabel("formula-0001 decision").selectOption("teacher_edit");
  await page.getByLabel("Teacher transcription", { exact: true }).fill("2x^3 - 21x^2 + 69x - 70 = 0");
  await page.getByLabel("Teacher note", { exact: true }).fill("H.2-D.1 browser teacher_edit validation");
  await page.getByRole("combobox", { name: /state$/ }).first().selectOption("resolved");
  await save(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ2-formula.png", fullPage: true });
  await page.getByRole("button", { name: "Major questionを追加" }).click();
  await page.getByLabel("Label", { exact: true }).fill("Browser validation node");
  await page.getByLabel("Text 1", { exact: true }).fill("Review node validation only");
  await save(page);
  await page.getByLabel("Parent", { exact: true }).selectOption("q1");
  await save(page);
  await page.getByRole("button", { name: "Move up", exact: true }).click(); await save(page);
  await page.getByRole("button", { name: "Move down", exact: true }).click(); await save(page);
  await page.getByLabel("含める（外すと除外扱い）").uncheck(); await save(page);
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Question tree" }).getByRole("button", { name: /Browser validation node.*Excluded/ })).toBeVisible();
  await page.getByRole("navigation", { name: "Question tree" }).getByRole("button", { name: /q3$/ }).click();
  await page.getByRole("button", { name: "formula-0004", exact: true }).click();
  await expect(page.getByText("Native-only region：比較用PDF cropです。Visionは実行されていません。")).toBeVisible();
  const stale = await context.newPage();
  await load(stale, "sampleQ2");
  await page.getByLabel("Label", { exact: true }).fill("問題３ browser check");
  await save(page);
  await stale.getByLabel("Label", { exact: true }).fill("stale tab edit");
  await stale.getByRole("button", { name: "Revisionを保存", exact: true }).click();
  await expect(stale.locator(".teacher-review [role=alert]")).toContainText("A newer revision exists");
  await stale.screenshot({ path: "test-results/screenshots/h2d1-conflict.png", fullPage: true });
  await stale.close();
  await reviewed(page);
  const final = await (await page.request.get(`/api/v1/question-import-reviews/${info.review_id}`)).json() as ReviewDocument;
  expect(final.snapshot.nodes.find(n => n.source_draft_stable_key === "q1.1")?.formula_decisions["formula-0001"].teacher_transcription).toBe("2x^3 - 21x^2 + 69x - 70 = 0");
});

test("sampleQ3 graph crop, partial Ricoh labels, raw and teacher decision", async ({ page }) => {
  await load(page, "sampleQ3");
  await edit(page);
  await page.getByRole("navigation", { name: "Question tree" }).getByRole("button", { name: /q3$/ }).click();
  await page.getByRole("button", { name: "figure-0001", exact: true }).click();
  await expect(page.getByAltText("figure-0001 original crop")).toBeVisible();
  await expect(page.locator("rect[data-source-id=figure-0001]")).toHaveCount(1);
  await expect(page.getByText("Partial · Needs review")).toBeVisible();
  await expect(page.getByTestId("evidence-panel")).toContainText("structured=false");
  await expect(page.getByTestId("evidence-panel")).toContainText("-2π");
  await page.getByText("Unstructured observation（未確定）").click();
  await page.getByText("Raw Vision response（読み取り専用）").click();
  await expect(page.getByTestId("raw-vision-output")).toContainText('"choices"');
  await page.getByLabel("figure-0001 decision").selectOption("needs_correction");
  await page.getByLabel("Teacher note", { exact: true }).fill("Ricoh partial observationを確認。原PDFを参照する（browser検証）。");
  await save(page);
  await page.screenshot({ path: "test-results/screenshots/h2d1-sampleQ3-graph.png", fullPage: true });
  await reviewed(page);
  await page.setViewportSize({ width: 760, height: 1000 });
  await expect(page.getByAltText("原PDF 1ページ")).toBeVisible();
  const preview = await page.getByRole("region", { name: "原PDFプレビュー" }).boundingBox();
  const tree = await page.getByRole("navigation", { name: "Question tree" }).boundingBox();
  expect(tree!.y).toBeGreaterThan(preview!.y);
  await page.screenshot({ path: "test-results/screenshots/h2d1-tablet.png", fullPage: true });
});
