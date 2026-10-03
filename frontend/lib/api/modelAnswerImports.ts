import { apiFetch } from "./client";

export interface ModelAnswerSourceSegment {
  page_index: number;
  text_start: number;
  text_end: number;
  element_ids: string[];
  id?: string;
  original_text?: string;
  text_sha256?: string;
  bbox?: number[] | null;
  geometry?: SpatialAssignment;
}

export interface SpatialAssignment {
  question_id: string | null;
  assignment_status: string;
  confidence: number;
  evidence: string;
  region?: { heading: string; origin: string; page_index: number; top: number; bottom: number } | null;
}

export type ModelAnswerContentCategory =
  | "question" | "model_answer" | "alternative_answer" | "rubric" | "note" | "uncertain";

export interface ModelAnswerClassifiedSegment {
  id: string;
  start: number;
  end: number;
  text: string;
  source_text: string;
  category: ModelAnswerContentCategory;
  confidence: number;
}

export interface ModelAnswerClassificationGroup {
  text: string;
  segment_ids: string[];
  label?: string;
}

export interface RubricConsolidatedGroup {
  id: string;
  group_id: string;
  segment_ids: string[];
  kind: "rubric" | "note" | "question" | "other" | "uncertain";
  description: string;
  source_text: string;
  points: number;
  points_conflict: boolean;
  confidence: number;
  needs_teacher_review: boolean;
  merge_type: "llm_group" | "mechanical_fallback" | string;
  source_segments: Array<Record<string, unknown>>;
}

export interface ModelAnswerSemanticClassification {
  profile_id?: string;
  model_id?: string;
  runtime_type?: string;
  method: string;
  status: "classified" | "needs_teacher_review" | "teacher_reviewed" | "fallback" | string;
  reason?: string;
  confidence: number | null;
  threshold: number;
  candidate_text: string;
  segments: ModelAnswerClassifiedSegment[];
  question_segments: ModelAnswerClassificationGroup[];
  model_answers: ModelAnswerClassificationGroup[];
  alternative_answers: ModelAnswerClassificationGroup[];
  rubric_candidates: ModelAnswerClassificationGroup[];
  rubric_groups?: RubricConsolidatedGroup[];
  rubric_grouping_method?: string;
  notes: ModelAnswerClassificationGroup[];
  uncertain_segments: ModelAnswerClassificationGroup[];
  manual_alternative_answers?: Array<{ id: string; text: string }>;
  primary_answer_text: string;
}

export interface ModelAnswerDraftEntry {
  id: string;
  question_id: string | null;
  mapping_state: "automatic" | "manual_mapped" | "needs_review" | string;
  mapped_question_label?: string | null;
  extraction_method?: "visual_difference_guided_native_text" | "native_text_fallback" | string;
  answer_text: string;
  candidate_text?: string;
  disposition?: "include" | "unassigned" | "excluded" | "ignored";
  ignore_reason?: string;
  teacher_correction?: { teacher_confirmed?: boolean; [key: string]: unknown };
  rubric_edits?: Array<{ id: string; description: string; points: number; segment_ids?: string[];
    confidence?: number | null; points_conflict?: boolean; points_confirmed?: boolean;
    grouping_confirmed?: boolean; grouping_method?: string }>;
  rubric_merge_history?: Array<Array<{ id: string; description: string; points: number; segment_ids?: string[];
    confidence?: number | null; points_conflict?: boolean; points_confirmed?: boolean;
    grouping_confirmed?: boolean; grouping_method?: string }>>;
  answer_kind?: "primary" | "alternative";
  loaded_model_answer?: { id: string; version: number; question_id: string };
  geometry?: SpatialAssignment;
  semantic_classification?: ModelAnswerSemanticClassification;
  question_text_removal?: {
    status: "removed" | "not_removed" | string;
    method?: "exact" | "fuzzy" | null;
    confidence?: number | null;
    removed_prefix_length?: number;
    question_id?: string | null;
  };
  source: {
    kind?: "teacher_manual" | string;
    material_id: string | null;
    source_sha256: string | null;
    segments: ModelAnswerSourceSegment[];
  };
}

