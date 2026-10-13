import {editQuestionText,readQuestionText,openQuestionOperations} from "./authoringEditMode";
import {canonicalQuestionRoot} from "../lib/canonicalQuestionPath";
import {readFile} from "node:fs/promises";
import {execFileSync} from "node:child_process";
import {test,expect,type Page} from "@playwright/test";
import {confirmAnalysis,saveAuthoring} from "./authoringNotifications";

test.setTimeout(180000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,"requires disposable real API / RuntimeManager harness");

async function calls(page:Page){return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async profile=>{const data=await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();return data.lines.filter((line:string)=>line.includes("POST /v1/chat/completions")).length;}));}

test("real Sample Q5 revision history forks exact diagrams and confirms an independent second edition",async({page},testInfo)=>{
 const productionExclusion=false;
 await page.setViewportSize({width:1600,height:1000});
 await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);
 const expectedReviewConflicts:Promise<void>[]=[];page.on("response",response=>{if(response.status()===409&&/\/authoring\/review$/.test(response.url()))expectedReviewConflicts.push(response.json().then(body=>{expect(body.error.message).toBe("AUTHORING_SAVE_CONFLICT");}));});
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));page.on("console",message=>{if(message.type()==="error")errors.push(message.text());});
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Sample Q5 three-child inclusion",total_points:100}});expect(created.status()).toBe(201);const tid=(await created.json()).id,base=`/api/v1/tests/${tid}`,authoring=base+"/authoring";
 await page.goto(`/tests/${tid}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();
 const materialSelect=page.getByLabel("利用資料",{exact:true}),controls=page.getByRole("group",{name:"利用資料の操作",exact:true}),selector=page.getByLabel("対象設問",{exact:true});
 async function add(role:string,file:string){await materialSelect.selectOption("action:add");await page.getByLabel("資料の種類",{exact:true}).selectOption(role);await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:file.split("/").at(-1)!,mimeType:"application/pdf",buffer:await readFile(file)});await page.getByRole("button",{name:"いいえ",exact:true}).click();await saveAuthoring(page);}
 async function analyze(){const result=page.waitForResponse(r=>r.request().method()==="POST"&&(/\/authoring\/(source-import|analyze-answer)$/.test(r.url())));await confirmAnalysis(page,controls,"解析");const response=await result;expect(response.status(),await response.text()).toBe(200);await expect(page.locator(".authoring-analysis-progress")).toHaveCount(0);}
 await add("question_sheet","../testData/SampleQ/sampleQ5.pdf");await analyze();
 let row=(await(await page.request.get(authoring)).json()).revision;const parent=row.snapshot.nodes.find((n:any)=>/問題\s*[3３]/.test(n.label.raw));expect(parent,JSON.stringify(row.snapshot.nodes.map((n:any)=>n.label))).toBeTruthy();
 await selector.selectOption(parent.stable_key);const question=page.locator("#authoring-question");await openQuestionOperations(page);await question.getByRole("button",{name:"小問の分割案を作成",exact:true}).click();const proposal=page.getByRole("dialog",{name:/の分割案/});await expect(proposal).toBeVisible();const parts=proposal.locator(".authoring-split-block");let children=0;for(let i=0;i<await parts.count();i++){if(await parts.nth(i).getByRole("combobox").inputValue()==="child"){await parts.nth(i).getByLabel("小問名",{exact:true}).fill(`(${++children})`);}}expect(children).toBe(3);await proposal.getByRole("button",{name:"分割を適用",exact:true}).click();await saveAuthoring(page);
 await add("model_answer_source","../testData/SampleQ/modelAnswer/sampleQ5_modelAnswer.pdf");await analyze();
 row=(await(await page.request.get(authoring)).json()).revision;const nodes=row.snapshot.nodes,child=nodes.find((n:any)=>n.parent_key===parent.stable_key&&n.label.raw==="(1)");expect(child).toBeTruthy();

 const childrenNodes=nodes.filter((n:any)=>n.parent_key===parent.stable_key).sort((a:any,b:any)=>a.sort_order-b.sort_order);
 expect(childrenNodes).toHaveLength(3);
 // Native extraction is left unchanged in the first case. The second is an
 // explicit saved-state fixture matching the supplied production evidence.
 if(productionExclusion){const fixture=structuredClone(row.snapshot);for(const entry of fixture.domains.answer.entries){if(childrenNodes.slice(0,2).some((n:any)=>n.stable_key===entry.authoring_question_key)){entry.disposition="excluded";entry.mapping_state="automatic";entry.ignore_reason="classified_as_non_answer";entry.semantic_classification={...entry.semantic_classification,status:"classified"};delete entry.teacher_correction;}}const saved=await page.request.put(authoring,{data:{expected_edit_version:row.edit_version,snapshot:fixture}});expect(saved.status(),await saved.text()).toBe(200);row=await saved.json();await testInfo.attach("controlled-production-pre-accept-state",{body:JSON.stringify(row.snapshot.domains.answer.entries,null,2),contentType:"application/json"});await page.reload();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();}
 const answer=page.locator("#authoring-answer");
 async function editor(index:number){await selector.selectOption(childrenNodes[index].stable_key);const entry=answer.locator('[id^="authoring-candidate-"]').first();await expect(entry).toBeVisible();if(await entry.getByRole("button",{name:"本文編集",exact:true}).count())await entry.getByRole("button",{name:"本文編集",exact:true}).click();return {entry,diagram:entry.getByRole("region",{name:"模範解答の図",exact:true}),id:(await entry.getAttribute("id"))!.replace("authoring-candidate-","")};}
 const first=await editor(0);await first.diagram.getByRole("button",{name:"図候補を確認",exact:true}).click();await expect(first.diagram.getByAltText("図1の切り出し範囲",{exact:true})).toBeVisible();await first.diagram.getByRole("button",{name:/^この図を(確認して)?使用$/}).click();
 async function evidence(stage:string){const saved=(await(await page.request.get(authoring)).json()).revision;const target=await editor(2);const endpoint=`${authoring}/entries/${target.id}/diagrams?question_id=${childrenNodes[2].stable_key}&scope=reuse&reuse_diagnostics=true`;const response=await page.request.get(endpoint);expect(response.status()).toBe(200);const result=await response.json();const hierarchy=saved.snapshot.nodes.map((n:any)=>({key:n.stable_key,parentKey:n.parent_key}));const states=childrenNodes.map((n:any)=>({key:n.stable_key,parent:n.parent_key,root:canonicalQuestionRoot(n.stable_key,hierarchy),entries:saved.snapshot.domains.answer.entries.filter((e:any)=>e.authoring_question_key===n.stable_key)}));expect(new Set(states.map((s:any)=>s.root)).size).toBe(1);await testInfo.attach(stage,{body:JSON.stringify({saved_revision:saved.id,edit_version:saved.edit_version,snapshot_path:"domains.answer.entries",states,endpoint,response:result},null,2),contentType:"application/json"});return {result,target};}
 const before=await evidence("auto-before-save");expect(before.result.reusable_diagrams).toHaveLength(0);await expect(before.target.diagram.getByText("他の小問で図を再利用するには、図を選択した後に保存してください。",{exact:true})).toBeVisible();await saveAuthoring(page);expect((await evidence("auto-after-save")).result.reusable_diagrams).toHaveLength(1);
 const second=await editor(1),manual=second.diagram.getByRole("region",{name:"PDFから手動切り取り",exact:true});await manual.getByRole("button",{name:"PDFから切り取る",exact:true}).click();const viewer=page.getByRole("region",{name:"利用資料PDF",exact:true}),overlay=viewer.getByLabel("図の範囲を矩形選択",{exact:true});await expect(overlay).toBeVisible();await viewer.getByRole("button",{name:"ページに合わせる",exact:true}).click();await overlay.scrollIntoViewIfNeeded();await viewer.locator(".pdf-pane-viewport").evaluate(el=>{el.scrollTop=el.scrollHeight-el.clientHeight;});const bounds=(await overlay.boundingBox())!,dimensions=(await overlay.getAttribute("viewBox"))!.split(" ").map(Number);const point=(x:number,y:number)=>({x:bounds.x+x/dimensions[2]*bounds.width,y:bounds.y+y/dimensions[3]*bounds.height});const a=point(345,625),b=point(505,765);await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:8});await page.mouse.up();await manual.getByRole("button",{name:"選択範囲をプレビュー",exact:true}).click();await expect(manual.getByAltText("手動切り取りのプレビュー",{exact:true})).toBeVisible();await manual.getByRole("button",{name:"使用する",exact:true}).click();expect((await evidence("manual-before-save")).result.reusable_diagrams).toHaveLength(1);await saveAuthoring(page);
 const after=await evidence("two-origins-after-save");expect(after.result.reusable_diagrams).toHaveLength(2);expect(after.result.reuse_diagnostics.candidate_count).toBe(2);if(productionExclusion){for(const id of[first.id,second.id]){const entry=after.result.reuse_diagnostics.entry_states.find((e:any)=>e.entry_id===id);expect(entry.effective_disposition).toBe("include");expect(entry.ignore_reason).toBe("classified_as_non_answer");}}await expect(after.target.diagram.getByAltText("再利用できる図",{exact:true})).toHaveCount(2);await expect(after.target.diagram.getByText("他の小問で図を再利用するには、図を選択した後に保存してください。",{exact:true})).toHaveCount(0);
 const noInference=await calls(page);for(let i=0;i<2;i++){const target=await editor(2);const action=target.diagram.getByRole("button",{name:"この図を再利用",exact:true}).and(target.diagram.locator("button:enabled"));await action.first().click();await saveAuthoring(page);}expect(await calls(page)).toEqual(noInference);
 await page.reload();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();await page.getByRole("link",{name:"戻る",exact:true}).click();await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();expect((await evidence("two-origins-after-resume")).result.reusable_diagrams).toHaveLength(2);
 // Configure the disposable authoring Test from the actual PDF's score scheme.
 // These are explicit teacher fixture decisions, not confirmation defaults.
 row=(await(await page.request.get(authoring)).json()).revision;
 const fixture=structuredClone(row.snapshot),leaves=fixture.nodes.filter((n:any)=>n.included&&!fixture.nodes.some((c:any)=>c.included&&c.parent_key===n.stable_key));
 expect(leaves).toHaveLength(6);
 const scores=[30,10,30,10,8,12];
 for(let i=0;i<leaves.length;i++){const n=leaves[i];n.score_semantics="direct";n.score_points=scores[i];fixture.rubrics[n.stable_key]=[{id:`teacher-criterion-${n.stable_key}`,description:"教師がPDFの正答と採点条件を確認",points:scores[i],levels:[{score:0,condition:"No credit"},{score:scores[i],condition:"Teacher-confirmed complete response"}],segment_ids:[],grouping_confirmed:true,provenance:{source:"teacher_manual"}}];}
 for(const entry of fixture.domains.answer.entries){
   if(!entry.authoring_question_key){entry.disposition="ignored";entry.teacher_correction={teacher_confirmed:true,disposition:"ignored"};}
   else if(entry.semantic_classification?.status==="needs_teacher_review")entry.semantic_classification.status="teacher_reviewed";
 }
 for(const warning of fixture.domains.question.document.warnings)fixture.domains.question.snapshot.warning_states[warning.id]={state:"acknowledged",note:"実PDFの本文と図を確認した検証fixture"};
 const configured=await page.request.put(authoring,{data:{snapshot:fixture,expected_edit_version:row.edit_version}});expect(configured.status(),await configured.text()).toBe(200);
 const savedRaw=await(await page.request.get(authoring)).text(),saved=JSON.parse(savedRaw).revision;
 expect((await(await page.request.get(authoring+"/review")).json()).can_confirm).toBe(true);
 await page.reload();await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
 const beforeConfirm=await calls(page);const confirming=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/authoring/confirm"));
 await page.getByRole("button",{name:"この内容でテストを確定",exact:true}).click();await page.getByRole("dialog",{name:"この内容でテストを確定しますか？"}).getByRole("button",{name:"この内容でテストを確定",exact:true}).click();expect((await confirming).status()).toBe(200);
 const confirmedRaw=await(await page.request.get(authoring+"/confirmed")).text(),active=JSON.parse(confirmedRaw).active;
 expect(active.snapshot).toEqual(saved.snapshot);expect(active.snapshot_sha256).toBe(saved.snapshot_sha256);
 const records=saved.snapshot.domains.answer.entries.flatMap((e:any)=>e.diagram_records||[]);
 expect(records.some((r:any)=>r.scope==="manual"&&r.source_type==="manual_pdf_crop")).toBe(true);
 expect(records.some((r:any)=>r.scope==="reuse")).toBe(true);
 expect(records.filter((r:any)=>r.state==="accepted")).toHaveLength(4);
 expect(active.snapshot.domains.answer.entries.flatMap((e:any)=>(e.diagram_records||[]).map((r:any)=>({id:r.id,revision:r.revision})))).toEqual(records.map((r:any)=>({id:r.id,revision:r.revision})));

 // Hash raw API JSON through the backend's canonical JSON representation;
 // parsing into JS first would lose distinctions such as 1.0 versus 1.
 const hash=(raw:string,key:string)=>execFileSync("python",["-c","import json,sys; from scoring.pdf_native import canonical_hash; print(canonical_hash(json.load(sys.stdin)[sys.argv[1]]['snapshot']))",key],{input:raw,encoding:"utf8"}).trim();
 expect(hash(confirmedRaw,"active")).toBe(active.snapshot_sha256);expect(hash(savedRaw,"revision")).toBe(active.snapshot_sha256);
 expect((await(await page.request.get(authoring)).json()).revision.snapshot).toEqual(saved.snapshot);
 expect(await calls(page)).toEqual(beforeConfirm);
 await expect(page.getByRole("button",{name:"要修正事項、未解決0件",exact:true})).toBeVisible();
 expect((await(await page.request.get(authoring+"/review")).json()).issues).toEqual([]);
 const body={revision_id:saved.id,expected_edit_version:saved.edit_version,expected_snapshot_sha256:saved.snapshot_sha256};
 const duplicate=await page.request.post(authoring+"/confirm",{data:body});expect(duplicate.status()).toBe(200);expect((await duplicate.json()).id).toBe(active.id);
 await page.reload();await page.getByLabel("対象設問",{exact:true}).selectOption("all");
 await expect(page.getByRole("button",{name:"要修正事項、未解決0件",exact:true})).toBeVisible();
 await expect(page.getByText("確認状態を保存しても、元の警告は残ります。",{exact:true})).toHaveCount(0);
 await expect(page.getByLabel("対象設問",{exact:true}).locator('option').filter({hasText:/ \*/})).toHaveCount(0);
 await page.getByRole("link",{name:"戻る",exact:true}).click();await page.getByRole("link",{name:"テスト内容を見る",exact:true}).click();
 await expect(page.getByRole("button",{name:"要修正事項、未解決0件",exact:true})).toBeVisible();
 expect((await(await page.request.get(authoring+"/review")).json()).issues).toEqual([]);


 await page.getByRole("button",{name:"版の履歴",exact:true}).click();
 const history=page.getByRole("dialog",{name:"版の履歴"});
 await history.getByRole("button",{name:"第1版 — 現在の確定版",exact:true}).click();
 const oldContent=history.getByRole("region",{name:"第1版の確定内容"});
 await expect(oldContent.getByText("確定済み。この版は編集できません。",{exact:true})).toBeVisible();
 await expect(oldContent.locator("textarea,input")).toHaveCount(0);
 for(const image of await oldContent.locator("img").all())await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
 await history.getByRole("button",{name:"修正版を作成",exact:true}).click();
 await expect(history).toHaveCount(0);
 const forkRaw=await(await page.request.get(authoring)).text(),fork=JSON.parse(forkRaw).revision;
 expect(fork.parent_confirmed_revision_id).toBe(active.id);expect(fork.snapshot).toEqual(active.snapshot);
 expect(hash(forkRaw,"revision")).toBe(active.snapshot_sha256);expect(fork.edit_version).toBeGreaterThan(active.edit_version);
 expect((await(await page.request.get(authoring+"/confirmed")).json()).active.id).toBe(active.id);
 expect((await(await page.request.get(authoring+"/review")).json()).issues).toEqual([]);
 const changed=structuredClone(fork.snapshot);changed.metadata.description="第2版の教師確認メモ";
 const saveB=await page.request.put(authoring,{data:{expected_edit_version:fork.edit_version,snapshot:changed}});expect(saveB.status()).toBe(200);
 const savedB=await saveB.json();const savedBRaw=await(await page.request.get(authoring)).text();expect((await(await page.request.get(authoring+"/confirmed/"+active.id)).json()).snapshot).toEqual(active.snapshot);
 await page.reload();await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
 await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeEnabled();
 const responseB=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/authoring/confirm"));
 await page.getByRole("button",{name:"この内容でテストを確定",exact:true}).click();await page.getByRole("dialog",{name:"この内容でテストを確定しますか？"}).getByRole("button",{name:"この内容でテストを確定",exact:true}).click();
 expect((await responseB).status()).toBe(200);
 const secondRaw=await(await page.request.get(authoring+"/confirmed")).text(),secondEdition=JSON.parse(secondRaw).active;
 expect(hash(secondRaw,"active")).toBe(secondEdition.snapshot_sha256);expect(hash(savedBRaw,"revision")).toBe(secondEdition.snapshot_sha256);
 expect(secondEdition.label).toBe("第2版");expect(secondEdition.parent_confirmed_revision_id).toBe(active.id);expect(secondEdition.snapshot).toEqual(savedB.snapshot);
 expect((await(await page.request.get(authoring+"/confirmed/"+active.id)).json()).snapshot).toEqual(active.snapshot);
 const repeatOld=await page.request.post(authoring+"/confirm",{data:body});expect(repeatOld.status()).toBe(200);expect((await repeatOld.json()).id).toBe(active.id);expect((await(await page.request.get(authoring+"/confirmed")).json()).active.id).toBe(secondEdition.id);
 await page.reload();await page.getByRole("link",{name:"戻る",exact:true}).click();await page.getByRole("link",{name:"テスト内容を見る",exact:true}).click();
 await page.getByRole("button",{name:"版の履歴",exact:true}).click();
 await expect(history.getByRole("button",{name:"第2版 — 現在の確定版",exact:true})).toBeVisible();
 await history.getByRole("button",{name:"第1版 — 確定済み",exact:true}).click();
 await expect(history.getByText("第2版の教師確認メモ",{exact:true})).toHaveCount(0);
 await history.getByRole("button",{name:"第2版 — 現在の確定版",exact:true}).click();
 await expect(history.getByText("第2版の教師確認メモ",{exact:true})).toBeVisible();
 expect(await calls(page)).toEqual(beforeConfirm);await Promise.all(expectedReviewConflicts);
 const expectedConflictConsole="Failed to load resource: the server responded with a status of 409 (Conflict)";
 expect(errors.filter(message=>message!==expectedConflictConsole)).toEqual([]);
 expect(errors.filter(message=>message===expectedConflictConsole).length).toBeLessThanOrEqual(expectedReviewConflicts.length);
});
