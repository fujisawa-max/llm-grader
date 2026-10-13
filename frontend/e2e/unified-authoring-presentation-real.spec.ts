import {test,expect} from '@playwright/test';
import {saveAuthoring} from './authoringNotifications';
test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable real API and production frontend');
test('normal authoring presents current content, compact figure state and authoritative Rubric labels',async({page})=>{
 await page.goto('/login');await page.getByLabel('メールアドレス').fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();const create=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Compact ModelAnswer validation',total_points:10}});expect(create.status()).toBe(201);const tid=(await create.json()).id,base=`/api/v1/tests/${tid}/authoring`;
 await page.goto(`/tests/${tid}/authoring`);await page.getByRole('button',{name:'設問を追加',exact:true}).click();await saveAuthoring(page);let row=(await(await page.request.get(base)).json()).revision;const key=row.snapshot.nodes[0].stable_key;row.snapshot.nodes[0].body_text='Compute x.';row.snapshot.nodes[0].ordered_content=[{type:'text',order:0,text:'Compute x.'}];row.snapshot.question_text_buffers[key]='Compute x.';row.snapshot.nodes[0].score_semantics='direct';row.snapshot.nodes[0].score_points=10;row.snapshot.answers[key]={primary:'$x=1$',alternatives:['A second accepted answer'],diagram_records:[]};row.snapshot.rubrics[key]=[{id:'compact-answer-criterion',description:'Correct x',points:10,grouping_confirmed:true,levels:[{score:0,condition:'No credit'},{score:10,condition:'Correct x'}],segment_ids:[],provenance:{source:'teacher_manual'}}];expect((await page.request.put(base,{data:{snapshot:row.snapshot,expected_edit_version:row.edit_version}})).status()).toBe(200);await page.reload();

 const question=page.locator('#authoring-question'),answer=page.locator('#authoring-answer'),rubric=page.locator('#authoring-rubric');
 const persisted=(await(await page.request.get(base)).json()).revision;
 await expect(question.getByRole('heading',{name:persisted.snapshot.nodes[0].label.raw,exact:true})).toHaveCount(0);
 await expect(question.locator('.compact-question-body')).toContainText('Compute x.');
 await expect(question.getByText('図は登録されていません。',{exact:true})).toBeVisible();
 await expect(answer.getByText('図は登録されていません。',{exact:true})).toBeVisible();
 await expect(rubric.getByRole('heading',{name:'採点基準',exact:true})).toBeVisible();
 await expect(rubric.getByRole('heading',{name:'採点基準候補',exact:true})).toHaveCount(0);
 await expect(rubric.getByText('最高点は得点段階から自動計算されます。',{exact:true})).toHaveCount(0);
 await expect(rubric.locator('.compact-rubric-criterion').first()).toContainText('最高点: 10点');
 const operations=question.locator('[data-authoring-figure-operations]');
 // This manually authored fixture has no source-review machinery; no candidate gallery is introduced.
 await expect(operations).toHaveCount(0);
 await expect(question.getByRole('button',{name:'図候補を確認',exact:true})).toHaveCount(0);
 await expect(answer.locator('textarea')).toHaveCount(0);
 await page.reload();await expect(question.getByText('図は登録されていません。',{exact:true})).toBeVisible();
 expect((await(await page.request.get(base)).json()).revision.snapshot).toEqual(persisted.snapshot);
 expect((await(await page.request.get(`/api/v1/tests/${tid}/archive-impact`)).json()).grading_jobs).toBe(0);
});

test('structured figure issue opens the exact assigned Answer figure operation without saving',async({page})=>{
 await page.goto('/login');await page.getByLabel('メールアドレス').fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const tid=process.env.AUTHORING_CORRECTION_QUEUE_TEST_ID!,base=`/api/v1/tests/${tid}/authoring`,saved=(await(await page.request.get(base)).json()).revision;
 const entry=saved.snapshot.domains.answer.entries.find((e:any)=>e.authoring_question_key);
 expect(entry).toBeTruthy();
 await page.goto(`/tests/${tid}/authoring`);await page.getByLabel('対象設問',{exact:true}).selectOption(entry.authoring_question_key);
 const card=page.locator(`[id="authoring-candidate-${entry.id}"]`),operations=card.locator('[data-authoring-figure-operations]');
 await expect(operations.locator(':scope > summary')).toHaveAttribute('aria-expanded','false');
 // Control only the structured issue response; actual saved content/API/figure controls stay real.
 await page.route(`**${base}/review`,async route=>{const response=await route.fetch(),body=await response.json();body.issues=[...body.issues,{question_key:entry.authoring_question_key,entry_id:entry.id,section:'answer',domain:'answer',field:'diagram',code:'grading_visual_incomplete',message:'図を使った採点に必要な参照範囲が未確認です。',action_label:'図の参照を確認',expected_state:'図の出典と範囲を確認してください。'}];body.can_confirm=false;await route.fulfill({response,json:body});});
 await page.getByRole('button',{name:'最終確認へ',exact:true}).click();await page.locator('.authoring-issue-cards article').filter({hasText:'図を使った採点に必要な参照範囲が未確認です。'}).getByRole('button',{name:'図の参照を確認',exact:true}).click();
 await expect(page.getByLabel('対象設問',{exact:true})).toHaveValue(entry.authoring_question_key);await expect(operations.locator(':scope > summary')).toHaveAttribute('aria-expanded','true');
 await expect(card.getByRole('button',{name:'図候補を確認',exact:true})).toBeVisible();await expect(card.getByRole('button',{name:'図候補を確認',exact:true})).toBeFocused();await operations.locator(':scope > summary').click();await expect(card.getByText('図の出典・範囲に確認が必要です。',{exact:true})).toBeVisible();
 expect((await(await page.request.get(base)).json()).revision).toEqual(saved);
 expect((await(await page.request.get(`/api/v1/tests/${tid}/archive-impact`)).json()).grading_jobs).toBe(0);
});
