import { test, expect } from "@playwright/test";
import type { ReviewNode } from "../types/reviews";
import { buildQuestionPath } from "../lib/reviewValidation";
import { collectScoreGuidance, scoreDifference, scoreDisplay, uncoveredScoreWarnings } from "../lib/importPlanGuidance";

function question(key: string, label: string, parent: string | null, points: number | null,
  semantics: ReviewNode["score_semantics"], order: number): ReviewNode {
  return {
    review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
    parent_key: parent, node_type: parent ? "subquestion" : "major_question", depth: parent ? 1 : 0,
    sort_order: order, label: { raw: label, normalized: label }, body_text: "内容",
    ordered_content: [{ type: "text", order: 0, text: "内容" }], included: true,
    score_semantics: semantics, score_points: points, review_flags: [], formula_decisions: {},
    figure_decisions: {}, warning_states: {},
  };
}

test("parent score blocker groups recursive child details and distinguishes unset from zero", () => {
  const nodes = [
    question("q2", "問題2", null, 40, "direct", 0),
    question("q2.1", "(1)", "q2", 30, "direct", 0),
    question("q2.2", "(2)", "q2", null, "unset", 1),
    question("q2.2.1", "1.", "q2.2", 0, "direct", 0),
  ];
  const guidance = collectScoreGuidance(["parent_direct_score:q2"], nodes);
  expect(guidance).toHaveLength(1);
  expect(guidance[0]).toMatchObject({ code: "parent_direct_score", node: nodes[0], children: nodes.slice(1, 3) });
  expect(buildQuestionPath("q2.2.1", nodes)).toBe("問題2 > (2) > 1.");
  expect(scoreDisplay(null)).toBe("未設定");
  expect(scoreDisplay(0)).toBe("0点");
  expect(scoreDifference(40, 30)).toBe("10点不足");
  expect(scoreDifference(40, 50)).toBe("10点超過");
  expect(scoreDifference(40, 40)).toBeNull();
});

test("each-child score conflicts group under the full parent path", () => {
  const nodes = [
    question("q3", "問題3", null, 20, "each_child", 0),
    question("q3.1", "(1)", "q3", 10, "direct", 0),
    question("q3.2", "(2)", "q3", null, "unset", 1),
  ];
  const guidance = collectScoreGuidance(["score_conflict:q3.1"], nodes);
  expect(guidance).toHaveLength(1);
  expect(guidance[0].node.stable_key).toBe("q3");
  expect(guidance[0].children).toEqual(nodes.slice(1));
  expect(guidance[0].codes).toEqual(["score_conflict:q3.1"]);
});

test("child unset warnings are not repeated when a parent blocker already lists them", () => {
  const nodes = [
    question("q2", "問題2", null, 40, "direct", 0),
    question("q2.1", "(1)", "q2", 30, "direct", 0),
    question("q2.2", "(2)", "q2", null, "unset", 1),
    question("q3", "問題3", null, 20, "direct", 1),
    question("q3.1", "(1)", "q3", null, "unset", 0),
  ];
  const blockers = collectScoreGuidance(["parent_direct_score:q2"], nodes);
  const warnings = collectScoreGuidance(["score_unset:q2.2", "score_unset:q3.1"], nodes);
  expect(uncoveredScoreWarnings(blockers, warnings).map(issue => issue.node.stable_key)).toEqual(["q3.1"]);
});
