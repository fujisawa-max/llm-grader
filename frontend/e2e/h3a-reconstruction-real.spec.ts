import { test, expect } from "@playwright/test";

const testId = "5e9b6804-94eb-418b-8e09-7f7493fa6cce";

test("H.3-A reconstruction inspection is read-only", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const response = await page.request.fetch(`http://127.0.0.1:18093${url.pathname}${url.search}`, {
      method: request.method(), headers: request.headers(),
      data: request.method() === "GET" ? undefined : request.postData() || undefined,
    });
    await route.fulfill({ response });
  });
  await page.goto(`/tests/${testId}?section=students`);
  await expect(page.getByRole("heading", { name: "Student Answer Reconstruction" })).toBeVisible();
  await expect(page.getByText(/Reconstruction run未実行/)).toBeVisible();
  await expect(page.getByText(/ModelAnswer、Rubric、採点はこの画面には入りません/)).toBeVisible();
  await page.waitForTimeout(300);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
