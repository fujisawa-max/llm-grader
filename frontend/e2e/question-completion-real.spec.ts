import {test, expect, type Page} from "@playwright/test";
import {readFile} from "node:fs/promises";

test.skip(!process.env.QUESTION_COMPLETION_TEST_IDS, "requires disposable production-like API fixture");

async function runtimeEvidence(page: Page) {
  const manager = process.env.LLM_GRADER_RUNTIME_MANAGER_URL!;
  return Promise.all(["grader", "ocr", "math_ocr", "ornith_rubric_draft"].map(async profile => {
    const status = await (await page.request.get(`${manager}/runtimes/${profile}/status`)).json();
    const logs = await (await page.request.get(`${manager}/runtimes/${profile}/logs?tail=1000`)).json();
    return {profile, pid: status.pid, started_at: status.started_at,
      calls: logs.lines.filter((line: string) => line.includes("POST /v1/chat/completions")).length};
  }));
}

for (const savedAnswer of [false, true]) {
  test(`registered Question guidance survives reload and opens ${savedAnswer ? "saved Answer review" : "Answer upload"} without analysis`, async ({page}) => {
    const errors: string[] = [];
    let expectedFailure = false;
    page.on("pageerror", error => errors.push(error.message));
    page.on("dialog", dialog => dialog.accept());
    await page.goto("/login");
    await page.getByLabel("メールアドレス").fill(process.env.TEXT_TOOL_TEACHER_EMAIL!);
    await page.getByLabel("パスワード").fill(process.env.MODEL_ANSWER_CLASSIFICATION_PASSWORD!);
    await page.getByRole("button", {name: "ログイン"}).click();
    await expect(page).not.toHaveURL(/login/);
    // The login page's unauthenticated /auth/me probe is expected; audit the authenticated workflow.
    page.on("console", event => {
      if (event.type() === "error" && !(expectedFailure && event.text().includes("409"))) errors.push(event.text());
    });
    page.on("response", response => {
      if (response.status() >= 400 && !(expectedFailure && response.status() === 409 && response.url().endsWith("/confirm")))
        errors.push(`${response.status()} ${response.url()}`);
    });
    const testId = JSON.parse(process.env.QUESTION_COMPLETION_TEST_IDS!)[savedAnswer ? 1 : 0];
    const answerPath = `/api/v1/model-answer-import-drafts/${process.env.QUESTION_COMPLETION_DRAFT_ID}`;
    const answerBefore = savedAnswer ? await (await page.request.get(answerPath)).json() : null;
    const runtimeBefore = await runtimeEvidence(page);
    const upload = await page.request.post(`/api/v1/tests/${testId}/question-materials`, {
      headers: {"content-type": "application/pdf", "x-filename": "completion-question.pdf"},
      data: await readFile(process.env.QUESTION_CONTINUATION_PDF_PATH!)});
    expect(upload.status()).toBe(201);
    const extraction = await upload.json();
    const draft = await (await page.request.post(`/api/v1/question-imports/${extraction.id}/draft`)).json();
    const review = await (await page.request.post(`/api/v1/question-import-drafts/${draft.id}/reviews`)).json();
    const reviewUrl = `/question-import-reviews/${review.id}`;
    const formal = async () => (await page.request.get(`/api/v1/tests/${testId}/questions`)).json();
    await page.goto(reviewUrl);
    const guidance = page.getByRole("region", {name: "次に行う作業"});
    await expect(page.getByLabel("問題文", {exact: true})).toBeEditable();
    await expect(guidance).toHaveCount(0); // Unresolved formulas, saved revision only.
    expect(await formal()).toEqual([]);

    for (const node of review.snapshot.nodes) {
      await page.getByLabel("対象設問", {exact: true}).selectOption(node.stable_key);
      await page.getByRole("button", {name: "問題文を確認", exact: true}).click();
    }
    const warnings = page.getByRole("combobox", {name: /確認事項 .*の状態/});
    for (let i = 0; i < await warnings.count(); i++) await warnings.nth(i).selectOption("acknowledged");
    const saved = page.waitForResponse(response => response.url().endsWith("/revisions") && response.request().method() === "POST");
    await page.getByRole("button", {name: "変更を保存", exact: true}).click();
    expect((await saved).status()).toBe(200);
    await expect(guidance).toHaveCount(0);
    const marked = page.waitForResponse(response => response.url().endsWith("/mark-reviewed"));
    await page.getByRole("button", {name: "確認済みにする", exact: true}).click();
    expect((await marked).status()).toBe(200);
    await expect(guidance).toHaveCount(0); // Confirmed review is not formal registration.
    await page.getByRole("button", {name: "問題登録前の最終確認へ", exact: true}).click();
    const register = page.getByRole("button", {name: "確認した問題を登録", exact: true});
    await expect(register).toBeEnabled();

    if (!savedAnswer) {
      // Exercise the real server's revision-conflict failure, then retry the unchanged plan.
      expectedFailure = true;
      await page.route(`**/question-import-reviews/${review.id}/confirm`, route => route.continue({
        postData: JSON.stringify({...route.request().postDataJSON(), expected_revision: 1})}));
      const failed = page.waitForResponse(response => response.url().endsWith("/confirm"));
      await register.click();
      expect((await failed).status()).toBe(409);
      await expect(page.locator(".teacher-review p[role=alert]")).toBeVisible();
      await expect(guidance).toHaveCount(0);
      expect(await formal()).toEqual([]);
      await page.unroute(`**/question-import-reviews/${review.id}/confirm`);
      expectedFailure = false;
    }

    const registered = page.waitForResponse(response => response.url().endsWith("/confirm"));
    await register.click();
    expect((await registered).status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(`${reviewUrl}$`)); // No automatic redirect.
    await expect(guidance).toHaveClass("next-action");
    await expect(guidance.getByRole("heading", {name: "次に行う作業"})).toBeVisible();
    await expect(guidance).toContainText("問題の登録が完了しました。次は解答・採点基準を確認・登録してください。");
    await expect.poll(async () => (await formal()).length).toBe(2);
    await page.reload();
    await expect(guidance).toBeVisible();
    await expect(page.getByRole("button", {name: "新しい修正版で編集を再開"})).toBeVisible();
    await expect(page.getByRole("button", {name: "最新の内容を再読み込み"})).toBeVisible();
    await expect(page.getByRole("link", {name: "← 試験の問題画面に戻る"})).toHaveAttribute("href", `/tests/${testId}?section=questions`);
    const next = guidance.getByRole("link", {name: "解答・採点基準へ進む ›", exact: true});
    await expect(next).toHaveAttribute("href", `/tests/${testId}?section=answers`);
    // Question choices are live domain metadata: registration legitimately adds them.
    const beforeNavigation = savedAnswer ? await (await page.request.get(answerPath)).json() : null;
    if (savedAnswer) {
      expect(beforeNavigation.entries).toEqual(answerBefore.entries);
      expect(beforeNavigation.revision).toBe(answerBefore.revision);
    }
    const writes: string[] = [];
    page.on("request", request => {if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) writes.push(request.url());});
    await next.focus();
    await next.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers$`));
    const sources = page.getByRole("region", {name: "模範解答登録"});
    await expect(sources).toBeVisible();
    await expect(page.getByRole("navigation", {name: "作業の進み具合"}).locator(".workflow-step").first()).toContainText("完了");
    const testGuidance = page.getByRole("region", {name: "次に行う作業"});
    await expect(testGuidance).toHaveClass("next-action compact");
    await expect(testGuidance).toContainText("未登録または未確認の模範解答があります。");
    await expect(testGuidance.getByRole("button", {name: "模範解答を確認 ›"})).toBeVisible();
    await testGuidance.getByRole("button", {name: "模範解答を確認 ›"}).click();
    await expect(page).toHaveURL(new RegExp(`/tests/${testId}\\?section=answers$`));
    if (savedAnswer) {
      await sources.getByRole("button", {name: "saved-completion-answer.pdfの前回の解析結果を編集"}).click();
      await expect(page).toHaveURL(new RegExp(`/model-answer-import-reviews/${answerBefore.id}$`));
      await page.getByLabel("編集対象").selectOption(`unassigned:${answerBefore.entries[0].id}`);
      await expect(page.getByLabel("模範解答本文 1", {exact: true})).toHaveValue("Saved teacher answer.");
      expect(await (await page.request.get(answerPath)).json()).toEqual(beforeNavigation);
    } else {
      await expect(sources.getByText("ファイルを選択")).toBeVisible();
      await expect(sources.getByRole("button", {name: /前回の解析結果を編集/})).toHaveCount(0);
    }
    await page.goto(reviewUrl);
    await expect(guidance).toBeVisible();
    expect(writes).toEqual([]); // Navigation/resume creates no revisions, analysis, or duplicate reviews.
    expect(await runtimeEvidence(page)).toEqual(runtimeBefore);
    expect(errors).toEqual([]);
  });
}
