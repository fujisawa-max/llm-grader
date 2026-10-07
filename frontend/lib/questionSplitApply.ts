import type {ReviewNode} from "@/types/reviews";
import {clearTextSourceMapping, type SplitProposal} from "./questionSplit";
export function applyQuestionSplit(node: ReviewNode, splitProposal: SplitProposal, newKey:()=>string, nodes:ReviewNode[] = []) {
    if(splitDuplicate(node,splitProposal,nodes))return;
    const chosen = splitProposal.children.filter(child => child.included && (child.role||"child")==="child");
    const eligible = new Set(["automatic", "manual_mapped", "unmapped_override"]);
    if (!chosen.length || chosen.some(child => !eligible.has(child.mappingStatus) || !child.contentValid || !child.label.trim())) return;
    const copy = (items: ReviewNode["ordered_content"]) => items.map((item, order) => ({ ...item, order }));
    const retained = splitProposal.placements.filter(place => place.owner === null ||
      (!splitProposal.children[place.owner].included || splitProposal.children[place.owner].role==="parent")).filter(place=>place.owner===null||splitProposal.children[place.owner].role!=="exclude").map(place => place.item);
    const assigned = (items: ReviewNode["ordered_content"], kind: "formula" | "figure") => new Set(items.flatMap(item => {
      const type = `${kind}_region`;
      if (item.type === type && "region_id" in item && typeof item.region_id === "string") return [item.region_id];
      if (item.type === "text" && Array.isArray(item.merged_source_segments)) {
        return item.merged_source_segments.filter(segment => segment.type === type).map(segment => String(segment.region_id));
      }
      return [];
    }));
    const excludedItems=splitProposal.children.filter(c=>c.role==="exclude").flatMap(c=>c.items);
    const excludedFormula=assigned(excludedItems,"formula"),excludedFigure=assigned(excludedItems,"figure");
    const movedFormula = new Set<string>(), movedFigure = new Set<string>();
    const children = splitProposal.children.filter(child => child.included && (child.role||"child")==="child").map((child, index): ReviewNode => {
      const key = newKey();
      const childItems = child.mappingStatus === "unmapped_override" ? clearTextSourceMapping(child.items) : child.items;
      const formulas = assigned(childItems, "formula"), figures = assigned(childItems, "figure");
      formulas.forEach(value => movedFormula.add(value)); figures.forEach(value => movedFigure.add(value));
      return { review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
        parent_key: node.stable_key, node_type: "subquestion", depth: node.depth + 1, sort_order: index,
        label: { raw: child.label, normalized: child.label }, body_text: childItems.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
        ordered_content: copy(childItems), included: true, score_semantics: "unset", score_points: null,
        review_flags: [], formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => formulas.has(key))),
        figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => figures.has(key))),
        source_mapping_decision: child.mappingStatus === "automatic" ? "automatic"
          : child.mappingStatus === "manual_mapped" ? "teacher_manual_mapping" : "teacher_unmapped_override",
        warning_states: {} };
    });
    const parentItems = copy(retained);
    const updated: ReviewNode = { ...node, ordered_content: parentItems,
      body_text: parentItems.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
      score_semantics: node.score_semantics === "each_child" ? "each_child" : "sum_children",
      score_points: node.score_semantics === "each_child" ? node.score_points : null,
      formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => !movedFormula.has(key))),
      figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => !movedFigure.has(key))) };
    for(const key of excludedFormula)updated.formula_decisions[key]={decision:"excluded"};
    for(const key of excludedFigure)updated.figure_decisions[key]={decision:"excluded"};
    const parentHasTextMapping = parentItems.some(item => item.type === "text" && (
      Object.keys(item).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
      "source_slice" in item || Array.isArray(item.merged_source_segments) &&
      item.merged_source_segments.some(segment => segment.type !== "formula_region" &&
        Object.keys(segment).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
        segment.type !== "formula_region" && "source_slice" in segment)));
    if (!parentHasTextMapping) delete updated.source_mapping_decision;
    return {updated,children};
}

/** Presentation decisions reference existing source placements; never reconstruct text. */
export function reviewQuestionSplit(proposal:SplitProposal,node:ReviewNode, firstContext=false) : SplitProposal {
  const hasParent=proposal.placements.some(p=>p.owner===null);
  const offset=hasParent?1:0;
  const children=proposal.children.map(child=>({...child,role:("child" as "parent"|"child"|"exclude")}));
  if(firstContext&&!hasParent&&children.length)children[0].role="parent";
  if(hasParent)children.unshift({label:"共通本文",items:proposal.parentItems,included:true,mappingStatus:"automatic",contentValid:true,selectedSourceIds:[],role:"parent"} as typeof children[number]);
  // A repeated wrapper ordinal is context, not another copy of the selected child.
  for(const child of children)if(repeatsWrapper(node,child))child.role="parent";
  return {...proposal,targetKey:node.stable_key,children,placements:proposal.placements.map(p=>({...p,owner:p.owner===null?(hasParent?0:null):p.owner+offset}))};
}
function ordinal(text:string){return text.trim().match(/^(?:[（(](\d+)[）)]|(\d+)[.)]|(\d+)\.)/)?.slice(1).find(Boolean)||null;}
function repeatsWrapper(node:ReviewNode,child:SplitProposal["children"][number]){
  const selected=node.body_text.trim(),number=ordinal(node.label.raw);
  const text=child.items.filter(i=>i.type==="text").map(i=>String("text" in i?i.text:"")).join("\n").trim();
  const strip=(value:string)=>value.replace(/^(?:[（(]\d+[）)]|\d+[.)])\s*/, "");
  return !!node.parent_key&&!!number&&ordinal(child.label)===number&&ordinal(selected)===number&&
    !!text&&(selected.startsWith(text)||strip(selected).startsWith(strip(text)));
}
function sourceSignature(items:ReviewNode["ordered_content"]){
  return JSON.stringify(items.map(item=>({type:item.type,...Object.fromEntries(Object.entries(item).filter(([key])=>["source_slice","source_element_ids","merged_source_segments","region_id"].includes(key)))})));
}
export function splitDuplicate(node:ReviewNode,proposal:SplitProposal,nodes:ReviewNode[]):boolean {
  return proposal.children.filter(c=>c.included&&(c.role||"child")==="child").some(c=>{
    const text=c.items.map(i=>i.type==="text"?String(i.text||""):"").join("\n").trim();
    const selectedText=node.ordered_content.map(i=>i.type==="text"?String(i.text||""):"").join("\n").trim();
    if(repeatsWrapper(node,c)||node.parent_key&&ordinal(node.label.raw)&&ordinal(c.label)===ordinal(node.label.raw)&&text===selectedText)return true;
    return nodes.filter(n=>n.parent_key===node.stable_key).some(n=>
      text&&text===n.body_text.trim()||sourceSignature(c.items)===sourceSignature(n.ordered_content)&&
      c.items.some(i=>"source_slice" in i||"source_element_ids" in i||"region_id" in i));
  });
}
