import {expect,type Locator,type Page} from "@playwright/test";

export async function confirmAnalysis(page:Page,controls:Locator,action:"解析"|"再解析",accept=true){
  await controls.getByRole("button",{name:action,exact:true}).click();
  const dialog=page.getByRole("dialog",{name:/を(再)?解析しますか/});
  await expect(dialog).toBeVisible();
  if(accept)await dialog.getByRole("button",{name:action,exact:true}).click();
  else await dialog.getByRole("button",{name:"キャンセル",exact:true}).click();
}

export async function expectSaveToast(page:Page){
  await expect(page.locator(".authoring-toast").filter({hasText:"保存しました"}).last()).toBeVisible();
}

export async function expectUnsavedAnalysisHint(page:Page,controls:Locator){
  await expect(page.getByLabel("解析前の保存",{exact:true})).toHaveCount(0);
  const hint=controls.getByRole("group",{name:"解析できない理由",exact:true});
  const tooltip=hint.getByRole("tooltip");
  await hint.hover();
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveText("未保存の変更があります。この資料を解析する前に保存してください。");
  await page.mouse.move(0,0);
  await expect(tooltip).toBeHidden();
  await hint.focus();
  await expect(tooltip).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(tooltip).toBeHidden();
}
