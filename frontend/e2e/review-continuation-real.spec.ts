import {test, expect, type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";
test.skip(!process.env.QUESTION_CONTINUATION_TEST_ID, "requires disposable real API fixture");
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
}
function audit(page: Page) {
  const errors: string[] = [], writes: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => {if(m.type()==="error") errors.push(m.text());});
  page.on("request", r => {if(["POST","PUT","DELETE"].includes(r.method())) writes.push(r.url());});
  page.on("response", r => {if(r.status()>=400) errors.push(`${r.status()} ${r.url()}`);});
  return {errors,writes};
}

async function runtimeEvidence(page:Page) {
  const manager=process.env.LLM_GRADER_RUNTIME_MANAGER_URL!;
  return Promise.all(["grader","ocr","math_ocr","ornith_rubric_draft"].map(async profile=>{
    const status=await (await page.request.get(`${manager}/runtimes/${profile}/status`)).json();
    const logs=await (await page.request.get(`${manager}/runtimes/${profile}/logs?tail=1000`)).json();
    return {profile,pid:status.pid,started_at:status.started_at,
      inferenceCalls:logs.lines.filter((line:string)=>line.includes("POST /v1/chat/completions")).length};
  }));
}

test("Question unresolved links focus exact controls, preserve buffers, and resume saved review without analysis", async ({page}) => {
  await login(page);
  const testId=process.env.QUESTION_CONTINUATION_TEST_ID!;
  const uploaded=await page.request.post(`/api/v1/tests/${testId}/question-materials`,{
    headers:{"content-type":"application/pdf","x-filename":"question-continuation.pdf"},
    data:await readFile(process.env.QUESTION_CONTINUATION_PDF_PATH!)});
  expect(uploaded.status()).toBe(201);
  const extraction=await uploaded.json();
  const draft=await (await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();
  let saved=await (await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).json();
  expect(saved.regions.filter((r:{region_type:string})=>r.region_type==="formula")).toHaveLength(2);
  const initialKeys=saved.snapshot.nodes.map((n:{stable_key:string})=>n.stable_key);
  const url=`/api/v1/question-import-reviews/${saved.id}`;
  await page.goto(`/question-import-reviews/${saved.id}`);
  const log=audit(page);
  const runtimesBefore=await runtimeEvidence(page);
  const selector=page.getByLabel("対象設問",{exact:true});
  const editor=page.getByLabel("問題文",{exact:true});
  const original=await editor.inputValue();
  await editor.fill(original+"\n未保存の追記");
  await page.getByRole("button",{name:/数式 確認済み.*未確認を表示/}).click();
  const list=page.getByRole("region",{name:"未確認の設問一覧"});
  await expect(list.getByRole("button",{name:/数式未確認/})).toHaveCount(2);
  await list.getByRole("button",{name:/問題2 — 数式未確認/}).click();
  await expect(selector).toHaveValue(initialKeys[1]);
  await expect(page.getByRole("button",{name:"問題文を確認",exact:true})).toBeFocused();
  await page.getByRole("button",{name:"問題文を確認",exact:true}).click();
  await expect(list.getByRole("button",{name:/数式未確認/})).toHaveCount(1);
  await list.getByRole("button",{name:/問題1 — 数式未確認/}).click();
  await expect(selector).toHaveValue(initialKeys[0]);
  await expect(editor).toHaveValue(original+"\n未保存の追記");
  expect(log.writes).toEqual([]); // Issue navigation and confirmation are local.
  await page.getByRole("button",{name:"変更を保存",exact:true}).click();
  await expect(page.getByRole("button",{name:"変更を保存",exact:true})).toBeDisabled();
  // The API intentionally rejects mark-reviewed; its error must list targets.
  const rejected=page.waitForResponse(r=>r.url().endsWith("/mark-reviewed"));
  await page.getByRole("button",{name:"確認済みにする",exact:true}).click();
  expect((await rejected).status()).toBe(422);
  const failure=page.getByRole("alert",{name:"確認エラー"});
  await expect(failure.getByRole("button",{name:/問題1 — 数式未確認/})).toBeVisible();
  await selector.selectOption(initialKeys[1]);
  await failure.getByRole("button",{name:/問題1 — 数式未確認/}).click();
  await expect(selector).toHaveValue(initialKeys[0]);
  await expect(page.getByRole("button",{name:"問題文を確認",exact:true})).toBeFocused();
  await page.getByRole("button",{name:"問題文を確認",exact:true}).click();
  await expect(failure).toHaveCount(0);
  await expect(list.getByRole("button",{name:/数式未確認/})).toHaveCount(0);
  await page.getByRole("button",{name:"変更を保存",exact:true}).click();
  await expect(page.getByRole("button",{name:"変更を保存",exact:true})).toBeDisabled();
  saved=await (await page.request.get(url)).json();
  expect(saved.current_revision).toBeGreaterThan(1);
  // Explicit resume is GET-only, and source SHA, decisions and edits survive.
  expect(log.errors.filter(error => !error.includes("422") ||
    !(error.includes("/mark-reviewed") || error.includes("Failed to load resource")))).toEqual([]);
  log.writes.length=0; log.errors.length=0;
  await page.goto(`/tests/${testId}?section=questions`);
  const sources=page.getByRole("region",{name:"問題用紙登録"});
  await expect(sources.getByRole("button",{name:"question-continuation.pdfの前回の解析結果を編集"})).toBeVisible();
  await expect(sources.getByRole("button",{name:"question-continuation.pdfを再解析する"})).toBeVisible();
  await sources.getByRole("button",{name:"question-continuation.pdfの前回の解析結果を編集"}).click();
  await expect(page).toHaveURL(new RegExp(`/question-import-reviews/${saved.id}$`));
  await selector.selectOption(initialKeys[0]);
  await expect(editor).toHaveValue(original+"\n未保存の追記");
  expect(await (await page.request.get(url)).json()).toEqual(saved);
  expect(log.writes).toEqual([]);
  expect(log.errors).toEqual([]);
  expect(await runtimeEvidence(page)).toEqual(runtimesBefore);
});

test("ModelAnswer and nested Rubric issue links share navigation and saved draft resume is GET-only", async ({page}) => {
  await login(page);
  const draftId=process.env.ANSWER_CONTINUATION_DRAFT_ID!;
  const testId=process.env.ANSWER_CONTINUATION_TEST_ID!;
  const [first,second]=JSON.parse(process.env.ANSWER_CONTINUATION_QUESTION_IDS!);
  const path=`/api/v1/model-answer-import-drafts/${draftId}`;
  const initial=await (await page.request.get(path)).json();
  await page.goto(`/model-answer-import-reviews/${draftId}`);
  const log=audit(page);
  const runtimesBefore=await runtimeEvidence(page);
  const selector=page.getByLabel("編集対象");
  const blockers=page.getByRole("status",{name:"登録できない理由"});
  await expect(blockers).toContainText("問題2 > (2) > 1.");
  await blockers.getByRole("button",{name:/問題2 > \(2\) > 1\..*主な模範解答/}).click();
  await expect(selector).toHaveValue(`question:${first}`);
  await expect(page.locator(".model-answer-import-entry textarea:focus")).toHaveCount(1);
  const local=page.getByLabel("模範解答本文 1",{exact:true});
  await local.fill("Unsaved alternative edit.");
  await page.getByLabel("模範解答 1 の種類").selectOption("primary");
  await expect(blockers).toHaveCount(0);
  const pointIssue=page.getByRole("button",{name:/問題2 > \(2\) > 2\. — 採点基準の配点を確認/});
  await pointIssue.click();
  await expect(selector).toHaveValue(`question:${second}`);
  await expect(page.getByLabel("配点を確認しました",{exact:true})).toBeFocused();
  await page.getByLabel("配点を確認しました",{exact:true}).check();
  await expect(pointIssue).toHaveCount(0);
  const totalIssue=page.getByRole("button",{name:/問題2 > \(2\) > 2\. — 採点基準の配点合計/});
  await totalIssue.click();
  await expect(page.getByLabel("採点基準候補 2-1 の配点",{exact:true})).toBeFocused();
  await page.getByLabel("採点基準候補 2-1 の配点",{exact:true}).fill("10");
  await expect(totalIssue).toHaveCount(0);
  await page.getByRole("button",{name:/設問未割当 — 模範解答候補の設問を指定/}).click();
  await expect(selector).toHaveValue(`unassigned:${initial.entries[2].id}`);
  await expect(page.locator("[data-question-assignment]")).toBeFocused();
  await selector.selectOption(`question:${first}`);
  await expect(local).toHaveValue("Unsaved alternative edit.");
  expect(log.writes).toEqual([]);
  await page.getByRole("button",{name:"下書き保存",exact:true}).click();
  await expect(page.getByText("下書きを保存しました。正式な模範解答はまだ登録されていません。",{exact:true})).toBeVisible();
  const saved=await (await page.request.get(path)).json();
  expect(saved.entries[0].answer_text).toBe("Unsaved alternative edit.");
  expect(saved.entries[1].rubric_edits[0].points_confirmed).toBe(true);
  log.writes.length=0;
  await page.goto(`/tests/${testId}?section=answers`);
  const sources=page.getByRole("region",{name:"模範解答登録"});
  await expect(sources.getByRole("button",{name:"answer-continuation.pdfを再解析する"})).toBeVisible();
  await sources.getByRole("button",{name:"answer-continuation.pdfの前回の解析結果を編集"}).click();
  await expect(page).toHaveURL(new RegExp(`/model-answer-import-reviews/${draftId}$`));
  await selector.selectOption(`question:${first}`);
  await expect(local).toHaveValue("Unsaved alternative edit.");
  await selector.selectOption(`question:${second}`);
  await expect(page.getByLabel("配点を確認しました",{exact:true})).toBeChecked();
  expect(await (await page.request.get(path)).json()).toEqual(saved);
  expect(log.writes).toEqual([]);
  expect(log.errors).toEqual([]);
  expect(await runtimeEvidence(page)).toEqual(runtimesBefore);
  // No implicit formal registration while navigating/saving/resuming.
  expect(await (await page.request.get(`/api/v1/tests/${testId}/model-answers`)).json()).toEqual([]);
  expect(await (await page.request.get(`/api/v1/tests/${testId}/rubrics`)).json()).toEqual([]);
});
