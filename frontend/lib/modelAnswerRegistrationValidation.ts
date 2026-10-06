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

export function isEffectivelyBlank(value: string | null | undefined): boolean {
  return ![...(value || "")].some((char) => !/[\s\u00a0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u2060\u3000\ufeff\u0000-\u001f\u007f-\u009f]/u.test(char));
}

export function hasAcceptedDiagram(entry: ModelAnswerDraftEntry, sourceSha?: string): boolean {
  return !!entry.diagram_records?.some(record => record.state === "accepted" && record.status !== "unresolved"
    && !record.reason_code && (!sourceSha || record.source_sha256 === sourceSha) && (record.assigned_question_id || record.target_key) === entry.question_id && !!record.crop_sha256);
}

export function isModelAnswerRegistrationEntry(entry: ModelAnswerDraftEntry): boolean {
  if (entry.diagram_records?.length || entry.source?.kind === "teacher_manual" || !entry.semantic_classification?.segments?.length) return true;
  const categories = new Set(entry.semantic_classification.segments.map((segment) => segment.category));
  return categories.has("model_answer") || categories.has("alternative_answer") || categories.has("uncertain");
}

export function validateModelAnswerRegistration(
  draft: Pick<ModelAnswerImportDraft, "entries" | "questions" | "confirmed_entry_ids"> & Partial<Pick<ModelAnswerImportDraft, "source_sha256">>,
  targetLabels: Map<string, string>,
): RegistrationValidationItem[] {
  const items: RegistrationValidationItem[] = [];
  const confirmed = new Set(draft.confirmed_entry_ids || []);
  const included = draft.entries.filter((entry) => dispositionOf(entry) === "include" && !confirmed.has(entry.id)
    && isModelAnswerRegistrationEntry(entry)
    && (entry.diagram_records?.length || entry.source?.kind === "teacher_manual"
      || !(isEffectivelyBlank(entry.answer_text) && isEffectivelyBlank(entry.candidate_text))));
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
    if (!entry.question_id) add(entry, "question_mapping_required", "対応先の設問を選ぶか、この候補を未割当または除外にしてください。");
    else if (!draft.questions.some((question) => question.id === entry.question_id && question.is_gradable)) {
      add(entry, "invalid_question_mapping", "登録できる採点対象の設問を選び直してください。");
    }
    if (isEffectivelyBlank(entry.answer_text) && !hasAcceptedDiagram(entry, draft.source_sha256)) add(entry, "empty_answer_text", "模範解答本文が空で、使用する図も登録されていません。本文を入力するか、模範解答の図を選択してください。");
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
