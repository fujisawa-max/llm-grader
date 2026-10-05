import {test, expect} from "@playwright/test";
import {questionContent, editQuestionContent} from "../lib/questionContent";
import {questionMathSource} from "../lib/questionMathSource";
import {suggestSubquestions} from "../lib/questionSplit";
import {mergeContiguousText} from "../lib/reviewTextMerge";
import type {ReviewNode, Region} from "../types/reviews";

const region: Region = {region_id:"formula", region_type:"formula", page_index:0, bbox:[40,30,90,60],
  source_element_ids:["native-math"], assigned_question_key:"q", review_flags:[], text_fragments:[{native_text:"𝑇𝑃+𝐹𝑃=24", element_id:"native-math", bbox:[40,30,90,60]}]};
function node(): ReviewNode {
  return {stable_key:"q", review_node_id:"q", source_draft_stable_key:"q", source_draft_node_id:"q",
    parent_key:null,node_type:"major_question",depth:0,sort_order:0,label:{raw:"問題1",normalized:"問題1"}, body_text:"",
    ordered_content:[{type:"text",order:0,text:"次の式を用いよ。",source_element_ids:["prose"]},
      {type:"formula_region",order:1,region_id:"formula",source_element_ids:["native-math"],page_index:0,bbox:region.bbox},
      {type:"text",order:2,text:"原文を確認する。",source_element_ids:["after"]}],
    included:true,score_points:null,score_semantics:"unset",review_flags:[],formula_decisions:{},figure_decisions:{},warning_states:{}};
}
test("one coherent editor retains internal native formula identity", () => {
  const n = node(), before = structuredClone(n);
  expect(questionContent(n, [region]).text).toBe("次の式を用いよ。\n𝑇𝑃+𝐹𝑃=24\n原文を確認する。");
  expect(n).toEqual(before);
});
test("prose edit stays local to its immutable anchor and leaves formula/figure evidence untouched", () => {
  const n = node();
  n.ordered_content.push({type:"figure_region",region_id:"figure",order:3,source_element_ids:["diagram"],bbox:[50,100,90,140],page_index:0});
  const edited = editQuestionContent(n, [region], questionContent(n, [region]).text.replace("次の式", "こちらの式"))!;
  expect(edited.ordered_content[0].source_element_ids).toEqual(["prose"]);
  expect(edited.ordered_content.slice(1)).toEqual(n.ordered_content.slice(1));
});
test("OCR apply stores Markdown math while retaining native anchor and requiring coherent review", () => {
  const n = node();
  const edited = editQuestionContent(n, [region], questionContent(n,[region]).text.replace("𝑇𝑃+𝐹𝑃=24", () => "$$\nTP+FP=24\n$$"))!;
  expect(questionContent(edited,[region]).text).toContain("$$\nTP+FP=24\n$$");
  expect(("merged_source_segments" in edited.ordered_content[1] ? edited.ordered_content[1].merged_source_segments : [])).toEqual([{...n.ordered_content[1],order:undefined}].map(({order: _,...rest}) => rest));
  expect(edited.formula_decisions.formula).toMatchObject({decision:"merged_into_text",teacher_transcription:"TP+FP=24",confirmation_status:"unreviewed"});
  const manuallyEdited = editQuestionContent(edited, [region], questionContent(edited,[region]).text.replace("TP+FP", "TP-FP"))!;
  expect(manuallyEdited.formula_decisions.formula.teacher_transcription).toBe("TP-FP=24");
  expect(n.formula_decisions).toEqual({});
});
test("structure must be saved before requesting OCR; whole owned slices become eligible after save", () => {
  const n = node(), split = {...node(), stable_key:"teacher-child",source_draft_stable_key:null,parent_key:"q"};
  split.ordered_content = [{type:"text",order:0,text:"𝑇𝑃",source_element_ids:["first","second"],source_slice:[10,12,20]}];
  expect(questionMathSource("review",1,split,n)).toBeUndefined();
  expect(questionMathSource("review",2,split,structuredClone(split))).toMatchObject({nodeKey:"teacher-child",expectedSource:{items:[expect.objectContaining({source_slice:[10,12,20]})]}});
});
test("verified full source order separates repeated mathematical Unicode/numeric occurrences", () => {
  const n = node();
  const source = "1. 𝑇𝑃=24\n24\n2. 𝑇𝑃=24\n24";
  n.ordered_content = [{type:"text",order:0,text:source,source_element_ids:["a","b","c","d"]}];
  const split = suggestSubquestions(n)!;
  expect(split.children.map(c => c.mappingStatus)).toEqual(["automatic","automatic"]);
  const allSlices = split.children.map(c => c.items.map(i => i.source_slice!));
  expect(allSlices[0][allSlices[0].length-1][1]).toBeLessThanOrEqual(allSlices[1][0][0]);
  const combined = mergeContiguousText([...split.children[0].items, ...split.children[1].items].map((item,order) => ({...item,order})),[0,1,2,3])!;
  expect(JSON.stringify(combined)).toContain("source_slice");
  expect(questionContent({...n,ordered_content:combined},[]).text).toContain("𝑇𝑃=24");
});
test("numbering edits on both sides preserve the unchanged native formula anchor", () => {
  const n = node(), text = questionContent(n,[region]).text;
  const value = text.replace("次の式", "1. 次の式").replace("原文", "2. 原文");
  const edited = editQuestionContent(n,[region],value)!;
  expect(questionContent(edited,[region]).text).toBe(value);
  expect(edited.ordered_content[1]).toEqual(n.ordered_content[1]);
  expect(edited.formula_decisions).toEqual({});
});
test("empty structural nodes can receive prose without flattening figure metadata", () => {
  const n = node();
  n.ordered_content = [{type:"figure_region",region_id:"figure",order:0,bbox:[10,10,100,100],page_index:0}];
  const edited = editQuestionContent(n,[],"図を参照する。")!;
  expect(questionContent(edited,[]).text).toBe("図を参照する。");
  expect(edited.ordered_content[1]).toEqual({...n.ordered_content[0], order:1});
});
test("temporary invalid math remains editable while source confirmation is reset", () => {
  const n = node(), initial = questionContent(n,[region]).text;
  const applied = editQuestionContent(n,[region],initial.replace("𝑇𝑃+𝐹𝑃=24", () => "$TP+FP=24$"))!;
  const changed = questionContent(applied,[region]).text.replace("$TP+FP=24$", "$$TP+FP=24$");
  const partial = editQuestionContent(applied,[region],changed)!;
  expect(questionContent(partial,[region]).text).toBe(changed);
  expect(partial.formula_decisions.formula.confirmation_status).toBe("unreviewed");
  expect(partial.ordered_content[1].source_element_ids).toBeUndefined();
  expect("merged_source_segments" in partial.ordered_content[1] && partial.ordered_content[1].merged_source_segments?.length).toBe(1);
});
test("explicit deletion excludes only that source formula and retains immutable region identity", () => {
  const n = node(), initial = questionContent(n,[region]).text;
  const applied = editQuestionContent(n,[region],initial.replace("𝑇𝑃+𝐹𝑃=24", () => "$TP+FP=24$"))!;
  const removed = editQuestionContent(applied,[region],questionContent(applied,[region]).text.replace("$TP+FP=24$", ""))!;
  expect(removed.formula_decisions.formula.decision).toBe("excluded");
  expect(removed.formula_decisions.formula.teacher_transcription).toBe("TP+FP=24");
  expect(removed.ordered_content[0]).toEqual(n.ordered_content[0]);
  expect(removed.ordered_content[2]).toEqual(n.ordered_content[2]);
  expect("merged_source_segments" in removed.ordered_content[1] && removed.ordered_content[1].merged_source_segments).toEqual([]);
  expect(region.source_element_ids).toEqual(["native-math"]);
});

