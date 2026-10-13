import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {meaningfulTextEdit,questionTextReviewed} from '../lib/authoringTextReview';
import type {ReviewNode} from '../types/reviews';

function node(text='Original text'):ReviewNode {
 return {review_node_id:'q',stable_key:'q',source_draft_stable_key:'q',source_draft_node_id:'q',parent_key:null,
  node_type:'major_question',depth:0,sort_order:0,label:{raw:'問題3',normalized:'3'},body_text:text,
  ordered_content:[{type:'text',order:0,text}],included:true,score_semantics:'direct',score_points:10,
  review_flags:[],formula_decisions:{},figure_decisions:{},warning_states:{}};
}
test('only a current meaningful manual input reviews unsaved text',()=>{
 const saved=node(),original=structuredClone(saved);
 expect(questionTextReviewed(saved,saved,[],'Changed text','Changed text')).toBe(true);
 expect(questionTextReviewed(saved,saved,[],'Changed text',undefined)).toBe(false);
 expect(questionTextReviewed(saved,saved,[],'Changed text','Older input')).toBe(false);
 expect(saved).toEqual(original);expect(saved.teacher_correction).toBeUndefined();
});
test('no-op, whitespace normalization and edit/revert do not create review',()=>{
 const saved=node();
 for(const text of ['Original text',' Original  text\n','Original\u0085text','Original\u001ftext']){
  expect(meaningfulTextEdit('Original text',text)).toBe(false);
  expect(questionTextReviewed(saved,saved,[],text,text)).toBe(false);
 }
 expect(meaningfulTextEdit('Original text','Actual correction')).toBe(true);
});
test('only scoped server text receipt supplies saved review; source rebuild reopens it',()=>{
 const saved=node();saved.teacher_correction={text_review:{teacher_confirmed:true,confirmation_origin:'manual_edit'}};
 expect(questionTextReviewed(saved,saved,[],'Original text',undefined)).toBe(true);
 expect(questionTextReviewed(saved,saved,[],'System replacement',undefined)).toBe(false);
 const rebuilt=node('System replacement');
 expect(questionTextReviewed(rebuilt,rebuilt,[],'System replacement',undefined)).toBe(false);
 rebuilt.teacher_correction={teacher_confirmed:true,confirmation_origin:'manual_edit'};
 expect(questionTextReviewed(rebuilt,rebuilt,[],'System replacement',undefined)).toBe(false);
});

