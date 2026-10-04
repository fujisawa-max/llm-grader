import { apiFetch, json } from "./client";
export type LatexProposal = {
  math_regions?: {page_index: number; crop_image?: string; raw_latex: string}[];
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
