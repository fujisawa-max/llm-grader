import {expect, type Page} from "@playwright/test";

export async function assertDesktopReviewLayout(page: Page, selectorLabel: string) {
  const shell = page.locator(".review-workspace-shell");
  const actions = shell.locator(".review-workspace-actions");
  const source = shell.locator(".review-workspace-source");
  const editor = shell.locator(".review-workspace-editor");
  const selector = page.getByLabel(selectorLabel, {exact:true});
  await expect(selector).toHaveCount(1);
  await expect(editor.getByLabel(selectorLabel, {exact:true})).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect(actions).toBeInViewport();
  await expect(selector).toBeInViewport();
  await expect(page.getByRole("heading", {level:1}).first()).not.toBeInViewport();
  const header = (await page.locator(".header").boundingBox())!;
  expect((await actions.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height);
  await expect.poll(async () => {
    const bar = (await actions.boundingBox())!;
    const pdf = (await source.boundingBox())!;
    const target = (await shell.locator(".review-workspace-selector").boundingBox())!;
    return pdf.y >= bar.y + bar.height && target.y >= bar.y + bar.height;
  }).toBe(true);
  const pdf = (await source.boundingBox())!;
  const body = (await editor.boundingBox())!;
  expect(pdf.x + pdf.width).toBeLessThanOrEqual(body.x);
  expect(pdf.width / (pdf.width + body.width)).toBeGreaterThan(.35);
  expect(pdf.width / (pdf.width + body.width)).toBeLessThan(.45);
  expect(pdf.height).toBeGreaterThan(page.viewportSize()!.height * .6);
  const viewport = source.locator(".pdf-pane-viewport,.review-preview-viewport");
  expect((await viewport.boundingBox())!.height).toBeGreaterThan(page.viewportSize()!.height * .5);
  expect(pdf.y + pdf.height).toBeLessThanOrEqual(page.viewportSize()!.height);
}

export async function assertNarrowReviewLayout(page: Page, selectorLabel: string) {
  await page.setViewportSize({width:700,height:900});
  const source = page.locator(".review-workspace-source");
  await expect.poll(() => source.evaluate(element => getComputedStyle(element).position)).toBe("static");
  const pdf = (await source.boundingBox())!;
  const editor = (await page.locator(".review-workspace-editor").boundingBox())!;
  expect(pdf.y + pdf.height).toBeLessThanOrEqual(editor.y);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect(page.getByLabel(selectorLabel, {exact:true})).toHaveCount(1);
  await expect(page.getByLabel(selectorLabel, {exact:true})).toBeInViewport();
  await expect(page.locator(".review-workspace-actions")).toBeInViewport();
  await page.setViewportSize({width:1920,height:1080});
}
