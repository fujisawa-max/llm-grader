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
