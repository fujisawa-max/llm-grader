import type { ModelAnswerDraftEntry, ModelAnswerImportDraft } from "@/lib/api/modelAnswerImports";
import { dispositionOf } from "@/lib/modelAnswerReviewTargets";

export interface RegistrationValidationItem {
  candidateId?: string;
  questionId?: string;
  reviewTargetId?: string;
  reasonCode: string;
  category?: string;
  disposition?: string;
  severity: "blocking";
  message: string;
}

const categoryLabels: Record<string, string> = {
  question: "問題文", model_answer: "模範解答", alternative_answer: "別解",
  rubric: "採点基準候補", note: "補足・注記", uncertain: "分類未確定",
};

export function validateModelAnswerRegistration(
  draft: Pick<ModelAnswerImportDraft, "entries" | "questions" | "confirmed_entry_ids">,
  targetLabels: Map<string, string>,
): RegistrationValidationItem[] {
  const items: RegistrationValidationItem[] = [];
  const confirmed = new Set(draft.confirmed_entry_ids || []);
  const included = draft.entries.filter((entry) => dispositionOf(entry) === "include" && !confirmed.has(entry.id));
  const unresolvedOrder = new Map(draft.entries
    .filter((entry) => dispositionOf(entry) === "unassigned" || !entry.question_id || !draft.questions.some((question) => question.id === entry.question_id))
    .map((entry, index) => [entry.id, index + 1]));
  const labelFor = (entry: ModelAnswerDraftEntry) => entry.question_id && draft.questions.some((question) => question.id === entry.question_id)
    ? targetLabels.get(`question:${entry.question_id}`) || "設問"
    : `対応する設問なし (${unresolvedOrder.get(entry.id) || 1})`;
  const add = (entry: ModelAnswerDraftEntry | undefined, reasonCode: string, message: string, category?: string) => {
    items.push({
      ...(entry ? {
        candidateId: entry.id,
        questionId: entry.question_id || undefined,
        reviewTargetId: entry.question_id && draft.questions.some((question) => question.id === entry.question_id)
          ? `question:${entry.question_id}` : `unassigned:${entry.id}`,
        category,
        disposition: dispositionOf(entry),
        message: `${labelFor(entry)} — ${message}`,
      } : { message }),
      reasonCode,
      severity: "blocking",
    });
  };

  if (!included.length) add(undefined, "no_registration_candidates", "登録対象となる模範解答がありません。候補を取り込み対象にしてください。");
  for (const entry of included) {
    const firstCategory = entry.semantic_classification?.segments[0]?.category;
    const categoryPrefix = firstCategory ? `${categoryLabels[firstCategory] || "分類未確定"}: ` : "";
    if (!entry.question_id) add(entry, "question_mapping_required", `${categoryPrefix}対応先の設問を選ぶか、この候補を未割当または除外にしてください。`,
      firstCategory);
    else if (!draft.questions.some((question) => question.id === entry.question_id && question.is_gradable)) {
      add(entry, "invalid_question_mapping", `${categoryPrefix}登録できる採点対象の設問を選び直してください。`, firstCategory);
    }
    if (!entry.answer_text.trim()) add(entry, "empty_answer_text", "模範解答本文が空です。本文を入力してください。");
    if (entry.semantic_classification?.status === "needs_teacher_review") {
      const categories = [...new Set(entry.semantic_classification.segments.map((segment) => segment.category))];
      const category = categories.map((value) => categoryLabels[value] || "分類未確定").join("・") || "分類未確定";
      add(entry, "classification_review_required", `分類結果を確認してください（${category}）。`, categories[0]);
    }
  }

  const primaries = included.filter((entry) => (entry.answer_kind || "primary") === "primary" && entry.question_id);
  const primaryCounts = new Map<string, number>();
  primaries.forEach((entry) => primaryCounts.set(entry.question_id!, (primaryCounts.get(entry.question_id!) || 0) + 1));
  for (const entry of primaries.filter((candidate) => primaryCounts.get(candidate.question_id!)! > 1)) {
    add(entry, "duplicate_primary_answer", "同じ設問に主な模範解答が複数あります。1件に整理するか別解に変更してください。");
  }
  const primaryIds = new Set(primaries.map((entry) => entry.question_id));
  for (const entry of included.filter((candidate) => candidate.answer_kind === "alternative" && candidate.question_id && !primaryIds.has(candidate.question_id))) {
    add(entry, "primary_answer_required", "主な模範解答がありません。主な模範解答を追加してください。");
  }
  return items;
}
