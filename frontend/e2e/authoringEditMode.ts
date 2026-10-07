import type {Page} from "@playwright/test";
/** Editing regressions explicitly enter the authoring screen's default previews. */
export async function openAuthoringEditors(page:Page){
  await page.locator(".authoring-preview-editor").first().waitFor();
  const buttons=page.locator(".authoring-preview-editor").getByRole("button",{name:"編集する",exact:true});
  while(await buttons.count())await buttons.first().click();
}
