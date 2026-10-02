import { expect, test } from "@playwright/test";
import { buildReviewTargets, resolveReviewTarget } from "../lib/modelAnswerReviewTargets";
import type { ModelAnswerImportDraft } from "../lib/api/modelAnswerImports";

test("review targets keep nested breadcrumbs and place unresolved and excluded after questions", () => {
  const draft = {
    questions: [
      { id: "nested", parent_id: "sub", label: "問題2 > (2) > 2." },
      { id: "q2", parent_id: null, label: "問題2" },
      { id: "sub", parent_id: "q2", label: "問題2 > (2)" },
    ],
    entries: [
      { id: "source-1", question_id: null, disposition: "unassigned" },
      { id: "source-2", question_id: "q2", disposition: "excluded" },
    ],
  } as ModelAnswerImportDraft;
  const targets = buildReviewTargets(draft);
  expect(targets.map((target) => target.label)).toEqual([
    "問題2", "問題2 > (2)", "問題2 > (2) > 2.",
    "対応する設問なし (1)", "除外済み > 模範解答ではない文章 (1)",
  ]);
  expect(resolveReviewTarget(targets, "question:deleted")?.id).toBe("question:q2");
  expect(resolveReviewTarget(targets, "unassigned:source-1")?.entryId).toBe("source-1");
});
