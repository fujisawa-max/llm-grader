import { expect, test } from "@playwright/test";
import { buildReviewTargets, resolveReviewTarget } from "../lib/modelAnswerReviewTargets";
import type { ModelAnswerImportDraft } from "../lib/api/modelAnswerImports";
import { questionBreadcrumb } from "../lib/modelAnswerQuestionNavigation";

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

test("API hierarchy rank wins over interleaved source and question response order", () => {
  const draft = {
    questions: [
      { id: "q3a", parent_id: "q3", label: "問題3 > (1)", hierarchy_order: 7 },
      { id: "q2b2", parent_id: "q2b", label: "問題2 > (2) > 2.", hierarchy_order: 5 },
      { id: "q2b1", parent_id: "q2b", label: "問題2 > (2) > 1.", hierarchy_order: 4 },
      { id: "q1", parent_id: null, label: "問題1", hierarchy_order: 0 },
    ],
    entries: [
      { id: "pdf-last", question_id: "q3a" },
      { id: "pdf-first", question_id: "q1" },
      { id: "unresolved", question_id: null },
    ],
  } as ModelAnswerImportDraft;
  expect(buildReviewTargets(draft).map((target) => target.label)).toEqual([
    "問題1", "問題2 > (2) > 1.", "問題2 > (2) > 2.", "問題3 > (1)",
    "対応する設問なし (1)",
  ]);
});

test("shared breadcrumb resolves nested labels and retains server label when a structural parent is absent", () => {
  const questions = [
    { id: "q2", parent_id: null, display_label: "問題2" },
    { id: "q2b", parent_id: "q2", display_label: "(2)" },
    { id: "nested", parent_id: "q2b", display_label: "2." },
  ];
  expect(questionBreadcrumb(questions[2], questions)).toBe("問題2 > (2) > 2.");
  expect(questionBreadcrumb({ ...questions[2], label: "問題2 > (2) > 2." }, [questions[2]]))
    .toBe("問題2 > (2) > 2.");
});
