import type {Page} from "@playwright/test";
/** Editing regressions explicitly enter the authoring screen's default previews. */
export async function openAuthoringEditors(page:Page){
  await page.locator(".authoring-preview-editor").first().waitFor();
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
