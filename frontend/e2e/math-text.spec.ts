import { test, expect } from "@playwright/test";
import { parseMathText } from "../lib/mathText";

test("math parser preserves text, delimiters and escaped dollars", () => {
  expect(parseMathText("既存の文章\n次の行")).toEqual([{ kind: "text", value: "既存の文章\n次の行" }]);
  expect(parseMathText("精度は $P=\\frac{TP}{TP+FP}$ です")).toEqual([
    { kind: "text", value: "精度は " }, { kind: "inline", value: "P=\\frac{TP}{TP+FP}" }, { kind: "text", value: " です" },
  ]);
  expect(parseMathText("前\n$$\\sum_{i=1}^{n}x_i$$\n後")).toEqual([
    { kind: "text", value: "前\n" }, { kind: "display", value: "\\sum_{i=1}^{n}x_i" }, { kind: "text", value: "\n後" },
  ]);
  expect(parseMathText("料金 \\$100 と $未完了")).toEqual([{ kind: "text", value: "料金 $100 と $未完了" }]);
  expect(parseMathText("\\frac{1}{3}")).toEqual([{ kind: "display", value: "\\frac{1}{3}" }]);
  expect(parseMathText("$$\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$$")[0].kind).toBe("display");
});

test("KaTeX rendering and source round-trip in an isolated teacher workspace", async ({ page }) => {
  test.setTimeout(120_000);
  page.setDefaultTimeout(15_000);
  const testId = process.env.MATH1_TEST_ID;
  test.skip(!testId, "Set MATH1_TEST_ID for an isolated database");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("メールアドレス").fill(process.env.MATH1_TEACHER_EMAIL || "teacher-math@example.invalid");
  await page.getByLabel("パスワード", { exact: true }).fill(process.env.MATH1_TEACHER_PASSWORD || "DemoTeacherChanged123!");
  await page.getByRole("button", { name: "ログイン", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(`/tests/${testId}?section=questions`);
  await expect(page.getByRole("button", { name: "問題を追加" })).toBeVisible();
  const source = "次の値を求めなさい。\n$$\\frac{1}{3}+\\frac{1}{6}$$";
  if (await page.locator(".question-table-pane .katex").count() === 0) {
    await page.getByRole("button", { name: "問題を追加" }).click();
    await page.locator(".question-table-pane form .field").filter({ hasText: "問題番号" }).locator("input").fill("1");
    await page.locator(".question-table-pane form .field").filter({ hasText: "問題文" }).locator("textarea").fill(source);
    await page.locator(".question-table-pane form .field").filter({ hasText: "配点" }).locator("input").fill("100");
    await expect(page.getByLabel("数式プレビュー").locator(".katex")).toHaveCount(1);
    await page.getByRole("button", { name: "保存", exact: true }).click();
  }
  await page.reload();
  await expect(page.locator(".question-table-pane .katex")).toHaveCount(1);
  await page.getByRole("button", { name: "問題文を編集" }).click();
  await expect(page.getByLabel("問題文の原文 1")).toHaveValue(source);
  const inlineQuestion = "精度は $P=\\frac{TP}{TP+FP}$ で求める。";
  await page.getByLabel("問題文の原文 1").fill(inlineQuestion);
  await expect(page.getByLabel("数式プレビュー").locator(".katex")).toHaveCount(1);
  await page.getByRole("button", { name: "変更を保存" }).click();
  await page.reload();
  await page.getByRole("button", { name: "問題文を編集" }).click();
  await expect(page.getByLabel("問題文の原文 1")).toHaveValue(inlineQuestion);
  await page.getByRole("navigation", { name: "テスト準備" }).getByRole("button", { name: "模範解答", exact: true }).click();
  await page.getByLabel("模範解答本文").fill("$\\frac{$");
  await expect(page.getByLabel("数式プレビュー").locator(".math-error")).toBeVisible();
  await page.getByLabel("模範解答本文").fill('<img src=x onerror=alert(1)>');
  await expect(page.getByLabel("数式プレビュー").locator("img")).toHaveCount(0);
  await page.getByLabel("模範解答本文").fill("$$\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$$");
  await expect(page.getByLabel("数式プレビュー").locator(".katex")).toHaveCount(1);
  await page.getByLabel("模範解答本文").fill("$$\\frac{1}{2}$$");
  await expect(page.getByLabel("数式プレビュー").locator(".katex")).toHaveCount(1);
  await page.getByRole("button", { name: "模範解答の新しい版を保存" }).click();
  await page.reload();
  await expect(page.getByLabel("模範解答本文")).toHaveValue("$$\\frac{1}{2}$$");
  await page.getByRole("navigation", { name: "テスト準備" }).getByRole("button", { name: "採点基準", exact: true }).click();
  await page.getByRole("button", { name: "＋採点基準を追加" }).click();
  const rubricText = "$\\frac{TP}{TP+FP}$ が正しく示されていれば5点";
  await page.getByLabel("採点基準 1", { exact: true }).fill(rubricText);
  await page.getByLabel("採点基準 1の配点").fill("100");
  await expect(page.getByLabel("数式プレビュー").locator(".katex")).toHaveCount(1);
  await page.getByRole("button", { name: "この問題の採点基準を保存" }).click();
  await page.reload();
  await expect(page.getByLabel("採点基準 1", { exact: true })).toHaveValue(rubricText);
  expect(errors).toEqual([]);
});
