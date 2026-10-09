import {test, expect, type Page} from "@playwright/test";

test.setTimeout(90000);
test.skip(!process.env.DIAGRAM_OVERRIDE_DRAFT_ID || process.env.LLM_GRADER_STUB_DIAGRAM_RESPONSE_MODE !== "truncated", "requires isolated managed truncated-Ricoh fixture");
async function calls(page: Page) {
  return Promise.all(["ocr", "math_ocr", "ornith_rubric_draft", "grader"].map(async profile => {
    const value = await (await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();
    return value.lines.filter((line: string) => line.includes("POST /v1/chat/completions")).length;
  }));
}
test("PDF fallback truncated Ricoh: explicit teacher acceptance after correction, save/resume and formal transfer", async ({page}) => {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name: "ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  const errors: string[] = [];
  let expectedSourceFailure = false;
  const expectedConsoleErrors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", e => {
    if (e.type() !== "error") return;
    if (expectedSourceFailure && e.text().includes("status of 409")) expectedConsoleErrors.push(e.text());
    else errors.push(e.text());
  });
  const did = process.env.DIAGRAM_OVERRIDE_DRAFT_ID!;
  const children = JSON.parse(process.env.DIAGRAM_OVERRIDE_CHILD_IDS!) as string[];
  const base = `/api/v1/model-answer-import-drafts/${did}`;
  await page.goto(`/model-answer-import-reviews/${did}`);
  const selector = page.getByLabel("編集対象", {exact: true});
  await selector.selectOption(`question:${children[0]}`);
  await page.getByRole("button", {name: /に模範解答を追加$/}).click();
  const candidate = page.locator('[data-entry-id^="teacher-entry-"]');
  const section = candidate.getByRole("region", {name: "模範解答の図", exact: true});
  const register = page.getByRole("button", {name: "模範解答として登録", exact: true});
  const before = await calls(page);
  await section.getByRole("button", {name: "図候補を確認", exact: true}).click();
  await expect(section.getByRole("button", {name: "親設問の図候補を表示"})).toHaveCount(0);
  await section.getByRole("button", {name: "このPDFのすべての図候補を表示"}).click();
  await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  await expect(page.locator(".diagram-overlay")).toBeVisible();
  await expect(section.getByText("この図が設問に対応する図か自動では確認できませんでした。PDFと図の範囲を確認し、正しければ使用してください。別の範囲をPDFから切り出すこともできます。", {exact: true})).toBeVisible();
  await expect(section.getByText(/diagram_ricoh_output_truncated/)).not.toBeVisible();
  const use = section.getByRole("button", {name: "この図を確認して使用", exact: true});
  await expect(use).toBeEnabled();
  await expect(section.getByRole("checkbox")).toHaveCount(0);
  await expect(register).toBeDisabled();
  const detectedCalls = await calls(page);
  expect(detectedCalls[0]).toBe(before[0]+1);
  expect(detectedCalls.slice(1)).toEqual(before.slice(1));
  await section.getByRole("button", {name: "範囲を修正", exact: true}).click();
  for (const [label, value] of [["左", "68"], ["上", "138"], ["右", "232"], ["下", "302"]])
    await section.getByLabel(`図の範囲 ${label}`).fill(value);
  await section.getByRole("button", {name: "プレビューを更新"}).click();
  await expect(section.getByAltText("修正後の図の範囲")).toBeVisible();
  await section.getByRole("button", {name: "範囲を適用", exact: true}).click();
  await expect(register).toBeDisabled(); // correction is not acceptance
  await use.click();
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
  await expect(register).toBeEnabled();
  await expect(candidate.getByRole("textbox", {name: /模範解答本文/})).toHaveValue("");
  const saved = page.waitForResponse(r => r.url().endsWith(did) && r.request().method() === "PUT");
  await page.getByRole("button", {name: "下書き保存", exact: true}).click();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await selector.selectOption(`question:${children[0]}`);
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
  await expect(register).toBeEnabled();
  const draft = await (await page.request.get(base)).json();
  const record = draft.entries[0].diagram_records[0];
  expect(record.teacher_confirmed).toBe(true);
  expect(record.trust_state_at_accept).toBe("teacher_confirmable");
  expect(record.confirmation_reason_code).toBe("diagram_ricoh_output_truncated");
  expect(record.ricoh_finish_reason).toBe("length");
  expect(record.final_bbox).toEqual([68,138,232,302]);
  expect(await calls(page)).toEqual(detectedCalls);

  // A revalidated hard-invalid source cannot keep readiness or be clicked.
  await page.route("**/entries/*/diagrams?question_id=*", async route => {
    const response = await route.fetch(); const result = await response.json();
    result.diagrams = result.diagrams.map((d: object) => ({...d, state: "candidate", status: "unresolved", reason_code: "diagram_source_stale", trust_state: "hard_invalid", teacher_confirmed: false}));
    await route.fulfill({response, json: result});
  });
  await page.reload();
  await expect(section.getByText("この図は元PDFとの対応を確認できないため使用できません。変更を保存して再度図候補を確認するか、別候補を選択してください。", {exact: true})).toBeVisible();
  await expect(section.getByRole("button", {name: "この図を使用", exact: true})).toBeDisabled();
  await expect(register).toBeDisabled();
  await page.unroute("**/entries/*/diagrams?question_id=*");
  // Whole-request source-integrity rejection also fails local readiness closed.
  expectedSourceFailure = true;
  await page.route("**/entries/*/diagrams?question_id=*", route => route.fulfill({status: 409,
    json: {error: {code: "diagram_source_integrity_error", message: "fixture source mismatch"}}}));
  await page.reload();
  await expect(section.getByRole("alert")).toHaveText("図の出典または範囲を確認できません。範囲を見直すか、再度図候補を確認してください。");
  await expect(section.getByRole("button", {name: "この図を使用", exact: true})).toBeDisabled();
  await expect(register).toBeDisabled();
  await expect(section.getByText("diagram_source_integrity_error", {exact: true})).not.toBeVisible();
  expect(expectedConsoleErrors.length).toBeGreaterThan(0);
  expectedSourceFailure = false;
  await page.unroute("**/entries/*/diagrams?question_id=*");
  await page.reload();
  await expect(register).toBeEnabled();
  // Backend rejects a forged confirmation with a mismatched source identity.
  const forged = structuredClone(draft.entries);
  forged[0].diagram_records[0].source_sha256 = "0".repeat(64);
  const rejected = await page.request.put(base, {data: {expected_revision: draft.revision, entries: forged}});
  expect(rejected.status()).toBe(422);
  const confirmed = page.waitForResponse(r => r.url().endsWith("/confirm"));
  await register.click();
  const response = await confirmed;
  expect(response.status()).toBe(200);
  const formal = (await response.json()).model_answers[0];
  expect(formal.answer_text).toBe("");
  expect(formal.provenance_json.diagrams[0].teacher_confirmed).toBe(true);
  expect(formal.provenance_json.diagrams[0].acceptance_method).toBe("accepted_by_teacher_after_unresolved_detection");
  expect(await calls(page)).toEqual(detectedCalls);
  expect(errors).toEqual([]);
});
