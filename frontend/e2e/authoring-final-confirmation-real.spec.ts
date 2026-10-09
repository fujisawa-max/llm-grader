import {test,expect,type Page} from "@playwright/test";
import {openAuthoringEditors} from "./authoringEditMode";

test.setTimeout(90000);
test.skip(!process.env.RUNTIME_MANAGER_E2E,"requires isolated FastAPI/production browser harness");
async function modelCalls(page:Page){
  return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async profile=>{
    const data=await(await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();
    return data.lines.filter((line:string)=>line.includes("POST /v1/chat/completions")).length;
  }));
}
test("final review confirms one exact saved authoring revision atomically",async({page})=>{
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(process.env.MODEL_ANSWER_CLASSIFICATION_EMAIL!);
  await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
  await page.getByRole("button",{name:"ログイン"}).click();
  await expect(page).not.toHaveURL(/login/);
  const seed=await (await page.request.get(`/api/v1/tests/${process.env.MODEL_ANSWER_CLASSIFICATION_TEST_ID}`)).json();
  const created=await page.request.post(`/api/v1/offerings/${seed.course_offering_id}/tests`,{data:{name:"Final confirmation browser",total_points:10}});
  expect(created.status()).toBe(201);const exam=await created.json();const base=`/api/v1/tests/${exam.id}`;
  await page.goto(`/tests/${exam.id}/authoring`);
  await page.getByRole("button",{name:"設問を追加",exact:true}).click();
  await page.getByRole("button",{name:"設問設定の変更",exact:true}).click();
  await page.getByRole("spinbutton",{name:/^配点/}).fill("10");
  await page.getByRole("button",{name:"プレビューに戻る",exact:true}).click();
  await openAuthoringEditors(page);
  await page.getByLabel("問題文",{exact:true}).fill("x + 1 = 2");
  await page.getByLabel("模範解答本文",{exact:true}).fill("x = 1");
  await page.getByRole("button",{name:"基準を追加"}).click();
  await page.getByLabel(/^基準\d+の本文$/).fill("x=1を示す");
  await page.getByLabel(/^基準\d+の配点$/).fill("10");
  const review=page.getByRole("button",{name:"最終確認へ"});await review.click();
  await expect(page.getByRole("button",{name:"この内容でテストを確定",exact:true})).toBeDisabled();
  await page.getByRole("button",{name:"保存",exact:true}).first().click();
  await expect(page.getByText("未保存の変更があります",{exact:true})).not.toBeVisible();
  await review.click();
  const confirmButton=page.getByRole("button",{name:"この内容でテストを確定",exact:true});
  await expect(confirmButton).toBeEnabled();
  await expect(page.getByRole("table",{name:"テスト全体の設問と採点準備"})).toContainText("準備完了");
  const saved=(await (await page.request.get(base+"/authoring")).json()).revision;
  const dialog=page.getByRole("dialog",{name:"この内容でテストを確定しますか？"});
  const callsBeforeConfirm=await modelCalls(page);
  await confirmButton.click();await dialog.getByRole("button",{name:"この内容でテストを確定",exact:true}).click();
  await expect(page.getByText(/確定済み — revision/)).toBeVisible();
  const active=(await (await page.request.get(base+"/authoring/confirmed")).json()).active;
  expect(active.snapshot_sha256).toBe(saved.snapshot_sha256);
  expect(active.snapshot).toEqual(saved.snapshot);
  const duplicate=await page.request.post(base+"/authoring/confirm",{data:{revision_id:saved.id,
    expected_edit_version:saved.edit_version,expected_snapshot_sha256:saved.snapshot_sha256}});
  expect(duplicate.status()).toBe(200);expect((await duplicate.json()).id).toBe(active.id);
  expect(await modelCalls(page)).toEqual(callsBeforeConfirm);
  expect(await (await page.request.get(base+"/questions")).json()).toHaveLength(1);
  expect(await (await page.request.get(base+"/model-answers")).json()).toHaveLength(1);
  const rubric=await page.request.get(base+"/rubrics");expect(rubric.status()).toBe(200);
  await page.reload();await page.getByLabel("対象設問",{exact:true}).selectOption("all");
  await expect(page.getByText(/確定済み — revision/)).toBeVisible();
  expect((await (await page.request.get(base+"/authoring/confirmed")).json()).active.id).toBe(active.id);
});
