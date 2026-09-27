import { test, expect } from "@playwright/test";
const api = process.env.H2E_API_URL || "http://127.0.0.1:18051/api/v1";
const q1 = "48e6195a-5d0e-4c8c-8ada-a3c67c78c3cc";
test.skip(!process.env.H2E_REAL, "Requires explicit H.2 verification DB authorization");

test("sampleQ1 問題への取り込み内容を確認 → explicit Confirm → persistent 問題への取り込み済み → hierarchy", async ({page, request, browser}) => {
  console.log("Chromium", browser.version());
  const before = await (await request.get(`${api}/tests/70a63c23-f1b1-46b7-852c-046148b6f451/questions`)).json();
  await page.goto(`/question-import-reviews/${q1}`);
  await expect(page.getByRole('heading', {name: '教師による確認', exact: true})).toBeVisible();
  const existing = await (await request.get(`${api}/question-import-reviews/${q1}/confirmation`)).json();
  if (!existing) {
    await page.getByRole('button', {name: '問題への取り込み内容を確認', exact: true}).click();
    const panel = page.getByRole('heading', {name: '問題への取り込み確認'}).locator('..');
    await expect(panel).toContainText('設問 8');
    await expect(panel).toContainText('構造用 2');
    await expect(panel).toContainText('採点対象 6');
    await expect(panel).toContainText('合計点 100');
    await expect(panel).toContainText('取り込み可能');
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: '問題として追加', exact: true}).click();
  }
  await expect(page.locator('.badge-success')).toContainText('問題への取り込み済み');
  await page.reload();
  await expect(page.locator('.badge-success')).toContainText('問題への取り込み済み');
  await expect(page.getByRole('button', {name: '問題として追加', exact: true})).toHaveCount(0);
  await page.getByRole('link', {name: '← 試験の問題画面に戻る'}).click();
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
      await expect(page.getByText(/問題への取り込み済み/)).toBeVisible();
      return;
    }
    await page.getByRole('button', {name:'問題への取り込み内容を確認',exact:true}).click();
    await expect(page.getByRole('heading', {name:'問題への取り込み確認'}).locator('..')).toContainText('native_formula_requires_teacher_edit');
    await expect(page.getByRole('button',{name:'問題として追加',exact:true})).toBeDisabled();
    if (sample === 'sampleQ2') await expect(page.getByRole('heading',{name:'問題への取り込み確認'}).locator('..')).toContainText('合計点 要確認');
    await page.screenshot({path:`test-results/h2e1-${sample}-blocker.png`,fullPage:true});
  });
}
