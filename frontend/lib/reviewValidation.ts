import type { ReviewNode } from "@/types/reviews";

export type FieldIssues = Record<string, Record<string, string[]>>;
export interface ReviewFieldError {
  nodeKey: string;
  fieldKey: string;
  path: string;
  fieldLabel: string;
  message: string;
  targetId: string;
}

export function buildQuestionPath(nodeKey: string, nodes: ReviewNode[]): string {
  const byKey = new Map(nodes.map(node => [node.stable_key, node]));
  const labels: string[] = [];
  const seen = new Set<string>();
  let current = byKey.get(nodeKey);
  while (current && !seen.has(current.stable_key)) {
    seen.add(current.stable_key);
    labels.unshift(current.label.raw.trim() || current.label.normalized.trim() || "名称未設定の設問");
    current = current.parent_key ? byKey.get(current.parent_key) : undefined;
  }
  return labels.join(" > ") || "選択中の設問";
}

export function reviewFieldId(nodeKey: string, fieldKey: string): string {
  return `review-field-${encodeURIComponent(nodeKey)}-${encodeURIComponent(fieldKey)}`;
}

export function reviewFieldLabel(node: ReviewNode, fieldKey: string): string {
  if (fieldKey === "source_mapping") return "元資料との対応情報";
  if (fieldKey === "label") return "設問名";
  if (fieldKey === "score") return "配点";
  if (fieldKey === "parent") return "設問の階層";
  if (fieldKey === "content" || fieldKey.startsWith("text:") || fieldKey.startsWith("formula:")) return "問題文";
  return "保存内容";
}

export function reviewFieldErrors(nodes: ReviewNode[], issues: FieldIssues): ReviewFieldError[] {
  return nodes.flatMap(node => Object.entries(issues[node.stable_key] || {}).flatMap(([fieldKey, messages]) =>
    messages.map(message => ({
      nodeKey: node.stable_key, fieldKey, path: buildQuestionPath(node.stable_key, nodes),
      fieldLabel: reviewFieldLabel(node, fieldKey), message,
      targetId: reviewFieldId(node.stable_key, fieldKey),
    }))));
}

export function validateReviewFields(nodes: ReviewNode[]): FieldIssues {
  const found: FieldIssues = {};
  for (const node of nodes.filter(item => item.included)) {
    const fields: Record<string, string[]> = {};
    if (!node.label.raw.trim()) fields.label = ["設問名を入力してください。"];
    if (!nodes.some(child => child.included && child.parent_key === node.stable_key) &&
        (!node.ordered_content.length || node.ordered_content.every(item => item.type === "text" && !String(item.text ?? "").trim()))) {
      fields.content = ["問題文が空です。入力してください。"];
    }
    if (["direct", "each_child"].includes(node.score_semantics) && node.score_points === null) {
      fields.score = ["配点を入力してください。"];
    }
    for (const [key, value] of Object.entries(node.formula_decisions)) {
      if (value.decision === "teacher_edit" && !value.teacher_transcription?.trim()) {
        fields[`formula:${key}`] = ["数式の内容を入力してください。"];
      }
    }
    if (Object.keys(fields).length) found[node.stable_key] = fields;
  }
  return found;
}
