import {test,expect,type Page} from "@playwright/test";
import {openAuthoringEditors} from "./authoringEditMode";
import {readFile} from "node:fs/promises";
test.setTimeout(150000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,"isolated real API/production build required");
async function calls(page:Page){return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async p=>{
 const data=await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${p}/logs?tail=1000`)).json();return data.lines.filter((s:string)=>s.includes("POST /v1/chat/completions")).length;
}));}
test("compact material controls, role-aware explicit analysis and every Test editing entry",async({page})=>{
 await page.setViewportSize({width:1920,height:1080});await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",e=>{if(e.type()==="error")errors.push(e.text());});
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exams=[];for(const name of ["Analysis access A","Analysis access B","Analysis access C"]){const result=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name,total_points:10}});expect(result.status()).toBe(201);exams.push(await result.json());}
 const base=`/api/v1/tests/${exams[1].id}`,before=await calls(page);
 await page.goto(`/offerings/${seed.course_offering_id}`);for(const exam of exams){const row=page.getByRole("row").filter({hasText:exam.name});await expect(row.getByRole("link",{name:"編集",exact:true})).toHaveAttribute("href",`/tests/${exam.id}/authoring`);}
 await page.getByRole("row").filter({hasText:exams[1].name}).getByRole("link",{name:"編集",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exams[1].id}/authoring$`));
 await page.getByRole("button",{name:"編集用の下書きを作成"}).click();await page.getByRole("button",{name:"設問を追加",exact:true}).click();await page.getByLabel("問題文",{exact:true}).waitFor({state:"attached"});await openAuthoringEditors(page);await page.getByLabel("問題文",{exact:true}).fill("Teacher saved Question");
 const controls=page.getByRole("group",{name:"利用資料の操作",exact:true}),select=page.getByLabel("利用資料",{exact:true});await controls.getByRole("button",{name:"一覧",exact:true}).click();await page.getByRole("button",{name:"資料を追加",exact:true}).click();
 const bytes=await(await page.request.get(`/api/v1/tests/${seed.id}/materials/${process.env.MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID}/file`)).body();
 const files:{id:string;material_type:string}[]=[];
 for(const [role,buffer] of [["model_answer_source",bytes],["rubric_source",bytes],["question_sheet",await readFile(process.env.QUESTION_MATH_PDF_PATH!)],["supplementary_source",bytes]] as const){
  await page.getByLabel("資料の種類",{exact:true}).selectOption(role);await page.getByLabel("資料を追加",{exact:true}).setInputFiles({name:role+".pdf",mimeType:"application/pdf",buffer});await expect(select).toContainText(role+".pdf");
 }
 files.push(...await(await page.request.get(base+"/materials")).json());
 await controls.getByRole("button",{name:"一覧",exact:true}).click();await select.selectOption(files.find(m=>m.material_type==="supplementary_source")!.id);await expect(controls.getByRole("button",{name:"解析",exact:true})).toBeDisabled();await expect(page.getByText("選択資料の解析: この資料は解析対象ではありません。",{exact:true})).toBeVisible();
 await select.selectOption(files.find(m=>m.material_type==="model_answer_source")!.id);await expect(controls.getByRole("button",{name:"解析",exact:true})).toBeDisabled();await expect(page.getByText("選択資料の解析: 変更を保存してから解析してください。",{exact:true})).toBeVisible();
 await page.getByRole("button",{name:"保存",exact:true}).click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();await expect(controls.getByRole("button",{name:"解析",exact:true})).toBeEnabled();expect(await calls(page)).toEqual(before);
 const b=(await controls.boundingBox())!,dropdown=(await select.boundingBox())!,toolbar=(await page.locator(".review-workspace-source .pdf-pane-toolbar").boundingBox())!,pdf=(await page.locator(".pdf-pane-viewport").boundingBox())!;
 expect(b.height).toBeLessThan(48);expect(dropdown.width).toBeGreaterThan(170);expect(toolbar.y).toBeGreaterThanOrEqual(b.y+b.height);expect(pdf.height).toBeGreaterThan(550);expect(pdf.width).toBeGreaterThanOrEqual((await page.locator(".review-workspace-source").boundingBox())!.width*.8);
 for(const label of ["解析","差換え","一覧"]){const button=(await controls.getByRole("button",{name:label,exact:true}).boundingBox())!;expect(Math.abs(button.y-dropdown.y)).toBeLessThan(8);}
 const key=await page.getByLabel("対象設問",{exact:true}).inputValue(),previous=(await(await page.request.get(base+"/authoring")).json()).revision;
 const observed:string[]=[];page.on("request",r=>{if(r.method()==="POST"&&(r.url().includes("analyze-answer")||r.url().includes("question-materials")))observed.push(r.url());});
 page.once("dialog",d=>{expect(d.message()).toContain("現在の保存済み下書き");void d.accept();});await controls.getByRole("button",{name:"解析",exact:true}).click();await expect(page.getByText("選択資料を解析しています。完了までお待ちください。",{exact:true})).toBeVisible();await expect(controls.getByRole("button",{name:"解析中…",exact:true})).toBeDisabled();
 await expect(page.getByText("解析結果を新しい編集用下書きに取り込みました。解析前の保存済み下書きと正式内容は保持されています。",{exact:true})).toBeVisible();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();await expect(page.getByLabel("対象設問",{exact:true})).toHaveValue(key);await expect(page.getByLabel("問題文",{exact:true})).toHaveValue("Teacher saved Question");
 const analyzed=(await(await page.request.get(base+"/authoring")).json()).revision;expect(analyzed.id).not.toBe(previous.id);expect(analyzed.revision).toBe(previous.revision+1);expect(observed).toHaveLength(1);
 const after=await calls(page);expect(after[2]).toBeGreaterThan(before[2]);
 // Reanalysis requires explicit confirmation; cancelling changes neither revision nor runtime calls.
 page.once("dialog",d=>d.dismiss());await controls.getByRole("button",{name:"再解析",exact:true}).click();expect((await(await page.request.get(base+"/authoring")).json()).revision.id).toBe(analyzed.id);expect(await calls(page)).toEqual(after);
 await select.selectOption(files.find(m=>m.material_type==="rubric_source")!.id);page.once("dialog",d=>d.accept());await controls.getByRole("button",{name:"解析",exact:true}).click();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();expect((await(await page.request.get(base+"/authoring")).json()).revision.snapshot.domains.answer.material_id).toBe(files.find(m=>m.material_type==="rubric_source")!.id);
 await select.selectOption(files.find(m=>m.material_type==="model_answer_source")!.id);await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();await page.reload();await select.selectOption(files.find(m=>m.material_type==="model_answer_source")!.id);await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();
 await select.selectOption(files.find(m=>m.material_type==="question_sheet")!.id);page.once("dialog",d=>d.accept());await controls.getByRole("button",{name:"解析",exact:true}).click();await expect(controls.getByRole("button",{name:"再解析",exact:true})).toBeEnabled();expect(observed.some(url=>url.includes("question-materials"))).toBe(true);
 expect((await(await page.request.get(base+"/authoring")).json()).revision.snapshot.domains.question.document.source_pdf_sha256).toBeTruthy();
 for(const domain of ["questions","model-answers","rubrics"])expect(await(await page.request.get(base+`/${domain}`)).json()).toEqual([]);
 await page.setViewportSize({width:760,height:900});const narrow=(await controls.boundingBox())!;expect(narrow.height).toBeLessThan(90);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole("link",{name:"戻る",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exams[1].id}$`));await page.getByRole("region",{name:"次に行う作業"}).getByRole("button",{name:"編集を続ける ›",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exams[1].id}/authoring$`));
 const offering=await(await page.request.get(`/api/v1/offerings/${seed.course_offering_id}`)).json();await page.goto("/");const card=page.locator(".recent-course-card").filter({has:page.locator(`a[href='/courses/${offering.course_id}']`)});await expect(card.getByLabel("最近のテスト").getByRole("link")).toHaveCount(1);expect(errors).toEqual([]);
});
