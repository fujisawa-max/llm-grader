"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { grading, type StudentResult } from "@/lib/api/grading";

export default function StudentResultPage() {
  const submissionId = String(useParams().submissionId);
  const portalEnabled = process.env.NEXT_PUBLIC_STUDENT_PORTAL_ENABLED === "true" || process.env.NEXT_PUBLIC_STUDENT_PORTAL_ENABLED === "1";
  const [data, setData] = useState<StudentResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!portalEnabled) return;
    grading.studentResult(submissionId).then(setData).catch((value) => setError(value instanceof Error ? value.message : "結果を読み込めません"));
  }, [submissionId, portalEnabled]);
  if (!portalEnabled) return <AppShell><main className="result-page"><div className="notice warning-panel"><strong>学生ポータルは現在無効です</strong><p>採点結果は教員がPDFまたはCSVで配布します。</p></div></main></AppShell>;
  if (error) return <AppShell><div className="error">{error}</div></AppShell>;
  if (!data) return <AppShell><div className="loading">結果を読み込んでいます…</div></AppShell>;
  return <AppShell><main className="result-page"><div className="page-header"><div><h1>{data.test.title}</h1><p className="muted">公開日時: {data.published_at || "—"}</p></div><div className="final-score"><strong>{data.score} / {data.max_score}</strong><span>{data.percentage == null ? "—" : `${data.percentage.toFixed(2)}%`}</span></div></div>{data.status === "RESULT_CHANGED_AFTER_PUBLICATION" && <div className="notice warning-panel"><strong>結果が更新されています</strong><p>教員による再公開が必要です。現在は最後に公開された結果を表示しています。</p></div>}<div className="result-actions"><a className="button secondary" href={grading.studentResultPdfUrl(submissionId)}>結果PDF</a></div><section className="result-questions">{data.questions.map((question) => <article className="panel section" key={question.label}><div className="grading-question-header"><h2>{question.label}</h2><strong>{question.score} / {question.max_score}</strong></div>{question.student_answer.text && <pre className="answer-text">{question.student_answer.text}</pre>}{question.student_answer.visual_assets.map((asset) => <img className="evidence-asset-image" key={asset.url} src={asset.url} alt={`${question.label} の答案画像`} />)}{question.feedback && <div className="student-feedback"><h3>Feedback</h3><p>{question.feedback}</p></div>}{question.criteria.length > 0 && <div><h3>Criterion feedback</h3><ul className="rubric-list">{question.criteria.map((criterion) => <li key={criterion.label}><strong>{criterion.label}</strong> {criterion.score == null ? "" : `${criterion.score} / ${criterion.max_score}`} {criterion.feedback && <span>— {criterion.feedback}</span>}</li>)}</ul></div>}</article>)}</section></main></AppShell>;
}
