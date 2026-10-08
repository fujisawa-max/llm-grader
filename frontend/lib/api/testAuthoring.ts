import {apiFetch, json} from "./client";
import type {ReviewNode, ReviewDocument, ReviewSnapshot} from "@/types/reviews";
import type {ModelAnswerDraftEntry, RubricCandidateEdit} from "./modelAnswerImports";
import type {DiagramRecord} from "@/types/diagrams";
export type AuthoringCriterion = RubricCandidateEdit;
export interface AuthoringSnapshot {
  schema_version: "test-authoring.v1";
  metadata: {name: string; description: string; total_points: number};
  nodes: ReviewNode[];
  answers: Record<string, {primary: string; alternatives: string[]; diagram_records: DiagramRecord[]}>;
  rubrics: Record<string, AuthoringCriterion[]>;
  rubric_histories?: Record<string,AuthoringCriterion[][]>;
  source_provenance: Record<string, unknown> & {analysis_materials?:{id:string;sha256:string}[];authoring_origins?: {identities: Record<string,{formal_question_id?:string|null}>}};
  question_text_buffers?: Record<string,string>;
  materials: {id: string; sha256: string | null; role: string; replaces_material_id?:string}[];
  domains?: {
    question?: {document: Omit<ReviewDocument, "snapshot">; snapshot: Omit<ReviewSnapshot, "nodes">};
    answer?: {analysis_result?:{status:string;assigned_count:number;unresolved_count:number;candidate_count:number;fallback_count:number}; sources?:Record<string,{draft_id:string;material_id:string;source_sha256:string;artifact_ref:string;question_regions:{question_id:string;page_index:number;left:number;top:number;right:number;bottom:number;depth:number}[]}>; draft_id: string; revision: number; material_id: string; source_sha256: string; question_regions:{question_id:string;page_index:number;left:number;top:number;right:number;bottom:number;depth:number}[]; entries: (ModelAnswerDraftEntry & {authoring_question_key?: string | null; manual_alternative_answers?:{id:string;text:string}[]})[]};
  };
}
export interface AnalysisReadiness {state:"ready"|"unsaved_changes"|"missing_material"|"unsupported"|"stale_source"|"busy"|"readonly";reason:string;analyzed?:boolean}
export interface SourceWarning {question_key:string|null;code:string;message:string}
export interface AuthoringRevision {analysis_readiness?:Record<string,AnalysisReadiness>;source_warnings?:SourceWarning[];id: string; test_id: string; revision: number; edit_version: number; state: string; snapshot: AuthoringSnapshot; snapshot_sha256: string; baseline_sha256: string}
export interface AuthoringIssue {question_key: string | null; section: string; message: string; field?: string}
export interface ArchiveImpact {test_id: string; name: string; questions: number; model_answers: number; rubrics: number; submissions: number; grading_jobs: number; results: number; impact_sha256: string}
const path = (id: string) => `/tests/${encodeURIComponent(id)}`;
export const testAuthoring = {
  status: (id:string) => apiFetch<{state:string|null}>(path(id)+"/authoring/status"),
  get: (id: string) => apiFetch<{revision: AuthoringRevision | null; legacy: AuthoringSnapshot; publication_available: boolean; external_source_change: boolean; source_problems:{domain:string;code:string}[]}>(path(id)+"/authoring"),
  begin: (id: string) => apiFetch<AuthoringRevision>(path(id)+"/authoring/revisions", {method: "POST"}),
  save: (id: string, snapshot: AuthoringSnapshot, expected: number, continue_after_external_change=false) => apiFetch<AuthoringRevision>(path(id)+"/authoring", {...json({snapshot, expected_edit_version: expected, continue_after_external_change}), method: "PUT"}),
  analyzeAnswer: (id:string, material_id:string, expected_edit_version:number,preserve_previous=false) => apiFetch<AuthoringRevision>(path(id)+"/authoring/analyze-answer", json({material_id,expected_edit_version,preserve_previous})),
  importSources: (id: string, expected_edit_version: number, preserve_previous=false, analysis_material_id?:string) => apiFetch<AuthoringRevision>(path(id)+"/authoring/source-import", json({expected_edit_version,preserve_previous,analysis_material_id})),
  reviewLocal: (id:string,snapshot:AuthoringSnapshot,expected_edit_version:number) => apiFetch<{issues:AuthoringIssue[]}>(path(id)+"/authoring/review",json({snapshot,expected_edit_version})),
  review: (id: string) => apiFetch<{issues: AuthoringIssue[]; total_points: number; can_confirm: boolean}>(path(id)+"/authoring/review"),
  recent: (courseId: string) => apiFetch<{tests: {id: string; name: string; authoring_state: string; status: string}[]}>(`/courses/${encodeURIComponent(courseId)}/recent-tests`),
  impact: (id: string) => apiFetch<ArchiveImpact>(path(id)+"/archive-impact"),
  archive: (id: string, test_name: string, impact_sha256: string) => apiFetch<{archived: boolean}>(path(id)+"/archive", json({test_name, impact_sha256})),
};
