import { canonicalQuestionPath } from "./canonicalQuestionPath";
export interface QuestionNavigationItem {
  id: string;
  parent_id?: string | null;
  display_label?: string | null;
  question_number?: string | null;
  label?: string;
}

export function questionBreadcrumb(question: QuestionNavigationItem, questions: QuestionNavigationItem[]): string {
  return canonicalQuestionPath(question.id, questions.map(item => ({key: item.id, parentKey: item.parent_id,
    label: item.display_label || item.question_number || item.label || "問題", fallbackPath: item.label})), "問題");
}
