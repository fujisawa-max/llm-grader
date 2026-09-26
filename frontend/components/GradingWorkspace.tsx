"use client";

import { useEffect, useMemo, useState } from "react";
import { grading, type GradingDetail, type GradingOverview } from "@/lib/api/grading";
import { orderedGradableQuestions, teacherQuestionLabel } from "@/lib/questionOrder";
import type { Question, Submission } from "@/types/domain";

interface IdentityRow { submission_id: string; student_number?: string; student_display_label?: string; score: number; max: number; status: string; }

export function GradingWorkspace({testId, questions, submissions}: {testId: string; questions: Question[]; submissions: Submission[]}) {
  const [overview, setOverview] = useState<GradingOverview>();
  const [detail, setDetail] = useState<GradingDetail>();
  const [selectedSubmissionId, setSelectedSubmissionId] = useState("");
  const [selectedQuestionId, setSelectedQuestionId] = useState("");
  const [error, setError] = useState("");
  const orderedQuestions = useMemo(() => orderedGradableQuestions(questions), [questions]);
  const rows = useMemo(() => [...(overview?.students || [])].sort((a, b) => (a.student_number || "").localeCompare(b.student_number || "") || a.submission_id.localeCompare(b.submission_id)), [overview]);
  const selectedRow = rows.find(row => row.submission_id === selectedSubmissionId) || rows[0];
  const selectedQuestion = orderedQuestions.find(question => question.id === selectedQuestionId) || orderedQuestions[0];
  const selectedQuestionResult = detail?.questions.find(row => row.question.id === selectedQuestion?.id);
  const attemptFor = (submissionId: string) => submissions.find(submission => submission.id === submissionId)?.attempt_number || 1;
  const displayLabel = (row: IdentityRow) => `${row.student_display_label || "学生情報未確認"} / 答案${attemptFor(row.submission_id)}回目`;
  useEffect(() => { let active = true; setError(""); grading.overview(testId).then(value => { if (active) setOverview(value); }).catch(() => { if (active) setError("採点結果を読み込めませんでした。"); }); return () => { active = false; }; }, [testId]);
  useEffect(() => { if (rows.length && !rows.some(row => row.submission_id === selectedSubmissionId)) setSelectedSubmissionId(rows[0].submission_id); }, [rows, selectedSubmissionId]);
  useEffect(() => { if (!selectedRow) return; let active = true; setDetail(undefined); grading.detail(testId, selectedRow.submission_id).then(value => { if (active) { setDetail(value); setSelectedQuestionId(current => current || orderedQuestions[0]?.id || ""); } }).catch(() => { if (active) setError("採点詳細を読み込めませんでした。"); }); return () => { active = false; }; }, [testId, selectedRow?.submission_id, orderedQuestions]);
  if (error && !overview) return <section className="panel section"><p className="error">{error}</p></section>;
  return <section className="panel section grading-workspace" aria-label="採点ワークスペース"><h2>採点</h2><p className="muted">現在のauthoritative採点結果を確認します。採点済みの答案は再実行しません。</p>{overview && <><div className="grading-selection-bar"><label>学生を選択<select aria-label="採点対象の学生" value={selectedRow?.submission_id || ""} onChange={event => { setSelectedSubmissionId(event.target.value); setSelectedQuestionId(orderedQuestions[0]?.id || ""); }}>{rows.map(row => <option key={row.submission_id} value={row.submission_id}>{displayLabel(row)}</option>)}</select></label><div className="grading-current-total"><strong>{selectedRow?.score ?? "—"} / {selectedRow?.max ?? "—"}</strong><span>{selectedRow?.status === "COMPLETE" ? "採点済み" : selectedRow?.status || "—"}</span></div></div><div className="grading-workspace-grid"><nav className="question-selector grading-question-selector" aria-label="採点対象の設問"><h3>設問</h3>{orderedQuestions.map(question => <button type="button" key={question.id} className={selectedQuestion?.id === question.id ? "question-select active" : "question-select"} onClick={() => setSelectedQuestionId(question.id)}>{teacherQuestionLabel(question, questions)}<small>{detail?.questions.find(row => row.question.id === question.id)?.authoritative ? "採点済み" : "未採点"}</small></button>)}</nav><article className="question-detail-pane grading-result-detail">{selectedQuestion && <><header className="question-detail-header"><div><p className="muted">選択中の設問</p><h3>{teacherQuestionLabel(selectedQuestion, questions)}</h3></div><strong>{selectedQuestionResult?.authoritative?.score ?? "—"} / {selectedQuestionResult?.authoritative?.max_score ?? selectedQuestion.max_points ?? "—"}</strong></header>{selectedQuestionResult?.authoritative ? <><p className="ok">この設問は採点済みです。</p><a className="button secondary" href={`/tests/${testId}/grading/${selectedRow?.submission_id}`}>採点結果を確認</a>{selectedQuestionResult.feedback ? <div className="detail-block"><h4>フィードバック</h4><p>{typeof selectedQuestionResult.feedback === "string" ? selectedQuestionResult.feedback : "採点結果にフィードバックがあります。"}</p></div> : null}<div className="detail-block"><h4>基準別得点</h4><ul className="rubric-list">{selectedQuestionResult.criteria.map((criterion, index) => <li key={String(criterion.id || index)}>{String(criterion.description || criterion.label || `基準${index + 1}`)}: {String(criterion.score ?? "—")} / {String(criterion.max_score ?? criterion.points ?? "—")}</li>)}</ul></div></> : <><p className="notice">この設問はまだ採点されていません。</p><button type="button" className="button secondary" disabled>採点を開始（Worker実行が必要）</button><p className="muted">採点処理は明示的なproduction Worker操作から実行します。</p></>}</>}</article></div></>}</section>;
}
