import type {ReviewNode} from "@/types/reviews";
import {clearTextSourceMapping, type SplitProposal} from "./questionSplit";
export function applyQuestionSplit(node: ReviewNode, splitProposal: SplitProposal, newKey:()=>string) {
    const chosen = splitProposal.children.filter(child => child.included);
    const eligible = new Set(["automatic", "manual_mapped", "unmapped_override"]);
    if (!chosen.length || chosen.some(child => !eligible.has(child.mappingStatus) || !child.contentValid || !child.label.trim())) return;
    const copy = (items: ReviewNode["ordered_content"]) => items.map((item, order) => ({ ...item, order }));
    const retained = splitProposal.placements.filter(place => place.owner === null ||
      !splitProposal.children[place.owner].included).map(place => place.item);
    const assigned = (items: ReviewNode["ordered_content"], kind: "formula" | "figure") => new Set(items.flatMap(item => {
      const type = `${kind}_region`;
      if (item.type === type && "region_id" in item && typeof item.region_id === "string") return [item.region_id];
      if (item.type === "text" && Array.isArray(item.merged_source_segments)) {
        return item.merged_source_segments.filter(segment => segment.type === type).map(segment => String(segment.region_id));
      }
      return [];
    }));
    const movedFormula = new Set<string>(), movedFigure = new Set<string>();
    const children = splitProposal.children.filter(child => child.included).map((child, index): ReviewNode => {
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
    const parentHasTextMapping = parentItems.some(item => item.type === "text" && (
      Object.keys(item).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
      "source_slice" in item || Array.isArray(item.merged_source_segments) &&
      item.merged_source_segments.some(segment => segment.type !== "formula_region" &&
        Object.keys(segment).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
        segment.type !== "formula_region" && "source_slice" in segment)));
    if (!parentHasTextMapping) delete updated.source_mapping_decision;
    return {updated,children};
}