test("explicit reconciliation of a deleted item separator retains both native anchors", () => {
  const n = node();
  n.ordered_content = ["2変数 x1, x2 に対して、", "x1 + x2 - 3 の値が", "0以上ならクラス1"].map((text,order) =>
    ({type:"text",text,order,source_element_ids:[`source-${order}`],page_index:0,source_slice:[0,text.length,text.length]}));
  const before = structuredClone(n);
  const value = questionContent(n,[]).text.replace("\n", "");
  const edited = editQuestionContent(n,[],value)!;
  expect(questionContent(edited,[]).text).toBe(value);
  expect(edited.ordered_content[0].source_element_ids).toEqual(["source-0"]);
  const first = edited.ordered_content[0];
  expect("merged_source_segments" in first && first.merged_source_segments).toContainEqual(expect.objectContaining({source_element_ids:["source-1"]}));
  expect(edited.ordered_content[1]).toEqual({...before.ordered_content[2],order:1});
  expect(n).toEqual(before);
});
test("native formula text edit preserves its exact raw spelling until explicit review", () => {
  const n = node();
  const value = questionContent(n,[region]).text.replace("𝑇𝑃+𝐹𝑃=24", "𝑇𝑃-𝐹𝑃=24");
  const edited = editQuestionContent(n,[region],value)!;
  expect(questionContent(edited,[region]).text).toBe(value);
  expect(edited.ordered_content).toEqual(n.ordered_content);
  expect(edited.formula_decisions.formula).toMatchObject({decision:"teacher_edit",teacher_transcription:"𝑇𝑃-𝐹𝑃=24",confirmation_status:"unreviewed"});
});
test("explicit newline insertion at a native item edge preserves every newline and source anchor", () => {
  const n = node();
  n.ordered_content = [{type:"text",order:0,text:"先頭",source_element_ids:["a"]},{type:"text",order:1,text:"次行",source_element_ids:["b"]}];
  const value = "先頭\n\n次行";
  const edited = editQuestionContent(n,[],value)!;
  expect(questionContent(edited,[]).text).toBe(value);
  expect(edited.ordered_content.flatMap(item => item.source_element_ids || [])).toEqual(["a","b"]);
});
