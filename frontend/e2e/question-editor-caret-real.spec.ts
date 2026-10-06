import {test, expect} from "@playwright/test";
import {readFile} from "node:fs/promises";
import {assertDesktopReviewLayout, assertNarrowReviewLayout} from "./review-layout-assertions";
test.skip(!process.env.QUESTION_CARET_TEST_ID, "isolated Question source fixture required");

test("Question newline joining keeps the edit location and editor DOM identity", async ({page}) => {
  await page.setViewportSize({width:1920,height:1080});
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("dialog", dialog => dialog.accept());
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  page.on("console", event => {if(event.type() === "error") errors.push(event.text());});
  const upload = await page.request.post(`/api/v1/tests/${process.env.QUESTION_CARET_TEST_ID}/question-materials`, {
    headers:{"content-type":"application/pdf","x-filename":"caret-question.pdf"},
    data:await readFile(process.env.QUESTION_CARET_PDF_PATH!)});
  expect(upload.status()).toBe(201);
  const extraction = await upload.json();
  const draft = await (await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();
  const initial = await (await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).json();
  const path = `/api/v1/question-import-reviews/${initial.id}`;
  const read = async () => (await page.request.get(path)).json();
  const formal = async () => (await page.request.get(`/api/v1/tests/${process.env.QUESTION_CARET_TEST_ID}/questions`)).json();
  const formalBefore = await formal();
  let revisionCalls = 0, modelCalls = 0;
  page.on("request", request => {
    if(request.method() === "POST" && request.url().endsWith("/revisions")) revisionCalls++;
    if(request.url().endsWith("/math-ocr") || request.url().endsWith("/latex-normalize")) modelCalls++;
  });
  await page.goto(`/question-import-reviews/${initial.id}`);
  const editor = page.getByLabel("問題文", {exact:true});
  await expect(editor).toBeEditable();
  await assertDesktopReviewLayout(page, "対象設問");
  await assertNarrowReviewLayout(page, "対象設問");
  const original = await editor.inputValue();
  expect(original.split("\n").length).toBeGreaterThanOrEqual(3);
  const join = original.indexOf("\n",original.indexOf("2変数"));
  await editor.evaluate((element, at) => {
    const area=element as HTMLTextAreaElement;
    (window as unknown as {originalEditor:HTMLTextAreaElement}).originalEditor=area;
    area.focus(); area.setSelectionRange(at,at);
  },join);
  await editor.press("Delete");
  const observation = await editor.evaluate(element => {
    const area=element as HTMLTextAreaElement;
    return {text:area.value, start:area.selectionStart,end:area.selectionEnd,
      sameDOM:(window as unknown as {originalEditor:HTMLTextAreaElement}).originalEditor===area};
  });
  console.log("newline deletion observation", JSON.stringify({join,...observation}));
  expect(observation.sameDOM).toBe(true);
  expect(observation.text).toBe(original.slice(0,join)+original.slice(join+1));
  expect(observation.start).toBe(join);
  expect(observation.end).toBe(join);
  const joined = original.slice(0,join)+original.slice(join+1);
  const caret = async (at: number, end = at) => editor.evaluate((element, range) => {
    const area=element as HTMLTextAreaElement; area.focus(); area.setSelectionRange(range.at,range.end);
  }, {at,end});
  const assertEdit = async (text: string, at: number) => {
    await expect(editor).toHaveValue(text);
    expect(await editor.evaluate(element => {
      const area=element as HTMLTextAreaElement;
      return {start:area.selectionStart,end:area.selectionEnd,sameDOM:(window as unknown as {originalEditor:HTMLTextAreaElement}).originalEditor===area};
    })).toEqual({start:at,end:at,sameDOM:true});
  };
  // Native newline insertion, undo/redo, and Backspace across the boundary.
  await editor.press("Enter");
  await assertEdit(original,join+1);
  await editor.press("Control+z");
  await assertEdit(joined,join);
  await editor.press("Control+Shift+z");
  await assertEdit(original,join+1);
  await editor.press("Backspace");
  await assertEdit(joined,join);
  await editor.pressSequentially("x  y");
  await assertEdit(joined.slice(0,join)+"x  y"+joined.slice(join),join+4);
  await editor.press("Backspace");
  await assertEdit(joined.slice(0,join)+"x  "+joined.slice(join),join+3);
  await editor.press("Delete");
  await assertEdit(joined.slice(0,join)+"x  "+joined.slice(join+1),join+3);

  // Exercise the browser's actual clipboard paste, without requiring the
  // secure-origin Clipboard API on the non-loopback HTTP fixture.
  const pasted = "貼り付け\n複数行";
  await editor.fill(original+"\n"+pasted);
  await caret(original.length+1,original.length+1+pasted.length);
  await editor.press("Control+c");
  await editor.fill(original);
  await caret(join);
  await editor.press("Control+v");
  await assertEdit(original.slice(0,join)+pasted+original.slice(join),join+pasted.length);
  await caret(join,join+pasted.length);
  await editor.press("Delete");
  await assertEdit(original,join);
  await caret(join,join+5);
  await page.keyboard.insertText("連結");
  await assertEdit(original.slice(0,join)+"連結"+original.slice(join+5),join+2);

  // Chromium composition events and commit through its IME protocol. This
  // exercises native composition/input; OS conversion-candidate UI is manual.
  await editor.fill(original);
  await caret(join);
  const client = await page.context().newCDPSession(page);
  await editor.evaluate(element => {
    (window as unknown as {compositionEvents:string[]}).compositionEvents=[];
    for(const event of ["compositionstart","compositionupdate","compositionend"])
      element.addEventListener(event, e => (window as unknown as {compositionEvents:string[]}).compositionEvents.push(e.type));
  });
  await client.send("Input.imeSetComposition", {text:"にほん",selectionStart:3,selectionEnd:3});
  await assertEdit(original.slice(0,join)+"にほん"+original.slice(join),join+3);
  expect(revisionCalls).toBe(0); expect(modelCalls).toBe(0);
  await client.send("Input.insertText", {text:"日本語"});
  await assertEdit(original.slice(0,join)+"日本語"+original.slice(join),join+3);
  expect(await page.evaluate(() => (window as unknown as {compositionEvents:string[]}).compositionEvents)).toEqual([
    "compositionstart","compositionupdate","compositionupdate","compositionend"]);
  await client.detach();

  // Incomplete Markdown/LaTeX and repeated spaces remain exact local text.
  const partial = original+"\n** $\\frac{  未確定";
  await editor.fill(partial);
  await expect(editor).toHaveValue(partial);
  expect(await read()).toEqual(initial);
  const selector = page.getByRole("combobox", {name:"対象設問",exact:true});
  const keys = await selector.locator("option").evaluateAll(options => options.map(option => (option as HTMLOptionElement).value));
  await selector.selectOption(keys[1]);
  const sibling = await editor.inputValue();
  await editor.fill(sibling+" 未保存の追記");
  await selector.selectOption(keys[0]);
  await expect(editor).toHaveValue(partial);
  await selector.selectOption(keys[1]);
  await expect(editor).toHaveValue(sibling+" 未保存の追記");
  await editor.fill(sibling);
  await selector.selectOption(keys[0]);
  // Persist a joined native item boundary, retaining all source anchors.
  await editor.fill(joined);
  expect(await read()).toEqual(initial);
  expect(await formal()).toEqual(formalBefore);
  expect(revisionCalls).toBe(0); expect(modelCalls).toBe(0);
  const saved = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/revisions"));
  await page.getByRole("button", {name:"変更を保存",exact:true}).click();
  expect((await saved).status()).toBe(200);
  const server = await read();
  expect(server.current_revision).toBe(initial.current_revision+1);
  expect(server.snapshot.nodes[1]).toEqual(initial.snapshot.nodes[1]);
  const anchors = (items: {source_element_ids?: string[];merged_source_segments?: {source_element_ids?: string[]}[]}[]) =>
    items.flatMap(item => [...(item.source_element_ids || []),...(item.merged_source_segments || []).flatMap(segment => segment.source_element_ids || [])]);
  expect(anchors(server.snapshot.nodes[0].ordered_content)).toEqual(anchors(initial.snapshot.nodes[0].ordered_content));
  expect(await formal()).toEqual(formalBefore);
  await page.reload();
  await expect(editor).toHaveValue(joined);
  expect(revisionCalls).toBe(1); expect(modelCalls).toBe(0);
  expect(errors).toEqual([]);
});

test("native item separators and raw formula typing stay local; unsafe score boundaries fail closed on Save", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button", {name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  page.on("console", event => {if(event.type() === "error") errors.push(event.text());});
  const upload = await page.request.post(`/api/v1/tests/${process.env.QUESTION_CARET_TEST_ID}/question-materials`, {
    headers:{"content-type":"application/pdf","x-filename":"native-item-caret.pdf"},
    data:await readFile(process.env.QUESTION_MATH_PDF_PATH!)});
  expect(upload.status()).toBe(201);
  const extraction=await upload.json();
  const draftResponse=await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`);
  expect(draftResponse.status()).toBe(201);
  const draft=await draftResponse.json();
  const created=await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`);
  expect(created.status()).toBe(201);
  const initial=await created.json();
  const read = async () => (await page.request.get(`/api/v1/question-import-reviews/${initial.id}`)).json();
  let saves=0, modelCalls=0;
  page.on("request", request => {
    if(request.method() === "POST" && request.url().endsWith("/revisions")) saves++;
    if(request.url().endsWith("/math-ocr") || request.url().endsWith("/latex-normalize")) modelCalls++;
  });
  await page.goto(`/question-import-reviews/${initial.id}`);
  const editor=page.getByLabel("問題文",{exact:true});
  const original=await editor.inputValue();
  const dom=await editor.elementHandle();
  const at=original.indexOf("\n");
  await editor.evaluate((element, position) => {
    const area=element as HTMLTextAreaElement; area.focus(); area.setSelectionRange(position,position);
  },at);
  await editor.press("Delete");
  const joined=original.slice(0,at)+original.slice(at+1);
  await expect(editor).toHaveValue(joined);
  expect(await editor.evaluate(element => (element as HTMLTextAreaElement).selectionStart)).toBe(at);
  expect(await editor.evaluate((element, before) => element===before,dom)).toBe(true);
  await page.getByRole("button",{name:"変更を保存",exact:true}).click();
  await expect(page.getByRole("alert",{name:"保存エラー"})).toContainText("元資料との対応を確認できません");
  await expect(editor).toHaveValue(joined);
  expect(await read()).toEqual(initial); expect(saves).toBe(0);
  await editor.fill(original);
  const formulaAt=original.indexOf("Precision=")+5;
  await editor.evaluate((element, position) => {
    const area=element as HTMLTextAreaElement; area.focus(); area.setSelectionRange(position,position);
  },formulaAt);
  await editor.pressSequentially("x");
  const raw=original.slice(0,formulaAt)+"x"+original.slice(formulaAt);
  await expect(editor).toHaveValue(raw); // No automatic dollar delimiters/reprojection.
  expect(await editor.evaluate(element => (element as HTMLTextAreaElement).selectionStart)).toBe(formulaAt+1);
  expect(await editor.evaluate((element, before) => element===before,dom)).toBe(true);
  const saved=page.waitForResponse(response => response.request().method()==="POST" && response.url().endsWith("/revisions"));
  await page.getByRole("button",{name:"変更を保存",exact:true}).click();
  expect((await saved).status()).toBe(200);
  const server=await read();
  expect(server.snapshot.nodes[0].ordered_content).toEqual(initial.snapshot.nodes[0].ordered_content);
  expect(Object.values(server.snapshot.nodes[0].formula_decisions)).toContainEqual(expect.objectContaining({
    decision:"teacher_edit",confirmation_status:"unreviewed",teacher_transcription:expect.stringContaining("Precixsion=")}));
  await page.reload();
  await expect(editor).toHaveValue(raw);
  expect(saves).toBe(1); expect(modelCalls).toBe(0);
  expect(errors).toEqual([]);
});
