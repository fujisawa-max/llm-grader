import {test, expect, type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";
test.setTimeout(60000);
test.skip(!process.env.DIAGRAM_TEST_ID, "requires isolated production API fixture");
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name: "ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
}
async function calls(page: Page) {
  const root = process.env.LLM_GRADER_RUNTIME_MANAGER_URL!;
  return Promise.all(["ocr", "math_ocr", "ornith_rubric_draft", "grader"].map(async profile => {
    const r = await (await page.request.get(`${root}/runtimes/${profile}/logs?tail=1000`)).json();
    return r.lines.filter((line: string) => line.includes("POST /v1/chat/completions")).length;
  }));
}
async function saveQuestion(page: Page) {
  const saved = page.waitForResponse(r => r.url().endsWith("/revisions") && r.request().method() === "POST");
  await page.getByRole("button", {name: "変更を保存", exact: true}).click();
  expect((await saved).status()).toBe(200);
}

test("Question vector diagrams: preview/highlight, accept, drag correction, exclude, reload and formal transfer", async ({page}) => {
  await login(page);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", e => {if (e.type() === "error") errors.push(e.text());});
  const before = await calls(page);
  const tid = process.env.DIAGRAM_TEST_ID!;
  const upload = await page.request.post(`/api/v1/tests/${tid}/question-materials`, {
    headers: {"content-type": "application/pdf", "x-filename": "diagram.pdf"}, data: await readFile(process.env.DIAGRAM_PDF_PATH!)});
  expect(upload.status()).toBe(201);
  const draft = await (await page.request.post(`/api/v1/question-imports/${(await upload.json()).id}/draft`)).json();
  const review = await (await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).json();
  await page.goto(`/question-import-reviews/${review.id}`);
  const section = page.getByRole("region", {name: "図の確認", exact: true});
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  await expect(page.locator(".diagram-overlay")).toBeVisible();
  const source = await page.locator(".review-workspace-source").boundingBox();
  const editor = await page.locator(".review-workspace-editor").boundingBox();
  expect(source!.x).toBeLessThan(editor!.x);
  await section.getByRole("button", {name: "この図を使用"}).click();
  await expect(section.getByText(/使用中 ·/)).toBeVisible();
  expect(await (await page.request.get(`/api/v1/tests/${tid}/questions`)).json()).toEqual([]);
  await saveQuestion(page); await page.reload();
  await expect(section.getByText(/使用中 ·/)).toBeVisible();
  await section.getByRole("button", {name: "範囲を修正", exact: true}).click();
  const overlay = page.locator(".diagram-selecting");
  const bounds = await overlay.boundingBox();
  await page.mouse.move(bounds!.x + bounds!.width * 65/400, bounds!.y + bounds!.height * 75/500);
  await page.mouse.down();
  await page.mouse.move(bounds!.x + bounds!.width * 235/400, bounds!.y + bounds!.height * 245/500);
  await page.mouse.up();
  await expect(section.getByLabel("図の範囲 左")).toHaveValue(/6[45](\.|$)/);
  await section.getByRole("button", {name: "プレビューを更新"}).click();
  await expect(section.getByAltText("修正後の図の範囲")).toBeVisible();
  await section.getByRole("button", {name: "範囲を適用"}).click();
  await saveQuestion(page); await page.reload();
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();
  const selector = page.getByLabel("対象設問", {exact: true});
  await selector.selectOption(review.snapshot.nodes[1].stable_key);
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await section.getByRole("button", {name: "対象外にする"}).click();
  await saveQuestion(page); await page.reload();
  await expect(section.getByText(/対象外 ·/)).toBeVisible();
  for (const node of review.snapshot.nodes) {
    await selector.selectOption(node.stable_key);
    const confirm = page.getByRole("button", {name: "問題文を確認", exact: true});
    if (await confirm.count()) await confirm.click();
  }
  const warnings = page.getByRole("combobox", {name: /確認事項 .*の状態/});
  for (let i = 0; i < await warnings.count(); i++) await warnings.nth(i).selectOption("acknowledged");
  await saveQuestion(page);
  await page.getByRole("button", {name: "確認済みにする", exact: true}).click();
  await page.getByRole("button", {name: "問題登録前の最終確認へ", exact: true}).click();
  page.on("dialog", d => d.accept());
  const registered = page.waitForResponse(r => r.url().endsWith("/confirm"));
  await page.getByRole("button", {name: "確認した問題を登録", exact: true}).click();
  expect((await registered).status()).toBe(200);
  const formal = await (await page.request.get(`/api/v1/tests/${tid}/questions`)).json();
  expect(formal).toHaveLength(2);
  expect(formal.flatMap((q: {content?: {items: {type: string}[]}}) => q.content?.items || []).filter((i: {type: string}) => i.type === "figure")).toHaveLength(1);
  expect(await calls(page)).toEqual(before);
  expect(errors).toEqual([]);
});

