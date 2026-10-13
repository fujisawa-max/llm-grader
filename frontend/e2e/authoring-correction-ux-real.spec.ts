import {test,expect,type Page,type Locator} from '@playwright/test';
import {saveAuthoring} from './authoringNotifications';

test.setTimeout(90000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable API / RuntimeManager / production frontend');
async function login(page:Page){
  await page.setViewportSize({width:1600,height:900});
  const authReady=page.waitForResponse(r=>r.url().endsWith('/auth/me'));
  await page.goto('/login');await authReady;
  await page.getByLabel('メールアドレス').fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
  await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
}
async function visibleContent(page:Page,content:Locator){
  await expect(content).toBeVisible();
  const box=(await content.boundingBox())!;
  const stickyBottom=await page.locator('.review-workspace-selector').evaluate(el=>el.getBoundingClientRect().bottom);
  expect(box.y).toBeGreaterThanOrEqual(stickyBottom);
  expect(box.y).toBeLessThan(800);
  expect(box.y+Math.min(box.height,100)).toBeLessThanOrEqual(900);
}
async function calls(page:Page){return Promise.all(['ocr','math_ocr','ornith_rubric_draft','grader'].map(async profile=>{
  const result=await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();
  return result.lines.filter((line:string)=>line.includes('POST /v1/chat/completions')).length;
}));}
function errors(page:Page){const failures:string[]=[];page.on('pageerror',e=>failures.push(e.message));page.on('console',m=>{if(m.type()==='error')failures.push(m.text());});return failures;}

test('manual classification-routing edits confirm semantics, preserve automatic history, and prose edits do not',async({page})=>{
  await login(page);const failures=errors(page),tid=process.env.AUTHORING_CORRECTION_CLASSIFICATION_TEST_ID!,base=`/api/v1/tests/${tid}/authoring`;
  await page.goto(`/tests/${tid}/authoring`);await page.getByRole('button',{name:'設問を追加',exact:true}).waitFor();
  let row=(await(await page.request.get(base)).json()).revision;
  const original=row.snapshot.domains.answer.entries.find((e:any)=>e.semantic_classification?.status==='needs_teacher_review');expect(original).toBeTruthy();
  const automatic=structuredClone(original.semantic_classification),key=original.authoring_question_key;
  const selector=page.getByLabel('対象設問',{exact:true}),option=selector.locator(`option[value="${key}"]`);
  await selector.selectOption(key);await expect(option).toContainText(' *');await expect(page.getByRole('button',{name:'要修正 1件',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'最終確認へ',exact:true}).click();
  await page.locator('.authoring-issue-cards article').filter({hasText:'候補の分類が未確認'}).getByRole('button',{name:'模範解答を確認',exact:true}).click();
  const entry=page.locator(`#authoring-candidate-${original.id}`),details=entry.locator('[data-authoring-classification]');
  await expect(details).toHaveAttribute('open','');await visibleContent(page,details.locator('summary'));
  await expect(details).toHaveClass(/authoring-correction-target/);
  const before=await calls(page);await entry.getByLabel('模範解答本文',{exact:true}).fill(original.answer_text+' Teacher prose correction.');await saveAuthoring(page);
  row=(await(await page.request.get(base)).json()).revision;let saved=row.snapshot.domains.answer.entries.find((e:any)=>e.id===original.id);
  expect(saved.semantic_classification.status).toBe('needs_teacher_review');expect(saved.teacher_correction?.confirmation_origin).not.toBe('manual_edit');
  expect(saved.teacher_correction.text_review.confirmation_origin).toBe('manual_edit');
  expect(saved.teacher_correction.text_review.teacher_confirmed).toBe(true);
  expect(saved.semantic_classification).toEqual(automatic);
  expect(saved.diagram_records).toEqual(original.diagram_records);
  await expect(option).toContainText(' *');await expect(page.getByRole('button',{name:'要修正 1件',exact:true})).toBeVisible();
  await entry.getByLabel('解答の種類',{exact:true}).selectOption('alternative');
  await entry.getByLabel('解答の種類',{exact:true}).selectOption('primary');
  await expect(page.getByRole('button',{name:/^要修正 \d+件$/})).toHaveCount(0);await expect(option).not.toContainText('*');
  await expect(page.locator('.authoring-save-button')).toHaveClass(/is-dirty/);
  await saveAuthoring(page);row=(await(await page.request.get(base)).json()).revision;saved=row.snapshot.domains.answer.entries.find((e:any)=>e.id===original.id);
  expect(saved.semantic_classification.status).toBe('teacher_reviewed');expect(saved.teacher_correction.confirmation_origin).toBe('manual_edit');expect(saved.teacher_correction.classification_original).toEqual(automatic);
  expect((await(await page.request.get(base+'/review')).json()).issues).toEqual([]);
  // Category overrides retain the original automatic result too.
  await details.locator('select').first().selectOption('model_answer');await saveAuthoring(page);
  saved=(await(await page.request.get(base)).json()).revision.snapshot.domains.answer.entries.find((e:any)=>e.id===original.id);
  expect(saved.semantic_classification.segments[0].category).toBe('model_answer');expect(saved.teacher_correction.classification_original).toEqual(automatic);expect(saved.teacher_correction.classification_reviewed_fields).toContain('segment_category');
  await page.reload();await selector.selectOption(key);await expect(option).not.toContainText('*');expect(await calls(page)).toEqual(before);expect(failures).toEqual([]);
});

test('unassigned Answer and Rubric queues focus exact candidates and resolve by assignment or explicit exclusion',async({page})=>{
  await login(page);const failures=errors(page),tid=process.env.AUTHORING_CORRECTION_QUEUE_TEST_ID!,base=`/api/v1/tests/${tid}/authoring`;
  await page.goto(`/tests/${tid}/authoring`);await page.getByRole('button',{name:'設問を追加',exact:true}).waitFor();
  let row=(await(await page.request.get(base)).json()).revision;
  const answers=row.snapshot.domains.answer.entries.filter((e:any)=>!e.authoring_question_key),rubrics=row.snapshot.domains.rubric.entries.filter((e:any)=>!e.authoring_question_key);
  expect(answers).toHaveLength(2);expect(rubrics).toHaveLength(2);
  const target=row.snapshot.nodes[0].stable_key,before=await calls(page),otherAnswer=structuredClone(row.snapshot.domains.answer.entries.filter((e:any)=>e.authoring_question_key));
  const selector=page.getByLabel('対象設問',{exact:true});
  async function navigateCandidate(id:string,section:'answer'|'rubric'){
    await page.getByRole('button',{name:'最終確認へ',exact:true}).click();
    const issue=page.locator('.authoring-issue-cards article').filter({hasText:section==='answer'?'設問未割当の模範解答候補':'設問未割当の採点基準候補'}).first();
    await issue.getByRole('button',{name:section==='answer'?'模範解答を確認':'採点基準を修正',exact:true}).click();await expect(selector).toHaveValue('unassigned');
    const entry=page.locator(`[id="authoring-candidate-${id}"]`);await expect(entry).toHaveClass(/authoring-correction-target/);await expect(entry.getByRole('combobox',{name:'対応する設問',exact:true})).toBeFocused();
    await visibleContent(page,entry.locator('.authoring-candidate-resolution'));
    await visibleContent(page,entry.getByLabel('未割当候補の本文',{exact:true}));
    await expect(page.locator(`#authoring-${section}`)).toContainText('この候補を対応する設問へ割り当てるか、不要な候補として除外してください。');return entry;
  }
  let entry=await navigateCandidate(answers[0].id,'answer');await entry.getByRole('combobox',{name:'対応する設問',exact:true}).selectOption(target);
  await saveAuthoring(page);let review=(await(await page.request.get(base+'/review')).json());expect(review.issues.some((i:any)=>i.entry_id===answers[0].id)).toBe(false);
  entry=await navigateCandidate(answers[1].id,'answer');await entry.getByRole('button',{name:'不要として除外',exact:true}).click();await expect(entry.getByRole('status')).toContainText('除外済み');await saveAuthoring(page);
  entry=await navigateCandidate(rubrics[0].id,'rubric');await entry.getByRole('combobox',{name:'対応する設問',exact:true}).selectOption(target);await saveAuthoring(page);
  review=(await(await page.request.get(base+'/review')).json());expect(review.issues.some((i:any)=>i.entry_id===rubrics[0].id)).toBe(false);
  entry=await navigateCandidate(rubrics[1].id,'rubric');await entry.getByRole('button',{name:'不要として除外',exact:true}).click();await saveAuthoring(page);
  row=(await(await page.request.get(base)).json()).revision;
  for(const [domain,originals] of [['answer',answers],['rubric',rubrics]] as const){
    const current=row.snapshot.domains[domain].entries;
    for(const original of originals){const saved=current.find((e:any)=>e.id===original.id);expect(saved.source).toEqual(original.source);expect(saved.source_draft_id).toBe(original.source_draft_id);expect(saved.teacher_correction.confirmation_origin).toBe('manual_edit');}
    expect(current.find((e:any)=>e.id===originals[0].id).authoring_question_key).toBe(target);expect(current.find((e:any)=>e.id===originals[1].id).disposition).toBe('ignored');
  }
  expect(row.snapshot.domains.answer.entries.filter((e:any)=>otherAnswer.some((o:any)=>o.id===e.id))).toEqual(otherAnswer);
  review=(await(await page.request.get(base+'/review')).json());expect(review.issues).toEqual([]);
  await page.getByRole('button',{name:'最終確認へ',exact:true}).click();await expect(page.getByRole('heading',{name:'要修正事項 0件',exact:true})).toBeVisible();
  await page.reload();await selector.selectOption(target);await expect(selector.locator(`option[value="${target}"]`)).not.toContainText('*');await expect(page.getByRole('button',{name:/^要修正 \d+件$/})).toHaveCount(0);
  expect(await calls(page)).toEqual(before);expect((await(await page.request.get(`/api/v1/tests/${tid}/archive-impact`)).json()).grading_jobs).toBe(0);expect(failures).toEqual([]);
});

test('Rubric correction and confirmation keep criterion text below sticky controls with surrounding context',async({page})=>{
  await login(page);const failures=errors(page);
  const seed=await(await page.request.get(`/api/v1/tests/${process.env.AUTHORING_CORRECTION_QUEUE_TEST_ID}`)).json();
  const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Criterion content scroll correction',total_points:10}});expect(created.status()).toBe(201);
  const tid=(await created.json()).id,base=`/api/v1/tests/${tid}/authoring`;
  await page.goto(`/tests/${tid}/authoring`);await page.getByRole('button',{name:'設問を追加',exact:true}).click();await saveAuthoring(page);
  let row=(await(await page.request.get(base)).json()).revision;const node=row.snapshot.nodes[0];node.body_text='Review this Question.';node.ordered_content=[{type:'text',order:0,text:node.body_text}];node.score_semantics='direct';node.score_points=10;row.snapshot.question_text_buffers[node.stable_key]=node.body_text;
  row.snapshot.answers[node.stable_key]={primary:'Teacher answer.',alternatives:[],diagram_records:[]};row.snapshot.rubrics[node.stable_key]=Array.from({length:5},(_,i)=>({id:`criterion-${i}`,description:`Criterion ${i+1}: review this full source condition.`,points:2,levels:[{score:0,condition:"No credit"},{score:2,condition:"Complete criterion"}],segment_ids:[],grouping_confirmed:i!==4,provenance:{source:'teacher_manual'}}));
  expect((await page.request.put(base,{data:{snapshot:row.snapshot,expected_edit_version:row.edit_version}})).status()).toBe(200);await page.reload();
  await page.getByRole('button',{name:'最終確認へ',exact:true}).click();await page.locator('.authoring-issue-cards article').filter({hasText:'統合内容が未確認'}).getByRole('button',{name:'採点基準を修正',exact:true}).click();
  const criterion=page.locator('#authoring-rubric-criterion-4'),body=criterion.locator('.compact-rubric-body');await expect(criterion).toHaveClass(/authoring-correction-target/);await visibleContent(page,body);
  const originalCriterion=structuredClone(row.snapshot.rubrics[node.stable_key][4]);
  await criterion.locator('.compact-rubric-criterion-header').getByRole('button',{name:'編集',exact:true}).click();
  const bodyDialog=page.getByRole('dialog',{name:'採点基準本文'});await bodyDialog.getByLabel('採点基準本文').fill(originalCriterion.description+' Teacher text correction.');await bodyDialog.getByRole('button',{name:'完了',exact:true}).click();await saveAuthoring(page);
  const corrected=(await(await page.request.get(base)).json()).revision.snapshot.rubrics[node.stable_key][4];
  expect(corrected.provenance.text_review.confirmation_origin).toBe('manual_edit');
  expect(corrected.grouping_confirmed).toBe(false);
  expect(corrected.points).toBe(originalCriterion.points);expect(corrected.levels).toEqual(originalCriterion.levels);
  await expect(page.getByRole('button',{name:/^要修正 \d+件$/})).toBeVisible();
  await criterion.getByRole('button',{name:'この採点基準を確認',exact:true}).click();await expect(page.getByRole('button',{name:/^要修正 \d+件$/})).toHaveCount(0);await visibleContent(page,body);await saveAuthoring(page);
  row=(await(await page.request.get(base)).json()).revision;expect(row.snapshot.rubrics[node.stable_key][4].grouping_confirmed).toBe(true);expect((await(await page.request.get(base+'/review')).json()).issues).toEqual([]);expect(failures).toEqual([]);
});
