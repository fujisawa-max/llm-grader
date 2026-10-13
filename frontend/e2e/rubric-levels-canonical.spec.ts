import {test,expect} from "@playwright/test";
import {derivedRubricMaximum,initialRubricLevels,prepareRubricCriteria} from "../lib/rubricLevels";
import {editAnswerText,openAuthoringEditors,editQuestionText} from "./authoringEditMode";

test("Web criteria derive their maximum only from score levels",()=>{
  const levels=initialRubricLevels(10,"Full response");
  expect(levels).toEqual([
    {score:0,condition:"基準を満たしていない。"},
    {score:10,condition:"Full response"},
  ]);
  expect(derivedRubricMaximum({levels:[...levels,{score:5,condition:"Partial"}]})).toBe(10);
  expect(derivedRubricMaximum({levels:[levels[0],{score:5,condition:"Partial"}]})).toBe(5);
  expect(prepareRubricCriteria([{id:"old",description:"Full response",points:10,levels:[]}])[0].levels)
    .toEqual(levels);
  expect(prepareRubricCriteria([{id:"new",description:"",points:0,levels:[]}])[0].levels)
    .toEqual([{score:0,condition:"基準を満たしていない。"},{score:null,condition:""}]);
  expect(initialRubricLevels(8,"Uncertain",true))
    .toEqual([{score:0,condition:"基準を満たしていない。"},{score:8,condition:""}]);
});

