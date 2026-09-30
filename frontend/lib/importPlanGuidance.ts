import type { ReviewNode } from "@/types/reviews";

export type ScoreGuidance = {
  id: string;
  code: string;
  codes: string[];
  node: ReviewNode;
  parent: ReviewNode | null;
  children: ReviewNode[];
};

const SCORE_CODE = /^(parent_direct_score|score_conflict|score_unset|score_method_unset|sum_children_requires_children|ambiguous_score|each_child_structural_child):(.+)$/;

export function isDetailedScoreGuidanceCode(code: string): boolean {
  return SCORE_CODE.test(code);
}

/** Resolve score blockers to one hierarchy group so duplicate child conflicts read together. */
export function collectScoreGuidance(codes: string[], nodes: ReviewNode[]): ScoreGuidance[] {
  const byKey = new Map(nodes.map(node => [node.stable_key, node]));
  const groups = new Map<string, ScoreGuidance>();
  for (const code of [...new Set(codes)]) {
    const match = SCORE_CODE.exec(code);
    if (!match) continue;
    const [, reason, key] = match;
    const subject = byKey.get(key);
    if (!subject) continue;
    const parent = reason === "parent_direct_score" ||
      (reason === "score_conflict" && subject.score_semantics === "each_child")
      ? subject
      : ["score_conflict", "each_child_structural_child"].includes(reason) && subject.parent_key
        ? byKey.get(subject.parent_key) || subject : subject;
    const groupId = ["parent_direct_score", "score_conflict", "each_child_structural_child"].includes(reason)
      ? parent.stable_key : `${reason}:${key}`;
    const existing = groups.get(groupId);
    if (existing) {
      existing.codes.push(code);
      if (reason === "parent_direct_score" || reason === "score_conflict") existing.code = reason;
      continue;
    }
    groups.set(groupId, {
      id: groupId,
      code: reason,
      codes: [code],
      node: parent,
      parent: parent.parent_key ? byKey.get(parent.parent_key) || null : null,
      children: nodes.filter(node => node.included && node.parent_key === parent.stable_key)
        .sort((left, right) => left.sort_order - right.sort_order),
    });
  }
  return [...groups.values()];
}

/** Avoid repeating child score warnings that are already described in a parent blocker card. */
export function uncoveredScoreWarnings(blockers: ScoreGuidance[], warnings: ScoreGuidance[]): ScoreGuidance[] {
  const coveredNodes = new Set(blockers.flatMap(issue => [issue.node.stable_key, ...issue.children.map(child => child.stable_key)]));
  return warnings.filter(issue => issue.code !== "score_unset" || !coveredNodes.has(issue.node.stable_key));
}

export function scoreDisplay(points: number | null | undefined): string {
  return points === null || points === undefined ? "未設定" : `${points}点`;
}

export function scoreDifference(expected: number | null | undefined, actual: number): string | null {
  if (expected === null || expected === undefined || expected === actual) return null;
  const difference = Math.abs(expected - actual);
  return expected > actual ? `${difference}点不足` : `${difference}点超過`;
}
