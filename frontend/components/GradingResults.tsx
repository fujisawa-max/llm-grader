"use client";

import { useEffect, useMemo, useState } from "react";
import { grading, type GradingDetail, type GradingOverview } from "@/lib/api/grading";
import { orderedGradableQuestions, teacherQuestionLabel } from "@/lib/questionOrder";
import type { Question, Submission } from "@/types/domain";

export function GradingResults({testId, questions, submissions}: {testId: string; questions: Question[]; submissions: Submission[]}) {
  const [overview, setOverview] = useState<GradingOverview>();
  const [details, setDetails] = useState<Record<string, GradingDetail>>({});
  const [expanded, setExpanded] = useState<string[]>([]);
  const [error, setError] = useState("");
  const orderedQuestions = useMemo(() => orderedGradableQuestions(questions), [questions]);
  const rows = useMemo(() => [...(overview?.students || [])].sort((a, b) => (a.student_number || "").localeCompare(b.student_number || "") || a.submission_id.localeCompare(b.submission_id)), [overview]);
  const attemptFor = (id: string) => submissions.find(submission => submission.id === id)?.attempt_number || 1;
  useEffect(() => { let active = true; grading.overview(testId).then(value => { if (active) setOverview(value); }).catch(() => { if (active) setError("採点結果を読み込めませんでした。"); }); return () => { active = false; }; }, [testId]);
  async function toggle(id: string) { if (expanded.includes(id)) { setExpanded(expanded.filter(value => value !== id)); return; } if (!details[id]) { try { const value = await grading.detail(testId, id); setDetails(current => ({...current, [id]: value})); } catch { setError("設問別の採点結果を読み込めませんでした。"); return; } } setExpanded([...expanded, id]); }
  if (error && !overview) return <section className="panel section"><p className="error">{error}</p></section>;
  return <section className="panel section grading-results" aria-label="採点結果"><h2>採点結果</h2><p className="muted">現在有効な採点結果を表示しています。</p>{error && <p className="error">{error}</p>}{!overview ? <p>採点結果を読み込んでいます…</p> : !rows.length ? <p className="empty">採点結果はまだありません。</p> : <table className="table results-table"><thead><tr><th>学籍番号・氏名</th><th>合計点</th><th>状態</th><th>詳細</th></tr></thead><tbody>{rows.map(row => <tr key={row.submission_id}><td>{row.student_display_label || "学生情報未確認"} / 答案{attemptFor(row.submission_id)}回目</td><td><strong>{row.score} / {row.max}</strong></td><td>{row.status === "COMPLETE" ? "採点済み" : "要確認"}</td><td><button type="button" className="button secondary" onClick={() => void toggle(row.submission_id)}>{expanded.includes(row.submission_id) ? "詳細を閉じる" : "設問別詳細"}</button></td></tr>)}{rows.flatMap(row => expanded.includes(row.submission_id) && details[row.submission_id] ? [<tr key={`${row.submission_id}-detail`}><td colSpan={4}><div className="result-detail-grid"><h3>{row.student_display_label || "学生情報未確認"}</h3>{orderedQuestions.map(question => { const item = details[row.submission_id].questions.find(value => value.question.id === question.id); return <article key={question.id} className="result-question-row"><span>{teacherQuestionLabel(question, questions)}</span><strong>{item?.authoritative ? `${item.authoritative.score} / ${item.authoritative.max_score}` : "—"}</strong></article>; })}</div></td></tr>] : [])}</tbody></table>}</section>;
}
