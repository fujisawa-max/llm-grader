import { apiFetch, json } from "./client";
export type LatexProposal = {
  reason_code?: string | null;
  grouping_summary?: Record<string, number | boolean>;
  math_regions?: {page_index: number; crop_image?: string; raw_latex?: string; raw_response?: unknown;
    ricoh_raw_response?: unknown; grouping_method?: string; grouping_confidence?: number | null;
    crop_width?: number; crop_height?: number; source_field?: string; normalized_candidate?: string;
    bbox?: number[]; crop_bbox?: number[]; ricoh_used?: boolean; ricoh_result?: unknown;
    rejection_code?: string; validation?: string; segment_ids?: string[];
    raw_ocr_text?: string; normalized_ocr_text?: string; candidate_count?: number; duplicate_count?: number;
    selected_candidate_index?: number; selected_candidate?: string; normalization_steps?: unknown[];
    candidate_scores?: {index: number; start: number; end: number; raw_candidate: string; normalized_candidate: string;
      score: number; accepted: boolean; duplicate_of?: number; rejection_reason?: string | null;
      unsupported_identifiers?: string[]; unsupported_numbers?: string[]; normalization_steps?: unknown[]}[]}[];
  source?: Record<string, unknown>;
  status: "safe" | "ambiguous" | "no_change" | "rejected";
  original_text: string; normalized_text: string; confidence: number | null;
  warnings: string[]; changes: {type: string; source: string}[]; profile: string; model: string;
};
export type TextContext = "model_answer" | "rubric" | "question" | "sample_answer" | "generic";
export function normalizeLatex(text: string, context_type: TextContext, context_label: string) {
  return apiFetch<LatexProposal>("/text-tools/latex-normalize", json({text, context_type, context_label}));
}

export function mathOCR(source: {draftId: string; entryId: string; revision: number}, text: string) {
  return apiFetch<LatexProposal>(`/model-answer-import-drafts/${encodeURIComponent(source.draftId)}/entries/${encodeURIComponent(source.entryId)}/math-ocr`, json({text, expected_revision: source.revision}));
}
