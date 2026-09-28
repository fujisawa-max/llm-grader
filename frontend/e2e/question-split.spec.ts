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

test("split partitions a merged text item across its original source anchors", () => {
  const intro = { type: "text", order: 0, text: "導入文です。\n", page_index: 0, source_element_ids: ["intro"] };
  const parts = { type: "text", order: 1, text: "1. 境界を描く\n2. 領域を示す", page_index: 0, source_element_ids: ["parts"] };
  const merged = node("導入文です。\n1. 境界を描く\n2. 領域を示す");
  merged.ordered_content = [{
    ...intro, text: `${intro.text}${parts.text}`,
    merged_source_segments: [{
      page_index: parts.page_index, source_element_ids: parts.source_element_ids,
    }],
  }];
  const proposal = suggestSubquestions(merged, { ordered_content: [intro, parts] });
  expect(proposal?.canApply).toBe(true);
  expect(contentText(proposal?.parentItems[0])).toBe("導入文です。\n");
  const first = proposal?.children[0].items[0];
  const second = proposal?.children[1].items[0];
  expect(first && "merged_source_segments" in first ? first.merged_source_segments?.[0].source_slice : null)
    .toEqual([0, Array.from("1. 境界を描く\n").length, Array.from(parts.text).length]);
  expect(second && "merged_source_segments" in second ? second.merged_source_segments?.[0].source_slice : null)
    .toEqual([Array.from("1. 境界を描く\n").length, Array.from(parts.text).length, Array.from(parts.text).length]);
});

test("formula merged between text sources stays with its source line after splitting", () => {
  const first = { type: "text", order: 0, text: "1. 式の値を求める: ", page_index: 0, source_element_ids: ["first"] };
  const second = { type: "text", order: 2, text: "\n2. 領域を示す", page_index: 0, source_element_ids: ["second"] };
  const formula = { type: "formula_region", order: 1, region_id: "f1", page_index: 0, source_element_ids: ["formula"] };
  const merged = node("1. 式の値を求める: $x+1$\n2. 領域を示す");
  merged.ordered_content = [{ ...first, text: "1. 式の値を求める: $x+1$\n2. 領域を示す", merged_source_segments: [formula, second] }];
  merged.formula_decisions = { f1: { decision: "merged_into_text", teacher_transcription: "x+1" } };
  const proposal = suggestSubquestions(merged, { ordered_content: [first, formula, second] });
  expect(proposal?.canApply).toBe(true);
  const firstChild = proposal?.children[0].items[0];
  const secondChild = proposal?.children[1].items[0];
  expect(firstChild && "merged_source_segments" in firstChild ? firstChild.merged_source_segments?.map(segment => segment.type) : [])
    .toContain("formula_region");
  expect(secondChild && "merged_source_segments" in secondChild ? secondChild.merged_source_segments?.map(segment => (segment.source_element_ids as string[] | undefined)?.[0]) : [])
    .toContain("second");
});

test("split refuses to invent source ranges after the source text was rewritten", () => {
  const original = "導入文です。\n1. 境界を描く\n2. 領域を示す";
  const edited = node("導入文です。\n1. 新しく書き直した内容\n2. 領域を示す");
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.canApply).toBe(false);
  expect(proposal?.notes.join(" ")).toContain("一意に照合できません");
});
