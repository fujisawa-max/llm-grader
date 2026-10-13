import type {Page,Locator} from "@playwright/test";
/** Editing regressions explicitly enter the authoring screen's default previews. */
export async function openAuthoringEditors(page:Page){
  await page.locator("#authoring-answer").waitFor();
  await page.locator("[data-authoring-figure-operations]").evaluateAll(els=>els.forEach(el=>(el as HTMLDetailsElement).open=true));
  await page.locator("[data-answer-operations]").evaluateAll(els=>els.forEach(el=>(el as HTMLDetailsElement).open=true));
  const buttons=page.locator(".authoring-preview-editor").getByRole("button",{name:/^(編集する|本文編集)$/});
  while(await buttons.count())await buttons.first().click();
}

export async function openQuestionDialog(page:Page){
  await page.locator('#authoring-question [data-question-edit]').click();
  return page.getByRole('dialog',{name:'問題文',exact:true});
}
export async function editQuestionText(page:Page,text:string){
  const dialog=await openQuestionDialog(page);await dialog.getByLabel('問題文',{exact:true}).fill(text);await dialog.getByRole('button',{name:'完了',exact:true}).click();
}
export async function readQuestionText(page:Page){
  const dialog=await openQuestionDialog(page);const text=await dialog.getByLabel('問題文',{exact:true}).inputValue();await dialog.getByRole('button',{name:'キャンセル',exact:true}).click();return text;
}
export async function openQuestionOperations(page:Page){
  const back=page.locator('#authoring-question').getByRole('button',{name:'プレビューに戻る',exact:true});if(await back.count())await back.click();
  const details=page.locator('#authoring-question .compact-question-operations');if(!await details.evaluate(el=>(el as HTMLDetailsElement).open))await details.locator('summary').click();
}

export async function openAnswerDialog(page:Page,scope?:Locator){
  await (scope||page.locator('#authoring-answer')).locator('[data-answer-edit]').first().click();
  return page.getByRole('dialog',{name:'模範解答本文',exact:true});
}
export async function editAnswerText(page:Page,text:string,scope?:Locator){const dialog=await openAnswerDialog(page,scope);await dialog.getByLabel('模範解答本文',{exact:true}).fill(text);await dialog.getByRole('button',{name:'完了',exact:true}).click();}
export async function readAnswerText(page:Page,scope?:Locator){const dialog=await openAnswerDialog(page,scope);const text=await dialog.getByLabel('模範解答本文',{exact:true}).inputValue();await dialog.getByRole('button',{name:'キャンセル',exact:true}).click();return text;}
export async function addModelAnswer(page:Page,text=''){await page.locator('#authoring-answer').getByRole('button',{name:'模範解答を追加',exact:true}).click();const dialog=page.getByRole('dialog',{name:'模範解答本文',exact:true});await dialog.getByLabel('模範解答本文',{exact:true}).fill(text);await dialog.getByRole('button',{name:'完了',exact:true}).click();}
