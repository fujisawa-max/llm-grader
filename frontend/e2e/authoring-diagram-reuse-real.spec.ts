import {test,expect,type Page} from "@playwright/test";
test.setTimeout(90000);
test.skip(!process.env.DIAGRAM_AUTHORING_DRAFT_ID||process.env.LLM_GRADER_STUB_DIAGRAM_RESPONSE_MODE!=="truncated","managed truncated-Ricoh authoring fixture required");
async function calls(page:Page){return Promise.all(["ocr","math_ocr","ornith_rubric_draft","grader"].map(async profile=>{
  const data=await (await page.request.get(`${process.env.LLM_GRADER_RUNTIME_MANAGER_URL}/runtimes/${profile}/logs?tail=1000`)).json();return data.lines.filter((s:string)=>s.includes("POST /v1/chat/completions")).length;
}));}
test("unified authoring accepts corrected unresolved diagrams and reuses them without publishing or inference",async({page})=>{
  await page.setViewportSize({width:1920,height:1080});await page.goto("/login");await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);await page.getByRole("button",{name:"ログイン"}).click();await expect(page).not.toHaveURL(/login/);
  const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",e=>{if(e.type()==="error")errors.push(e.text());});
  const draft=await (await page.request.get(`/api/v1/model-answer-import-drafts/${process.env.DIAGRAM_AUTHORING_DRAFT_ID}`)).json(),tid=draft.test_id,base=`/api/v1/tests/${tid}/authoring`,children=JSON.parse(process.env.DIAGRAM_AUTHORING_CHILD_IDS!) as string[];
  await page.goto(`/tests/${tid}/authoring`);await page.getByRole("button",{name:"編集用の下書きを作成"}).click();const selector=page.getByLabel("対象設問",{exact:true});await selector.selectOption(children[0]);await page.getByRole("button",{name:"模範解答を追加",exact:true}).click();
  const candidate=page.locator('[id^="authoring-candidate-teacher-entry-"]'),section=candidate.getByRole("region",{name:"模範解答の図",exact:true});
  await section.getByRole("button",{name:"図候補を確認",exact:true}).click();await section.getByRole("button",{name:"このPDFのすべての図候補を表示",exact:true}).click();await expect(section.getByAltText("図1の切り出し範囲")).toBeVisible();
  await expect(section.getByText("図の出典範囲を自動では確認できませんでした。PDFと図の範囲を確認してください。教師が確認した図は使用できます。",{exact:true})).toBeVisible();
  const detected=await calls(page);await section.getByRole("button",{name:"範囲を修正",exact:true}).click();for(const [label,value]of[["左","68"],["上","138"],["右","232"],["下","302"]])await section.getByLabel(`図の範囲 ${label}`).fill(value);
  await section.getByRole("button",{name:"プレビューを更新",exact:true}).click();await expect(section.getByAltText("修正後の図の範囲")).toBeVisible();await section.getByRole("button",{name:"範囲を適用",exact:true}).click();await section.getByRole("button",{name:"この図を確認して使用",exact:true}).click();
  await expect(section.getByText(/使用中 · 教師が範囲を修正/)).toBeVisible();await expect(page.getByText("未保存の変更があります",{exact:true})).toBeVisible();await page.getByRole("button",{name:"保存",exact:true}).click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();
  const first=(await (await page.request.get(base)).json()).revision.snapshot.domains.answer.entries[0].diagram_records[0];expect(first.teacher_confirmed).toBe(true);
  await selector.selectOption(children[1]);await page.getByRole("button",{name:"模範解答を追加",exact:true}).click();await expect(section.getByText("この大問ですでに使用している図",{exact:true})).toBeVisible();await section.getByRole("button",{name:"この図を再利用",exact:true}).click();await expect(section.getByRole("button",{name:"使用中",exact:true})).toBeDisabled();
  await page.getByRole("button",{name:"保存",exact:true}).click();await expect(page.getByText("下書きを保存しました。",{exact:true})).toBeVisible();await page.reload();await selector.selectOption(children[1]);await expect(section.getByRole("button",{name:"使用中",exact:true})).toBeDisabled();
  const saved=(await (await page.request.get(base)).json()).revision.snapshot.domains.answer.entries;expect(saved).toHaveLength(2);expect(saved[1].diagram_records[0].crop_sha256).toBe(first.crop_sha256);expect(saved[1].diagram_records[0].acceptance_method).toBe("reused_confirmed_diagram");expect(await calls(page)).toEqual(detected);
  expect((await (await page.request.get(`/api/v1/tests/${tid}/model-answers`)).json())).toEqual([]);expect((await (await page.request.get(`/api/v1/model-answer-import-drafts/${draft.id}`)).json()).entries).toEqual([]);expect(errors).toEqual([]);
});
