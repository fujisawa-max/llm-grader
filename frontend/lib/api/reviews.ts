import { apiFetch, json } from "./client";
import type { Json, PreviewMetadata, RegionEvidence, ReviewDocument, ReviewEntry, ReviewSnapshot, RevisionInfo } from "@/types/reviews";
const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "");
const path = (id: string) => `/question-import-reviews/${encodeURIComponent(id)}`;
export interface ImportPlan { revision: number; revision_sha256: string; plan_sha256: string; nodes: {review_node_id: string}[]; existing_question_count: number; total_points: number | null; structural_count: number; gradable_count: number; figure_count: number; formula_count: number; excluded_count: number; blockers: string[]; warnings: string[]; }
export interface Confirmation {id: string; test_id: string; state: string; structural_count: number; gradable_count: number; total_points: number | null; items: {review_node_id: string; test_question_id: string | null; excluded: boolean}[]; }
export interface CorrectionOperation {source_region_id: string; expected_old_transcription: string; new_transcription: string;}
export interface CorrectionPlan {question_id: string; current_content_sha256: string; new_content_sha256: string; operations: {source_region_id: string; previous: string; new: string}[]; resulting_context_sha256: string; plan_sha256: string;}
export interface CorrectionHistory {id: string; correction_version: number; source_region_ids: string[]; previous_content_sha256: string; new_content_sha256: string; reason_code: string; created_at?: string | null;}
export const reviews = {
  confirmation: (id: string) => apiFetch<Confirmation | null>(path(id) + "/confirmation"),
  importPlan: (id: string) => apiFetch<ImportPlan>(path(id) + "/import-plan", { method: "POST" }),
  confirm: (id: string, body: {expected_revision: number; expected_revision_sha256: string; import_plan_sha256: string; mode: "append"}) => apiFetch<Confirmation>(path(id) + "/confirm", json(body)),
  list: (testId: string) => apiFetch<ReviewEntry[]>(`/tests/${encodeURIComponent(testId)}/question-import-reviews`),
  create: (draftId: string) => apiFetch<ReviewDocument>(`/question-import-drafts/${encodeURIComponent(draftId)}/reviews`, { method: "POST" }),
  get: (id: string, revision?: number) => apiFetch<ReviewDocument>(path(id) + (revision ? `/revisions/${revision}` : "")),
  save: (id: string, snapshot: ReviewSnapshot, base_revision: number) => apiFetch<ReviewDocument>(path(id) + "/revisions", json({ snapshot, base_revision })),
  reviewed: (id: string, base_revision: number) => apiFetch<ReviewDocument>(path(id) + "/mark-reviewed", json({ base_revision })),
  history: (id: string) => apiFetch<{ revisions: RevisionInfo[] }>(path(id) + "/revisions"),
  metadata: (id: string, page: number) => apiFetch<PreviewMetadata>(path(id) + `/pages/${page}/metadata`),
  previewUrl: (id: string, page: number) => base + path(id) + `/pages/${page}/preview`,
  cropUrl: (id: string, region: string) => base + path(id) + `/regions/${encodeURIComponent(region)}/crop`,
  evidence: (id: string, region: string) => apiFetch<RegionEvidence>(path(id) + `/regions/${encodeURIComponent(region)}/evidence`),
  raw: (id: string, region: string) => apiFetch<{ raw: Json; source_raw_sha256: string }>(path(id) + `/regions/${encodeURIComponent(region)}/vision-raw`),
};

export const corrections = {
  plan: (questionId: string, body: {expected_content_sha256: string; operations: CorrectionOperation[]; reason_code: string; note?: string}) =>
    apiFetch<CorrectionPlan>(`/test-questions/${encodeURIComponent(questionId)}/correction-plan`, json(body)),
  apply: (questionId: string, body: {expected_content_sha256: string; operations: CorrectionOperation[]; reason_code: string; note?: string; plan_sha256: string}) =>
    apiFetch<{id: string; new_content_sha256: string}>(`/test-questions/${encodeURIComponent(questionId)}/corrections`, json(body)),
  history: (questionId: string) => apiFetch<{corrections: CorrectionHistory[]}>(`/test-questions/${encodeURIComponent(questionId)}/corrections`),
};
