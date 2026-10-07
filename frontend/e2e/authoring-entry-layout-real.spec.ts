import {openAuthoringEditors} from "./authoringEditMode";
import {test,expect,type Page} from "@playwright/test";
test.setTimeout(90000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,"requires isolated real API/production frontend");
async function modelCalls(page:Page){
  return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async profile=>{
    const result=await (await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();
    return result.lines.filter((line:string)=>line.includes("POST /v1/chat/completions")).length;
  }));
}
test("Test and single right-hand recent shortcut open authoring; source stacks vertically and preserves edits",async({page})=>{
  await page.setViewportSize({width:1920,height:1080});await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);
  const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",e=>{if(e.type()==="error")errors.push(e.text());});
  const callsBefore=await modelCalls(page);
  const seed=await (await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
  const create=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Authoring entry and source layout",total_points:10}});
  expect(create.status()).toBe(201);const exam=await create.json(),base=`/api/v1/tests/${exam.id}`;
  const pdf=await (await page.request.get(`/api/v1/tests/${seed.id}/materials/${process.env.MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID}/file`)).body();
  const materials=[];
  for(const role of ["question_sheet","model_answer_source"]){
    const uploaded=await page.request.post(base+"/materials/upload",{headers:{"Content-Type":"application/pdf","X-Source-Role":role,"X-Filename":role+".pdf"},data:pdf});
    expect(uploaded.status()).toBe(201);materials.push(await uploaded.json());
  }
  await page.goto(`/tests/${exam.id}`);
  const guidance=page.getByRole("region",{name:"次に行う作業"});await expect(guidance).toContainText("テスト内容を編集してください。");
  await guidance.getByRole("button",{name:"テスト内容を編集 ›",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exam.id}/authoring$`));
  await expect.poll(async()=>(await (await page.request.get(base+"/authoring")).json()).revision?.state).toBe("draft");
  await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();
  await expect(page.getByRole("button",{name:/下書き.*作成/})).toHaveCount(0);
  const initial=(await (await page.request.get(base+"/authoring")).json()).revision;await page.reload();await page.getByRole("button",{name:"設問を追加",exact:true}).waitFor();expect((await (await page.request.get(base+"/authoring")).json()).revision.id).toBe(initial.id);expect(await modelCalls(page)).toEqual(callsBefore);
  await page.getByRole("button",{name:"設問を追加",exact:true}).click();
  await page.getByLabel("問題文",{exact:true}).waitFor({state:"attached"});await openAuthoringEditors(page);const text=page.getByLabel("問題文",{exact:true});await text.fill("第1行\n第2行\n第3行");
  await page.getByRole("checkbox",{name:"採点基準",exact:true}).uncheck();
  const selected=await page.getByLabel("対象設問",{exact:true}).inputValue();
  const source=page.locator(".review-workspace-source"),editor=page.locator(".review-workspace-editor");
  const material=page.getByLabel("利用資料",{exact:true}),toolbar=source.getByRole("toolbar",{name:"PDF表示操作"}),viewport=source.locator(".pdf-pane-viewport");
  await expect(source.getByRole("button",{name:"拡大",exact:true})).toBeEnabled();
  const boxes=async()=>({source:(await source.boundingBox())!,editor:(await editor.boundingBox())!,selector:(await material.boundingBox())!,toolbar:(await toolbar.boundingBox())!,pdf:(await viewport.boundingBox())!});
  let b=await boxes();
  expect(b.selector.y+b.selector.height).toBeLessThanOrEqual(b.toolbar.y+1);
  expect(b.toolbar.y+b.toolbar.height).toBeLessThanOrEqual(b.pdf.y+1);
  expect(b.pdf.width).toBeGreaterThanOrEqual(b.source.width*.8);expect(b.pdf.width).toBeGreaterThan(400);expect(b.pdf.height).toBeGreaterThan(500);
  expect(b.source.x+b.source.width).toBeLessThan(b.editor.x);expect(b.source.width/b.editor.width).toBeGreaterThan(.55);
  await source.getByRole("button",{name:"拡大",exact:true}).click();
  await source.getByRole("button",{name:"縮小",exact:true}).click();
  await source.getByRole("button",{name:"ページに合わせる",exact:true}).click();await source.getByRole("button",{name:"幅に合わせる",exact:true}).click();
  await source.getByRole("button",{name:"倍率をリセット",exact:true}).click();await expect(toolbar.getByText("100%",{exact:true})).toBeVisible();
  await material.selectOption(materials[1].id);await expect(source.getByRole("button",{name:"拡大",exact:true})).toBeEnabled();
  await expect(text).toHaveValue("第1行\n第2行\n第3行");await expect(page.getByLabel("対象設問",{exact:true})).toHaveValue(selected);
  await expect(page.getByRole("checkbox",{name:"採点基準",exact:true})).not.toBeChecked();await expect(page.getByText("未保存の変更があります",{exact:true})).toBeVisible();
  await expect(source.locator(".diagram-overlay")).toHaveCount(0);
  await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));b=await boxes();
  const action=(await page.locator(".review-workspace-actions").boundingBox())!;
  expect(b.selector.y).toBeGreaterThanOrEqual(action.y+action.height);
  expect(b.pdf.y+b.pdf.height).toBeLessThanOrEqual(1080);expect(b.source.y).toBeGreaterThanOrEqual(0);
  await page.setViewportSize({width:760,height:900});await page.evaluate(()=>window.scrollTo(0,0));b=await boxes();
  expect(b.editor.y).toBeGreaterThanOrEqual(b.source.y+b.source.height);expect(b.selector.y+b.selector.height).toBeLessThanOrEqual(b.toolbar.y+1);
  expect(b.pdf.width).toBeGreaterThanOrEqual(b.source.width*.8);
  await page.setViewportSize({width:1920,height:1080});await page.getByRole("button",{name:"保存",exact:true}).click();
  await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
  const saved=(await (await page.request.get(base+"/authoring")).json()).revision;
  // A newer unstarted Test must not displace this active authoring draft.
  expect((await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Newer unstarted test",total_points:10}})).status()).toBe(201);
  const offering=await (await page.request.get(`/api/v1/offerings/${seed.course_offering_id}`)).json();
  await page.goto("/");const card=page.locator(".recent-course-card").filter({has:page.locator(`a[href='/courses/${offering.course_id}']`)});
  const recent=card.getByLabel("最近のテスト",{exact:true});await expect(recent).toContainText(exam.name);await expect(recent.getByRole("link")).toHaveCount(1);
  const left=(await card.locator(".recent-course-details").boundingBox())!,right=(await recent.boundingBox())!;
  expect(right.x).toBeGreaterThanOrEqual(left.x+left.width);await expect(card.getByRole("link",{name:"開く",exact:true})).toBeVisible();
  await page.setViewportSize({width:560,height:900});await expect(recent.getByRole("link",{name:"編集を続ける",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await recent.getByRole("link",{name:"編集を続ける",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exam.id}/authoring$`));
  await expect(text).toHaveValue(saved.snapshot.nodes[0].body_text);
  expect((await (await page.request.get(base+"/authoring")).json()).revision.id).toBe(saved.id);
  await page.goto(`/tests/${exam.id}`);await guidance.getByRole("button",{name:"編集を続ける ›",exact:true}).click();await expect(page).toHaveURL(new RegExp(`/tests/${exam.id}/authoring$`));
  expect(await modelCalls(page)).toEqual(callsBefore);expect(errors).toEqual([]);
});
