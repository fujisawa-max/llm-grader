import {confirmAnalysis,saveAuthoring} from "./authoringNotifications";
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
  await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:`split-${kind}.pdf`,mimeType:"application/pdf",buffer:await readFile(process.env[`AUTHORING_SPLIT_${kind}_PDF_PATH`]!)});await expect(select).toContainText(`split-${kind}.pdf`);await page.getByRole("button",{name:"いいえ",exact:true}).click();
 }
 await saveAuthoring(page);
 const materials=await(await page.request.get(base+"/materials")).json();
 await select.selectOption(materials.find((m:{material_type:string})=>m.material_type==="question_sheet").id);
 await confirmAnalysis(page,controls,"解析");await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
 const view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 await expect(editor).toContainText("First task");const text=(await editor.inputValue()).replace("First task","(1) First task").replace("Second task","(2) Second task");await editor.fill(text);
 await saveAuthoring(page);
 let requests=0;await page.route("**/authoring/nodes/*/split-suggest",async route=>{requests++;await new Promise(r=>setTimeout(r,450));await route.continue();});
 await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();const running=page.getByRole("button",{name:"分割案を作成中…",exact:true});await expect(running).toBeDisabled();await expect(running.locator(".spinner")).toBeVisible();await running.evaluate(el=>(el as HTMLButtonElement).click());
 const proposal=page.getByRole("dialog",{name:/の分割案/});await expect(proposal).toBeVisible();expect(requests).toBe(1);await expect(page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true})).toBeEnabled();
 const pendingRevision=(await(await page.request.get(base+"/authoring")).json()).revision;
 await expect(proposal).toBeVisible();expect((await(await page.request.get(base+"/authoring")).json()).revision).toEqual(pendingRevision);
 await expect(proposal.locator('select[aria-label^="分割部分"]')).toHaveCount(3);await expect(proposal.getByLabel("分割部分 1の扱い",{exact:true})).toHaveValue("parent");
 const blocks=proposal.locator(".authoring-split-block");await expect(blocks).toHaveCount(3);
 await expect(proposal.locator(".authoring-split-divider")).toHaveCount(2);
 for(const block of await blocks.all())await expect(block.locator(".authoring-split-divider")).toHaveCount(0);
 const dividerPositions=await proposal.locator(".authoring-split-divider").evaluateAll(nodes=>nodes.map(node=>({previous:node.previousElementSibling?.className,next:node.nextElementSibling?.className})));
 expect(dividerPositions).toEqual([{previous:"authoring-split-block",next:"authoring-split-block"},{previous:"authoring-split-block",next:"authoring-split-block"}]);

 const noCalls=await calls(page);await proposal.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("exclude");await proposal.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("child");
 await proposal.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(editor).toContainText("First task");await editor.fill((await editor.inputValue())+"\nTeacher changed first child");
 await view.getByRole("button",{name:"設問設定の変更",exact:true}).click();await page.getByLabel("配点の扱い").selectOption("direct");await view.locator('input[type="number"]').fill("5");await view.getByRole("button",{name:"本文編集",exact:true}).click();
 await saveAuthoring(page);expect(await calls(page)).toEqual(noCalls);
 const before=(await(await page.request.get(base+"/authoring")).json()).revision,tree=before.snapshot.nodes,target=await page.getByLabel("対象設問",{exact:true}).inputValue(),root=tree.find((n:{parent_key:string|null})=>n.parent_key===null);expect(root).toBeTruthy();expect(tree.filter((n:{parent_key:string|null})=>n.parent_key===root.stable_key)).toHaveLength(2);expect(root.body_text).toContain("Common introduction");expect(root.body_text).not.toContain("First task");
 for(const role of ["model_answer_source","rubric_source"]){
  const before=(await(await page.request.get(base+"/authoring")).json()).revision.snapshot;
  await select.selectOption(materials.find((m:{material_type:string})=>m.material_type===role).id);await confirmAnalysis(page,controls,"解析");await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
  const row=(await(await page.request.get(base+"/authoring")).json()).revision;expect(row.snapshot.nodes).toEqual(tree);expect(await page.getByLabel("対象設問",{exact:true}).inputValue()).toBe(target);
  if(role==="model_answer_source"){
   expect(row.snapshot.domains.answer.analysis_result.assigned_count).toBe(2);expect(row.snapshot.domains.rubric).toEqual(before.domains.rubric);
   const answerToggle=page.getByRole("checkbox",{name:"解答",exact:true});if(!(await answerToggle.isChecked()))await answerToggle.check();
   await page.getByRole("region",{name:"模範解答候補",exact:true}).first().getByRole("button",{name:"本文編集",exact:true}).click();
   const diagram=page.getByRole("region",{name:"模範解答の図",exact:true}).first(),discover=diagram.getByRole("button",{name:"図候補を確認",exact:true});
   await expect(discover).toBeEnabled();await expect(diagram.getByText("設問の構造・対応先の変更を保存してから、図候補を確認してください。",{exact:true})).toHaveCount(0);
   const discovery=page.waitForResponse(response=>response.request().method()==="POST"&&/\/authoring\/entries\/[^/]+\/diagrams/.test(response.url()));await discover.click();expect((await discovery).status()).toBe(200);
  }else{expect(row.snapshot.domains.rubric.analysis_result.assigned_count).toBe(2);expect(row.snapshot.domains.answer).toEqual(before.domains.answer);}
  await expect(page.locator(".authoring-toast").filter({hasText:role==="rubric_source"?"採点基準を解析しました":"模範解答を解析しました"}).filter({hasText:"対応済み2件 / 未対応"})).toBeVisible();
 }
 const final=(await(await page.request.get(base+"/authoring")).json()).revision;expect(final.snapshot.answers[target].primary).toContain("Correct answer one");expect(final.snapshot.rubrics[target].length).toBeGreaterThan(0);expect(final.snapshot.domains.answer.material_role).toBe("model_answer_source");expect(final.snapshot.domains.rubric.material_role).toBe("rubric_source");
 await expect(page.getByRole("heading",{name:"問題",exact:true})).toBeVisible();await expect(page.getByRole("heading",{name:"模範解答",exact:true})).toBeVisible();await expect(page.getByRole("heading",{name:"採点基準",exact:true})).toBeVisible();
 await expect(page.getByLabel("問題文",{exact:true})).toContainText("Teacher changed first child");
 await page.getByRole("button",{name:"編集する",exact:true}).first().click();
 const criterion=page.getByLabel(/^基準\d+の本文$/).first();await criterion.fill((await criterion.inputValue())+" teacher rubric edit");
 await expect(page.getByRole("button",{name:"保存",exact:true}).first()).toBeEnabled();await saveAuthoring(page);await page.reload();expect((await(await page.request.get(base+"/authoring")).json()).revision.snapshot.nodes).toEqual(tree);
 const persisted=(await(await page.request.get(base+"/authoring")).json()).revision,counts=await calls(page);
 await page.getByRole("link",{name:"戻る",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exam.id}$`));await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();expect((await(await page.request.get(base+"/authoring")).json()).revision).toEqual(persisted);expect(await calls(page)).toEqual(counts);
 for(const domain of ["questions","model-answers","rubrics"])expect(await(await page.request.get(base+`/${domain}`)).json()).toEqual([]);
});

test("teacher marks parent/child/excluded blocks; duplicate wrapper rejected, real grandchildren and AI retry preserved",async({page})=>{
 await login(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Review split roles",total_points:10}})).json();
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const selector=page.getByLabel("対象設問",{exact:true}),parent=await selector.inputValue(),view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 await editor.fill("intro\n(1) first\n(2) retained\n(3) discarded");const beforeCancel=(await(await page.request.get("/api/v1/tests/"+exam.id+"/authoring")).json()).revision.snapshot;await page.getByRole("button",{name:"小問の分割案を作成",exact:true}).click();
 const proposal=page.getByRole("dialog",{name:/の分割案/});await expect(proposal).toBeVisible();
 await expect(page.getByRole("region",{name:"小問の分割案",exact:true})).toHaveCount(0);
 await expect.poll(()=>proposal.evaluate(dialog=>dialog.contains(document.activeElement))).toBe(true);
 await page.keyboard.press("Escape");await expect(proposal).toHaveCount(0);
 expect((await(await page.request.get("/api/v1/tests/"+exam.id+"/authoring")).json()).revision.snapshot).toEqual(beforeCancel);
 await page.getByRole("button",{name:"小問の分割案を作成",exact:true}).click();await expect(proposal).toBeVisible();
 await proposal.getByLabel("分割部分 3の扱い",{exact:true}).selectOption("parent");await proposal.getByLabel("分割部分 4の扱い",{exact:true}).selectOption("exclude");const count=await calls(page);
 await proposal.getByRole("button",{name:"分割を適用",exact:true}).click();const child=await selector.inputValue();await selector.selectOption(parent);await expect(editor).toContainText("intro");await expect(editor).toContainText("retained");expect(await editor.inputValue()).not.toContain("discarded");expect(await editor.inputValue()).not.toContain("first");expect(await calls(page)).toEqual(count);
 await selector.selectOption(child);await editor.fill("(1) Shared stem\n1. Deep A\n2. Deep B [split_failure]");await saveAuthoring(page);
 await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();await expect(page.getByRole("alert").filter({hasText:"分割案を取得できませんでした"})).toBeVisible();await expect(editor).toContainText("[split_failure]");await expect(page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true})).toBeEnabled();
 await editor.fill("(1) Shared stem\n1. Deep A\n2. Deep B");await page.getByRole("button",{name:"AIで小問の分割案を作成",exact:true}).click();const nestedProposal=page.getByRole("dialog",{name:/の分割案/});await expect(nestedProposal).toBeVisible();await expect(nestedProposal.getByLabel("分割部分 1の扱い",{exact:true})).toHaveValue("parent");
 await nestedProposal.getByLabel("分割部分 1の扱い",{exact:true}).selectOption("child");await nestedProposal.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(page.getByRole("alert").filter({hasText:"重複"})).toBeVisible();await expect(selector).toHaveValue(child);
 await nestedProposal.getByLabel("分割部分 1の扱い",{exact:true}).selectOption("parent");await nestedProposal.getByRole("button",{name:"分割を適用",exact:true}).click();await expect(editor).toContainText("Deep A");await expect(selector.locator("option").filter({hasText:"問題1 > (1) > 1."})).toHaveCount(1);await expect(selector.locator("option").filter({hasText:"問題1 > (1) > (1)"})).toHaveCount(0);
 await saveAuthoring(page);await page.reload();const row=(await(await page.request.get(`/api/v1/tests/${exam.id}/authoring`)).json()).revision;expect(row.snapshot.nodes.filter((n:{parent_key:string|null})=>n.parent_key===child)).toHaveLength(2);expect(JSON.stringify(row.snapshot.nodes)).not.toContain("discarded");expect(await(await page.request.get(`/api/v1/tests/${exam.id}/questions`)).json()).toEqual([]);
});


test("unmatched analysis is actionable and retained for explicit manual assignment",async({page})=>{
 await login(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Unresolved analysis",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();
 const target=await page.getByLabel("対象設問",{exact:true}).inputValue(),view=page.getByLabel("問題の表示切替",{exact:true});
 await view.getByRole("button",{name:"設問設定の変更",exact:true}).click();await page.getByLabel(/設問番号・見出し/).fill("問題9");
 const select=page.getByLabel("利用資料",{exact:true});await select.selectOption("action:add");await page.getByLabel("資料の種類",{exact:true}).selectOption("model_answer_source");
 await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"unmatched.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.AUTHORING_SPLIT_ANSWER_PDF_PATH!)});await page.getByRole("button",{name:"いいえ",exact:true}).click();
 await saveAuthoring(page);
 const tree=(await(await page.request.get(base+"/authoring")).json()).revision.snapshot.nodes;
 await confirmAnalysis(page,page.getByRole("group",{name:"利用資料の操作"}),"解析");
 await expect(page.getByRole("alert").filter({hasText:"設問未割当の候補から確認・割当してください"})).toBeVisible();
 await expect(page.getByLabel("対象設問",{exact:true})).toHaveValue("unassigned");
 const row=(await(await page.request.get(base+"/authoring")).json()).revision;expect(row.snapshot.nodes).toEqual(tree);expect(row.snapshot.domains.answer.analysis_result.assigned_count).toBe(0);expect(row.snapshot.domains.answer.entries.length).toBeGreaterThan(0);
 const count=await calls(page);await page.getByLabel("解答の表示切替",{exact:true}).first().getByRole("button",{name:"本文編集",exact:true}).click();await page.getByLabel("対応する設問",{exact:true}).first().selectOption(target);await saveAuthoring(page);
 expect(await calls(page)).toEqual(count);const saved=(await(await page.request.get(base+"/authoring")).json()).revision;expect(saved.snapshot.nodes).toEqual(tree);expect(saved.snapshot.answers[target].primary).toBeTruthy();
 expect(await(await page.request.get(base+"/model-answers")).json()).toEqual([]);
});

test("saved Q3 split discovers only Q3 parent diagrams and shares accepted diagrams with sibling children",async({page})=>{
 await test.skip(!process.env.AUTHORING_SPLIT_DIAGRAM_TEST_ID||!process.env.RUNTIME_MANAGER_E2E,"isolated diagram authoring fixture required");
 await login(page);await page.setViewportSize({width:1440,height:900});
 const tid=process.env.AUTHORING_SPLIT_DIAGRAM_TEST_ID!,base=`/api/v1/tests/${tid}`,authoring=`${base}/authoring`;
 const formalQuestionsBefore=await(await page.request.get(`${base}/questions`)).json();
 const importResponse=await page.request.post(`${base}/model-answer-imports`,{data:{material_id:process.env.AUTHORING_SPLIT_DIAGRAM_MATERIAL_ID}});expect(importResponse.status(),await importResponse.text()).toBe(201);
 await page.goto(`/tests/${tid}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();
 const row=(await(await page.request.get(authoring)).json()).revision,parent=row.snapshot.nodes.find((n:{label:{raw:string}})=>n.label.raw==="問題3");expect(parent).toBeTruthy();
 const selector=page.getByLabel("対象設問",{exact:true}),questionView=page.getByLabel("問題の表示切替",{exact:true});await selector.selectOption(parent.stable_key);await questionView.getByRole("button",{name:"本文編集",exact:true}).click();
 const editor=page.getByLabel("問題文",{exact:true});await editor.fill("問題3\n(1) 第一の確認\n(2) 第二の確認\n(3) 第三の確認");await page.getByRole("button",{name:"小問の分割案を作成",exact:true}).click();
 const proposal=page.getByRole("dialog",{name:/問題3の分割案/});await expect(proposal).toBeVisible();await expect(proposal.locator(".authoring-split-block")).toHaveCount(4);await proposal.getByRole("button",{name:"分割を適用",exact:true}).click();
 await saveAuthoring(page);let saved=(await(await page.request.get(authoring)).json()).revision;const children=saved.snapshot.nodes.filter((n:{parent_key:string|null;included:boolean})=>n.parent_key===parent.stable_key&&n.included).sort((a:{sort_order:number},b:{sort_order:number})=>a.sort_order-b.sort_order);expect(children).toHaveLength(3);
 await selector.selectOption(children[0].stable_key);const answerSection=page.locator("#authoring-answer"),addAnswer=answerSection.getByRole("button",{name:"模範解答を追加",exact:true});await addAnswer.click();await saveAuthoring(page);
 const firstEntry=(await(await page.request.get(authoring)).json()).revision.snapshot.domains.answer.entries.find((entry:{authoring_question_key:string})=>entry.authoring_question_key===children[0].stable_key);expect(firstEntry).toBeTruthy();
 const firstCandidate=page.locator(`#authoring-candidate-${firstEntry.id}`);await firstCandidate.getByRole("button",{name:"本文編集",exact:true}).click();const firstDiagram=firstCandidate.getByRole("region",{name:"模範解答の図",exact:true});
 const parentDiscovery=page.waitForResponse(response=>response.request().method()==="POST"&&response.url().includes("scope=parent"));await firstDiagram.getByRole("button",{name:"図候補を確認",exact:true}).click();expect((await parentDiscovery).status()).toBe(200);
 await expect(firstDiagram.getByAltText("図1の切り出し範囲",{exact:true})).toBeVisible();await expect(firstDiagram.locator("[data-diagram-id]")).toHaveCount(1);await expect(firstDiagram.getByText("図の範囲が設問の出典範囲を超えています。",{exact:true})).toHaveCount(0);
 const acceptedButton=firstDiagram.getByRole("button",{name:"この図を使用",exact:true});await expect(acceptedButton).toBeEnabled();await acceptedButton.click();await saveAuthoring(page);
 await selector.selectOption(children[1].stable_key);const addSibling=answerSection.getByRole("button",{name:"模範解答を追加",exact:true});await addSibling.click();await saveAuthoring(page);
 saved=(await(await page.request.get(authoring)).json()).revision;const siblingEntry=saved.snapshot.domains.answer.entries.find((entry:{authoring_question_key:string})=>entry.authoring_question_key===children[1].stable_key);expect(siblingEntry).toBeTruthy();
 const sibling=page.locator(`#authoring-candidate-${siblingEntry.id}`),siblingEdit=sibling.getByRole("button",{name:"本文編集",exact:true});if(await siblingEdit.count())await siblingEdit.click();const siblingDiagram=sibling.getByRole("region",{name:"模範解答の図",exact:true});await expect(siblingDiagram.getByText("この大問ですでに使用している図",{exact:true})).toBeVisible();await expect(siblingDiagram.getByAltText("再利用できる図",{exact:true})).toBeVisible();await siblingDiagram.getByRole("button",{name:"この図を再利用",exact:true}).click();await saveAuthoring(page);
 const answerBeforeRubric=(await(await page.request.get(authoring)).json()).revision.snapshot.domains.answer;
 const rubricBinding=await(await page.request.post(`${base}/materials/${process.env.AUTHORING_SPLIT_DIAGRAM_MATERIAL_ID}/reuse`,{data:{material_type:"rubric_source"}})).json();
 const current=(await(await page.request.get(authoring)).json()).revision,analyzed=await page.request.post(`${authoring}/analyze-answer`,{data:{material_id:rubricBinding.id,expected_edit_version:current.edit_version,preserve_previous:true}});expect(analyzed.status(),await analyzed.text()).toBe(200);
 expect((await analyzed.json()).snapshot.domains.answer).toEqual(answerBeforeRubric);await page.reload();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();await selector.selectOption(children[1].stable_key);const siblingEditAfterReload=sibling.getByRole("button",{name:"本文編集",exact:true});if(await siblingEditAfterReload.count())await siblingEditAfterReload.click();await expect(siblingDiagram.getByText("この大問ですでに使用している図",{exact:true})).toBeVisible();await expect(siblingDiagram.getByRole("button",{name:"使用中",exact:true})).toBeDisabled();
 const persisted=(await(await page.request.get(authoring)).json()).revision;await page.getByRole("link",{name:"戻る",exact:true}).click();await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();expect((await(await page.request.get(authoring)).json()).revision).toEqual(persisted);await selector.selectOption(children[1].stable_key);const siblingEditAfterResume=sibling.getByRole("button",{name:"本文編集",exact:true});if(await siblingEditAfterResume.count())await siblingEditAfterResume.click();await expect(siblingDiagram.getByRole("button",{name:"使用中",exact:true})).toBeDisabled();
 expect(await(await page.request.get(`${base}/questions`)).json()).toEqual(formalQuestionsBefore);
});
