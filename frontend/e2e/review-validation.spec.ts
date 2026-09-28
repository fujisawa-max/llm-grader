import { test, expect } from "@playwright/test";
import { buildQuestionPath, reviewFieldErrors, reviewFieldId, validateReviewFields } from "../lib/reviewValidation";
import type { ReviewNode } from "../types/reviews";

function node(key: string, parent: string | null, label: string, text: string): ReviewNode {
  return {
    review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
    parent_key: parent, node_type: parent ? "subquestion" : "major_question", depth: parent ? 1 : 0,
    sort_order: 0, label: { raw: label, normalized: label }, body_text: text,
    ordered_content: [{ type: "text", order: 0, text }], included: true,
    score_semantics: "unset", score_points: null, review_flags: [], formula_decisions: {},
    figure_decisions: {}, warning_states: {},
  };
}

test("question paths follow displayed parent labels at any depth", () => {
  const nodes = [node("q1", null, "問題1", "導入"), node("q1-1", "q1", "(1)", "設問"),
    node("q1-1-a", "q1-1", "(a)", "設問"), node("q2", null, "問題2", "導入")];
  expect(buildQuestionPath("q1", nodes)).toBe("問題1");
  expect(buildQuestionPath("q1-1", nodes)).toBe("問題1 > (1)");
  expect(buildQuestionPath("q1-1-a", nodes)).toBe("問題1 > (1) > (a)");
  expect(buildQuestionPath("q2", nodes)).toBe("問題2");
});

test("multiple field errors retain their question path and unique target", () => {
  const nodes = [node("q1", null, "問題1", "導入"), node("q1-2", "q1", "(2)", ""),
    node("q2", null, "問題2", "導入"), node("q2-1", "q2", "(1)", "")];
  const issues = validateReviewFields(nodes);
  const errors = reviewFieldErrors(nodes, issues);
  expect(errors.map(error => `${error.path} > ${error.fieldLabel}`)).toEqual([
    "問題1 > (2) > 問題文1", "問題2 > (1) > 問題文1",
  ]);
  expect(errors[0].message).toContain("問題文が空です");
  expect(errors[0].targetId).toBe(reviewFieldId("q1-2", "text:0"));
  expect(errors[1].targetId).not.toBe(errors[0].targetId);
});