test('Sample Q5 working review is immediate, survives failed Save, persists on Save, and reopens after native reanalysis',async({page})=>{
 test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable production-like harness');test.setTimeout(90000);
 await page.setViewportSize({width:1600,height:900});await page.goto('/login');
 await page.getByLabel('メールアドレス').fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
 await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
 await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const made=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Working text review fix4a Sample Q5',total_points:100}});expect(made.status()).toBe(201);
 const exam=await made.json(),base=`/api/v1/tests/${exam.id}/authoring`;
 let row=await(await page.request.post(base+'/revisions')).json();
 const upload=await page.request.post(`/api/v1/tests/${exam.id}/question-materials`,{headers:{'content-type':'application/pdf','x-filename':'sampleQ5.pdf'},data:await readFile('../testData/SampleQ/sampleQ5.pdf')});expect(upload.status()).toBe(201);
 const extraction=await upload.json(),material=(await(await page.request.get(`/api/v1/tests/${exam.id}/materials`)).json()).find((m:{id:string})=>m.id===extraction.material_id);
 row.snapshot.materials.push({id:material.id,role:material.material_type,sha256:material.sha256});
 const binding=await page.request.put(base,{data:{snapshot:row.snapshot,expected_edit_version:row.edit_version}});expect(binding.status()).toBe(200);row=await binding.json();
 const draft=await(await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();
 expect((await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).status()).toBe(201);
 expect((await page.request.post(base+'/source-import',{data:{expected_edit_version:row.edit_version,analysis_material_id:material.id}})).status()).toBe(200);
 const modelCalls=async()=>Promise.all(['ocr','math_ocr','ornith_rubric_draft','grader'].map(async profile=>{
  const response=await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`);
  const log=await response.json();return log.lines.filter((line:string)=>line.includes('POST /v1/chat/completions')).length;
 }));
 const callsBefore=await modelCalls();
 const unexpected:string[]=[];page.on('request',request=>{if(/math-ocr|latex-normalize|analyze-answer|grading-jobs/.test(request.url()))unexpected.push(request.url());});
 await page.goto(`/tests/${exam.id}/authoring`);const selector=page.getByLabel('対象設問',{exact:true});await selector.selectOption('q3');
 await page.locator('#authoring-question').getByRole('button',{name:'本文編集',exact:true}).click();
 const editor=page.getByLabel('問題文',{exact:true}),confirm=page.getByRole('button',{name:'問題文を確認',exact:true});
 const contradictory=page.getByText('元資料と問題文を照合してください。編集後は再確認が必要です。',{exact:true});
 await expect(confirm).toBeVisible();await expect(contradictory).toBeVisible();const original=await editor.inputValue();
 await editor.focus();await expect(confirm).toBeVisible();await editor.fill(original);await expect(confirm).toBeVisible();
 await editor.fill(original+' ');await expect(confirm).toBeVisible();
 await editor.fill(original+'\n教師の本文修正。');await expect(confirm).toHaveCount(0);await expect(contradictory).toHaveCount(0);
 // Body review never approves pending automatic formula extraction.
 await expect(page.getByRole('button',{name:'数式を確認',exact:true})).toBeVisible();
 await editor.fill(original);await expect(confirm).toBeVisible();await expect(contradictory).toBeVisible();
 await confirm.click();
 async function save(expected=200){const response=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));await page.getByRole('button',{name:'保存',exact:true}).click();expect((await response).status()).toBe(expected);}
 await save();const baseline=(await(await page.request.get(base)).json()).revision;
 const before=baseline.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');
 const corrected=original+'\n教師の本文修正。';await editor.fill(corrected);
 await expect(confirm).toHaveCount(0);await expect(contradictory).toHaveCount(0);
 await expect(page.getByRole('button',{name:'数式を確認',exact:true})).toHaveCount(0);
 await expect(page.locator('.authoring-save-button')).toHaveClass(/is-dirty/);
 await selector.selectOption('q2');const warning=page.locator(`[id="review-warning-${encodeURIComponent('node:q2:ambiguous_geometric_order')}"]`);await expect(warning).toBeVisible();
 await selector.selectOption('q3');await expect(confirm).toHaveCount(0);
 expect((await(await page.request.get(base)).json()).revision).toEqual(baseline);
 // Only this disposable Test's Save response is intercepted; no receipt is forged.
 await page.route(`**${base}`,async route=>{if(route.request().method()!=='PUT'){await route.continue();return;}
  const sent=route.request().postDataJSON().snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');
  expect(sent.teacher_correction).toEqual(before.teacher_correction);
  await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:{code:'AUTHORING_SAVE_CONFLICT',message:'Controlled Save failure'}})});
 });
 await save(409);await expect(editor).toHaveValue(corrected);await expect(confirm).toHaveCount(0);await expect(contradictory).toHaveCount(0);
 expect((await(await page.request.get(base)).json()).revision).toEqual(baseline);
 await page.unroute(`**${base}`);await save();
 const saved=(await(await page.request.get(base)).json()).revision,after=saved.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');
 expect(after.teacher_correction.text_review.confirmation_origin).toBe('manual_edit');expect(after.formula_decisions).toEqual(before.formula_decisions);
 await page.reload();await selector.selectOption('q3');await page.locator('#authoring-question').getByRole('button',{name:'本文編集',exact:true}).click();
 await expect(editor).toHaveValue(corrected);await expect(confirm).toHaveCount(0);await expect(contradictory).toHaveCount(0);
 const formula=Object.values(after.formula_decisions).find((decision:any)=>decision.teacher_transcription?.includes('2,2')) as {teacher_transcription:string};expect(formula).toBeTruthy();
 await editor.fill(corrected.replace(formula.teacher_transcription,formula.teacher_transcription.replace('2,2','3,3')));
 await expect(confirm).toHaveCount(0);await expect(page.getByRole('button',{name:'数式を確認',exact:true})).toBeVisible();
 expect((await(await page.request.get(base)).json()).revision.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3').formula_decisions).toEqual(after.formula_decisions);
 await editor.fill(corrected);await save();
 // Actual native Question reanalysis rebuilds content without model/OCR calls.
 const controls=page.getByRole('group',{name:'利用資料の操作',exact:true});await controls.getByRole('button',{name:'再解析',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'問題用紙を再解析しますか？',exact:true});await expect(dialog).toBeVisible();
 const refreshed=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(base+'/source-import'));
 await dialog.getByRole('button',{name:'再解析',exact:true}).click();expect((await refreshed).status()).toBe(200);
 await selector.selectOption('q3');await expect(confirm).toBeVisible();await expect(contradictory).toBeVisible();
 await expect(editor).not.toHaveValue(corrected);
 const rebuilt=(await(await page.request.get(base)).json()).revision.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');expect(rebuilt.teacher_correction?.text_review).toBeUndefined();
 expect(unexpected).toEqual([]);
 expect(await modelCalls()).toEqual(callsBefore);
});