test("ModelAnswer diagram is separately reviewed, corrected and saved without changing formal answer", async ({page}) => {
  await login(page);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const tid = process.env.DIAGRAM_ANSWER_TEST_ID!;
  const created = await page.request.post(`/api/v1/tests/${tid}/model-answer-imports`, {data: {material_id: process.env.DIAGRAM_ANSWER_MATERIAL_ID}});
  expect(created.status()).toBe(201);
  const draft = await created.json();
  const before = await calls(page);
  await page.goto(`/model-answer-import-reviews/${draft.id}`);
  const section = page.getByRole("region", {name: "模範解答の図", exact: true});
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  await expect(page.locator(".diagram-overlay")).toBeVisible();
  await section.getByRole("button", {name: "この図を使用"}).click();
  await section.getByRole("button", {name: "範囲を修正", exact: true}).click();
  for (const [label, value] of [["左", "65"], ["上", "75"], ["右", "235"], ["下", "245"]])
    await section.getByLabel(`図の範囲 ${label}`).fill(value);
  await section.getByRole("button", {name: "プレビューを更新"}).click();
  await expect(section.getByAltText("修正後の図の範囲")).toBeVisible();
  await section.getByRole("button", {name: "範囲を適用"}).click();
  const save = page.waitForResponse(r => r.url().endsWith(draft.id) && r.request().method() === "PUT");
  await page.getByRole("button", {name: "下書き保存", exact: true}).click();
  expect((await save).status()).toBe(200);
  await page.reload();
  await expect(section.getByText(/使用中 ·/)).toBeVisible();
  const saved = await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json();
  const diagrams = saved.entries.flatMap((e: {diagram_records?: {domain: string}[]}) => e.diagram_records || []);
  expect(diagrams).toHaveLength(1); expect(diagrams[0].domain).toBe("model_answer");
  expect(await (await page.request.get(`/api/v1/tests/${tid}/model-answers`)).json()).toEqual([]);
  const registered = page.waitForResponse(r => r.url().endsWith("/confirm"));
  await page.getByRole("button", {name: "模範解答として登録", exact: true}).click();
  expect((await registered).status()).toBe(200);
  const formal = await (await page.request.get(`/api/v1/tests/${tid}/model-answers`)).json();
  const transferred = formal.flatMap((a: {provenance_json: {diagrams?: {state: string; teacher_adjusted: boolean}[]}}) => a.provenance_json.diagrams || []);
  expect(transferred).toHaveLength(1);
  expect(transferred[0].state).toBe("accepted"); expect(transferred[0].teacher_adjusted).toBe(true);
  expect(await calls(page)).toEqual(before);
  expect(errors).toEqual([]);
});

test("saved reviewed split keeps vector diagram exclusive to its source-owning child", async ({page}) => {
  await login(page);
  const before = await calls(page);
  const upload = await page.request.post(`/api/v1/tests/${process.env.DIAGRAM_SPLIT_TEST_ID}/question-materials`, {
    headers: {"content-type": "application/pdf", "x-filename": "split-diagram.pdf"}, data: await readFile(process.env.DIAGRAM_PDF_PATH!)});
  const draft = await (await page.request.post(`/api/v1/question-imports/${(await upload.json()).id}/draft`)).json();
  const review = await (await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).json();
  const base = `/api/v1/question-import-reviews/${review.id}`;
  const snapshot = review.snapshot;
  const parent = snapshot.nodes[0];
  const child = {...structuredClone(parent), stable_key: "teacher-diagram-child", review_node_id: "teacher-diagram-child",
    source_draft_stable_key: null, source_draft_node_id: null, parent_key: parent.stable_key,
    node_type: "subquestion", sort_order: 0, review_flags: []};
  parent.ordered_content = [{type: "text", text: "教師が追加した親設問", order: 0}];
  parent.score_semantics = "sum_children"; parent.score_points = null;
  snapshot.nodes.push(child);
  const save = await page.request.post(base+"/revisions", {data: {base_revision: 1, snapshot}});
  expect(save.status()).toBe(200);
  await page.goto(`/question-import-reviews/${review.id}`);
  const selector = page.getByLabel("対象設問", {exact: true});
  const section = page.getByRole("region", {name: "図の確認", exact: true});
  await selector.selectOption(child.stable_key);
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  const result = await (await page.request.get(base+`/nodes/${child.stable_key}/diagrams`)).json();
  expect(result.diagrams[0].automatic_bbox).toEqual([70,80,230,240]);
  await selector.selectOption(parent.stable_key);
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await expect(section.getByText("この設問の出典範囲には図候補が見つかりませんでした。")).toBeVisible();
  await selector.selectOption(review.snapshot.nodes[1].stable_key);
  await section.getByRole("button", {name: "図候補を確認"}).click();
  const sibling = await (await page.request.get(base+`/nodes/${review.snapshot.nodes[1].stable_key}/diagrams`)).json();
  expect(sibling.diagrams[0].automatic_bbox).toEqual([70,330,230,455]);
  expect(sibling.diagrams[0].source_element_ids.some((id: string) => result.diagrams[0].source_element_ids.includes(id))).toBe(false);
  expect(await calls(page)).toEqual(before);
});

