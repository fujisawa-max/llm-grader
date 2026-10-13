import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {authoringBuffers,prepareAuthoringSave} from '../lib/authoringState';
test.setTimeout(90000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,'requires disposable production-like harness');
test('Sample Q5 source issues navigate to exact warning and resolve without body edits',async({page})=>{
 await page.setViewportSize({width:1600,height:900});
 await page.goto('/login');await page.getByLabel('メールアドレス').fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);await page.getByLabel('パスワード').fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole('button',{name:'ログイン',exact:true}).click();await expect(page).not.toHaveURL(/login/);
 const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
 const exam=await(await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:'Question source issue targets',total_points:100}})).json();
 const base=`/api/v1/tests/${exam.id}/authoring`;
 let row=await(await page.request.post(base+'/revisions')).json();
 const upload=await page.request.post(`/api/v1/tests/${exam.id}/question-materials`,{headers:{'content-type':'application/pdf','x-filename':'sampleQ5.pdf'},data:await readFile('../testData/SampleQ/sampleQ5.pdf')});expect(upload.status()).toBe(201);
 const extraction=await upload.json();
 const material=(await(await page.request.get(`/api/v1/tests/${exam.id}/materials`)).json()).find((m:{id:string})=>m.id===extraction.material_id);
 row.snapshot.materials.push({id:material.id,role:material.material_type,sha256:material.sha256});
 const bindingSave=await page.request.put(base,{data:{expected_edit_version:row.edit_version,snapshot:row.snapshot}});expect(bindingSave.status()).toBe(200);row=await bindingSave.json();
 const draft=await(await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();expect((await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).status()).toBe(201);
 const imported=await page.request.post(base+'/source-import',{data:{expected_edit_version:row.edit_version,analysis_material_id:extraction.material_id}});expect(imported.status()).toBe(200);row=await imported.json();
 // Establish the normal saved editor representation before source-only decisions.
 const initialSave=await page.request.put(base,{data:{expected_edit_version:row.edit_version,snapshot:prepareAuthoringSave(row.snapshot,authoringBuffers(row.snapshot))}});expect(initialSave.status()).toBe(200);row=await initialSave.json();
 const bodies=row.snapshot.nodes.map((n:{stable_key:string;body_text:string})=>[n.stable_key,n.body_text]);
 const before=(await(await page.request.get(base+'/review')).json()).issues;
 const owned=before.find((i:{code:string;question_key:string})=>i.code==='question_source_warning'&&i.question_key);
 expect(owned).toBeTruthy();
 const globals=before.filter((i:{code:string;question_key:string})=>i.code==='question_source_warning'&&!i.question_key);
 expect(globals).toHaveLength(1);expect(globals[0].warning_id).toBe('draft:document:unresolved_vector_evidence');
 const label='設問の図表や数値・文字・文章の位置関係を確認してください';
 const explanation='本来意図されている位置関係の認識に失敗した可能性があります。元資料と照合してください。';
 expect(owned.question_key).toBe('q2');expect(owned.warning_id).toBe('node:q2:ambiguous_geometric_order');expect(owned.message).toBe(label);
 const aggregateId='draft:document:ambiguous_geometric_order';
 const catalog=(await(await page.request.get(base+'/review')).json()).question_warning_catalog;
 expect(catalog.find((w:{id:string})=>w.id===aggregateId).actionable).toBe(false);
 expect(before.some((i:{warning_id:string})=>i.warning_id===aggregateId)).toBe(false);
 await page.goto(`/tests/${exam.id}/authoring`);
 const selector=page.getByLabel('対象設問',{exact:true});await selector.selectOption(owned.question_key);
 const count=before.filter((i:{question_key:string})=>i.question_key===owned.question_key).length;
 const tab=page.getByRole('button',{name:`要修正 ${count}件`,exact:true});await expect(tab).toBeVisible();
 await tab.click();const overlay=page.getByRole('region',{name:/の要修正$/});
 const card=overlay.locator('article').filter({hasText:owned.message});await expect(card).toContainText('確認状態を「確認済み」');await expect(card).toContainText(explanation);
 await card.getByRole('button',{name:'出典確認へ',exact:true}).click();
 const warning=page.locator(`[id="review-warning-${encodeURIComponent(owned.warning_id)}"]`);
 await expect(warning).toBeVisible();await expect(warning).toContainText(label);await expect(warning).toContainText(explanation);await expect(warning).toHaveClass(/authoring-correction-target/);
 const select=warning.getByRole('combobox');await expect(select).toBeFocused();
 expect(await selector.inputValue()).toBe(owned.question_key);
 const box=(await warning.boundingBox())!,bottom=await page.locator('.review-workspace-selector').evaluate(e=>e.getBoundingClientRect().bottom);
 expect(box.y).toBeGreaterThanOrEqual(bottom);expect(box.y).toBeLessThan(700);
 await warning.getByRole('button',{name:'確認済みにする',exact:true}).click();
 await expect(page.getByRole('button',{name:`要修正 ${count}件`,exact:true})).toHaveCount(0);
 const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));await page.getByRole('button',{name:'保存',exact:true}).click();expect((await saved).status()).toBe(200);
 const after=(await(await page.request.get(base+'/review')).json()).issues;
 expect(after.some((i:{warning_id:string})=>i.warning_id===owned.warning_id)).toBe(false);
 const remaining=after.filter((i:{question_key:string})=>i.question_key===owned.question_key).length;expect(remaining).toBe(count-1);
 const option=selector.locator(`option[value="${owned.question_key}"]`);if(remaining){await expect(option).toContainText(' *');await expect(page.getByRole('button',{name:`要修正 ${remaining}件`,exact:true})).toBeVisible();}else await expect(option).not.toContainText('*');
 await page.getByRole('button',{name:'最終確認へ',exact:true}).click();
 const globalCard=page.locator('.authoring-issue-cards article').filter({hasText:globals[0].message});await globalCard.getByRole('button',{name:'出典確認へ',exact:true}).click();
 await expect(selector).toHaveValue('all');
 const globalWarning=page.locator(`[id="review-warning-${encodeURIComponent(globals[0].warning_id)}"]`);await expect(globalWarning).toBeVisible();await expect(globalWarning).toHaveClass(/authoring-correction-target/);
 await globalWarning.getByRole('button',{name:'確認済みにする',exact:true}).click();
 const saved2=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));await page.getByRole('button',{name:'保存',exact:true}).click();expect((await saved2).status()).toBe(200);
 const final=(await(await page.request.get(base)).json()).revision;
 expect(final.snapshot.nodes.map((n:{stable_key:string;body_text:string})=>[n.stable_key,n.body_text])).toEqual(bodies);
 const finalIssues=(await(await page.request.get(base+'/review')).json()).issues;
 expect(finalIssues.some((i:{warning_id:string})=>i.warning_id===globals[0].warning_id)).toBe(false);
 expect(finalIssues.some((i:{warning_id:string})=>i.warning_id===aggregateId)).toBe(false);
 expect(final.snapshot.domains.question.snapshot.warning_states[aggregateId]).toBeUndefined();
 expect(final.snapshot.domains.question.document.warnings.some((w:{id:string})=>w.id===aggregateId)).toBe(true);
 await page.reload();await selector.selectOption('all');await expect(page.locator(`[id="review-warning-${encodeURIComponent(globals[0].warning_id)}"]`).getByRole('combobox')).toHaveValue('acknowledged');await expect(page.locator(`[id="review-warning-${encodeURIComponent(aggregateId)}"]`)).toHaveCount(0);await selector.selectOption('q2');await expect(selector.locator('option[value="q2"]')).not.toContainText('*');await page.getByRole('link',{name:'戻る',exact:true}).click();await page.getByRole('link',{name:'テスト内容を編集',exact:true}).click();await selector.selectOption('q2');await expect(selector.locator('option[value="q2"]')).not.toContainText('*');
 // Controlled server-response fixture for an independently attested document concern.
 // Real backend mixed/independent provenance behavior is covered in backend tests.
 await page.route(`**/api/v1/tests/${exam.id}/authoring/review`,async route=>{
  const response=await route.fetch(),data=await response.json();
  const current=route.request().method()==='POST'?route.request().postDataJSON().snapshot:
   (await(await page.request.get(base)).json()).revision.snapshot;
  const aggregate=data.question_warning_catalog.find((w:{id:string})=>w.id===aggregateId);
  aggregate.coverage.independent_evidence_ids=['fixture:page-1-header'];aggregate.actionable=true;delete aggregate.requirement_kind;
  if((current.domains.question.snapshot.warning_states[aggregateId]?.state||'unreviewed')==='unreviewed'){
   data.issues.push({...owned,question_key:null,warning_id:aggregateId,source_item_id:'document',source_scope:'draft',source_review_index:1,
    current_state:'元資料全体について確認が必要です。'});data.can_confirm=false;
  }
  await route.fulfill({response,json:data});
 });
 await page.reload();await page.getByRole('button',{name:'最終確認へ',exact:true}).click();
 const independent=page.locator('.authoring-issue-cards article').filter({hasText:label});
 await expect(independent).toHaveCount(1);await expect(independent).toContainText(explanation);
 await independent.getByRole('button',{name:'出典確認へ',exact:true}).click();await expect(selector).toHaveValue('all');
 const documentRow=page.locator(`[id="review-warning-${encodeURIComponent(aggregateId)}"]`);
 await expect(documentRow).toBeVisible();await expect(documentRow).toHaveClass(/authoring-correction-target/);
 await expect(documentRow).toContainText(label);await expect(documentRow).toContainText(explanation);
 await documentRow.getByRole('button',{name:'確認済みにする',exact:true}).click();
 const saveIndependent=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(base));
 await page.getByRole('button',{name:'保存',exact:true}).click();expect((await saveIndependent).status()).toBe(200);
 await page.getByRole('button',{name:'最終確認へ',exact:true}).click();await expect(page.locator('.authoring-issue-cards article').filter({hasText:label})).toHaveCount(0);
 const independentSaved=(await(await page.request.get(base)).json()).revision.snapshot;
 expect(independentSaved.domains.question.snapshot.warning_states[aggregateId].state).toBe('acknowledged');
 expect(independentSaved.nodes.map((n:{stable_key:string;body_text:string})=>[n.stable_key,n.body_text])).toEqual(bodies);

});
