import type {ModelAnswerDraftEntry, RubricCandidateEdit, RubricConsolidatedGroup} from "@/lib/api/modelAnswerImports";
import {reviewCandidateId} from "@/lib/reviewCandidateId";
type RubricEdit = RubricCandidateEdit;
export function pointHint(text: string): { description: string; points: number } {
  const prefix = text.match(/^\s*(\d+(?:\.\d+)?)\s*(?:点|points?)\s*[:：-]\s*/i);
  if (prefix) return { description: text.slice(prefix[0].length).trim(), points: Number(prefix[1]) };
  const match = text.match(/[（(]\s*(\d+(?:\.\d+)?)\s*(?:点|points?)\s*[）)]\s*$|\s+(\d+(?:\.\d+)?)\s*(?:点|points?)\s*$/i);
  const points = Number(match?.[1] || match?.[2] || 0);
  return { description: match ? text.slice(0, match.index).trim() : text.trim(), points };
}

export function rubricRows(entry: ModelAnswerDraftEntry): RubricEdit[] {
  const saved = entry.rubric_edits;
  if (saved !== undefined) return saved;
  const segments = entry.semantic_classification?.segments || [];
  const segmentsById = new Map((entry.semantic_classification?.segments || []).map((segment) => [segment.id, segment]));
  const groups = entry.semantic_classification?.rubric_groups?.filter((group) => group.kind === "rubric"
    && group.segment_ids.every((id) => segmentsById.get(id)?.category === "rubric")) || [];
  if (groups.length) return rubricGroupRows(groups);
  return segments.filter((segment) => segment.category === "rubric").map((segment) => ({
    id: segment.id, source_text: segment.source_text || segment.text, segment_ids: [segment.id], ...pointHint(segment.text), grouping_confirmed: true,
    grouping_method: "legacy",
  }));
}

export function rubricGroupRows(groups:RubricConsolidatedGroup[]):RubricEdit[]{
  return groups.map((group: RubricConsolidatedGroup) => ({
    id: group.id, source_text: group.source_text, segment_ids: group.segment_ids, description: group.description, points: group.points,
    confidence: group.confidence, points_conflict: group.points_conflict, points_confirmed: false,
    grouping_confirmed: !group.needs_teacher_review,
    grouping_method: group.merge_type,
  }));
}

export function joinRubricDescriptions(items: string[]) {
  return items.reduce((result, item) => {
    if (!result) return item.trim();
    const left = result.trimEnd(); const right = item.trimStart();
    if (!left || !right) return left + right;
    if (/^[、。，．！？!?：；:;）)】』」]/.test(right) || /[（(「『【]$/.test(left)) return left + right;
    if (/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]$/u.test(left)
        && /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u.test(right)) return left + right;
    return `${left} ${right}`;
  }, "");
}

export function mergeRubricRows(entry: ModelAnswerDraftEntry, ids: string[], type: "manual_above" | "manual_multi") {
    const rows = rubricRows(entry);
    if (ids.length < 2) return null;
    const chosen = rows.filter((row) => ids.includes(row.id));
    if (chosen.length !== ids.length) return null;
    const history = [...(entry.rubric_merge_history || []), rows].slice(-50);
    const segments = entry.semantic_classification?.segments || [];
    const rank = new Map(segments.map((segment, index) => [segment.id, index]));
    const orderedIds = [...new Set(chosen.flatMap((row) => row.segment_ids || [row.id]))].sort((a, b) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0));
    const descriptions = chosen.map((row) => row.description);
    const pointValues = chosen.map((row) => row.points).filter((value) => value > 0);
    const distinctPoints = [...new Set(pointValues)];
    const merged: RubricEdit = {
      id: reviewCandidateId("merged"), segment_ids: orderedIds,
      description: joinRubricDescriptions(descriptions), source_text: joinRubricDescriptions(chosen.map((row) => row.source_text ?? row.description)),
      provenance: { ...(orderedIds.length ? {} : {source: "teacher_manual"}), merge_type: type, source_candidate_ids: chosen.map((row) => row.id), previous_operations: chosen.map((row) => row.provenance || {}), teacher_confirmed: true, timestamp: new Date().toISOString(),
        ...(chosen.every((row) => row.provenance?.split_from_candidate_id === chosen[0].provenance?.split_from_candidate_id) && chosen[0].provenance?.split_from_candidate_id
          ? { ...chosen[0].provenance, start: Math.min(...chosen.map((row) => Number(row.provenance?.start))), end: Math.max(...chosen.map((row) => Number(row.provenance?.end))) } : {}) },
      points: distinctPoints.length === 1 && pointValues.length === chosen.length ? distinctPoints[0] : 0,
      confidence: Math.min(...chosen.map((row) => row.confidence ?? 0)),
      points_conflict: chosen.some((row) => row.points_conflict) || distinctPoints.length > 1 || pointValues.length > 1,
      points_confirmed: false, grouping_confirmed: true, grouping_method: type,
    };
    const firstIndex = Math.min(...chosen.map((row) => rows.findIndex((rowItem) => rowItem.id === row.id)));
    const next = rows.filter((row) => !ids.includes(row.id));
    next.splice(firstIndex, 0, merged);
    return {rubric_edits:next,rubric_merge_history:history};
}
