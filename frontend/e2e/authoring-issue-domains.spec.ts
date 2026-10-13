import {test,expect} from '@playwright/test';
import type {AuthoringIssue} from '../lib/api/testAuthoring';
import {authoringIssueDomain,countAuthoringIssueDomains,visibleAuthoringIssues} from '../lib/authoringIssueDomains';

const issue=(section:string,extra:Partial<AuthoringIssue>={}):AuthoringIssue=>({section,question_key:'child',message:'採点基準という語を含んでも本文のdomainは変わらない',...extra});

test('structured domains own counts; prose never classifies issues',()=>{
 const issues=[issue('question'),issue('answer'),issue('rubric'),issue('source',{domain:'answer'}),issue('source',{domain:'model_answer'})];
 expect(countAuthoringIssueDomains(issues)).toEqual({question:1,answer:3,rubric:1,common:0});
 expect(authoringIssueDomain(issue('question',{domain:'rubric'}))).toBe('rubric');
 expect(visibleAuthoringIssues(issues,{question:false,answer:true,rubric:false})).toEqual([issues[1],issues[3],issues[4]]);
});
test('test-wide source, total, Save, publication and unknown issues stay visible as common',()=>{
 const issues=['source','metadata','save','publication','future_domain'].map(section=>issue(section,{question_key:null}));
 expect(countAuthoringIssueDomains(issues)).toEqual({question:0,answer:0,rubric:0,common:5});
 expect(visibleAuthoringIssues(issues,{question:false,answer:false,rubric:false})).toEqual(issues);
});
test('domain union preserves server order, identities and direct Question ownership',()=>{
 const issues=[issue('question',{warning_id:'node:child:warning'}),issue('answer'),issue('rubric'),issue('rubric',{question_key:'parent'})];
 const before=structuredClone(issues);
 const selected=issues.filter(item=>item.question_key==='child');
 expect(visibleAuthoringIssues(selected,{question:true,answer:false,rubric:true})).toEqual([issues[0],issues[2]]);
 expect(visibleAuthoringIssues(selected,{question:true,answer:true,rubric:true})).toEqual(selected);
 expect(issues).toEqual(before);
});