export interface ModelAnswerDraftEntryUpdate {
  id: string;
  question_id: string | null;
  answer_text: string;
  disposition?: "include" | "unassigned" | "excluded" | "ignored";
  answer_kind?: "primary" | "alternative";
  loaded_model_answer_id?: string | null;
  classification_segments?: Array<Pick<ModelAnswerClassifiedSegment, "id" | "category" | "text">>;
  classification_reviewed?: boolean;
  manual_alternative_answers?: Array<{ id: string; text: string }>;
  rubric_edits?: Array<{ id: string; description: string; points: number; segment_ids?: string[];
    confidence?: number | null; points_conflict?: boolean; points_confirmed?: boolean;
    grouping_confirmed?: boolean; grouping_method?: string }>;
  rubric_merge_history?: Array<Array<{ id: string; description: string; points: number; segment_ids?: string[];
    confidence?: number | null; points_conflict?: boolean; points_confirmed?: boolean;
    grouping_confirmed?: boolean; grouping_method?: string }>>;
}

export interface ModelAnswerQuestionChoice {
  id: string;
  label: string;
  display_label: string;
  parent_id: string | null;
  is_gradable: boolean;
  hierarchy_order?: number;
  question_text?: string;
}

export interface ModelAnswerImportDraft {
  id: string;
  test_id: string;
  material_id: string;
  source_sha256: string;
  state: "editing" | "confirmed" | string;
  revision: number;
  entries: ModelAnswerDraftEntry[];
  saved_answers?: Array<{ id: string; question_id: string | null; answer_text: string | null; version: number }>;
  confirmed_entry_ids?: string[];
  questions: ModelAnswerQuestionChoice[];
  page_count: number;
  parser: { backend?: string; library?: string; version?: string };
  extraction?: {
    status: "used" | "fallback" | string;
    method?: string;
    reason?: string | null;
    comparison_size?: number;
    threshold?: number;
    regions?: Array<{ page_index: number; cell_bbox: number[]; pdf_bbox: number[] }>;
  } | null;
  pipeline?: { version: string; geometry_first: boolean; status: string;
    profile_id?: string | null; semantic_classification_fallback: boolean;
    semantic_classification_used: boolean; fallback_reasons: string[] };
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

export interface ModelAnswerImportDraftSummary {
  id: string;
  test_id: string;
  material_id: string;
  source_sha256: string;
  state: string;
  revision: number;
  created_at: string;
  updated_at: string;
  entry_count: number;
  confirmed_entry_count: number;
  resumable: boolean;
  pipeline?: ModelAnswerImportDraft["pipeline"];
}

const json = (value: unknown) => ({ method: "POST", body: JSON.stringify(value) });

export const modelAnswerImports = {
  list: (testId: string, materialId?: string) => apiFetch<{ drafts: ModelAnswerImportDraftSummary[] }>(
    `/tests/${encodeURIComponent(testId)}/model-answer-import-drafts${materialId ? `?material_id=${encodeURIComponent(materialId)}` : ""}`,
  ),
  create: (testId: string, materialId: string) => apiFetch<ModelAnswerImportDraft>(
    `/tests/${encodeURIComponent(testId)}/model-answer-imports`, json({ material_id: materialId }),
  ),
  get: (draftId: string) => apiFetch<ModelAnswerImportDraft>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}`,
  ),
  classify: (draftId: string, expectedRevision: number) => apiFetch<ModelAnswerImportDraft>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}/classify`,
    json({ expected_revision: expectedRevision }),
  ),
  update: (draftId: string, body: { expected_revision: number; entries: ModelAnswerDraftEntryUpdate[] }) => apiFetch<ModelAnswerImportDraft>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}`,
    { method: "PUT", body: JSON.stringify(body) },
  ),
  confirm: (draftId: string, expectedRevision: number) => apiFetch<{ draft: ModelAnswerImportDraft; model_answers: ImportedModelAnswer[] }>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}/confirm`,
    json({ expected_revision: expectedRevision }),
  ),
  registerRubric: (draftId: string, expectedRevision: number) => apiFetch<{ draft: ModelAnswerImportDraft; rubric: { id: string; version: number; status: string } }>(
    `/model-answer-import-drafts/${encodeURIComponent(draftId)}/register-rubric`,
    json({ expected_revision: expectedRevision }),
  ),
};