test("manual empty ModelAnswer discovers, reviews and registers only an accepted diagram", async ({page}) => {
  await login(page);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const tid = process.env.MANUAL_DIAGRAM_TEST_ID!;
  const created = await page.request.post(`/api/v1/tests/${tid}/model-answer-imports`, {data: {material_id: process.env.MANUAL_DIAGRAM_MATERIAL_ID}});
  expect(created.status()).toBe(201);
  const draft = await created.json();
  const base = `/api/v1/model-answer-import-drafts/${draft.id}`;
  const prepared = await page.request.put(base, {data: {expected_revision: draft.revision, entries: draft.entries.map((e: {id: string; question_id: string; answer_text: string}) => ({id: e.id, question_id: e.question_id, answer_text: e.answer_text, disposition: "excluded"}))}});
  expect(prepared.status()).toBe(200);
  // All three nested subquestions have exclusive spatial regions, never sibling crops.
  const ready = await prepared.json();
  const children = ready.questions.filter((q: {is_gradable: boolean}) => q.is_gradable);
  expect(children).toHaveLength(3);
  for (const [index, question] of children.entries()) {
    const entryId = `teacher-entry-${crypto.randomUUID()}`;
    const response = await page.request.post(`${base}/entries/${entryId}/diagrams?question_id=${question.id}`, {data: {expected_revision: ready.revision}});
    expect(response.status()).toBe(200);
    const records = (await response.json()).diagrams;
    expect(records).toHaveLength(1);
    expect(records[0].automatic_bbox).toEqual([70, 90 + 240*index, 230, 230 + 240*index]);
    expect(records[0].ricoh_used).toBe(false);
  }
  const before = await calls(page);
  await page.goto(`/model-answer-import-reviews/${draft.id}`);
  await page.getByRole("button", {name: /に模範解答を追加$/}).click();
  const candidate = page.locator('[data-entry-id^="teacher-entry-"]');
  const text = candidate.getByRole("textbox", {name: /模範解答本文/});
  await expect(text).toHaveValue("");
  const register = page.getByRole("button", {name: "模範解答として登録", exact: true});
  await expect(register).toBeDisabled();
  const section = candidate.getByRole("region", {name: "模範解答の図", exact: true});
  await section.getByRole("button", {name: "図候補を確認"}).click();
  await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  await expect(page.locator(".diagram-overlay")).toBeVisible();
  await expect(register).toBeDisabled();
  await section.getByRole("button", {name: "対象外にする"}).click();
  await expect(register).toBeDisabled();
  await section.getByRole("button", {name: "この図を使用"}).click();
  await expect(register).toBeEnabled();
  const saved = page.waitForResponse(r => r.url().endsWith(draft.id) && r.request().method() === "PUT");
  await page.getByRole("button", {name: "下書き保存", exact: true}).click();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(text).toHaveValue("");
  await expect(section.getByText(/使用中 ·/)).toBeVisible();
  await expect(register).toBeEnabled();
  // A stale result from authorized server revalidation must also invalidate
  // local readiness. The persisted valid fixture stays unchanged here.
  const diagramsUrl = "**/entries/*/diagrams?question_id=*";
  await page.route(diagramsUrl, async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.diagrams = body.diagrams.map((r: object) => ({...r, state: "candidate", status: "unresolved", reason_code: "diagram_source_stale", trust_state: "hard_invalid", teacher_confirmed: false}));
    await route.fulfill({response, json: body});
  });
  await page.reload();
  await expect(section.getByText(/この図は元PDFとの対応を確認できないため使用できません/)).toBeVisible();
  await expect(register).toBeDisabled();
  await page.unroute(diagramsUrl);
  await page.reload();
  await expect(section.getByText(/使用中 ·/)).toBeVisible();
  await expect(register).toBeEnabled();
  const registered = page.waitForResponse(r => r.url().endsWith("/confirm"));
  await register.click();
  const result = await registered;
  expect(result.status()).toBe(200);
  const answer = (await result.json()).model_answers[0];
  expect(answer.answer_text).toBe("");
  expect(answer.provenance_json.diagrams).toHaveLength(1);
  await page.goto(`/model-answer-import-reviews/${draft.id}`);
  await page.getByRole("group", {name: "登録済み模範解答"}).click();
  await expect(page.getByText("本文: なし", {exact: true})).toBeVisible();
  await expect(page.getByText("模範解答の図: 1件", {exact: true})).toBeVisible();
  expect(await calls(page)).toEqual(before);
  expect(errors).toEqual([]);
});

