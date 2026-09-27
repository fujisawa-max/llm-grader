import { test, expect } from "@playwright/test";

test("teacher workspace tabs use Japanese labels in an isolated environment", async ({ page }) => {
  const testId = process.env.JUI7C_AUDIT_TEST_ID;
  test.skip(!testId, "Set JUI7C_AUDIT_TEST_ID for an isolated test database");

  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.JUI7C_TEACHER_EMAIL || "teacher-jui7@example.invalid");
  await page.getByLabel("パスワード", { exact: true }).fill(process.env.JUI7C_TEACHER_PASSWORD || "DemoTeacherChanged123!");
  await page.getByRole("button", { name: "ログイン", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(`/tests/${testId}`);
  const tabs = page.getByRole("navigation", { name: "テスト準備" });
  for (const name of ["概要", "問題", "模範解答", "採点基準", "学生答案", "採点", "結果", "採点方針", "サンプル答案"]) {
    await tabs.getByRole("button", { name, exact: true }).click();
    await expect(tabs.getByRole("button", { name, exact: true })).toHaveClass(/active/);
    const visibleText = await page.locator("body").evaluate(element => (element as HTMLElement).innerText);
    expect(visibleText, `${name}タブの表示`).not.toMatch(/Approved Rubric|current authoritative|Teacher Review|Question selector|Student Answer Reconstruction|second_semester|READY_FOR_GRADING|REVIEW_REQUIRED/);
  }
  await page.goto(`/tests/${testId}/grading/review`);
  await expect(page.getByRole("heading", { name: "採点結果の確認" })).toBeVisible();
  await page.goto(`/tests/${testId}/grading/regrade-queue`);
  await expect(page.getByRole("heading", { name: "再採点依頼", exact: true, level: 1 })).toBeVisible();
});
