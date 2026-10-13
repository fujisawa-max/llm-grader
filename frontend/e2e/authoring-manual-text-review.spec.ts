import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {editQuestionContent,questionContent} from '../lib/questionContent';
import type {ReviewNode} from '../types/reviews';
import {prepareAuthoringSave} from '../lib/authoringState';
import type {AuthoringSnapshot} from '../lib/api/testAuthoring';

function mergedNode(status:'confirmed'|'unreviewed'):ReviewNode {
 return {review_node_id:'review-q3-child',stable_key:'q3-child',source_draft_stable_key:null,
  source_draft_node_id:null,parent_key:'q3',node_type:'subquestion',depth:1,sort_order:3,
  label:{raw:'(3)',normalized:'3'},body_text:'点$A(1,1)$、$B(2,2)$を記入してください。',
  ordered_content:[{type:'text',order:0,text:'点$A(1,1)$、$B(2,2)$を記入してください。',
   merged_source_segments:[{type:'formula_region',region_id:'math-a'},{type:'formula_region',region_id:'math-b'}]}],
  included:true,score_semantics:'direct',score_points:10,review_flags:[],warning_states:{},figure_decisions:{},
  formula_decisions:{'math-a':{decision:'merged_into_text',teacher_transcription:'、',confirmation_status:status},
   'math-b':{decision:'merged_into_text',teacher_transcription:'B(2,2)',confirmation_status:status}}};
}
for(const status of ['confirmed','unreviewed'] as const){
 test(`prose-only edit preserves ${status} embedded formulas including legacy punctuation`,()=>{
  const node=mergedNode(status),original=structuredClone(node);
  const text=questionContent(node,[]).text+' 各クラスを説明してください。';
  const changed=editQuestionContent(node,[],text)!;
  expect(changed.formula_decisions).toEqual(original.formula_decisions);
  expect(questionContent(changed,[]).text).toBe(text);
  expect(node).toEqual(original);
  const snapshot={nodes:[node]} as AuthoringSnapshot;
  const prepared=prepareAuthoringSave(snapshot,{'q3-child':text});
  expect(questionContent(prepared.nodes[0],[]).text).toBe(text);
  expect(prepared.nodes[0].formula_decisions).toEqual(original.formula_decisions);
 });
}
test('changing math still requires its independent confirmation',()=>{
 const node=mergedNode('confirmed');
 const changed=editQuestionContent(node,[],questionContent(node,[]).text.replace('B(2,2)','B(3,3)'))!;
 expect(changed.formula_decisions['math-b'].confirmation_status).toBe('unreviewed');
});
test('no-op editor transition preserves exact node identity',()=>{
 const node=mergedNode('confirmed');expect(editQuestionContent(node,[],questionContent(node,[]).text)).toBe(node);
});
test('missing saved literal mapping cannot approve a new unmapped edit',()=>{
 const node=mergedNode('confirmed');
 node.ordered_content[0]={...node.ordered_content[0],text:'点$A(1,1)$と$B(2,2)$を記入してください。'};
 const text=questionContent(node,[]).text+' 追加した文章。';
 const prepared=prepareAuthoringSave({nodes:[node]} as AuthoringSnapshot,{'q3-child':text});
 expect(prepared.question_text_buffers?.['q3-child']).toBe(text);
 expect(prepared.nodes[0].ordered_content).toEqual(node.ordered_content);
});

test('Sample Q5 manual prose Save preserves math review and unrelated warnings across resume',async({page})=>{
 test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable production-like harness');
 test.setTimeout(90000);
 await page.goto('/login');await page.getByLabel('メールアドレス').fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
 await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
 await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Manual text review Sample Q5',total_points:100}})).json();
 const base=`/api/v1/tests/${exam.id}/authoring`;
 let row=await(await page.request.post(base+'/revisions')).json();
 const upload=await page.request.post(`/api/v1/tests/${exam.id}/question-materials`,{headers:{'content-type':'application/pdf','x-filename':'sampleQ5.pdf'},data:await readFile('../testData/SampleQ/sampleQ5.pdf')});expect(upload.status()).toBe(201);
 const extraction=await upload.json();
 const material=(await(await page.request.get(`/api/v1/tests/${exam.id}/materials`)).json()).find((m:{id:string})=>m.id===extraction.material_id);
 row.snapshot.materials.push({id:material.id,role:material.material_type,sha256:material.sha256});
 const binding=await page.request.put(base,{data:{expected_edit_version:row.edit_version,snapshot:row.snapshot}});expect(binding.status()).toBe(200);row=await binding.json();
 const draft=await(await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();
 expect((await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).status()).toBe(201);
 expect((await page.request.post(base+'/source-import',{data:{expected_edit_version:row.edit_version,analysis_material_id:extraction.material_id}})).status()).toBe(200);
 await page.goto(`/tests/${exam.id}/authoring`);
 const selector=page.getByLabel('対象設問',{exact:true});await selector.selectOption('q3');
 await page.locator('#authoring-question').getByRole('button',{name:'本文編集',exact:true}).click();
 const editor=page.getByLabel('問題文',{exact:true});await expect(editor).toBeEditable();
 // Establish existing formula review using its ordinary explicit control.
 await page.getByRole('button',{name:'問題文を確認',exact:true}).click();
 async function save(){const response=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));await page.getByRole('button',{name:'保存',exact:true}).click();expect((await response).status()).toBe(200);}
 await save();
 const baseline=(await(await page.request.get(base)).json()).revision;
 const before=baseline.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');
 const beforeIssues=(await(await page.request.get(base+'/review')).json()).issues;
 const warnings=beforeIssues.filter((i:{code:string})=>i.code==='question_source_warning');
 const text=await editor.inputValue();await editor.fill(text+'\n各点について説明してください。');await save();
 const saved=(await(await page.request.get(base)).json()).revision;
 const after=saved.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3');
 expect(after.formula_decisions).toEqual(before.formula_decisions);
 expect(after.teacher_correction.text_review.confirmation_origin).toBe('manual_edit');
 const issues=(await(await page.request.get(base+'/review')).json()).issues;
 expect(issues.filter((i:{code:string})=>i.code==='question_source_warning')).toEqual(warnings);
 expect(issues.some((i:{code:string;question_key:string})=>i.question_key==='q3'&&['formula_review','authoring_text_source_unresolved'].includes(i.code))).toBe(false);
 const count=issues.filter((i:{question_key:string})=>i.question_key==='q3').length;
 expect(count).toBe(beforeIssues.filter((i:{question_key:string})=>i.question_key==='q3').length);
 const option=selector.locator('option[value="q3"]');
 if(count){await expect(option).toContainText(' *');await expect(page.getByRole('button',{name:`要修正 ${count}件`,exact:true})).toBeVisible();}
 else {await expect(option).not.toContainText('*');await expect(page.getByRole('button',{name:/^要修正 \d+件$/})).toHaveCount(0);}
 await page.reload();await selector.selectOption('q3');await page.locator('#authoring-question').getByRole('button',{name:'本文編集',exact:true}).click();await expect(editor).toHaveValue(text+'\n各点について説明してください。');
 expect((await(await page.request.get(base)).json()).revision.snapshot.nodes.find((n:ReviewNode)=>n.stable_key==='q3').teacher_correction).toEqual(after.teacher_correction);
 await page.getByRole('link',{name:'戻る',exact:true}).click();await page.getByRole('link',{name:'テスト内容を編集',exact:true}).click();
 await selector.selectOption('q3');await page.locator('#authoring-question').getByRole('button',{name:'本文編集',exact:true}).click();await expect(editor).toHaveValue(text+'\n各点について説明してください。');
});
