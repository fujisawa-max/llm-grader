import {confirmAnalysis} from "./authoringNotifications";
import {test,expect,type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";
test.setTimeout(240000);
test.skip(!process.env.AUTHORING_SPLIT_QUESTION_PDF_PATH,"isolated disposable authoring fixture required");
async function login(page:Page){await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);}
async function resume(page:Page,id:string){await page.getByRole("link",{name:"戻る",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${id}$`));await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();}
function observe(page:Page){const failures:string[]=[];page.on("pageerror",e=>failures.push(`page:${e.message}`));page.on("console",e=>{if(e.type()==="error")failures.push(`console:${e.text()}`)});page.on("requestfailed",r=>{const reason=r.failure()?.errorText||"";if(!(reason==="net::ERR_ABORTED"&&r.url().includes("?_rsc=")))failures.push(`request:${r.url()} ${reason}`)});page.on("response",r=>{if(r.status()>=500)failures.push(`http:${r.status()} ${r.url()}`)});return failures;}
async function bodyEdit(page:Page){const view=page.getByLabel("問題の表示切替",{exact:true});if(!await page.getByLabel("問題文",{exact:true}).isVisible())await view.getByRole("button",{name:"本文編集",exact:true}).click();}
async function save(page:Page){await page.getByRole("button",{name:"保存",exact:true}).first().click();await expect(page.locator(".authoring-toast").filter({hasText:"保存しました"}).last()).toBeVisible();await expect(page.getByText("未保存の変更があります",{exact:true})).toHaveCount(0);}
test("ten Save/reload/Back/resume cycles retain the active revision, exact text and stable Question tree",async({page})=>{
 await login(page);const failures=observe(page);await page.setViewportSize({width:1440,height:900});const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Authoring 10-cycle endurance",total_points:20}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const selector=page.getByLabel("対象設問",{exact:true}),key=await selector.inputValue(),view=page.getByLabel("問題の表示切替",{exact:true});
 await view.getByRole("button",{name:"設問設定の変更",exact:true}).click();await page.getByLabel(/設問番号・見出し/).fill("問題8");await page.getByRole("spinbutton",{name:/配点/}).fill("12");await view.getByRole("button",{name:"プレビューに戻る",exact:true}).click();await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 const initial=(await(await page.request.get(base+"/authoring")).json()).revision;let lastVersion=initial.edit_version;const initialId=initial.id,initialNumber=initial.revision;let previousHash=initial.snapshot_sha256;const trace:Array<Record<string,unknown>>=[];
 for(let i=1;i<=10;i++){
   const text=`Endurance exact text cycle ${i}\n$\\alpha_${i}$`;
   await editor.fill(text);await save(page);let response=await(await page.request.get(base+"/authoring")).json(),row=response.revision;
   expect(row.state).toBe("draft");expect(row.edit_version).toBe(lastVersion+1);lastVersion=row.edit_version;expect(row.id).toBe(initialId);expect(row.revision).toBe(initialNumber);expect(row.snapshot_sha256).not.toBe(previousHash);previousHash=row.snapshot_sha256;expect(row.snapshot.question_text_buffers[key]).toBe(text);
   const node=row.snapshot.nodes.find((n:{stable_key:string})=>n.stable_key===key);expect(node).toBeTruthy();trace.push({cycle:i,id:row.id,number:row.revision,edit_version:row.edit_version,snapshot_sha256:row.snapshot_sha256,key,parent:node.parent_key,points:node.score_points,text});
   expect((await(await page.request.get(base+"/authoring/status")).json()).revision_id).toBe(row.id);
   expect(await(await page.request.get(base+"/questions")).json()).toEqual([]);
   await page.reload();await expect(page.getByLabel("問題プレビュー",{exact:true})).toContainText(`Endurance exact text cycle ${i}`);
   await resume(page,exam.id);await bodyEdit(page);await expect(editor).toHaveValue(text);
   response=await(await page.request.get(base+"/authoring")).json();expect(response.revision).toEqual(row);
 }
 const last=(await(await page.request.get(base+"/authoring")).json()).revision;expect(last.edit_version).toBe(lastVersion);expect(last.snapshot.nodes.find((n:{stable_key:string})=>n.stable_key===key).parent_key).toBe(null);expect(last.snapshot.nodes.find((n:{stable_key:string})=>n.stable_key===key).score_points).toBe(12);
 expect(failures).toEqual([]);console.log("AUTHORING_ENDURANCE_TRACE",JSON.stringify(trace));
});

test("five dirty-save-reanalysis cycles disable readiness until Save and never start analysis on Save",async({page})=>{
 await login(page);const failures=observe(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Analysis readiness endurance",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const controls=page.getByRole("group",{name:"利用資料の操作"}),guidance=page.getByLabel("解析前の保存",{exact:true});
 await page.getByLabel("利用資料",{exact:true}).selectOption("action:add");await page.getByLabel("資料の種類",{exact:true}).selectOption("question_sheet");await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"readiness.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.AUTHORING_SPLIT_QUESTION_PDF_PATH!)});await save(page);
 const material=(await(await page.request.get(base+"/materials")).json()).find((m:{material_type:string})=>m.material_type==="question_sheet");await page.getByLabel("利用資料",{exact:true}).selectOption(material.id);
 await confirmAnalysis(page,controls,"解析");await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();const before=(await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/ocr/logs?tail=1000`)).json()).lines.filter((s:string)=>s.includes("POST /v1/chat/completions")).length;
 const view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 for(let i=1;i<=5;i++){
   await editor.fill(`${await editor.inputValue()}\nReadiness dirty cycle ${i}`);await expect(guidance).toBeVisible();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeDisabled();
   await guidance.getByRole("button",{name:"保存",exact:true}).click();await expect(guidance).toHaveCount(0);await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
   const calls=(await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/ocr/logs?tail=1000`)).json()).lines.filter((s:string)=>s.includes("POST /v1/chat/completions")).length;expect(calls).toBe(before);
   const saved=(await(await page.request.get(base+"/authoring")).json()).revision;expect(await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/ocr/logs?tail=1000`)).json().then((d:{lines:string[]})=>d.lines.filter(s=>s.includes("POST /v1/chat/completions")).length)).toBe(before);
   await confirmAnalysis(page,controls,"再解析");await expect.poll(async()=>{const row=(await(await page.request.get(base+"/authoring")).json()).revision;return row.id!==saved.id;}).toBe(true);await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
 }
 expect((await(await page.request.get(base+"/authoring")).json()).revision.state).toBe("draft");expect(await(await page.request.get(base+"/questions")).json()).toEqual([]);expect(failures).toEqual([]);
});


