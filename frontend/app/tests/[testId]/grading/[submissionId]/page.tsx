"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { grading, type GradingDetail } from "@/lib/api/grading";
import { AppShell } from "@/components/AppShell";
import { TeacherActionForm } from "@/components/TeacherActionForm";
import { TechnicalDetails, friendlyWarning } from "@/components/ui";

export default function StudentGradingDetailPage() {
  const params = useParams(); const testId = String(params.testId); const submissionId = String(params.submissionId);
  const [data, setData] = useState<GradingDetail | null>(null); const [error, setError] = useState("");
  const refresh = () => grading.detail(testId, submissionId).then(setData).catch((e) => setError(e instanceof Error ? e.message : "読み込みに失敗しました"));
  useEffect(() => { refresh(); }, [testId, submissionId]);
  if (error) return <AppShell><div className="error">{error}</div></AppShell>;
  if (!data) return <AppShell><div className="loading">採点詳細を読み込んでいます…</div></AppShell>;
  const studentLabel = data.submission.student_display_label || "学生情報未確認";
  return <AppShell><div className="breadcrumbs"><Link href={`/tests/${testId}/grading`}>採点結果</Link><span className="sep">/</span>{studentLabel}</div>
    <div className="page-header"><div><h1>{data.test.name} — {studentLabel}</h1><p className="muted">学生の採点結果</p>{data.submission.student_identity_review_required && <p className="warn">学生情報を確認してください。</p>}<TechnicalDetails label="技術情報"><p>Submission ID: {data.submission.id}</p></TechnicalDetails></div><div className="detail-actions"><div className="final-score"><strong>{data.submission.score} / {data.submission.max}</strong><span>{data.submission.percentage === null ? "—" : `${data.submission.percentage.toFixed(2)}%`}</span></div><a className="button secondary" href={grading.teacherResultPdfUrl(testId, submissionId)}>結果PDF</a><FinalizeButton testId={testId} submissionId={submissionId} finalized={Boolean(data.submission.finalized)} onDone={refresh} /></div></div>
    {data.submission.warnings.length > 0 && <WarningPanel warnings={data.submission.warnings} />}
    <AuditHistory rows={data.audit_history} />
    <section className="panel section"><h2>問題別の最終結果</h2>{data.questions.map((item) => <QuestionReview key={item.question.id} item={item} testId={testId} onChanged={refresh} />)}</section>
  </AppShell>;
}

function WarningPanel({ warnings }: { warnings: string[] }) { return <div className="notice warning-panel"><strong>確認事項</strong><div className="flag-list">{warnings.map((warning) => <TechnicalDetails label={friendlyWarning(warning)} key={warning}><code>{warning}</code></TechnicalDetails>)}</div><p className="muted">確認事項は採点結果とは別に表示しています。</p></div>; }

