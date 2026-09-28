import { test, expect } from "@playwright/test";
import { suggestSubquestions } from "../lib/questionSplit";
import type { ContentItem, ReviewNode } from "../types/reviews";

const contentText = (item: ContentItem | undefined) => item && "text" in item ? item.text : "";

function node(text: string): ReviewNode {
  return {
    review_node_id: "q1", stable_key: "q1", source_draft_stable_key: "q1", source_draft_node_id: null,
    parent_key: null, node_type: "major_question", depth: 0, sort_order: 0,
    label: { raw: "問題1", normalized: "問題1" }, body_text: text,
    ordered_content: [{ type: "text", order: 0, text, page_index: 0, source_element_ids: ["source-1"] }],
    included: true, score_semantics: "direct", score_points: 30, review_flags: [],
    formula_decisions: {}, figure_decisions: {}, warning_states: {},
  };
}

test("split candidates use paragraph markers and retain parent introduction", () => {
  const proposal = suggestSubquestions(node("導入文\n1. 境界\n\n(2) 領域\n（3） 点"));
  expect(proposal?.children.map(child => child.label)).toEqual(["(1)", "(2)", "(3)"]);
  expect(contentText(proposal?.parentItems[0])).toContain("導入文");
  expect(contentText(proposal?.children[0].items[0])).toContain("境界");
  expect(proposal?.children[1].items[0] && "source_element_ids" in proposal.children[1].items[0] &&
    proposal.children[1].items[0].source_element_ids).toEqual(["source-1"]);
  expect(proposal?.placements.map(place => place.owner)).toEqual([null, 0, 1, 2]);
});

test("ordinary decimal numbers do not form subquestions", () => {
  expect(suggestSubquestions(node("精度は0.95です。\n続きは1.25倍です。"))).toBeNull();
});