test('Answer-only workspace exposes Rubric count without showing its issues; Final Review stays complete',async({page})=>{
 test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable production-like API/browser harness');
 test.setTimeout(90000);
 await page.setViewportSize({width:1600,height:900});
 await page.goto('/login');await page.getByLabel('メールアドレス').fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
 await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
 await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Domain-scoped issue counts',total_points:10}});expect(created.status()).toBe(201);
 const exam=await created.json(),base=`/api/v1/tests/${exam.id}/authoring`;
 await page.goto(`/tests/${exam.id}/authoring`);await page.getByRole('button',{name:'設問を追加',exact:true}).click();
 const saveResponse=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));
 await page.getByRole('button',{name:'保存',exact:true}).click();expect((await saveResponse).status()).toBe(200);
 let row=(await(await page.request.get(base)).json()).revision;
 const node=row.snapshot.nodes[0],key=node.stable_key;
 node.body_text='Explain the answer.';node.ordered_content=[{type:'text',order:0,text:node.body_text}];node.score_points=10;node.score_semantics='direct';
 row.snapshot.question_text_buffers[key]=node.body_text;
 row.snapshot.answers[key]={primary:'Teacher-approved correct answer.',alternatives:[],diagram_records:[]};
 expect((await page.request.put(base,{data:{snapshot:row.snapshot,expected_edit_version:row.edit_version}})).status()).toBe(200);
 const review=await(await page.request.get(base+'/review')).json(),counts=countAuthoringIssueDomains(review.issues);
 expect(counts.answer).toBe(0);expect(counts.question).toBe(0);expect(counts.rubric).toBeGreaterThan(0);expect(counts.common).toBe(0);expect(review.can_confirm).toBe(false);
 const persisted=(await(await page.request.get(base)).json()).revision;
 const requests:string[]=[];page.on('request',request=>{if(/analyze|math-ocr|latex-normalize|grading-jobs/.test(request.url()))requests.push(request.url());});
 await page.reload();const selector=page.getByLabel('対象設問',{exact:true});await selector.selectOption(key);
 const question=page.getByRole('checkbox',{name:'問題',exact:true}),answer=page.getByRole('checkbox',{name:'解答',exact:true}),rubric=page.getByRole('checkbox',{name:'採点基準',exact:true});
 await question.uncheck();await answer.check();await rubric.uncheck();
 const summary=page.getByRole('group',{name:'要修正の分野別件数',exact:true});
 await expect(summary.getByLabel('解答 0件',{exact:true})).toHaveText('解答(0)');
 await expect(summary.getByLabel(`採点基準 ${counts.rubric}件`,{exact:true})).toHaveText(`採点基準(${counts.rubric})`);
 await expect(summary).toContainText('問題(0)');
 await expect(selector.locator(`option[value="${key}"]`)).toContainText(' *');
 const globalTrigger=page.getByRole('button',{name:`要修正事項、未解決${review.issues.length}件`,exact:true});
 await globalTrigger.click();const popup=page.getByRole('region',{name:'要修正事項',exact:true});
 await expect(popup).toContainText('表示中 0件');await expect(popup.locator('li')).toHaveCount(0);
 for(const item of review.issues)await expect(popup).not.toContainText(item.message);
 await popup.getByRole('button',{name:'閉じる',exact:true}).click();
 const floating=page.getByRole('button',{name:'要修正 0件',exact:true});await expect(floating).toBeVisible();await floating.click();
 const local=page.getByRole('region',{name:/の要修正$/});await expect(local.locator('article')).toHaveCount(0);await expect(local).toContainText('表示中の分野に要修正事項はありません');
 const measure=()=>page.locator('.review-workspace-body').evaluate(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,scroll:window.scrollY}));
 await page.keyboard.press('Escape');const before=await measure();await floating.click();expect(await measure()).toEqual(before);
 await rubric.check();await expect(local.locator('article')).toHaveCount(counts.rubric);
 await expect(summary.getByLabel('解答 0件',{exact:true})).toHaveText('解答(0)');
 await expect(page.getByRole('button',{name:`要修正 ${counts.rubric}件`,exact:true})).toBeVisible();
 // No duplicate union and no server state changes from toggles.
 await question.check();await expect(local.locator('article')).toHaveCount(review.issues.length);
 const unchanged=await(await page.request.get(base+'/review')).json();expect(unchanged.issues).toEqual(review.issues);expect(unchanged.can_confirm).toBe(false);
 expect((await(await page.request.get(base)).json()).revision).toEqual(persisted);
 await page.keyboard.press('Escape');await question.uncheck();await rubric.uncheck();
 await page.getByRole('button',{name:'最終確認へ',exact:true}).click();
 const final=page.getByRole('region',{name:'テスト全体確認',exact:true});
 await expect(final.locator('.authoring-issue-cards article')).toHaveCount(review.issues.length);
 for(const item of review.issues)await expect(final).toContainText(item.message);
 await expect(page.getByRole('button',{name:'この内容でテストを確定',exact:true})).toBeDisabled();
 // A global correction enables the hidden editor and keeps the precise target.
 const target=review.issues.find((item:AuthoringIssue)=>item.section==='rubric');
 await final.locator('.authoring-issue-cards article').filter({hasText:target.message}).getByRole('button').click();
 await expect(selector).toHaveValue(key);await expect(rubric).toBeChecked();await expect(page.locator('#authoring-rubric')).toBeVisible();
 await expect(page.locator('.authoring-correction-target')).toBeVisible();
 expect(requests).toEqual([]);
 await page.reload();await selector.selectOption(key);await expect(selector.locator(`option[value="${key}"]`)).toContainText(' *');
 // Visibility remains a preference, never an acknowledgment or saved issue state.
 expect((await(await page.request.get(base)).json()).revision).toEqual(persisted);
 // Introduce a separate real Question requirement to exercise a nonempty union.
 const changed=structuredClone(persisted.snapshot);
 changed.nodes[0].body_text='';changed.nodes[0].ordered_content=[{type:'text',order:0,text:''}];changed.question_text_buffers[key]='';
 expect((await page.request.put(base,{data:{snapshot:changed,expected_edit_version:persisted.edit_version}})).status()).toBe(200);
 const unionReview=await(await page.request.get(base+'/review')).json(),unionCounts=countAuthoringIssueDomains(unionReview.issues);
 expect(unionCounts.question).toBeGreaterThan(0);expect(unionCounts.answer).toBe(0);expect(unionCounts.common).toBe(0);
 await page.reload();await selector.selectOption(key);await question.uncheck();await answer.check();await rubric.check();
 const unionTrigger=page.getByRole('button',{name:`要修正事項、未解決${unionReview.issues.length}件`,exact:true});await unionTrigger.click();
 await expect(popup.locator('li')).toHaveCount(unionCounts.rubric);
 await question.check();await expect(popup.locator('li')).toHaveCount(unionCounts.question+unionCounts.rubric);
 for(const item of unionReview.issues)await expect(popup).toContainText(item.message);
 expect((await(await page.request.get(base+'/review')).json()).issues).toEqual(unionReview.issues);
 expect(requests).toEqual([]);
});
