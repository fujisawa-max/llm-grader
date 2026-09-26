import { test, expect } from "@playwright/test";

test.describe("instructor workflow foundation", () => {
  test("navigates and creates course, offering, test, and question", async ({ page }) => {
    const consoleErrors: string[] = [];
    const requestFailures: string[] = [];
    page.on("console", msg => {
      if (msg.type() === "error" && !msg.location().url.endsWith("/favicon.ico")) consoleErrors.push(msg.text());
    });
    page.on("pageerror", err => consoleErrors.push(err.message));
    page.on("requestfailed", req => {
      const failure = req.failure()?.errorText || "failed";
      const isExpectedRscAbort = req.url().includes("_rsc=") && failure.includes("ERR_ABORTED");
      if (!isExpectedRscAbort) requestFailures.push(`${req.url()} ${failure}`);
    });

    await page.goto("/");
    await expect(page.getByRole("link", { name: "科目", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/screenshots/home.png", fullPage: true });
    await page.getByRole("link", { name: "科目", exact: true }).click();
    await expect(page.getByRole("heading", { name: "科目", exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/screenshots/courses.png", fullPage: true });

    await page.getByRole("button", { name: "科目を作成" }).click();
    await page.getByLabel("科目名 *").fill("Phase H E2E Test Course");
    await page.getByLabel("科目コード").fill("PHASE-H-E2E");
    await page.getByLabel("説明").fill("headless browser verification");
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByRole("link", { name: "Phase H E2E Test Course" }).last()).toBeVisible();
    await page.getByRole("link", { name: "Phase H E2E Test Course" }).last().click();
    await expect(page.getByText("開講一覧")).toBeVisible();
    await page.screenshot({ path: "test-results/screenshots/course-detail.png", fullPage: true });

    await page.getByRole("button", { name: "開講を作成" }).last().click();
    await page.getByLabel("年度 *").fill("2026");
    await page.getByLabel("学期 *").selectOption("second_semester");
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByRole("link", { name: /2026年度/ })).toBeVisible();
    const offeringLink = page.getByRole("link", { name: /2026年度/ }).last();
    await offeringLink.click();
    await expect(page).toHaveURL(/\/offerings\//);

    await page.getByRole("button", { name: "テストを作成" }).last().click();
    await page.getByLabel("テスト名 *").fill("Phase H E2E Test");
    await page.getByLabel("合計点 *").fill("100");
    await page.getByRole("button", { name: "保存" }).click();
    const testLink = page.getByRole("link", { name: "Phase H E2E Test", exact: true });
    await expect(testLink).toBeVisible();
    const testHref = await testLink.getAttribute("href");
    expect(testHref).toMatch(/^\/tests\//);
    await page.goto(new URL(testHref!, page.url()).toString());
    await expect(page.getByRole("heading", { name: "Phase H E2E Test" })).toBeVisible();
    await expect(page.getByText("準備が必要です")).toBeVisible();
    await page.screenshot({ path: "test-results/screenshots/test-workspace.png", fullPage: true });

    await page.getByRole("button", { name: "問題", exact: true }).click();
    await page.getByRole("button", { name: "問題を追加" }).click();
    const questionForm = page.locator("form").filter({ hasText: "問題番号" });
    await questionForm.locator("input").nth(0).fill("1");
    await questionForm.locator("textarea").fill("x + 1 = 2 を解きなさい");
    await questionForm.locator('input[type="number"]').fill("10");
    await page.getByRole("button", { name: "保存" }).click();
    await expect(page.getByRole("cell", { name: "x + 1 = 2 を解きなさい", exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Phase H E2E Test" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "x + 1 = 2 を解きなさい", exact: true })).toBeVisible();
    const directUrl = page.url().split("?")[0];
    await page.goto(directUrl);
    await expect(page.getByText("採点準備")).toBeVisible();
    await expect(page.getByRole("link", { name: "科目" }).first()).toBeVisible();

    expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
    expect(requestFailures, requestFailures.join("\n")).toEqual([]);
  });

  test("missing resource is shown as an error state", async ({ page }) => {
    await page.goto("/tests/00000000-0000-0000-0000-000000000000");
    await expect(page.locator('[role="alert"].error')).toBeVisible();
    await expect(page.getByText(/not found|データが見つかりません|通信に失敗しました/)).toBeVisible();
  });
});
