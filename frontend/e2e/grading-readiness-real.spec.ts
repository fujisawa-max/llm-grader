import {test, expect} from "@playwright/test";

test.skip(!process.env.H2F_REAL, "Requires the isolated H.2-F validation fixture");
const q1 = "70a63c23-f1b1-46b7-852c-046148b6f451";
const q3 = "8df4ed72-9297-4082-bb21-1fdb6c500557";
const fixture = process.env.H2F_VALIDATION_TEST || "";

test("sampleQ1 hierarchy, structural protection, context and blockers", async ({page}) => {
  await page.goto(`/tests/${q1}?section=answers`);
  await expect(page.getByTestId("grading-summary")).toContainText("Gradable 6");
  await expect(page.getByTestId("grading-summary")).toContainText("Structural 2");
  await expect(page.getByText("Structural — not graded · Model Answer / Rubric not required")).toHaveCount(2);
  const rows = page.locator("tbody tr");
  await rows.nth(0).getByRole("button").click();
  await expect(page.getByRole("button", {name:"模範解答の新しい版を保存"})).toHaveCount(0);
  await rows.nth(1).getByRole("button").click();
  const ctx = page.getByRole("region", {name:"Effective Grading Context"});
  await expect(ctx).toContainText("ancestor");
  await expect(ctx).toContainText("self");
  await page.goto(`/tests/${q1}?section=rubric`);
  await expect(page.getByTestId("grading-summary")).toContainText("Blocked 6");
  await expect(page.getByText("Structural — not graded · Model Answer / Rubric not required")).toHaveCount(2);
  await page.goto(`/tests/${q1}?section=grading`);
  await expect(page.getByRole("button", {name:/採点を開始/})).toBeDisabled();
  await expect(page.locator("code").filter({hasText:"MISSING_MODEL_ANSWER"})).toHaveCount(6);
  await page.screenshot({path:"test-results/h2f-q1-readiness.png",fullPage:true});
});

test("sampleQ3 authoritative figure context and missing associations", async ({page}) => {
  await page.goto(`/tests/${q3}?section=answers`);
  await expect(page.getByTestId("grading-summary")).toContainText("Gradable 3");
  await page.locator("tbody tr").nth(2).getByRole("button").click();
  const ctx = page.getByRole("region", {name:"Effective Grading Context"});
  await expect(ctx).toContainText("Assets 1");
  await expect(ctx.getByRole("link", {name:/Authoritative figure/})).toHaveCount(1);
  await page.screenshot({path:"test-results/h2f-q3-context.png",fullPage:true});
});

test("isolated fixture association edit, retire, restore and READY", async ({page}) => {
  test.skip(!fixture, "Set H2F_VALIDATION_TEST from validation report");
  await page.goto(`/tests/${fixture}?section=answers`);
  await expect(page.getByTestId("grading-summary")).toContainText("Ready 1");
  await page.getByRole("button", {name:"Fixture child",exact:true}).click();
  await expect(page.getByRole("region", {name:"Effective Grading Context"})).toContainText("Synthetic parent context");
  await page.getByRole("button", {name:"現在の模範解答を解除"}).click();
  await expect(page.getByTestId("grading-summary")).toContainText("Blocked 1");
  await page.getByLabel("模範解答本文", {exact:true}).fill("Synthetic E2E fixture response only");
  await page.getByRole("button", {name:"模範解答の新しい版を保存"}).click();
  await expect(page.getByTestId("grading-summary")).toContainText("Ready 1");
  await page.reload();
  await expect(page.getByTestId("grading-summary")).toContainText("Ready 1");
  await page.goto(`/tests/${fixture}?section=grading`);
  await expect(page.getByRole("button", {name:/採点を開始/})).toBeEnabled();
  // Do not execute a grading job or model.
  await page.screenshot({path:"test-results/h2f-fixture-ready.png",fullPage:true});
});
