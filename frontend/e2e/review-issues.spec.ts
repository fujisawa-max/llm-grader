import {test, expect} from "@playwright/test";
import {canonicalQuestionPath} from "../lib/canonicalQuestionPath";
import {questionBreadcrumb} from "../lib/modelAnswerQuestionNavigation";
import {buildQuestionPath} from "../lib/reviewValidation";
import {questionReviewIssues} from "../lib/questionReviewIssues";
import type {ReviewDocument,ReviewNode} from "../types/reviews";
const node=(key:string,parent:string|null,label:string):ReviewNode=>({stable_key:key,review_node_id:key,
  parent_key:parent,source_draft_stable_key:"automatic",source_draft_node_id:"native",source_review_owner:"automatic",
  node_type:parent?"subquestion":"major_question",depth:0,sort_order:0,label:{raw:label,normalized:label},
  body_text:"source",ordered_content:[],included:true,score_semantics:"direct",score_points:10,
  formula_decisions:{},figure_decisions:{},warning_states:{},review_flags:[]});
function fixture(){
  const nodes=[node("major",null,"問題2"),node("sub","major","(2)"),node("formula-child","sub","2.")];
  const snapshot={nodes,warning_states:{},state:"editing"};
  const region={region_id:"formula-a",region_type:"formula",assigned_question_key:"automatic"};
  nodes[2].ordered_content=[{type:"formula_region",region_id:region.region_id,order:0}];
  return {nodes,document:{regions:[region],warnings:[],snapshot} as unknown as ReviewDocument};
}
test("review and formal selectors share the exact canonical hierarchy",()=>{
  const {nodes}=fixture();
  const formal=nodes.map(n=>({id:n.stable_key,parent_id:n.parent_key,display_label:n.label.raw}));
  expect(buildQuestionPath("formula-child",nodes)).toBe("問題2 > (2) > 2.");
  expect(questionBreadcrumb(formal[2],formal)).toBe(buildQuestionPath("formula-child",nodes));
});
test("canonical paths terminate cycles and retain server path when ancestors are absent",()=>{
  expect(questionBreadcrumb({id:"leaf",parent_id:"missing",label:"問題2 > (2) > 2."},[
    {id:"leaf",parent_id:"missing",label:"問題2 > (2) > 2."}])).toBe("問題2 > (2) > 2.");
  expect(canonicalQuestionPath("a",[{key:"a",parentKey:"b",label:"A"},{key:"b",parentKey:"a",label:"B"}])).toBe("B > A");
});
test("formula issue resolves to its reviewed split child and disappears after confirmation",()=>{
  const {nodes,document}=fixture();
  const make=()=>questionReviewIssues(document,document.snapshot,n=>n.source_review_owner,()=>nodes[2]);
  const issues=make();
  expect(issues).toHaveLength(1);expect(issues[0].questionKey).toBe("formula-child");
  expect(issues[0].path).toBe("問題2 > (2) > 2.");
  expect(issues[0].controlSelector).toBe("[data-review-confirm-content]");
  nodes[2].formula_decisions["formula-a"]={decision:"use_native",confirmation_status:"confirmed"};
  expect(make()).toEqual([]);
});
test("excluded formula owner is not borrowed by its sibling",()=>{
  const {nodes,document}=fixture();nodes[2].included=false;
  expect(questionReviewIssues(document,document.snapshot,n=>n.source_review_owner,()=>nodes[2])).toEqual([]);
});
test("warning resolution and score edits clear current issue lists without reload",()=>{
  const {nodes,document}=fixture();document.regions=[];
  document.warnings=[{id:"w",scope:"node",source_id:"automatic",owner:"automatic",code:"score_unset",blocking:true}];
  nodes[2].score_points=null;
  const make=()=>questionReviewIssues(document,document.snapshot,n=>n.source_review_owner,()=>nodes[2]);
  expect(make().map(i=>i.issueType)).toEqual(["warning","score"]);
  document.snapshot.warning_states={w:{state:"acknowledged"}};nodes[2].score_points=10;
  expect(make()).toEqual([]);
});
