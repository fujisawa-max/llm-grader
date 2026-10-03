import { test, expect } from "@playwright/test";

const testId = process.env.REVIEW_UX_TEST_ID;
const email = process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL;
const password = process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD;
test.skip(!testId || !email || !password, "requires isolated real API, production frontend and managed classifier stub");

test("unified review registers rubric candidates separately from model answers", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email!);
  await page.getByLabel("パスワード").fill(password!);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).not.toHaveURL(/\/login/);

  const sources = await (await page.request.get(`/api/v1/tests/${testId}/materials`)).json();
  const material = sources.find((item: { original_filename: string }) => item.original_filename === "unified-rubric-model-answer.pdf");
  expect(material).toBeTruthy();
  const createdResponse = await page.request.post(`/api/v1/tests/${testId}/model-answer-imports`, { data: { material_id: material.id } });
  expect(createdResponse.ok()).toBeTruthy();
  let draft = await createdResponse.json();
  if (!draft.entries.some((entry: { semantic_classification?: { segments?: Array<{ category: string }> } }) =>
    entry.semantic_classification?.segments?.some((segment) => segment.category === "rubric"))) {
    const classifiedResponse = await page.request.post(
      `/api/v1/model-answer-import-drafts/${draft.id}/classify`,
      { data: { expected_revision: draft.revision } },
    );
    expect(classifiedResponse.ok()).toBeTruthy();
    draft = await classifiedResponse.json();
  }
  if (!draft.entries.some((entry: { semantic_classification?: { segments?: Array<{ category: string }> } }) =>
    entry.semantic_classification?.segments?.some((segment) => segment.category === "rubric"))) {
    const teacherIdentified = draft.entries.find((entry: { semantic_classification?: { segments?: Array<{ text: string }> } }) =>
      entry.semantic_classification?.segments?.some((segment) => /\b5 points\b/i.test(segment.text)));
    expect(teacherIdentified, "fixture should contain an extracted 5-point criterion").toBeTruthy();
    const segments = teacherIdentified.semantic_classification.segments.map((segment: { id: string; text: string; category: string }) =>
      /\b5 points\b/i.test(segment.text) ? { ...segment, category: "rubric" } : segment);
    const editedEntries = draft.entries.map((entry: {
      id: string; question_id: string | null; answer_text: string; disposition: string; answer_kind: string;
      semantic_classification?: { segments?: Array<{ id: string; text: string; category: string }> };
    }) => ({
      id: entry.id, question_id: entry.question_id, answer_text: entry.answer_text,
      disposition: entry.disposition, answer_kind: entry.answer_kind,
      ...(entry.id === teacherIdentified.id ? { classification_segments: segments } : {}),
    }));
    const teacherEdit = await page.request.put(`/api/v1/model-answer-import-drafts/${draft.id}`, {
      data: { expected_revision: draft.revision, entries: editedEntries },
    });
    expect(teacherEdit.ok()).toBeTruthy();
    draft = await teacherEdit.json();
  }
  await page.goto(`/model-answer-import-reviews/${draft.id}`);
  await expect(page.getByRole("heading", { name: "解答・採点基準の確認" })).toBeVisible();
  await expect(page.getByLabel("編集対象")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "模範解答PDF" })).toBeVisible();

  const rubricEntry = draft.entries.find((entry: { semantic_classification?: { segments?: Array<{ category: string }> } }) =>
    entry.semantic_classification?.segments?.some((segment) => segment.category === "rubric"));
  expect(rubricEntry, "the managed classifier stub should identify the PDF rubric segment").toBeTruthy();
  await page.getByLabel("編集対象").selectOption(`question:${rubricEntry.question_id}`);
  const rubricDescription = page.getByLabel(/採点基準候補 .*-/).first();
  await expect(rubricDescription).toBeVisible();
  await rubricDescription.fill("過学習の説明が正しい");
  await page.getByLabel(/採点基準候補 .* の配点/).first().fill("10");

  const rubricSaved = page.waitForResponse((response) => response.url().endsWith("/register-rubric"));
  await page.getByRole("button", { name: "採点基準として登録" }).click();
  const registration = await rubricSaved;
  expect(registration.status()).toBe(200);
  await expect(page.getByText(/採点基準 v2 を登録しました/)).toBeVisible();
  const rubrics = await (await page.request.get(`/api/v1/tests/${testId}/rubrics`)).json();
  const imported = rubrics.find((row: { source_type: string }) => row.source_type === "model_answer_import");
  expect(imported.status).toBe("generated");
  expect(imported.rubric_json.provenance.kind).toBe("model_answer_import_rubric");
  expect(imported.rubric_json.questions).toHaveLength(3);
  await page.goto(`/tests/${testId}?section=answers&question=${encodeURIComponent(rubricEntry.question_id)}`);
  await expect(page.getByLabel("対象設問")).toHaveValue(rubricEntry.question_id);
  await expect(page.getByLabel("模範解答本文")).toBeVisible();
  await expect(page.getByText("採点基準: 登録済み・未承認")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "模範解答・採点基準PDF" })).toBeVisible();
});
