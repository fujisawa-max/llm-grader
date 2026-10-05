import {test, expect} from "@playwright/test";
import {bufferChanged, questionTextBuffer, reconcileQuestionText} from "../lib/questionEditing";
import type {ReviewNode} from "../types/reviews";
function node(): ReviewNode {
  return {review_node_id:"q",stable_key:"q",source_draft_stable_key:"q",source_draft_node_id:"q",parent_key:null,
    node_type:"major_question",depth:0,sort_order:0,label:{raw:"問題1",normalized:"問題1"},body_text:"",
    ordered_content:[{type:"text",order:0,text:"先頭",source_element_ids:["a"]},
      {type:"figure_region",order:1,region_id:"figure",source_element_ids:["image"]},
      {type:"text",order:2,text:"末尾",source_element_ids:["b"]}],
    included:true,score_semantics:"unset",score_points:null,review_flags:[],formula_decisions:{},figure_decisions:{},warning_states:{}};
}
test("local intermediate text remains independent of immutable evidence until explicit reconciliation", () => {
  const n = node(), before = structuredClone(n), buffer = questionTextBuffer(n,[]);
  buffer.text = "  ** $\\frac{\n入力中";
  expect(bufferChanged(buffer)).toBe(true);
  expect(n).toEqual(before);
  expect(reconcileQuestionText(n,[],buffer)).toBeNull(); // Cannot move prose across a figure.
  expect(buffer.text).toBe("  ** $\\frac{\n入力中");
  expect(n).toEqual(before);
});
test("explicit reconciliation preserves proof metadata and exact local text without mutating the buffer", () => {
  const n = node(), buffer = questionTextBuffer(n,[]);
  buffer.text = "先頭  追記\n末尾";
  buffer.ocrEdits = [{transformation:"source_math_ocr",source_sha256:"pinned"}];
  const reconciled = reconcileQuestionText(n,[],buffer)!;
  expect("text" in reconciled.ordered_content[0] && reconciled.ordered_content[0].text).toBe("先頭  追記");
  expect(reconciled.ordered_content[1]).toEqual(n.ordered_content[1]);
  expect(reconciled.math_ocr_edits).toEqual(buffer.ocrEdits);
  expect(n.math_ocr_edits).toBeUndefined();
  expect(buffer.baseline).toBe("先頭\n末尾");
});
