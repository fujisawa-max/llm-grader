import {test,expect} from "@playwright/test";
import {derivedRubricMaximum,initialRubricLevels,prepareRubricCriteria} from "../lib/rubricLevels";
import {openAuthoringEditors} from "./authoringEditMode";

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
test.skip(!process.env.RUNTIME_MANAGER_E2E,"requires isolated FastAPI/production browser harness");
test("Rubric score levels control criterion and Question totals through Save and Confirm",async({page})=>{
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button",{name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  const seed=await(await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
  const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:`Canonical Rubric levels ${Date.now()}`,total_points:10}});
  expect(created.status()).toBe(201);const exam=await created.json(),base=`/api/v1/tests/${exam.id}`;
  await page.goto(`/tests/${exam.id}/authoring`);
  await page.getByRole("button",{name:"設問を追加",exact:true}).click();
  await page.getByRole("button",{name:"設問設定の変更",exact:true}).click();
  await page.getByRole("spinbutton",{name:/^配点/}).fill("10");
  await page.getByRole("button",{name:"プレビューに戻る",exact:true}).click();
  await openAuthoringEditors(page);
  await page.getByLabel("問題文",{exact:true}).fill("x = 1");
  await page.getByLabel("模範解答本文",{exact:true}).fill("x = 1");
  await page.getByRole("button",{name:"基準を追加",exact:true}).click();
  const rubric=page.getByRole("region",{name:"採点基準候補",exact:true});
  const criterionText=rubric.getByLabel("基準1の本文",{exact:true});await criterionText.fill("x=1を正しく求める");
  const levels=rubric.getByRole("region",{name:"得点段階と部分点の条件"});
  await expect(levels).toContainText("この基準の配点: 0点");
  await expect(rubric.getByLabel("基準1の配点",{exact:true})).toHaveCount(0);
  await expect(levels.getByLabel("得点段階1の得点",{exact:true})).toHaveValue("0");
  await expect(levels.getByLabel("得点段階1の条件",{exact:true})).toHaveValue("基準を満たしていない。");
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  let saved=(await(await page.request.get(base+"/authoring")).json()).revision;
  expect(saved.snapshot.domains.rubric.entries[0].criteria[0].points).toBe(0);
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeDisabled();
  await expect(page.locator(".authoring-issue-cards")).toContainText("得点段階");
  await page.getByLabel("対象設問",{exact:true}).selectOption(saved.snapshot.nodes[0].stable_key);
  await page.getByRole("checkbox",{name:"採点基準",exact:true}).check();
  const score2=levels.getByLabel("得点段階2の得点",{exact:true}),condition2=levels.getByLabel("得点段階2の条件",{exact:true});
  await score2.fill("10");await condition2.fill("正しい値を求め、必要な説明も適切である。");
  await levels.getByRole("button",{name:"得点段階を追加",exact:true}).click();
  const score3=levels.getByLabel("得点段階3の得点",{exact:true}),condition3=levels.getByLabel("得点段階3の条件",{exact:true});
  await score3.fill("5");await condition3.fill("正しい値を求めているが、説明が不十分である。");
  await expect(levels).toContainText("この基準の配点: 10点");
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  const final=page.getByRole("button",{name:"この内容でテストを確定",exact:true});
  await expect(final).toBeEnabled();
  const summary=page.locator("details").filter({has:page.getByText("得点段階と部分点の条件",{exact:true})});
  await summary.locator("summary").click();
  await expect(summary).toContainText("最高点 10点");
  await expect(summary).toContainText("0点: 基準を満たしていない。");
  await expect(summary).toContainText("10点: 正しい値を求め、必要な説明も適切である。");
  await expect(summary).toContainText("5点: 正しい値を求めているが、説明が不十分である。");
  await page.getByLabel("対象設問",{exact:true}).selectOption(saved.snapshot.nodes[0].stable_key);
  await levels.getByRole("button",{name:"この得点段階を削除",exact:true}).nth(1).click();
  await expect(levels).toContainText("この基準の配点: 5点");
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeDisabled();
  await expect(page.locator(".authoring-issue-cards")).toContainText("得点段階の最高点合計");
  saved=(await(await page.request.get(base+"/authoring")).json()).revision;
  await page.getByLabel("対象設問",{exact:true}).selectOption(saved.snapshot.nodes[0].stable_key);
  await levels.getByRole("button",{name:"得点段階を追加",exact:true}).click();
  await levels.getByLabel("得点段階3の得点",{exact:true}).fill("10");
  await levels.getByLabel("得点段階3の条件",{exact:true}).fill("正しい値を求め、必要な説明も適切である。");
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("保存しました").last()).toBeVisible();
  await page.getByRole("button",{name:"最終確認へ",exact:true}).click();
  await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeEnabled();
  const confirmedSummary=page.locator("details").filter({has:page.getByText("得点段階と部分点の条件",{exact:true})});
  await confirmedSummary.locator("summary").click();
  await expect(confirmedSummary).toContainText("最高点 10点");
  await expect(confirmedSummary).toContainText("10点: 正しい値を求め、必要な説明も適切である。");
  saved=(await(await page.request.get(base+"/authoring")).json()).revision;
  await final.click();const confirmResponse=page.waitForResponse(response=>response.request().method()==="POST"&&response.url().endsWith("/authoring/confirm"));await page.getByRole("dialog").getByRole("button",{name:"この内容でテストを確定",exact:true}).click();expect((await confirmResponse).status()).toBe(200);
  const confirmed=(await(await page.request.get(base+"/authoring/confirmed")).json()).active;
  expect(confirmed.snapshot_sha256).toBe(saved.snapshot_sha256);
  const compiled=confirmed.snapshot.domains.grading_definition.questions[0].rubric.criteria[0];
  expect(compiled.max_score).toBe(10);expect(compiled.levels.map((level:{score:number})=>level.score)).toEqual([0,5,10]);
  await page.reload();await page.getByLabel("対象設問",{exact:true}).selectOption("all");
  await page.getByRole("button",{name:"版の履歴",exact:true}).click();
  await page.getByRole("dialog").getByRole("button",{name:/第1版 — 現在の確定版/}).click();
  const historical=page.getByRole("region",{name:"第1版の確定内容"});
  await expect(historical).toContainText("10点");
  await expect(historical).toContainText("5点");
});
