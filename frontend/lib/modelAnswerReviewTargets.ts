import type { ModelAnswerDraftEntry, ModelAnswerImportDraft, ModelAnswerQuestionChoice } from "@/lib/api/modelAnswerImports";

export interface ReviewTarget { id: string; label: string; kind: "question" | "unassigned" | "excluded"; questionId?: string; entryId?: string }

function effectivelyBlank(value: string | null | undefined): boolean {
  return ![...(value || "")].some((char) => !/[\s\u00a0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u2060\u3000\ufeff\u0000-\u001f\u007f-\u009f]/u.test(char));
}

function orderedQuestions(questions: ModelAnswerQuestionChoice[]): ModelAnswerQuestionChoice[] {
  if (questions.every((question) => Number.isInteger(question.hierarchy_order))) {
    return [...questions].sort((left, right) => left.hierarchy_order! - right.hierarchy_order!);
  }
  const byId = new Map(questions.map((question) => [question.id, question]));
  const order = new Map(questions.map((question, index) => [question.id, index]));
  const children = new Map<string | null, ModelAnswerQuestionChoice[]>();
  for (const question of questions) {
    const parent = question.parent_id && byId.has(question.parent_id) ? question.parent_id : null;
    children.set(parent, [...(children.get(parent) || []), question]);
  }
  const result: ModelAnswerQuestionChoice[] = [];
  const seen = new Set<string>();
  const walk = (parent: string | null) => {
    for (const question of (children.get(parent) || []).sort((left, right) =>
      (order.get(left.id) || 0) - (order.get(right.id) || 0))) {
      if (seen.has(question.id)) continue;
      seen.add(question.id);
      result.push(question);
      walk(question.id);
    }
  };
  walk(null);
  for (const question of questions) if (!seen.has(question.id)) result.push(question);
  return result;
}

export function dispositionOf(entry: ModelAnswerDraftEntry): "include" | "unassigned" | "excluded" | "ignored" {
  return entry.disposition || (entry.question_id ? "include" : "unassigned");
}

export function buildReviewTargets(draft: Pick<ModelAnswerImportDraft, "questions" | "entries">): ReviewTarget[] {
  const visibleEntries = draft.entries.filter((entry) => dispositionOf(entry) !== "ignored"
    && !(effectivelyBlank(entry.answer_text) && effectivelyBlank(entry.candidate_text)));
  const questions = orderedQuestions(draft.questions).map((question) => ({
    id: `question:${question.id}`, label: question.label, kind: "question" as const, questionId: question.id,
  }));
  const questionIds = new Set(draft.questions.map((question) => question.id));
  const unresolved = visibleEntries.filter((entry) => dispositionOf(entry) === "unassigned" || !entry.question_id || !questionIds.has(entry.question_id))
    .map((entry, index) => ({ id: `unassigned:${entry.id}`, label: `対応する設問なし (${index + 1})`,
      kind: "unassigned" as const, entryId: entry.id }));
  const excluded = visibleEntries.filter((entry) => dispositionOf(entry) === "excluded")
    .map((entry, index) => ({ id: `excluded:${entry.id}`, label: `除外済み > ${entry.question_id ? "模範解答ではない文章" : "取り込み対象外"} (${index + 1})`,
      kind: "excluded" as const, entryId: entry.id }));
  return [...questions, ...unresolved, ...excluded];
}

export function resolveReviewTarget(targets: ReviewTarget[], requested: string): ReviewTarget | undefined {
  return targets.find((target) => target.id === requested) || targets[0];
}