function AuditHistory({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return null;
  return <section className="panel section"><h2>Audit History</h2><table className="table compact"><thead><tr><th>Question</th><th>Event / source</th><th>Status</th><th>Score</th><th>Timestamp</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${String(row.id || index)}-${index}`}><td>{String(row.question || "Test")}</td><td>{String(row.event_type || row.source || "MODEL")}</td><td>{String(row.state || row.status || "—")}</td><td>{row.score == null ? "—" : `${String(row.score)} / ${String(row.max_score || "—")}`}</td><td>{String(row.created_at || row.completed_at || "—")}</td></tr>)}</tbody></table></section>;
}

function FinalizeButton({ testId, submissionId, finalized, onDone }: { testId: string; submissionId: string; finalized: boolean; onDone: () => void }) {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const finalize = async () => { setBusy(true); setError(""); try { await grading.finalizeSubmission(testId, submissionId); onDone(); } catch (e) { setError(e instanceof Error ? e.message : "確定に失敗しました"); } finally { setBusy(false); } };
  return <div className="finalize-control"><button className="button secondary" disabled={finalized || busy} onClick={finalize}>{finalized ? "採点確定済み" : busy ? "保存中…" : "採点を確定"}</button>{error && <small className="warn">{error}</small>}</div>;
}

function QuestionReview({ item, testId, onChanged }: { item: GradingDetail["questions"][number]; testId: string; onChanged: () => void }) {
  const result = item.authoritative;
  return <article className="grading-question"><div className="grading-question-header"><div><h3>{item.question.label}</h3><p className="muted">{item.question.title || item.question.text || ""}　{item.question.max_points}点</p></div><div className="question-score">{result ? <><strong>{result.score} / {result.max_score}</strong><span className={`source source-${result.source.toLowerCase()}`}>{result.source === "TEACHER_ADJUDICATION" ? "教師確定" : "モデル"}</span></> : <span className="warn">結果なし</span>}</div></div>
    <p className="muted">{item.historical_grading_count > 0 ? `過去の採点履歴 ${item.historical_grading_count}件` : "過去の採点履歴はありません"}</p>{item.warnings.length > 0 && <div className="flag-list question-flags">{item.warnings.map((warning) => <TechnicalDetails label={friendlyWarning(warning)} key={warning}><code>{warning}</code></TechnicalDetails>)}</div>}
    <details><summary>答案・基準・履歴を表示</summary><div className="grading-evidence-grid">
      <Evidence title="答案の読み取り結果"><p className="muted">手書き答案を読み取り、採点に使用する形に整理した内容です。</p><pre className="answer-text">{item.student_answer.answer_text || "（本文なし）"}</pre>{item.student_answer.reconstruction && <TechnicalDetails label="技術情報"><p>Reconstruction v{String(item.student_answer.reconstruction.version)} / {String(item.student_answer.reconstruction.id)}</p></TechnicalDetails>}</Evidence>
      <Evidence title="Question"><p>{item.question.context?.effective_text || item.question.text || "—"}</p></Evidence>
      <Evidence title="模範解答"><pre className="answer-text">{item.model_answer?.content || "—"}</pre>{item.model_answer && <TechnicalDetails label="技術情報"><p>V{item.model_answer.version} / SHA {item.model_answer.sha256}</p></TechnicalDetails>}</Evidence>
      <Evidence title="Rubric"><Rubric entry={item.rubric?.entry} /></Evidence>
      <Evidence title="Criterion breakdown"><Criteria criteria={item.criteria} definitions={item.rubric?.entry?.criteria} /></Evidence>
      <Evidence title="Feedback"><pre className="answer-text">{formatValue(item.feedback)}</pre>{item.teacher_reason && <><h5>Teacher decision reason</h5><pre className="answer-text">{item.teacher_reason}</pre></>}</Evidence>
      <Evidence title="Grading evidence"><EvidenceAssets item={item} testId={testId} /></Evidence>
      <Evidence title="History"><History rows={item.history} /></Evidence>
      <Evidence title="Teacher actions"><TeacherActionForm item={item} testId={testId} onDone={onChanged} /></Evidence>
      <Evidence title="Student-facing feedback override"><FeedbackOverrideForm item={item} testId={testId} onDone={onChanged} /></Evidence>
    </div></details>
  </article>;
}

function Evidence({ title, children }: { title: string; children: React.ReactNode }) { return <section className="evidence-card"><h4>{title}</h4>{children}</section>; }
function Criteria({ criteria, definitions }: { criteria: Array<Record<string, unknown>>; definitions?: unknown }) { if (!criteria.length) return <p className="muted">なし</p>; const definitionMap = new Map((Array.isArray(definitions) ? definitions : []).map((definition) => { const value = definition as Record<string, unknown>; return [String(value.id), value]; })); return <table className="table compact"><thead><tr><th>Criterion</th><th>Score</th><th>Evidence / reason</th></tr></thead><tbody>{criteria.map((row, index) => { const definition = definitionMap.get(String(row.criterion_id)); return <tr key={String(row.criterion_id || index)}><td><strong>{String(row.criterion_id || "—")}</strong>{definition?.description ? <><br /><span>{String(definition.description)}</span></> : null}</td><td>{String(row.score ?? "—")} / {String(row.max_score ?? definition?.points ?? "—")}</td><td>{String(row.reason || row.teacher_reason || "")}</td></tr>; })}</tbody></table>; }
function Rubric({ entry }: { entry: Record<string, unknown> | null | undefined }) { const criteria = Array.isArray(entry?.criteria) ? entry.criteria as Array<Record<string, unknown>> : []; return criteria.length ? <ul className="rubric-list">{criteria.map((criterion, index) => <li key={String(criterion.id || index)}><strong>{String(criterion.id || "criterion")}</strong> ({String(criterion.points || "—")}点) {String(criterion.description || "")}</li>)}</ul> : <p className="muted">基準なし</p>; }
function History({ rows }: { rows: Array<Record<string, unknown>> }) { if (!rows.length) return <p className="muted">履歴なし</p>; return <table className="table compact"><thead><tr><th>種別 / ID</th><th>状態</th><th>Score</th><th>日時</th></tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id || index)}><td>{row.source ? String(row.source) : "MODEL"}<br /><small>{String(row.id || "—")}</small></td><td>{String(row.state || row.status || "—")}</td><td>{row.score == null ? "—" : `${String(row.score)} / ${String(row.max_score ?? "—")}`}</td><td>{String(row.completed_at || row.created_at || "—")}</td></tr>)}</tbody></table>; }
function EvidenceAssets({ item, testId }: { item: GradingDetail["questions"][number]; testId: string }) { if (!item.visual_assets.length) return <p className="muted">テキスト答案</p>; return <div className="asset-list">{item.visual_assets.map((asset) => { const href = `/api/v1/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(String(item.student_answer.submission_id || ""))}/questions/${encodeURIComponent(item.question.id)}/visual-assets/${encodeURIComponent(String(asset.asset_id))}`; return <div className="asset-row" key={`${String(asset.asset_id)}-${String(asset.role)}`}><strong>{asset.role === "student_visual_answer" ? "学生の図答案" : asset.role === "question" ? "問題の図" : "模範解答の参照図"}</strong>{asset.role === "student_visual_answer" && <><img className="evidence-asset-image" src={href} alt="学生の図答案" /><a href={href} target="_blank" rel="noreferrer">画像を開く</a></>}{asset.role !== "student_visual_answer" && <span className="muted">参照用</span>}<TechnicalDetails label="技術情報"><span>SHA {String(asset.sha256 || "—")} · BBox {JSON.stringify(asset.bbox || "—")}</span></TechnicalDetails></div>; })}</div>; }
function formatValue(value: unknown): string { return typeof value === "string" ? value : JSON.stringify(value, null, 2) || "—"; }

function FeedbackOverrideForm({ item, testId, onDone }: { item: GradingDetail["questions"][number]; testId: string; onDone: () => void }) {
  const [feedback, setFeedback] = useState(""); const [teacherNote, setTeacherNote] = useState(""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const [error, setError] = useState("");
  const save = async (event: React.FormEvent) => { event.preventDefault(); setBusy(true); setMessage(""); setError(""); try { await grading.feedbackOverride(testId, item.student_answer.submission_id || "", item.question.id, feedback, teacherNote); setMessage("学生向けフィードバックを保存しました。"); onDone(); } catch (e) { setError(e instanceof Error ? e.message : "保存に失敗しました"); } finally { setBusy(false); } };
  return <form className="action-form" onSubmit={save}>{item.student_feedback_override && <div className="notice"><strong>Current student feedback</strong><p>{item.student_feedback_override.feedback}</p><small className="muted">Teacher note is internal and is not shown to students.</small></div>}<textarea aria-label="Student-facing feedback" required value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="学生に表示するフィードバック" /><textarea aria-label="Teacher note" value={teacherNote} onChange={(event) => setTeacherNote(event.target.value)} placeholder="教員内部メモ（学生には非表示）" /><button className="button secondary" disabled={busy || !feedback.trim()}>{busy ? "保存中…" : "Override feedback"}</button>{message && <small className="ok">{message}</small>}{error && <small className="error">{error}</small>}</form>;
}
