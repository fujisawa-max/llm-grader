import { test, expect } from "@playwright/test";
import { clearTextSourceMapping, mapCandidateToSources, suggestSubquestions, splitQuestionAtCaret } from "../lib/questionSplit";
import { mergeContiguousContent, mergeContiguousText } from "../lib/reviewTextMerge";
import { formulaIsConfirmed, setFormulaConfirmation } from "../lib/formulaConfirmation";
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
  const partsChars = Array.from(parts.text);
  const firstBodyStart = partsChars.indexOf("境");
  const secondBodyStart = partsChars.indexOf("領");
  expect(first && "merged_source_segments" in first ? first.merged_source_segments?.[0].source_slice : null)
    .toEqual([firstBodyStart, firstBodyStart + Array.from("境界を描く\n").length, partsChars.length]);
  expect(second && "merged_source_segments" in second ? second.merged_source_segments?.[0].source_slice : null)
    .toEqual([secondBodyStart, secondBodyStart + Array.from("領域を示す").length, partsChars.length]);
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
    ? proposal.children[1].items[0].source_slice : null).toEqual([19, 25, Array.from(original).length]);
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

test("mixed multi-merge keeps order, inline math, and every source anchor", () => {
  const items: ContentItem[] = [
    { type: "text", order: 0, text: "次の式", page_index: 0, source_element_ids: ["text-a"] },
    { type: "formula_region", order: 1, region_id: "f1", page_index: 0, source_element_ids: ["formula-a"] },
    { type: "text", order: 2, text: "について、", page_index: 0, source_element_ids: ["text-b"] },
    { type: "formula_region", order: 3, region_id: "f2", page_index: 0, source_element_ids: ["formula-b"] },
    { type: "text", order: 4, text: "を考える。", page_index: 0, source_element_ids: ["text-c"] },
  ];
  const merged = mergeContiguousContent(items, [0, 1, 2, 3, 4], { f1: "$$x^2$$", f2: "y=1" });
  expect(merged).toHaveLength(1);
  expect(contentText(merged?.[0])).toBe("次の式$x^2$について、$y=1$を考える。");
  expect((merged?.[0] as ContentItem & { merged_source_segments?: Record<string, unknown>[] }).merged_source_segments?.map(segment => segment.region_id))
    .toEqual(["f1", undefined, "f2", undefined]);
  expect(mergeContiguousContent(items, [0, 2], { f1: "x^2", f2: "y=1" })).toBeNull();
  const withFigure = [...items.slice(0, 1), { type: "figure_region", order: 1, region_id: "fig" } as ContentItem, ...items.slice(2)];
  expect(mergeContiguousContent(withFigure, [0, 1, 2], { f1: "x^2" })).toBeNull();
  expect(mergeContiguousContent(items, [1, 2], { f1: "x^2" })).toBeNull();
});

test("formula confirmation remains separate from independent or embedded state", () => {
  expect(formulaIsConfirmed({ decision: "unreviewed" })).toBe(false);
  expect(formulaIsConfirmed({ decision: "merged_into_text", teacher_transcription: "x+1", confirmation_status: "unreviewed" })).toBe(false);
  expect(formulaIsConfirmed({ decision: "merged_into_text", teacher_transcription: "x+1", confirmation_status: "confirmed" })).toBe(true);
  expect(formulaIsConfirmed({ decision: "excluded" })).toBe(true);
  const bulk = setFormulaConfirmation({ decision: "unreviewed" }, "confirmed", "bulk");
  expect(bulk).toMatchObject({ decision: "unreviewed", confirmation_status: "confirmed", confirmation_method: "bulk" });
});

test("repeated text in a verified complete source block keeps ordered occurrences", () => {
  const original = "1. 同じ指示\n1. 同じ指示";
  const edited = node(`${original} `);
  const canonical = { ordered_content: [{
    type: "text", order: 0, text: original, page_index: 0, source_element_ids: ["source-1"],
  }] };
  const proposal = suggestSubquestions(edited, canonical);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["automatic", "automatic"]);
  expect(proposal?.canApply).toBe(true);
  const slices = proposal!.children.map(child => child.items[0].source_slice!);
  expect(slices[0][1]).toBeLessThanOrEqual(slices[1][0]);
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
    ? proposal.children[0].items[0].source_slice : null).toEqual([3, 9, Array.from(original).length]);
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

test("a subquestion can be recursively split while matching the original source draft", () => {
  const canonicalText = "1. Accuracy\n2. Precision\n3. Recall";
  const canonicalItems: ContentItem[] = [{
    type: "text", order: 0, text: canonicalText, page_index: 0, source_element_ids: ["accuracy-list"],
  }];
  const nested = node(canonicalText);
  nested.stable_key = "q2.2";
  nested.review_node_id = "q2.2";
  nested.source_draft_stable_key = null;
  nested.node_type = "subquestion";
  nested.parent_key = "q2";
  nested.depth = 1;
  nested.ordered_content = structuredClone(canonicalItems);
  const proposal = suggestSubquestions(nested, { ordered_content: canonicalItems });
  expect(proposal?.children.map(child => child.label)).toEqual(["1.", "2.", "3."]);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["automatic", "automatic", "automatic"]);
  expect(proposal?.children.every(child => child.items.length === 1)).toBe(true);
  const originalChars = Array.from(canonicalText);
  const expectedSourceSlices = ["Accuracy", "Precision", "Recall"].map((value, index) => {
    const start = originalChars.join("").indexOf(value);
    return [start, start + Array.from(value).length + (index < 2 ? 1 : 0), originalChars.length];
  });
  expect(proposal?.children.map(child => child.items[0] && "source_slice" in child.items[0]
    ? child.items[0].source_slice : null)).toEqual(expectedSourceSlices);
});