for (const diagramScope of ["parent", "pdf"] as const) {
  test(`${diagramScope} fallback keeps source ownership and explicitly assigns one shared diagram`, async ({page}) => {
    await login(page);
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    page.on("console", e => {if (e.type() === "error") errors.push(e.text());});
    const before = await calls(page);
    const upper = diagramScope.toUpperCase();
    const did = process.env[`DIAGRAM_${upper}_DRAFT_ID`]!;
    const children = JSON.parse(process.env[`DIAGRAM_${upper}_CHILD_IDS`]!) as string[];
    const owner = process.env[`DIAGRAM_${upper}_OWNER_ID`]!;
    const base = `/api/v1/model-answer-import-drafts/${did}`;
    await page.goto(`/model-answer-import-reviews/${did}`);
    const selector = page.getByLabel("編集対象", {exact: true});
    const register = page.getByRole("button", {name: "模範解答として登録", exact: true});
    for (const qid of children.slice(0, 2)) {
      await selector.selectOption(`question:${qid}`);
      await page.getByRole("button", {name: /に模範解答を追加$/}).click();
      const candidate = page.locator('[data-entry-id^="teacher-entry-"]');
      const section = candidate.getByRole("region", {name: "模範解答の図", exact: true});
      await expect(candidate.getByRole("textbox", {name: /模範解答本文/})).toHaveValue("");
      await section.getByRole("button", {name: "図候補を確認", exact: true}).click();
      await expect(register).toBeDisabled();
      if (diagramScope === "parent") {
        await expect(section.getByText('親設問「問題3」に図候補があります。', {exact: true})).toBeVisible();
        await section.getByRole("button", {name: "親設問の図候補を表示", exact: true}).click();
      } else {
        await expect(section.getByRole("button", {name: "親設問の図候補を表示"})).toHaveCount(0);
        await section.getByRole("button", {name: "このPDFのすべての図候補を表示", exact: true}).click();
      }
      await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
      await expect(page.locator(".diagram-overlay")).toBeVisible();
      await expect(selector).toHaveValue(`question:${qid}`);
      await expect(register).toBeDisabled();
      await section.getByRole("button", {name: "この図を使用", exact: true}).click();
      await expect(register).toBeEnabled();
      if (qid === children[0]) {
        await section.getByRole("button", {name: "範囲を修正", exact: true}).click();
        for (const [label, value] of [["左", "68"], ["上", "138"], ["右", "232"], ["下", "302"]])
          await section.getByLabel(`図の範囲 ${label}`).fill(value);
        await section.getByRole("button", {name: "プレビューを更新"}).click();
        await expect(section.getByAltText("修正後の図の範囲")).toBeVisible();
        await section.getByRole("button", {name: "範囲を適用", exact: true}).click();
      }
      const saved = page.waitForResponse(r => r.url().endsWith(did) && r.request().method() === "PUT");
      await page.getByRole("button", {name: "下書き保存", exact: true}).click();
      expect((await saved).status()).toBe(200);
      await page.reload();
      await selector.selectOption(`question:${qid}`);
      await expect(section.getByText(/使用中 ·/)).toBeVisible();
    }
    const savedDraft = await (await page.request.get(base)).json();
    const assigned = savedDraft.entries.flatMap((e: {diagram_records?: {id: string; scope: string; source_question_id: string | null; assigned_question_id: string}[]}) => e.diagram_records || []);
    expect(assigned).toHaveLength(2);
    expect(assigned[0].id).toBe(assigned[1].id);
    expect(assigned.every((d: {scope: string}) => d.scope === diagramScope)).toBe(true);
    expect(assigned.map((d: {assigned_question_id: string}) => d.assigned_question_id)).toEqual(children.slice(0, 2));
    if (diagramScope === "parent") expect(assigned.every((d: {source_question_id: string}) => d.source_question_id === owner)).toBe(true);
    // Formal transfer preserves source owner and assigned child independently.
    const confirmed = page.waitForResponse(r => r.url().endsWith("/confirm"));
    await register.click();
    const response = await confirmed;
    expect(response.status()).toBe(200);
    const answers = (await response.json()).model_answers;
    expect(answers).toHaveLength(2);
    for (const answer of answers) {
      expect(answer.answer_text).toBe("");
      expect(answer.provenance_json.diagrams[0].assigned_question_id).toBe(answer.question_id);
      expect(answer.provenance_json.diagrams[0].scope).toBe(diagramScope);
    }
    expect(await calls(page)).toEqual(before);
    expect(errors).toEqual([]);
  });
}
