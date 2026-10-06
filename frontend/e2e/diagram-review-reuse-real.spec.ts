import {test, expect, type Page} from "@playwright/test";

test.setTimeout(90000);
test.skip(!process.env.DIAGRAM_REUSE_DRAFT_ID || process.env.LLM_GRADER_STUB_DIAGRAM_RESPONSE_MODE !== "truncated", "requires isolated managed truncated-Ricoh fixture");
async function calls(page: Page) {
  return Promise.all(["ocr", "math_ocr", "ornith_rubric_draft", "grader"].map(async profile => {
    const value = await (await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();
    return value.lines.filter((line: string) => line.includes("POST /v1/chat/completions")).length;
  }));
}
test("delayed source revalidation cannot erase a newer teacher acceptance", async ({page}) => {
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
  const did = process.env.DIAGRAM_REUSE_DRAFT_ID!;
  const children = JSON.parse(process.env.DIAGRAM_REUSE_CHILD_IDS!) as string[];
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
  await expect(section.getByText("図の出典範囲を自動では確認できませんでした。PDFと図の範囲を確認してください。教師が確認した図は使用できます。", {exact: true})).toBeVisible();
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
  // Save the corrected, unaccepted candidate, then hold its old GET. A newer
  // explicit discovery proves the source valid before teacher acceptance.
  const savedCandidate = page.waitForResponse(r => r.url().endsWith(did) && r.request().method() === "PUT");
  await page.getByRole("button", {name: "下書き保存", exact: true}).click();
  expect((await savedCandidate).status()).toBe(200);
  let release!: () => void;
  const gate = new Promise<void>(resolve => {release = resolve;});
  let held!: () => void;
  const heldRequest = new Promise<void>(resolve => {held = resolve;});
  expectedSourceFailure = true;
  await page.route("**/entries/*/diagrams?question_id=*", async route => {
    if (route.request().method() !== "GET" || route.request().url().includes("scope=")) {await route.continue(); return;}
    held(); await gate;
    await route.fulfill({status: 409, json: {error: {code: "diagram_source_stale", message: "old verification"}}});
  });
  await page.reload(); await heldRequest;
  await section.getByRole("button", {name: "図候補を確認", exact: true}).click();
  await section.getByRole("button", {name: "このPDFのすべての図候補を表示"}).click();
  await expect(candidate.getByText("未保存の変更があります", {exact: true})).not.toBeVisible();
  await use.click();
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
  await expect(section.getByRole("button", {name: "使用中", exact: true})).toBeDisabled();
  await expect(section.getByText("教師が確認して使用", {exact: true})).toBeVisible();
  await expect(candidate.getByText("未保存の変更があります", {exact: true})).toBeVisible();
  expect((await (await page.request.get(base)).json()).entries[0].diagram_records[0].state).toBe("candidate");
  release();
  await expect.poll(() => expectedConsoleErrors.length).toBeGreaterThan(0);
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
  await expect(register).toBeEnabled();
  await page.unroute("**/entries/*/diagrams?question_id=*");
  expectedSourceFailure = false;
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

  // The saved crop is offered to each sibling without rediscovery or inference.
  for (const qid of children.slice(1)) {
    await selector.selectOption(`question:${qid}`);
    await page.getByRole("button", {name: /に模範解答を追加$/}).click();
    const reusable = section.getByRole("region", {name: "この大問ですでに使用している図", exact: true});
    await expect(reusable.getByText("問題3 > (1) で使用中", {exact: true})).toBeVisible();
    await expect(reusable.getByAltText("再利用できる図")).toBeVisible();
    await expect(register).toBeDisabled();
    await reusable.getByRole("button", {name: "元PDFで確認"}).click();
    await expect(page.locator(".diagram-overlay")).toBeVisible();
    await expect(selector).toHaveValue(`question:${qid}`);
    await reusable.getByRole("button", {name: "この図を再利用", exact: true}).click();
    await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
    await expect(section.getByRole("button", {name: "使用中", exact: true})).toBeDisabled();
    await expect(candidate.getByText("未保存の変更があります", {exact: true})).toBeVisible();
    await expect(register).toBeEnabled();
    expect(await calls(page)).toEqual(detectedCalls);
    const savedReuse = page.waitForResponse(r => r.url().endsWith(did) && r.request().method() === "PUT");
    await page.getByRole("button", {name: "下書き保存", exact: true}).click();
    expect((await savedReuse).status()).toBe(200);
    await page.reload(); await selector.selectOption(`question:${qid}`);
    await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
    await expect(candidate.getByText("未保存の変更があります", {exact: true})).not.toBeVisible();
    await expect(register).toBeEnabled();
  }
  const finalDraft = await (await page.request.get(base)).json();
  const diagrams = finalDraft.entries.map((entry: {diagram_records: {crop_sha256: string}[]}) => entry.diagram_records[0]);
  expect(new Set(diagrams.map((d: {crop_sha256: string}) => d.crop_sha256)).size).toBe(1);
  expect(diagrams[1].acceptance_method).toBe("reused_confirmed_diagram");
  expect(diagrams[1].source_teacher_confirmed).toBe(true);
  expect(diagrams[1].assigned_question_id).toBe(children[1]);
  expect(diagrams[1].reused_from_question_id).toBe(children[0]);
  const formalResponse = page.waitForResponse(r => r.url().endsWith("/confirm"));
  await register.click();
  const response = await formalResponse;
  expect(response.status()).toBe(200);
  const answers = (await response.json()).model_answers;
  expect(answers).toHaveLength(3);
  expect(answers.every((answer: {answer_text: string}) => answer.answer_text === "")).toBe(true);
  expect(answers[1].provenance_json.diagrams[0].acceptance_method).toBe("reused_confirmed_diagram");
  expect(await calls(page)).toEqual(detectedCalls);
  expect(errors).toEqual([]);
});
