import type { Question } from "@/types/domain";

export function orderedGradableQuestions(questions: Question[]): Question[] {
  const walk = (parent: string | null, depth = 0): Question[] => {
    if (depth > questions.length) return [];
    return questions
      .filter(question => (question.parent_id || null) === parent)
      .sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id))
      .flatMap(question => [question, ...walk(question.id, depth + 1)]);
  };
  return walk(null).filter(question => question.is_gradable !== false);
}

export function teacherQuestionLabel(question: Question, questions: Question[]): string {
  const own = question.display_label || question.question_number || "問題";
  if (!question.parent_id) return own;
  const parent = questions.find(item => item.id === question.parent_id);
  return parent ? `${parent.display_label || parent.question_number} ${own}` : own;
}

export function gradingQuestionRank(stableKey?: string | null, label?: string | null): number {
  const key = `${stableKey || ""} ${label || ""}`.toLowerCase();
  const match = key.match(/q(\d+)(?:\.(\d+))?/);
  if (match) return Number(match[1]) * 100 + Number(match[2] || 0);
  if (key.includes("accuracy")) return 202;
  if (key.includes("precision")) return 203;
  if (key.includes("recall")) return 204;
  if (key.includes("問題3") || key.includes("question 3")) return 300;
  return 9999;
}
