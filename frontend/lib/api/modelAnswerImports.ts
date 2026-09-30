import { apiFetch } from "./client";

export interface ModelAnswerSourceSegment {
  page_index: number;
  text_start: number;
  text_end: number;
  element_ids: string[];
}

export interface ModelAnswerDraftEntry {
  id: string;
  question_id: string | null;
  mapping_state: "automatic" | "manual_mapped" | "needs_review" | string;
  mapped_question_label?: string | null;
  answer_text: string;
  source: {
    material_id: string;
    source_sha256: string;
    segments: ModelAnswerSourceSegment[];
  };
}

export interface ModelAnswerQuestionChoice {
  id: string;
  label: string;
  display_label: string;
  parent_id: string | null;
  is_gradable: boolean;
}

export interface ModelAnswerImportDraft {
  id: string;
  test_id: string;
  material_id: string;
  source_sha256: string;
  state: "editing" | "confirmed" | string;
  revision: number;
  entries: ModelAnswerDraftEntry[];
  questions: ModelAnswerQuestionChoice[];
  page_count: number;
  parser: { backend?: string; library?: string; version?: string };
  created_at: string;
}

export interface ImportedModelAnswer {
  id: string;
  question_id: string;
  answer_text: string;
  material_id: string;
  provenance_json: Record<string, unknown>;
  version: number;
  is_current: boolean;
}

const json = (value: unknown) => ({ method: "POST", body: JSON.stringify(value) });

export const modelAnswerImports = {
  create: (testId: string, materialId: string) => apiFetch<ModelAnswerImportDraft>(
    `/tests/${encodeURIComponent(testId)}/model-answer-imports`, json({ material_id: materialId }),
  ),
  get: (draftId: string) => apiFetch<ModelAnswerImportDraft>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}`,
  ),
  update: (draftId: string, body: { expected_revision: number; entries: Array<Pick<ModelAnswerDraftEntry, "id" | "question_id" | "answer_text">> }) => apiFetch<ModelAnswerImportDraft>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}`,
    { method: "PUT", body: JSON.stringify(body) },
  ),
  confirm: (draftId: string, expectedRevision: number) => apiFetch<{ draft: ModelAnswerImportDraft; model_answers: ImportedModelAnswer[] }>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}/confirm`,
    json({ expected_revision: expectedRevision }),
  ),
};
