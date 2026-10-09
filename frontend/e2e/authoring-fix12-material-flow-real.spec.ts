import {test,expect,type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";

test.setTimeout(120000);
test.skip(!process.env.RUNTIME_MANAGER_E2E||!process.env.QUESTION_MATH_PDF_PATH,"isolated FastAPI/production browser harness required");
async function login(page:Page){await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);}
async function fresh(page:Page,name:string){await login(page);const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();const made=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:`${name} ${Date.now()}`,total_points:10}});expect(made.status()).toBe(201);const exam=await made.json();await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();return exam;}

test("new material offers an explicit save then role-specific analysis confirmation and visible progress",async({page})=>{
 const exam=await fresh(page,"Fix12 registration flow");
 await page.getByLabel("利用資料",{exact:true}).selectOption("action:add");
 await expect(page.getByLabel("資料の種類",{exact:true})).toHaveValue("question_sheet");
 await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"question-fix12.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.QUESTION_MATH_PDF_PATH!)});
 const registration=page.getByRole("dialog",{name:"保存して解析へ進みますか？"});await expect(registration).toBeVisible();
 await expect(registration).toContainText("ファイルを読み込みました。");await expect(page.getByRole("button",{name:"保存",exact:true})).toHaveClass(/is-dirty/);
 await registration.getByRole("button",{name:"はい",exact:true}).click();
 await expect(registration).toHaveCount(0);const confirm=page.getByRole("dialog",{name:"問題用紙を解析しますか？"});await expect(confirm).toBeVisible();
 const response=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().includes("/authoring/source-import"));
 await confirm.getByRole("button",{name:"解析",exact:true}).click();
 await expect(page.getByRole("status").filter({hasText:"問題を解析しています…"})).toBeVisible();
 expect((await response).status()).toBe(200);
 await expect(page.getByRole("status").filter({hasText:"問題を解析しています…"})).toHaveCount(0);
 await expect(page.getByRole("button",{name:"保存",exact:true})).toHaveClass(/is-saved/);
});

test("registration prompt No preserves the unsaved binding and starts no analysis",async({page})=>{
 const exam=await fresh(page,"Fix12 registration no");
 await page.getByLabel("利用資料",{exact:true}).selectOption("action:add");
 await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"question-no.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.QUESTION_MATH_PDF_PATH!)});
 const registration=page.getByRole("dialog",{name:"保存して解析へ進みますか？"});await expect(registration).toBeVisible();
 const before=await page.request.get(`/api/v1/tests/${exam.id}/authoring`);const materialCount=(await(await page.request.get(`/api/v1/tests/${exam.id}/materials`)).json()).length;
 await registration.getByRole("button",{name:"いいえ",exact:true}).click();await expect(registration).toHaveCount(0);
 await expect(page.getByRole("button",{name:"保存",exact:true})).toHaveClass(/is-dirty/);
 expect((await(await page.request.get(`/api/v1/tests/${exam.id}/materials`)).json()).length).toBe(materialCount);
 expect((await(await page.request.get(`/api/v1/tests/${exam.id}/authoring`)).json()).revision.edit_version).toBe((await before.json()).revision.edit_version);
});

test("Save failure leaves registration actionable and never opens analysis confirmation",async({page})=>{
 await fresh(page,"Fix12 Save failure");await page.getByLabel("利用資料",{exact:true}).selectOption("action:add");
 await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:"question-save-failure.pdf",mimeType:"application/pdf",buffer:await readFile(process.env.QUESTION_MATH_PDF_PATH!)});
 const registration=page.getByRole("dialog",{name:"保存して解析へ進みますか？"});await expect(registration).toBeVisible();
 let analyses=0;page.on("request",request=>{if(request.url().includes("/authoring/source-import"))analyses++;});
 await page.route(/\/api\/v1\/tests\/[^/]+\/authoring$/,async route=>{
  if(route.request().method()==="PUT")await route.fulfill({status:409,contentType:"application/json",body:JSON.stringify({detail:"AUTHORING_SAVE_CONFLICT"})});
  else await route.continue();
 });
 await registration.getByRole("button",{name:"はい",exact:true}).click();
 await expect(registration.getByRole("alert")).toContainText("保存できませんでした");
 await expect(page.getByRole("dialog",{name:"問題用紙を解析しますか？"})).toHaveCount(0);
 expect(analyses).toBe(0);await expect(page.getByRole("button",{name:"保存",exact:true})).toHaveClass(/is-dirty/);
});

test("material editor changes only a binding role, delete preserves shared-file semantics, and next missing role is selected",async({page})=>{
 const exam=await fresh(page,"Fix12 material editor"),seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const bytes=await(await page.request.get(`/api/v1/tests/${seed.id}/materials/${process.env.MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID}/file`)).body();
 const base=`/api/v1/tests/${exam.id}`;
 const question=await page.request.post(base+"/materials/upload",{data:bytes,headers:{"Content-Type":"application/pdf","X-Source-Role":"question_sheet","X-Filename":"fix12-question.pdf"}});expect(question.status()).toBe(201);
 const answer=await page.request.post(base+"/materials/upload",{data:bytes,headers:{"Content-Type":"application/pdf","X-Source-Role":"model_answer_source","X-Filename":"fix12-answer.pdf"}});expect(answer.status()).toBe(201);const answerMaterial=await answer.json();
 await page.reload();await page.getByLabel("利用資料",{exact:true}).selectOption("action:add");await expect(page.getByLabel("資料の種類",{exact:true})).toHaveValue("rubric_source");
 await page.getByLabel("利用資料",{exact:true}).selectOption("action:manage");
 const item=page.getByRole("listitem").filter({hasText:"fix12-answer.pdf"});await item.getByLabel("fix12-answer.pdfの資料の種類",{exact:true}).selectOption("rubric_source");
 const changedResponse=page.waitForResponse(response=>response.request().method()==="PATCH"&&response.url().endsWith(`/materials/${answerMaterial.id}/role`));
 await item.getByRole("button",{name:"種類を変更",exact:true}).click();const changed=await changedResponse;expect(changed.status()).toBe(200);const binding=await changed.json();
 expect(binding.material_type).toBe("rubric_source");expect(binding.sha256).toBe(answerMaterial.sha256);expect(binding.storage_ref).toBe(answerMaterial.storage_ref);
 const deletedResponse=page.waitForResponse(response=>response.request().method()==="DELETE"&&response.url().endsWith(`/materials/${binding.id}`));
 await item.getByRole("button",{name:"資料を削除",exact:true}).click();const confirmation=page.getByRole("dialog",{name:"この資料を削除しますか？"});await expect(confirmation).toBeVisible();await confirmation.getByRole("button",{name:"資料を削除",exact:true}).click();expect((await deletedResponse).status()).toBe(200);
 const active=await(await page.request.get(base+"/materials")).json();expect(active.map((m:{id:string})=>m.id)).toContain((await question.json()).id);expect(active.map((m:{id:string})=>m.id)).not.toContain(binding.id);
 await page.getByRole("button",{name:"保存",exact:true}).click();await expect(page.getByText("未保存の変更があります",{exact:true})).toHaveCount(0);
});
