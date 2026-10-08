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
