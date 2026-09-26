import { test, expect } from "@playwright/test";
const api = process.env.H2E_API_URL || "http://127.0.0.1:18051/api/v1";
const q1 = "48e6195a-5d0e-4c8c-8ada-a3c67c78c3cc";
test.skip(!process.env.H2E_REAL, "Requires explicit H.2 verification DB authorization");

test("sampleQ1 Prepare Import → explicit Confirm → persistent Imported → hierarchy", async ({page, request, browser}) => {
  console.log("Chromium", browser.version());
  const before = await (await request.get(`${api}/tests/70a63c23-f1b1-46b7-852c-046148b6f451/questions`)).json();
  await page.goto(`/question-import-reviews/${q1}`);
  await expect(page.getByRole('heading', {name: 'Teacher Review', exact: true})).toBeVisible();
  const existing = await (await request.get(`${api}/question-import-reviews/${q1}/confirmation`)).json();
  if (!existing) {
    await page.getByRole('button', {name: 'Prepare Import', exact: true}).click();
    const panel = page.getByRole('heading', {name: 'Import preflight'}).locator('..');
    await expect(panel).toContainText('nodes 8');
    await expect(panel).toContainText('Structural 2');
    await expect(panel).toContainText('Gradable 6');
    await expect(panel).toContainText('total 100');
    await expect(panel).toContainText('No blockers');
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: 'Confirm & Import', exact: true}).click();
  }
  await expect(page.locator('.badge-success')).toContainText('Imported');
  await page.reload();
  await expect(page.locator('.badge-success')).toContainText('Imported');
  await expect(page.getByRole('button', {name: 'Confirm & Import', exact: true})).toHaveCount(0);
  await page.getByRole('link', {name: '← Test Workspace / Questions'}).click();
  await expect(page.locator('table tbody tr')).toHaveCount(8);
  await expect(page.getByText('Structural', {exact: true})).toHaveCount(2);
  await expect(page.getByText('Gradable', {exact: true})).toHaveCount(6);
  const rows = await (await request.get(`${api}/tests/70a63c23-f1b1-46b7-852c-046148b6f451/questions`)).json();
  expect(rows).toHaveLength(8);
  expect(rows.filter((q: {parent_id: string | null}) => q.parent_id)).toHaveLength(5);
  expect(rows.filter((q: {is_gradable: boolean}) => q.is_gradable).reduce((n: number,q: {max_points: number}) => n+q.max_points,0)).toBe(100);
  if (!existing) expect(rows.length-before.length).toBe(8);
  await page.screenshot({path:'test-results/h2e1-q1-hierarchy.png',fullPage:true});
});

for (const [sample, review] of [['sampleQ2','67ad0e7a-8159-491c-8863-a036b502777b'],['sampleQ3','352e741e-2986-40d3-a457-887f7e6f59a8']]) {
  test(`${sample} retains teacher decisions and displays conservative native blockers`, async ({page}) => {
    await page.goto(`/question-import-reviews/${review}`);
    if (sample === 'sampleQ3') {
      await expect(page.getByText(/Imported/)).toBeVisible();
      return;
    }
    await page.getByRole('button', {name:'Prepare Import',exact:true}).click();
    await expect(page.getByRole('heading', {name:'Import preflight'}).locator('..')).toContainText('native_formula_requires_teacher_edit');
    await expect(page.getByRole('button',{name:'Confirm & Import',exact:true})).toBeDisabled();
    if (sample === 'sampleQ2') await expect(page.getByRole('heading',{name:'Import preflight'}).locator('..')).toContainText('total unresolved');
    await page.screenshot({path:`test-results/h2e1-${sample}-blocker.png`,fullPage:true});
  });
}
