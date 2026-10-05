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
  const rubricEntryIndex = draft.entries.indexOf(rubricEntry) + 1;
  await page.getByLabel("編集対象").selectOption(`question:${rubricEntry.question_id}`);
  const rubricDescription = page.getByLabel(`採点基準候補 ${rubricEntryIndex}-1 本文`);
  await expect(rubricDescription).toBeVisible();
  await expect(page.getByText(/元segment 3件/)).toBeVisible();
  const first = page.getByLabel(`採点基準候補 ${rubricEntryIndex}-1 を選択`);
  const second = page.getByLabel(`採点基準候補 ${rubricEntryIndex}-2 を選択`);
  const third = page.getByLabel(`採点基準候補 ${rubricEntryIndex}-3 を選択`);
  await first.check(); await second.check(); await third.check();
  await page.getByRole("button", { name: "選択した項目をマージ" }).click();
  await expect(page.getByText(/採点基準候補（1件）/)).toBeVisible();
  const mergedText = page.getByLabel(`採点基準候補 ${rubricEntryIndex}-1 本文`);
  await expect(mergedText).toHaveValue(/identify overfitting\. cite evidence\. mention generalization\./);
  await expect(page.getByText(/複数の配点記述があります/)).toBeVisible();
  await page.getByRole("button", { name: "マージを解除（元に戻す）" }).click();
  await expect(page.getByText(/採点基準候補（3件）/)).toBeVisible();
  await page.getByRole("button", { name: "上とマージ" }).nth(0).click();
  await expect(page.getByText(/採点基準候補（2件）/)).toBeVisible();
  await page.getByRole("button", { name: "マージを解除（元に戻す）" }).click();
  await first.check(); await second.check();
  await page.getByRole("button", { name: "選択した項目をマージ" }).click();
  await page.getByLabel(`採点基準候補 ${rubricEntryIndex}-1 の配点`).fill("7");
  await page.getByLabel("配点を確認しました").check();
  await page.getByLabel(`採点基準候補 ${rubricEntryIndex}-2 の配点`).fill("3");
  await page.getByLabel("グルーピングを確認しました").nth(1).check();

  const savedDraft = page.waitForResponse((response) => response.url().includes("/model-answer-import-drafts/")
    && response.request().method() === "PUT");
  await page.getByRole("button", { name: "下書き保存" }).click();
  expect((await savedDraft).status()).toBe(200);
  const savedState = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json();
  let resumeWrites = 0;
  const monitorResume = (request: import("@playwright/test").Request) => {if(request.method() !== "GET") resumeWrites++;};
  page.on("request", monitorResume);
  await page.goto(`/tests/${testId}?section=answers`);
  await page.getByRole("region", {name:"模範解答登録"})
    .getByRole("button", {name:"unified-rubric-model-answer.pdfの前回の解析結果を編集"}).click();
  await expect(page).toHaveURL(new RegExp(`/model-answer-import-reviews/${draft.id}$`));
  expect(await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json()).toEqual(savedState);
  expect(resumeWrites).toBe(0);
  page.off("request", monitorResume);
  await page.getByLabel("編集対象").selectOption(`question:${rubricEntry.question_id}`);
  await expect(page.getByText(/採点基準候補（2件）/)).toBeVisible();
  await expect(page.getByLabel("グルーピングを確認しました").nth(1)).toBeChecked();

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
  expect(imported.rubric_json.questions[0].criteria).toHaveLength(2);
  expect(imported.rubric_json.provenance.questions[rubricEntry.question_id][0].grouping_method).toBe("manual_multi");
  await page.goto(`/tests/${testId}?section=answers&question=${encodeURIComponent(rubricEntry.question_id)}`);
  await expect(page.getByLabel("対象設問")).toHaveValue(rubricEntry.question_id);
  await expect(page.getByLabel("模範解答本文")).toBeVisible();
  await expect(page.getByText("採点基準: 登録済み・未承認")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "模範解答・採点基準PDF" })).toBeVisible();
});
