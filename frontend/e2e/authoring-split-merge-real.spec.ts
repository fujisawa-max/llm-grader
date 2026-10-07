import {test,expect,type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";
test.setTimeout(120000);
test.skip(!process.env.AUTHORING_SPLIT_QUESTION_PDF_PATH,"production-like isolated API/runtime fixture required");
async function login(page:Page){await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);}
async function calls(page:Page){return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async p=>{const data=await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${p}/logs?tail=1000`)).json();return data.lines.filter((s:string)=>s.includes("POST /v1/chat/completions")).length;}));}
test("AI split feedback/review and sequential answer/rubric analysis preserve the current source-backed tree",async({page})=>{
 await login(page);await page.setViewportSize({width:1920,height:1080});
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Split then merge",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();
 const select=page.getByLabel("利用資料",{exact:true}),controls=page.getByRole("group",{name:"利用資料の操作"});
 for(const [role,kind] of [["question_sheet","QUESTION"],["model_answer_source","ANSWER"],["rubric_source","RUBRIC"]]){
  await select.selectOption("action:add");await page.getByLabel("資料の種類",{exact:true}).selectOption(role);
  await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:`split-${kind}.pdf`,mimeType:"application/pdf",buffer:await readFile(process.env[`AUTHORING_SPLIT_${kind}_PDF_PATH`]!)});await expect(select).toContainText(`split-${kind}.pdf`);
 }
 await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
 const materials=await(await page.request.get(base+"/materials")).json();
 await select.selectOption(materials.find((m:{material_type:string})=>m.material_type==="question_sheet").id);
 page.once("dialog",d=>d.accept());await controls.getByRole("button",{name:"解析",exact:true}).click();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
 const view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 await expect(editor).toContainText("First task");const text=(await editor.inputValue()).replace("First task","(1) First task").replace("Second task","(2) Second task");await editor.fill(text);
 await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
 let requests=0;await page.route("**/authoring/nodes/*/split-suggest",async route=>{requests++;await new Promise(r=>setTimeout(r,450));await route.continue();});
 await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();const running=page.getByRole("button",{name:"分割案を作成中…",exact:true});await expect(running).toBeDisabled();await expect(running.locator(".spinner")).toBeVisible();await running.evaluate(el=>(el as HTMLButtonElement).click());
 const proposal=page.getByLabel("小問の分割案",{exact:true});await expect(proposal).toBeVisible();expect(requests).toBe(1);await expect(page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true})).toBeEnabled();
 const pendingRevision=(await(await page.request.get(base+"/authoring")).json()).revision;
 await select.selectOption(materials.find((m:{material_type:string})=>m.material_type==="model_answer_source").id);
 await expect(controls.getByRole("button",{name:"解析",exact:true})).toBeDisabled();await expect(proposal.getByRole("status")).toContainText("資料解析は分割案を適用またはキャンセルしてから実行できます");await expect(proposal).toBeVisible();expect((await(await page.request.get(base+"/authoring")).json()).revision).toEqual(pendingRevision);
 await select.selectOption(materials.find((m:{material_type:string})=>m.material_type==="question_sheet").id);
 await expect(proposal.locator('select[aria-label^="分割部分"]')).toHaveCount(3);await expect(proposal.getByLabel("分割部分 1の扱い",{exact:true})).toHaveValue("parent");
 const noCalls=await calls(page);await proposal.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("exclude");await proposal.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("child");
 await page.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(editor).toContainText("First task");await editor.fill((await editor.inputValue())+"\nTeacher changed first child");
 await view.getByRole("button",{name:"設問設定の変更",exact:true}).click();await page.getByLabel("配点の扱い").selectOption("direct");await view.locator('input[type="number"]').fill("5");await view.getByRole("button",{name:"本文編集",exact:true}).click();
 await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();expect(await calls(page)).toEqual(noCalls);
 const before=(await(await page.request.get(base+"/authoring")).json()).revision,tree=before.snapshot.nodes,target=await page.getByLabel("対象設問",{exact:true}).inputValue();expect(tree.filter((n:{parent_key:string|null})=>n.parent_key===tree[0].stable_key)).toHaveLength(2);expect(tree[0].body_text).toContain("Common introduction");expect(tree[0].body_text).not.toContain("First task");
 for(const role of ["model_answer_source","rubric_source"]){
  await select.selectOption(materials.find((m:{material_type:string})=>m.material_type===role).id);page.once("dialog",d=>d.accept());await controls.getByRole("button",{name:"解析",exact:true}).click();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
  const row=(await(await page.request.get(base+"/authoring")).json()).revision;expect(row.snapshot.nodes).toEqual(tree);expect(row.snapshot.domains.answer.analysis_result.assigned_count).toBe(2);expect(await page.getByLabel("対象設問",{exact:true}).inputValue()).toBe(target);
  await expect(page.getByText(/解析結果: 対応済み2件/)).toBeVisible();
 }
 const final=(await(await page.request.get(base+"/authoring")).json()).revision;expect(final.snapshot.answers[target].primary).toContain("Correct answer one");expect(final.snapshot.rubrics[target].length).toBeGreaterThan(0);expect(Object.keys(final.snapshot.domains.answer.sources)).toHaveLength(1);
 await expect(page.getByLabel("問題文",{exact:true})).toContainText("Teacher changed first child");
 await page.getByRole("button",{name:"編集する",exact:true}).first().click();
 const criterion=page.getByLabel("観点",{exact:true}).first();await criterion.fill((await criterion.inputValue())+" teacher rubric edit");
 await expect(page.getByRole("button",{name:"保存",exact:true}).first()).toBeEnabled();await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();await page.reload();expect((await(await page.request.get(base+"/authoring")).json()).revision.snapshot.nodes).toEqual(tree);
 const persisted=(await(await page.request.get(base+"/authoring")).json()).revision,counts=await calls(page);
 await page.getByRole("link",{name:"戻る",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exam.id}$`));await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();expect((await(await page.request.get(base+"/authoring")).json()).revision).toEqual(persisted);expect(await calls(page)).toEqual(counts);
 for(const domain of ["questions","model-answers","rubrics"])expect(await(await page.request.get(base+`/${domain}`)).json()).toEqual([]);
});

