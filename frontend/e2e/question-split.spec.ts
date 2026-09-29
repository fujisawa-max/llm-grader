import { test, expect } from "@playwright/test";
import { clearTextSourceMapping, mapCandidateToSources, suggestSubquestions } from "../lib/questionSplit";
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

test("an ambiguous candidate does not block safe candidates and remains unanchored in the parent", () => {
  const original = "導入文です。\n1. 境界を描く\n2. 領域を示す\n3. 点のクラスを答える";
  const edited = node("導入文です。\n1. 新しく書き直した内容\n2. 領域を示す\n3. 点のクラスを答える");
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.canApply).toBe(true);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["manual_required", "automatic", "automatic"]);
  expect(proposal?.children.map(child => child.included)).toEqual([false, true, true]);
  expect(proposal?.children[0].items[0]).toEqual({ type: "text", order: 0, text: "新しく書き直した内容\n" });
  expect(contentText(proposal?.placements[1]?.item)).toBe("1. 新しく書き直した内容\n");
  expect(proposal?.placements[1]?.item && "source_slice" in proposal.placements[1].item).toBe(false);
  expect(contentText(proposal?.placements[2]?.item)).toBe("2. 領域を示す\n");
  expect(proposal?.placements[2]?.item && "source_slice" in proposal.placements[2].item
    ? proposal.placements[2].item.source_slice : null).toEqual([16, 25, Array.from(original).length]);
  expect(proposal?.children[1].items[0] && "source_slice" in proposal.children[1].items[0]
    ? proposal.children[1].items[0].source_slice : null).toEqual([16, 25, Array.from(original).length]);
  expect(proposal?.notes.join(" ")).toContain("対応方法を選択してください");
});

test("ambiguous retained text keeps only verified formula provenance", () => {
  const canonicalText = "1. 元の説明 $x+1$\n2. 安全な記述";
  const currentText = "1. 書き換えた説明 $x+1$\n2. 安全な記述";
  const formula = { type: "formula_region", order: 1, region_id: "f1", page_index: 0, source_element_ids: ["formula-1"] };
  const edited = node(currentText);
  edited.ordered_content = [{ type: "text", order: 0, text: currentText, page_index: 0,
    source_element_ids: ["source-1"], merged_source_segments: [formula] }];
  edited.formula_decisions = { f1: { decision: "merged_into_text", teacher_transcription: "x+1" } };
  const canonical = { ordered_content: [{ type: "text", order: 0, text: canonicalText, page_index: 0,
    source_element_ids: ["source-1"] }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["manual_required", "automatic"]);
  const retained = proposal?.placements.find(place => place.owner === 0)?.item as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
  expect(contentText(retained)).toBe("1. 書き換えた説明 $x+1$\n");
  expect(retained).not.toHaveProperty("source_slice");
  expect(retained.merged_source_segments?.map(segment => segment.region_id)).toContain("f1");
});

test("all ambiguous candidates stay out of automatic split", () => {
  const original = "導入文です。\n1. 元の境界\n2. 元の領域";
  const edited = node("導入文です。\n1. 新しい境界\n2. 新しい領域");
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.canApply).toBe(false);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["manual_required", "manual_required"]);
  expect(proposal?.children.every(child => !child.included)).toBe(true);
  expect(proposal?.notes.join(" ")).toContain("対応情報なしで分割してください");
});

test("repeated source text is ambiguous instead of choosing an arbitrary occurrence", () => {
  const original = "1. 同じ指示\n1. 同じ指示";
  const edited = node(`${original} `);
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["manual_required", "manual_required"]);
  expect(proposal?.canApply).toBe(false);
});

test("candidate matching normalizes only whitespace while preserving canonical offsets", () => {
  const original = "1. 境界を描く\n2. 領域を示す";
  const edited = node("1.　境界を描く  \n2. 領域を示す");
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["automatic", "automatic"]);
  expect(proposal?.children[0].items[0] && "source_slice" in proposal.children[0].items[0]
    ? proposal.children[0].items[0].source_slice : null).toEqual([0, 9, Array.from(original).length]);
});

test("fragmented marker and text items are detected without changing the ordered content", () => {
  const sourceItems: ContentItem[] = [
    { type: "text", order: 0, text: "共通の導入文。", page_index: 0, source_element_ids: ["intro"] },
    { type: "text", order: 1, text: "(1)", page_index: 0, source_element_ids: ["marker-1"] },
    { type: "text", order: 2, text: "決定境界を描く。", page_index: 0, source_element_ids: ["body-1"] },
    { type: "text", order: 3, text: "（2）", page_index: 0, source_element_ids: ["marker-2"] },
    { type: "text", order: 4, text: "領域を斜線で示す。", page_index: 0, source_element_ids: ["body-2"] },
    { type: "text", order: 5, text: "問3", page_index: 0, source_element_ids: ["marker-3"] },
    { type: "text", order: 6, text: "点Aのクラスを記入する。", page_index: 0, source_element_ids: ["body-3"] },
  ];
  const edited = node("");
  edited.ordered_content = structuredClone(sourceItems);
  const before = structuredClone(edited.ordered_content);
  const proposal = suggestSubquestions(edited, { ordered_content: sourceItems });
  expect(proposal?.children.map(child => child.label)).toEqual(["(1)", "(2)", "(3)"]);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["automatic", "automatic", "automatic"]);
  expect(contentText(proposal?.parentItems[0])).toBe("共通の導入文。");
  expect(edited.ordered_content).toEqual(before);
});

test("manual mapping reuses selected canonical evidence and override leaves source slices absent", () => {
  const canonical: ContentItem[] = [
    { type: "text", order: 0, text: "導入文。", page_index: 0, source_element_ids: ["intro"] },
    { type: "text", order: 1, text: "1. 元の境界", page_index: 0, source_element_ids: ["source-1"] },
    { type: "text", order: 2, text: "2. 元の領域", page_index: 0, source_element_ids: ["source-2"] },
  ];
  const edited = node("");
  edited.ordered_content = [
    { ...canonical[0] },
    { ...canonical[1], text: "1. 書き換えた境界" },
    { ...canonical[2] },
  ];
  const proposal = suggestSubquestions(edited, { ordered_content: canonical });
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["manual_required", "automatic"]);
  const candidate = proposal!.children[0];
  const option = proposal!.sourceOptions.find(source => source.label.startsWith("source-1"))!;
  const mapped = mapCandidateToSources(candidate.items, [option.id], proposal!.sourceOptions);
  expect(mapped?.[0]).toHaveProperty("merged_source_segments", [option.evidence]);
  const unanchored = clearTextSourceMapping(candidate.items);
  expect(unanchored.every(item => !("source_slice" in item))).toBe(true);
  expect(unanchored.every(item => item.type !== "text" || !("source_element_ids" in item))).toBe(true);
});
