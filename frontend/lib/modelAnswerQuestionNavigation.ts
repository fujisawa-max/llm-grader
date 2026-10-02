export interface QuestionNavigationItem {
  id: string;
  parent_id?: string | null;
  display_label?: string | null;
  question_number?: string | null;
  label?: string;
}

export function questionBreadcrumb(question: QuestionNavigationItem, questions: QuestionNavigationItem[]): string {
  const byId = new Map(questions.map((item) => [item.id, item]));
  const labels: string[] = [];
  const seen = new Set<string>();
  let current: QuestionNavigationItem | undefined = question;
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    if (current.parent_id && !byId.has(current.parent_id) && current.label) return current.label;
    labels.unshift(current.display_label || current.question_number || current.label || "問題");
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return labels.join(" > ");
}
