import { test, expect } from "@playwright/test";

const testId = "5e9b6804-94eb-418b-8e09-7f7493fa6cce";

test("H.2-G mapping preview is read-only and shows missing answer blocker", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const upstream = `http://127.0.0.1:18092${url.pathname}${url.search}`;
    const response = await page.request.fetch(upstream, {
      method: request.method(),
      headers: request.headers(),
      data: request.method() === "GET" ? undefined : request.postData() || undefined,
    });
    await route.fulfill({ response });
  });
  await page.goto(`/tests/${testId}?section=grading`);
  await expect(page.getByRole("heading", { name: "Grading Input Mapping" })).toBeVisible();
  await expect(page.getByText(/Mapping:/)).toBeVisible();
  await expect(page.getByText(/Question ID:/).first()).toBeVisible();
  await expect(page.getByText(/Student Answer:/)).toBeVisible();
  await page.getByLabel("Mapping submission").selectOption({ label: "h2g-missing-answer / attempt 2" });
  await expect(page.getByText("MISSING_STUDENT_ANSWER")).toBeVisible();
  await expect(page.getByText("Orphan answers: 0")).toBeVisible();
  await expect(page.getByText(/Effective Context/)).toBeVisible();
});
