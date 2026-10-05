import type { ReviewDocument, ReviewNode, ReviewSnapshot } from "@/types/reviews";
import { formulaIsConfirmed } from "./formulaConfirmation";
import { buildQuestionPath, reviewFieldId } from "./reviewValidation";
import { reviewIssueLabel } from "./reviewLabels";
import { reviewWarningId, type ReviewIssueTarget } from "./reviewIssues";

export function questionReviewIssues(document: ReviewDocument, snapshot: ReviewSnapshot,
  sourceKey: (node: ReviewNode) => string | null | undefined,
  regionOwner: (id: string) => ReviewNode | undefined): ReviewIssueTarget[] {
  const nodes = snapshot.nodes.filter(node => node.included);
  const activeOwners = new Set(nodes.map(sourceKey).filter(Boolean));
  const issues: ReviewIssueTarget[] = [];
  for (const region of document.regions) {
    if (!region.assigned_question_key || !activeOwners.has(region.assigned_question_key)) continue;
    const owner = regionOwner(region.region_id);
    if (!owner?.included) continue;
    const formula = region.region_type === "formula";
    const decisions = nodes.filter(node => sourceKey(node) === region.assigned_question_key)
      .map(node => (formula ? node.formula_decisions : node.figure_decisions)[region.region_id]);
    if (formula ? decisions.some(formulaIsConfirmed) : decisions.some(value => value && value.decision !== "unreviewed")) continue;
    issues.push({id: region.region_id, domain: "question", questionKey: owner.stable_key,
      path: buildQuestionPath(owner.stable_key, snapshot.nodes), issueType: formula ? "formula" : "figure",
      message: formula ? "数式未確認" : "図未確認", itemId: region.region_id,
      targetId: formula ? reviewFieldId(owner.stable_key, "content") : reviewFieldId(owner.stable_key, `figure:${region.region_id}`),
      controlSelector: formula ? '[data-review-confirm-content]' : undefined});
  }
  for (const warning of document.warnings) {
    if ((snapshot.warning_states?.[warning.id]?.state || "unreviewed") !== "unreviewed") continue;
    const region = document.regions.find(item => item.region_id === warning.source_id);
    const owner = region && regionOwner(region.region_id) || snapshot.nodes.find(node =>
      node.stable_key === warning.owner || sourceKey(node) === (region?.assigned_question_key || warning.owner || warning.source_id));
    if (owner && !owner.included) continue;
    issues.push({id: warning.id, domain: "question", questionKey: owner?.stable_key,
      path: owner ? buildQuestionPath(owner.stable_key, snapshot.nodes) : warning.scope === "draft" ? "試験全体" : "設問未割当", issueType: "warning",
      message: reviewIssueLabel(warning.code), targetId: reviewWarningId(warning.id), controlSelector: "select"});
  }
  for (const node of nodes) {
    if (node.score_semantics !== "ambiguous" && node.score_semantics !== "unset" &&
      !(["direct", "each_child"].includes(node.score_semantics) && node.score_points === null)) continue;
    issues.push({id: `score:${node.stable_key}`, domain: "question", questionKey: node.stable_key,
      path: buildQuestionPath(node.stable_key, snapshot.nodes), issueType: "score", message: "配点を確認",
      targetId: reviewFieldId(node.stable_key, ["unset", "ambiguous", "each_child"].includes(node.score_semantics) ? "score_method" : "score")});
  }
  return issues;
}