test("recursive candidate detection keeps merged formula provenance with its nested subquestion", () => {
  const first = { type: "text", order: 0, text: "1. 値を求めよ: ", page_index: 0, source_element_ids: ["nested-first"] };
  const formula = { type: "formula_region", order: 1, region_id: "nested-formula", page_index: 0,
    source_element_ids: ["nested-formula-source"] };
  const second = { type: "text", order: 2, text: "\n2. 結果を説明せよ", page_index: 0,
    source_element_ids: ["nested-second"] };
  const merged = node("1. 値を求めよ: $x+1$\n2. 結果を説明せよ");
  merged.node_type = "subquestion";
  merged.depth = 1;
  merged.parent_key = "q2";
  merged.ordered_content = [{ ...first, text: "1. 値を求めよ: $x+1$\n2. 結果を説明せよ",
    merged_source_segments: [formula, second] }];
  merged.formula_decisions = { "nested-formula": {
    decision: "merged_into_text", teacher_transcription: "x+1",
  } };
  const proposal = suggestSubquestions(merged, { ordered_content: [first, formula, second] });
  expect(proposal?.children.map(child => child.label)).toEqual(["1.", "2."]);
  expect(proposal?.children.map(child => child.mappingStatus)).toEqual(["automatic", "automatic"]);
  expect(proposal?.children[0].items[0] && "merged_source_segments" in proposal.children[0].items[0]
    ? proposal.children[0].items[0].merged_source_segments?.map(segment => segment.type) : [])
    .toContain("formula_region");
  const secondCandidateItem = proposal?.children[1].items[0];
  const secondCandidateSegments = secondCandidateItem && "merged_source_segments" in secondCandidateItem
    ? secondCandidateItem.merged_source_segments || [] : [];
  expect(secondCandidateSegments.some(segment => Array.isArray(segment.source_element_ids) &&
    segment.source_element_ids[0] === "nested-second")).toBe(true);
});

test("multi-text merge keeps every source anchor and rejects gaps or non-text items", () => {
  const items: ContentItem[] = [
    { type: "text", order: 0, text: "前半", page_index: 0, source_element_ids: ["a"] },
    { type: "text", order: 1, text: "$x+1$", page_index: 0, source_element_ids: ["b"],
      merged_source_segments: [{ page_index: 0, source_element_ids: ["c"] }] },
    { type: "text", order: 2, text: "後半", page_index: 0, source_element_ids: ["c"] },
    { type: "formula_region", order: 3, region_id: "f1" },
    { type: "text", order: 4, text: "別の段落" },
  ];
  const merged = mergeContiguousText(items, [0, 1, 2]);
  expect(merged?.map(item => item.type)).toEqual(["text", "formula_region", "text"]);
  expect(merged?.[0]).toMatchObject({
    text: "前半$x+1$後半", source_element_ids: ["a"],
    merged_source_segments: [
      { page_index: 0, source_element_ids: ["b"] },
      { page_index: 0, source_element_ids: ["c"] },
    ],
  });
  expect(mergeContiguousText(items, [1, 4])).toBeNull();
  expect(mergeContiguousText(items, [2, 3])).toBeNull();
});


test("manual caret split keeps ordered repeated-token native ranges",()=>{
  const original=node("24\n24\n𝑇𝑃");
  const proposal=splitQuestionAtCaret(original,3,[{index:0,start:0,end:original.body_text.length,text:original.body_text}]);
  expect(proposal?.children).toHaveLength(2);
  expect(proposal?.children[0].items[0].source_slice).toEqual([0,3,8]);
  expect(proposal?.children[1].items[0].source_slice).toEqual([3,8,8]);
});

test("numbered split keeps a multi-line OCR formula block and its native anchor intact", () => {
  const value=node("1. 第一小問");
  const formula:ContentItem={type:"text",order:1,text:"$$\n\\frac{TP}{TP+FP}\n$$",
    merged_source_segments:[{type:"formula_region",region_id:"formula-1",page_index:0,source_element_ids:["formula-source"]}]};
  value.ordered_content.push(formula,{type:"text",order:2,text:"2. 第二小問"});
  const proposal=suggestSubquestions(value);
  expect(proposal?.children[0].items).toContainEqual(formula);
  expect(proposal?.placements.filter(p=>p.item===formula)).toHaveLength(1);
  expect(proposal?.children.flatMap(c=>c.items).filter(i=>"merged_source_segments" in i)).toHaveLength(1);
});
