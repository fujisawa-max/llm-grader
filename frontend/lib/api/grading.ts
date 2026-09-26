import { apiFetch } from "./client";

export type GradingOverview = {
  test: { id: string; name: string; total_points: number };
  totals: { question_count: number; student_count: number; completed_students: number; review_required_count: number; teacher_adjudicated_count: number };
  students: Array<{ submission_id: string; student_ref: string | null; student_number?: string; student_name?: string; student_display_label?: string; student_identity_review_required?: boolean; score: number; max: number; percentage: number | null; status: string; review_flags: string[]; teacher_adjudicated_count: number; finalized?: boolean; regrade_requested?: boolean; published?: boolean; published_at?: string | null; publication_status?: string }>;
};

export type StudentResult = {
  test: { title: string };
  score: number;
  max_score: number;
  percentage: number | null;
  questions: Array<{ label: string; score: number; max_score: number; feedback: string; criteria: Array<{ label: string; score: number | null; max_score: number | null; feedback: string }>; student_answer: { text: string; visual_assets: Array<{ url: string; bbox?: unknown; mime_type: string }> } }>;
  published_at: string | null;
  status: string;
  republish_required: boolean;
};

export type GradingDetail = {
  test: { id: string; name: string; total_points: number };
  submission: { id: string; student_ref: string | null; student_number?: string; student_name?: string; student_display_label?: string; student_identity_review_required?: boolean; status: string; score: number; max: number; percentage: number | null; warnings: string[]; review_flags?: string[]; teacher_adjudicated_count: number; finalized?: boolean; regrade_requests?: Array<Record<string, unknown>> };
  audit_history: Array<Record<string, unknown>>;
  questions: Array<{
    question: { id: string; label: string; question_number: string; title?: string | null; text?: string | null; stable_key?: string | null; max_points: number | null; context?: { effective_text?: string; assets?: unknown[] } };
    authoritative: { score: number; max_score: number; source: string; result_id: string; notes: string[] } | null;
    criteria: Array<Record<string, unknown>>;
    feedback: unknown;
    teacher_reason?: string | null;
    student_feedback_override?: { id: string; feedback: string; teacher_note?: string; created_at?: string } | null;
    model_answer: { id: string; version: number; content?: string | null; sha256: string } | null;
    rubric: { id: string; version: number; status: string; entry: Record<string, unknown> | null; entry_sha256: string | null } | null;
    student_answer: { submission_id?: string; reconstruction?: Record<string, unknown> | null; source?: string; answer_text?: string | null; page_ids?: string[]; source_pages?: Array<Record<string, unknown>>; bundle_sha256?: string };
    visual_assets: Array<Record<string, unknown>>;
    reconstruction_history: Array<Record<string, unknown>>;
    history: Array<Record<string, unknown>>;
    historical_grading_count: number;
    regrade_requests: Array<Record<string, unknown>>;
    warnings: string[];
  }>;
};

export type ReviewQueue = {
  test_id: string;
  filter: string;
  items: Array<Record<string, any>>;
  progress: { reviewed: number; total: number; remaining: number; warnings: number; regrade_pending: number; teacher_adjudicated: number };
};

export type RegradeQueue = {
  test_id: string;
  pending_count: number;
  requests: Array<Record<string, any>>;
};

export const grading = {
  overview: (testId: string) => apiFetch<GradingOverview>(`/tests/${encodeURIComponent(testId)}/grading`),
  detail: (testId: string, submissionId: string) => apiFetch<GradingDetail>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}`),
  reviewQueue: (testId: string, filter?: string) => apiFetch<ReviewQueue>(`/tests/${encodeURIComponent(testId)}/grading/review${filter ? `?filter=${encodeURIComponent(filter)}` : ""}`),
  regradeQueue: (testId: string, includeCompleted = false) => apiFetch<RegradeQueue>(`/tests/${encodeURIComponent(testId)}/grading/regrade-queue?include_completed=${includeCompleted ? "true" : "false"}`),
  teacherDecision: (testId: string, submissionId: string, questionId: string, body: { criterion_scores: Array<{ criterion_id: string; score: number }>; teacher_reason: string; teacher_note?: string }) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/questions/${encodeURIComponent(questionId)}/teacher-decision`, { method: "POST", body: JSON.stringify(body) }),
  requestRegrade: (testId: string, submissionId: string, questionId: string, reason: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/questions/${encodeURIComponent(questionId)}/regrade-request`, { method: "POST", body: JSON.stringify({ reason }) }),
  finalizeSubmission: (testId: string, submissionId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/finalize`, { method: "POST", body: JSON.stringify({}) }),
  finalizeTest: (testId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/finalize`, { method: "POST", body: JSON.stringify({}) }),
  publishTest: (testId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/publish`, { method: "POST", body: JSON.stringify({}) }),
  unpublishTest: (testId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/unpublish`, { method: "POST", body: JSON.stringify({}) }),
  publishSubmission: (testId: string, submissionId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/publish`, { method: "POST", body: JSON.stringify({}) }),
  unpublishSubmission: (testId: string, submissionId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/unpublish`, { method: "POST", body: JSON.stringify({}) }),
  feedbackOverride: (testId: string, submissionId: string, questionId: string, feedback: string, teacherNote?: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/questions/${encodeURIComponent(questionId)}/feedback-override`, { method: "POST", body: JSON.stringify({ feedback, teacher_note: teacherNote || undefined }) }),
  approveRegrade: (testId: string, requestId: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/regrade-requests/${encodeURIComponent(requestId)}/approve`, { method: "POST", body: JSON.stringify({}) }),
  rejectRegrade: (testId: string, requestId: string, reason: string) => apiFetch<Record<string, unknown>>(`/tests/${encodeURIComponent(testId)}/grading/regrade-requests/${encodeURIComponent(requestId)}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  // Browser downloads carry the HttpOnly session cookie; never put a
  // development user id or role assertion in a teacher-facing URL.
  exportUrl: (testId: string) => `${(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "")}/tests/${encodeURIComponent(testId)}/grading/export.csv`,
  teacherResultPdfUrl: (testId: string, submissionId: string) => `${(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "")}/tests/${encodeURIComponent(testId)}/grading/${encodeURIComponent(submissionId)}/result.pdf`,
  studentResult: (submissionId: string) => apiFetch<StudentResult>(`/student/results/${encodeURIComponent(submissionId)}`, { headers: process.env.NEXT_PUBLIC_STUDENT_ID ? { "X-Student-ID": process.env.NEXT_PUBLIC_STUDENT_ID } : {} }),
  studentResultPdfUrl: (submissionId: string) => `${(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "")}/student/results/${encodeURIComponent(submissionId)}/pdf${process.env.NEXT_PUBLIC_STUDENT_ID ? `?student_id=${encodeURIComponent(process.env.NEXT_PUBLIC_STUDENT_ID)}&role=student` : ""}`,
};