test("teacher marks parent/child/excluded blocks; duplicate wrapper rejected, real grandchildren and AI retry preserved",async({page})=>{
 await login(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Review split roles",total_points:10}})).json();
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const selector=page.getByLabel("対象設問",{exact:true}),parent=await selector.inputValue(),view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 await editor.fill("intro\n(1) first\n(2) retained\n(3) discarded");await page.getByRole("button",{name:"小問の分割案を作成",exact:true}).click();
 await page.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("parent");await page.getByLabel("分割部分 4の扱い",{exact:true}).selectOption("exclude");const count=await calls(page);
 await page.getByRole("button",{name:"分割を適用",exact:true}).click();const child=await selector.inputValue();await selector.selectOption(parent);await expect(editor).toContainText("intro");await expect(editor).toContainText("retained");expect(await editor.inputValue()).not.toContain("discarded");expect(await editor.inputValue()).not.toContain("first");expect(await calls(page)).toEqual(count);
 await selector.selectOption(child);await editor.fill("(1) Shared stem\n1. Deep A\n2. Deep B [split_failure]");await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
 await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();await expect(page.getByRole("alert").filter({hasText:"分割案を取得できませんでした"})).toBeVisible();await expect(editor).toContainText("[split_failure]");await expect(page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true})).toBeEnabled();
 await editor.fill("(1) Shared stem\n1. Deep A\n2. Deep B");await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();await expect(page.getByLabel("小問の分割案",{exact:true})).toBeVisible();await expect(page.getByLabel("分割部分 1の扱い",{exact:true})).toHaveValue("parent");
 await page.getByLabel("分割部分 1の扱い",{exact:true}).selectOption("child");await page.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(page.getByRole("alert").filter({hasText:"重複"})).toBeVisible();await expect(selector).toHaveValue(child);
 await page.getByLabel("分割部分 1の扱い",{exact:true}).selectOption("parent");await page.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(editor).toContainText("Deep A");await expect(selector.locator("option").filter({hasText:"問題1 > (1) > 1."})).toHaveCount(1);await expect(selector.locator("option").filter({hasText:"問題1 > (1) > (1)"})).toHaveCount(0);
 await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();await page.reload();const row=(await(await page.request.get(`/api/v1/tests/${exam.id}/authoring`)).json()).revision;expect(row.snapshot.nodes.filter((n:{parent_key:string|null})=>n.parent_key===child)).toHaveLength(2);expect(JSON.stringify(row.snapshot.nodes)).not.toContain("discarded");expect(await(await page.request.get(`/api/v1/tests/${exam.id}/questions`)).json()).toEqual([]);
});


test("unmatched analysis is actionable and retained for explicit manual assignment",async({page})=>{
 await login(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Unresolved analysis",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();
 const target=await page.getByLabel("対象設問",{exact:true}).inputValue(),view=page.getByLabel("問題の表示切替",{exact:true});
 await view.getByRole("button",{name:"設問設定の変更",exact:true}).click();await page.getByLabel(/設問番号・見出し/).fill("問題9");
 const select=page.getByLabel("利用資料",{exact:true});await select.selectOption("action:add");await page.getByLabel("資料の種類",{exact:true}).selectOption("model_answer_source");
 await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"unmatched.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.AUTHORING_SPLIT_ANSWER_PDF_PATH!)});
 await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
 const tree=(await(await page.request.get(base+"/authoring")).json()).revision.snapshot.nodes;
 page.once("dialog",d=>d.accept());await page.getByRole("group",{name:"利用資料の操作"}).getByRole("button",{name:"解析",exact:true}).click();
 await expect(page.getByRole("alert").filter({hasText:"解析結果を設問へ対応付けできませんでした"})).toBeVisible();
 const row=(await(await page.request.get(base+"/authoring")).json()).revision;expect(row.snapshot.nodes).toEqual(tree);expect(row.snapshot.domains.answer.analysis_result.assigned_count).toBe(0);expect(row.snapshot.domains.answer.entries.length).toBeGreaterThan(0);
 const count=await calls(page);await page.getByLabel("解答の表示切替",{exact:true}).first().getByRole("button",{name:"本文編集",exact:true}).click();await page.getByLabel("対応する設問",{exact:true}).first().selectOption(target);await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
 expect(await calls(page)).toEqual(count);const saved=(await(await page.request.get(base+"/authoring")).json()).revision;expect(saved.snapshot.nodes).toEqual(tree);expect(saved.snapshot.answers[target].primary).toBeTruthy();
 expect(await(await page.request.get(base+"/model-answers")).json()).toEqual([]);
});
