import {apiFetch, json} from "./client";
import type {ReviewNode} from "@/types/reviews";
import type {DiagramRecord} from "@/types/diagrams";
export interface AuthoringCriterion {id: string; description: string; points: number; [key: string]: unknown}
export interface AuthoringSnapshot {
  schema_version: "test-authoring.v1";
  metadata: {name: string; description: string; total_points: number};
  nodes: ReviewNode[];
  answers: Record<string, {primary: string; alternatives: string[]; diagram_records: DiagramRecord[]}>;
  rubrics: Record<string, AuthoringCriterion[]>;
  source_provenance: Record<string, unknown>;
  materials: {id: string; sha256: string | null; role: string}[];
}
export interface AuthoringRevision {id: string; test_id: string; revision: number; edit_version: number; state: string; snapshot: AuthoringSnapshot; snapshot_sha256: string; baseline_sha256: string}
export interface AuthoringIssue {question_key: string | null; section: string; message: string}
export interface ArchiveImpact {test_id: string; name: string; questions: number; model_answers: number; rubrics: number; submissions: number; grading_jobs: number; results: number; impact_sha256: string}
const path = (id: string) => `/tests/${encodeURIComponent(id)}`;
export const testAuthoring = {
  get: (id: string) => apiFetch<{revision: AuthoringRevision | null; legacy: AuthoringSnapshot; publication_available: boolean}>(path(id)+"/authoring"),
  begin: (id: string) => apiFetch<AuthoringRevision>(path(id)+"/authoring/revisions", {method: "POST"}),
  save: (id: string, snapshot: AuthoringSnapshot, expected: number) => apiFetch<AuthoringRevision>(path(id)+"/authoring", {...json({snapshot, expected_edit_version: expected}), method: "PUT"}),
  review: (id: string) => apiFetch<{issues: AuthoringIssue[]; total_points: number; can_confirm: boolean}>(path(id)+"/authoring/review"),
  recent: (courseId: string) => apiFetch<{tests: {id: string; name: string; authoring_state: string; status: string}[]}>(`/courses/${encodeURIComponent(courseId)}/recent-tests`),
  impact: (id: string) => apiFetch<ArchiveImpact>(path(id)+"/archive-impact"),
  archive: (id: string, test_name: string, impact_sha256: string) => apiFetch<{archived: boolean}>(path(id)+"/archive", json({test_name, impact_sha256})),
};
