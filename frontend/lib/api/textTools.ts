import { apiFetch, json } from "./client";
export type LatexProposal = {
  status: "safe" | "ambiguous" | "no_change" | "rejected";
  original_text: string; normalized_text: string; confidence: number;
  warnings: string[]; changes: {type: string; source: string}[]; profile: string; model: string;
};
export type TextContext = "model_answer" | "rubric" | "question" | "sample_answer" | "generic";
export function normalizeLatex(text: string, context_type: TextContext, context_label: string) {
  return apiFetch<LatexProposal>("/text-tools/latex-normalize", json({text, context_type, context_label}));
}