test.setTimeout(120000);
test("compact Rubric editor uses local dialogs and keeps score levels canonical",async({page})=>{
  test.skip(!process.env.RUNTIME_MANAGER_E2E,"requires isolated FastAPI/production browser harness");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button",{name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
  const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:`Compact Rubric ${Date.now()}`,total_points:10}});
  expect(created.status()).toBe(201);const exam=await created.json(),base=`/api/v1/tests/${exam.id}`;
  await page.goto(`/tests/${exam.id}/authoring`);
  await page.getByRole("button",{name:"設問を追加",exact:true}).click();
  await page.getByRole("button",{name:"設問設定の変更",exact:true}).click();
  await page.getByRole("spinbutton",{name:/^配点/}).fill("10");
  await page.getByRole("button",{name:"プレビューに戻る",exact:true}).click();
  await openAuthoringEditors(page);
  await editQuestionText(page,"x = 1");
  await editAnswerText(page,"x = 1");
  await page.getByRole("checkbox",{name:"採点基準",exact:true}).check();
  await page.getByRole("button",{name:"基準を追加",exact:true}).click();
  const rubric=page.getByRole("region",{name:"採点基準候補",exact:true});
  const criterion=rubric.locator(".compact-rubric-criterion").first();
  await expect(criterion.getByRole("button",{name:"編集",exact:true})).toBeVisible();
  await expect(rubric.getByLabel("基準1の配点",{exact:true})).toHaveCount(0);
  await expect(criterion.locator("textarea")).toHaveCount(0);
  const details=criterion.locator('details[aria-label="得点段階"]');
  await expect(details.locator("summary")).toContainText("2段階");
  await expect(details.locator("summary")).toContainText("最高点: 0点");
  await expect(details.locator("summary")).toContainText("未設定");
  await details.locator("summary").click();
  await expect(details.getByRole("table")).toBeVisible();
  await expect(details).toContainText("基準を満たしていない。");
  await expect(details.locator("textarea")).toHaveCount(0);

  await criterion.locator(".compact-rubric-criterion-header").getByRole("button",{name:"編集",exact:true}).click();
  const bodyDialog=page.getByRole("dialog",{name:"採点基準本文"});
  await bodyDialog.getByLabel("採点基準本文").fill("値を正しく求める。\n根拠を説明する。");
  await bodyDialog.getByRole("button",{name:"完了",exact:true}).click();
  await expect(criterion).toContainText("値を正しく求める。");

  async function editLevel(row:number,score:string,condition:string){
    await details.locator("tbody tr").nth(row).getByRole("button",{name:"編集",exact:true}).click();
    const dialog=page.getByRole("dialog",{name:/得点段階を編集/});
    await dialog.getByLabel("点数").fill(score);
    await dialog.getByLabel("条件").fill(condition);
    await dialog.getByRole("button",{name:"完了",exact:true}).click();
  }
  await details.locator("tbody tr").nth(0).getByRole("button",{name:"編集",exact:true}).click();
  const zeroLevelDialog=page.getByRole("dialog",{name:"得点段階を編集"});
  await expect(zeroLevelDialog.getByRole("button",{name:"得点段階を削除",exact:true})).toHaveCount(0);
  await zeroLevelDialog.getByRole("button",{name:"キャンセル",exact:true}).click();
  await editLevel(1,"10","必要事項をすべて満たしている。");
  await details.getByRole("button",{name:/得点段階を追加/}).click();
  let dialog=page.getByRole("dialog",{name:"得点段階を追加"});
  await dialog.getByLabel("点数").fill("5");await dialog.getByLabel("条件").fill("正答だが説明が一部不足している。");
  await dialog.getByRole("button",{name:"完了",exact:true}).click();
  await expect(details.locator("summary")).toContainText("3段階: 0点 / 5点 / 10点");
  await expect(details.locator("summary")).toContainText("最高点: 10点");
  await expect(page.getByText("未保存の変更があります").first()).toBeVisible();

  await details.locator("tbody tr").nth(2).getByRole("button",{name:"編集",exact:true}).click();
  dialog=page.getByRole("dialog",{name:"得点段階を編集"});
  await dialog.getByRole("button",{name:"得点段階を削除",exact:true}).click();
  await expect(details.locator("summary")).toContainText("最高点: 5点");
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  const afterRemoval=(await(await page.request.get(base+"/authoring")).json()).revision.snapshot;
  const removedCriterion=afterRemoval.domains.rubric.entries.flatMap((entry:{criteria?:{levels?:{score:number|null}[];points:number}[]})=>entry.criteria||[])[0];
  expect(removedCriterion.points).toBe(5);
  expect(Math.max(...removedCriterion.levels!.map((level:{score:number|null})=>level.score||0))).toBe(5);
  await page.reload();
  await expect(page.getByRole("region",{name:"採点基準候補",exact:true}).locator(".compact-rubric-criterion").first().locator('details[aria-label="得点段階"] summary')).toContainText("最高点: 5点");
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeDisabled();
  const rubricIssue=page.locator(".authoring-issue-cards article").filter({hasText:"得点段階"}).first();
  await expect(rubricIssue).toBeVisible();
  const navigateIssue=rubricIssue.getByRole("button",{name:/得点段階|採点基準/}).first();
  await navigateIssue.click();
  const selector=page.getByLabel("対象設問",{exact:true});
  await expect(selector).toHaveValue((await(await page.request.get(base+"/authoring")).json()).revision.snapshot.nodes[0].stable_key);
  await page.getByRole("checkbox",{name:"採点基準",exact:true}).check();
  const addHighest=page.getByRole("region",{name:"採点基準候補",exact:true}).locator(".compact-rubric-criterion").first().locator('details[aria-label="得点段階"]');
  await expect(addHighest).toHaveAttribute("open","");
  await expect(addHighest.locator("summary")).toHaveAttribute("aria-expanded","true");
  await addHighest.getByRole("button",{name:/得点段階を追加/}).click();
  dialog=page.getByRole("dialog",{name:"得点段階を追加"});
  await dialog.getByLabel("点数").fill("10");await dialog.getByLabel("条件").fill("必要事項をすべて満たしている。");
  await dialog.getByRole("button",{name:"完了",exact:true}).click();
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  const confirm=page.getByRole("button",{name:"この内容でテストを確定",exact:true});
  await expect(confirm).toBeEnabled();
  await page.getByText("得点段階と部分点の条件",{exact:true}).click();
  await expect(page.getByText("必要事項をすべて満たしている。").last()).toBeVisible();
  const saved=(await(await page.request.get(base+"/authoring")).json()).revision;
  await confirm.click();
  const confirmation=page.getByRole("dialog").getByRole("button",{name:"この内容でテストを確定",exact:true});
  const confirmResponse=page.waitForResponse(response=>response.request().method()==="POST"&&response.url().endsWith("/authoring/confirm"));
  await confirmation.click();expect((await confirmResponse).status()).toBe(200);
  const confirmed=(await(await page.request.get(base+"/authoring/confirmed")).json()).active;
  expect(confirmed.snapshot_sha256).toBe(saved.snapshot_sha256);
  await page.reload();await page.getByLabel("対象設問",{exact:true}).selectOption("all");
  await page.getByRole("button",{name:"版の履歴",exact:true}).click();
  await page.getByRole("dialog").getByRole("button",{name:/第1版 — 現在の確定版/}).click();
  const historical=page.getByRole("region",{name:"第1版の確定内容"});
  await expect(historical).toContainText("最高点 10点");
  const historicalLevel=historical.getByText("10点: 必要事項をすべて満たしている。",{exact:true});await historicalLevel.scrollIntoViewIfNeeded();await expect(historicalLevel).toBeVisible();
});
