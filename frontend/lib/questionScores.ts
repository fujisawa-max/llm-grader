import type { ReviewNode } from "@/types/reviews";

export type EffectiveQuestionScore = {
  points: number | null;
  knownPoints: number;
  knownCount: number;
  complete: boolean;
  missingLabels: string[];
};

/** Resolve a question's effective score without counting structural parents twice. */
export function effectiveQuestionScore(nodeKey: string, nodes: ReviewNode[], seen = new Set<string>()): EffectiveQuestionScore {
  const node = nodes.find(entry => entry.stable_key === nodeKey);
  if (!node || seen.has(nodeKey) || !node.included) {
    return { points: null, knownPoints: 0, knownCount: 0, complete: false, missingLabels: [node?.label.raw || "設問"] };
  }
  const nextSeen = new Set(seen).add(nodeKey);
  const children = nodes.filter(entry => entry.included && entry.parent_key === nodeKey)
    .sort((left, right) => left.sort_order - right.sort_order);

  if (!children.length) {
    if (node.score_semantics === "direct" && node.score_points !== null) {
      return { points: node.score_points, knownPoints: node.score_points, knownCount: 1, complete: true, missingLabels: [] };
    }
    return { points: null, knownPoints: 0, knownCount: 0, complete: false, missingLabels: [node.label.raw || "設問"] };
  }

  if (node.score_semantics === "sum_children") {
    const results = children.map(child => effectiveQuestionScore(child.stable_key, nodes, nextSeen));
    const knownPoints = results.reduce((sum, result) => sum + result.knownPoints, 0);
    const knownCount = results.reduce((sum, result) => sum + result.knownCount, 0);
    const missingLabels = results.flatMap(result => result.missingLabels);
    const complete = results.every(result => result.complete);
    return { points: complete ? knownPoints : null, knownPoints, knownCount, complete, missingLabels };
  }

  // Preserve the former equal-points-per-child behavior for already-saved reviews.
  if (node.score_semantics === "each_child" && node.score_points !== null &&
      children.every(child => !nodes.some(entry => entry.included && entry.parent_key === child.stable_key))) {
    const points = node.score_points * children.length;
    return { points, knownPoints: points, knownCount: children.length, complete: true, missingLabels: [] };
  }

  return { points: null, knownPoints: 0, knownCount: 0, complete: false, missingLabels: [node.label.raw || "設問"] };
}