test("a stale second browser tab cannot overwrite the latest saved authoring revision",async({page})=>{
 await login(page);const failures=observe(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Stale browser tab guard",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const viewA=page.getByLabel("問題の表示切替",{exact:true});await viewA.getByRole("button",{name:"本文編集",exact:true}).click();const editorA=page.getByLabel("問題文",{exact:true});await editorA.fill("Seed body");await save(page);
 const pageB=await page.context().newPage();await pageB.goto(`/tests/${exam.id}/authoring`);await pageB.getByRole("button",{name:"設問を追加",exact:true}).waitFor();const viewB=pageB.getByLabel("問題の表示切替",{exact:true});await viewB.getByRole("button",{name:"本文編集",exact:true}).click();const editorB=pageB.getByLabel("問題文",{exact:true});await editorB.fill("Tab B stale edit");
 await editorA.fill("Tab A authoritative edit");await save(page);const authoritative=(await(await page.request.get(base+"/authoring")).json()).revision;
 await pageB.getByRole("button",{name:"保存",exact:true}).first().click();await expect(pageB.locator(".error").filter({hasText:"保存できませんでした"})).toBeVisible();await expect(pageB.getByText("保存しました",{exact:true})).toHaveCount(0);
 const after=(await(await page.request.get(base+"/authoring")).json()).revision;expect(after).toEqual(authoritative);expect(after.snapshot.question_text_buffers[after.snapshot.nodes[0].stable_key]).toBe("Tab A authoritative edit");
 pageB.once("dialog",d=>d.accept());await pageB.reload();await expect(pageB.getByLabel("問題プレビュー",{exact:true})).toContainText("Tab A authoritative edit");expect(failures).toEqual([]);await pageB.close();
});

test("an edit made while Save is in flight remains dirty after the older response",async({page})=>{
 await login(page);const failures=observe(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"In-flight Save edit guard",total_points:10}})).json(),base=`/api/v1/tests/${exam.id}`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).click();const view=page.getByLabel("問題の表示切替",{exact:true});await view.getByRole("button",{name:"本文編集",exact:true}).click();const editor=page.getByLabel("問題文",{exact:true});
 let release!:()=>void,start!:()=>void;const held=new Promise<void>(resolve=>start=resolve),gate=new Promise<void>(resolve=>release=resolve);let intercepted=false;
 await page.route(`**/api/v1/tests/${exam.id}/authoring`,async route=>{if(route.request().method()==="PUT"&&!intercepted){intercepted=true;start();await gate;}await route.continue();});
 await editor.fill("Snapshot captured by Save");await page.getByRole("button",{name:"保存",exact:true}).first().click();await held;await editor.fill("Newer local edit during Save");release();
 await expect(page.locator(".authoring-toast").filter({hasText:"送信した内容は保存しました"}).filter({hasText:"その後の変更は未保存です"})).toBeVisible();await expect(editor).toHaveValue("Newer local edit during Save");await expect(page.getByText("未保存の変更があります",{exact:true})).toBeVisible();
 let revision=(await(await page.request.get(base+"/authoring")).json()).revision;expect(revision.snapshot.question_text_buffers[revision.snapshot.nodes[0].stable_key]).toBe("Snapshot captured by Save");
 await page.unroute(`**/api/v1/tests/${exam.id}/authoring`);await save(page);revision=(await(await page.request.get(base+"/authoring")).json()).revision;expect(revision.snapshot.question_text_buffers[revision.snapshot.nodes[0].stable_key]).toBe("Newer local edit during Save");expect(failures).toEqual([]);
});
