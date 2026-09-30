export type ID = string;
export type TestStatus = "draft" | "setup" | "rubric_review" | "ready" | "grading" | "completed" | "archived";
export interface User { id: ID; display_name: string; email?: string | null; role: "admin" | "teacher" | "student"; is_active: boolean; must_change_password: boolean; created_at: string; updated_at?: string; }
export interface Course { id: ID; owner_user_id: ID; code?: string | null; name: string; description?: string | null; is_archived: boolean; created_at: string; updated_at: string; }
export interface Offering { id: ID; course_id: ID; academic_year: number; term: string; term_label?: string | null; section?: string | null; display_name?: string | null; is_archived: boolean; created_at: string; updated_at: string; }
export interface Test { id: ID; course_offering_id: ID; name: string; description?: string | null; test_date?: string | null; status: TestStatus; total_points: number; created_at: string; updated_at: string; }
export interface Question { id: ID; test_id: ID; question_number: string; title?: string | null; question_text?: string | null; max_points: number | null; sort_order: number; parent_id?: string | null; display_label?: string | null; is_gradable?: boolean; node_type?: string; content_sha256?: string | null; provenance?: {origin?: string; confirmation_id?: string} | null; content?: {items: {type: string; asset_id?: string; source_region_id?: string; transcription?: string; text?: string}[]} | null; }
export interface Material { id: ID; test_id: ID; material_type: string; original_filename?: string | null; mime_type?: string | null; sha256?: string | null; }
export interface ModelAnswer { id: ID; test_id: ID; question_id?: ID | null; answer_text?: string | null; material_id?: ID | null; provenance_json?: Record<string, unknown> | null; version: number; is_current: boolean; created_at: string; }
export interface GradingPolicy { id: ID; test_id: ID; policy_text: string; version: number; is_current: boolean; created_at: string; }
export interface SampleAnswer { id: ID; test_id: ID; sample_key: string; material_id?: ID | null; transcription?: string | null; created_at: string; score_count?: number; }
export interface Student { id: ID; course_offering_id: ID; student_identifier: string; display_name?: string | null; is_active: boolean; }
export interface Submission { id: ID; test_id: ID; student_id: ID; submission_key: string; material_id: ID; attempt_number: number; status: string; }
export interface Rubric { id: ID; test_id: ID; version: number; status: string; source_type: string; rubric_json: { questions?: Array<{ question_id: ID; max_points: number; criteria: Array<{ id: string; description: string; points: number; guidance?: string | null }> }> }; rubric_text?: string | null; created_at: string; approved_at?: string | null; }
export interface Readiness { ready: boolean; checks: Record<string, boolean>; blocking_reasons: string[]; blocking_codes?: string[]; }
export interface Job { id: ID; state: string; current_phase?: string | null; execution_mode: string; total_items: number; completed_items: number; item_error_count: number; review_required_count: number; test_id?: ID | null; rubric_version_id?: ID | null; created_at: string; completed_at?: string | null; }
export interface ApiError { error?: { code?: string; message?: string; details?: unknown }; }
