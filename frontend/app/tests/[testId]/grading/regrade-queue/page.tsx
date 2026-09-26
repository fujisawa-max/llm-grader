"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { grading, type RegradeQueue } from "@/lib/api/grading";

export default function RegradeQueuePage() {
  const testId = String(useParams().testId);
  const [includeCompleted, setIncludeCompleted] = useState(false);
  const [data, setData] = useState<RegradeQueue | null>(null); const [error, setError] = useState("");
  const refresh = () => grading.regradeQueue(testId, includeCompleted).then(setData).catch((e) => setError(e instanceof Error ? e.message : "再採点キューを読み込めません"));
  useEffect(() => { refresh(); }, [testId, includeCompleted]);
  if (error) return <AppShell><div className="error">{error}</div></AppShell>;
  if (!data) return <AppShell><div className="loading">Regrade Queueを読み込んでいます…</div></AppShell>;
  return <AppShell><div className="breadcrumbs"><Link href={`/tests/${testId}/grading`}>採点結果</Link><span className="sep">/</span>Regrade Queue</div><div className="page-header"><div><h1>Regrade Queue</h1><p className="muted">Teacher approval後だけproduction Workerへ投入されます。</p></div><Link className="button secondary" href={`/tests/${testId}/grading/review`}>Review Workspace</Link></div><section className="cards grading-summary"><Summary title="Pending" value={String(data.pending_count)} /><Summary title="Requests" value={String(data.requests.length)} /></section><section className="panel section"><div className="review-toolbar"><label><input type="checkbox" checked={includeCompleted} onChange={(event) => setIncludeCompleted(event.target.checked)} /> 完了・却下済みも表示</label></div><h2>再採点依頼</h2>{data.requests.length === 0 ? <p className="empty">未解決の依頼はありません。</p> : <table className="table"><thead><tr><th>Student</th><th>Question</th><th>Reason</th><th>Requested</th><th>Score</th><th>Reconstruction</th><th>Rubric</th><th>Status</th><th>Actions</th></tr></thead><tbody>{data.requests.map((request) => <QueueRow key={String(request.request_id)} testId={testId} request={request} onDone={refresh} />)}</tbody></table>}</section></AppShell>;
}

function QueueRow({ testId, request, onDone }: { testId: string; request: Record<string, any>; onDone: () => void }) {
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const approve = async () => { setBusy(true); setMessage(""); try { await grading.approveRegrade(testId, String(request.request_id)); setMessage("APPROVED"); onDone(); } catch (e) { setMessage(e instanceof Error ? e.message : "承認に失敗しました"); } finally { setBusy(false); } };
  const reject = async () => { const reason = window.prompt("却下理由"); if (!reason?.trim()) return; setBusy(true); setMessage(""); try { await grading.rejectRegrade(testId, String(request.request_id), reason); setMessage("REJECTED"); onDone(); } catch (e) { setMessage(e instanceof Error ? e.message : "却下に失敗しました"); } finally { setBusy(false); } };
  const pending = String(request.status) === "PENDING"; const failed = String(request.status) === "FAILED";
  return <tr><td>{String(request.student_display_label || "学生情報未確認")}</td><td>{String(request.question_label || request.question_id || "—")}</td><td>{String(request.reason || "—")}</td><td>{String(request.created_at || "—")}</td><td>{request.score == null ? "—" : `${String(request.score)} / ${String(request.max_score || "—")}`}</td><td>v{String(request.reconstruction?.version || request.current_reconstruction_version || "—")}</td><td>v{String(request.current_rubric_version || "—")}</td><td><span className={`badge badge-${String(request.status).toLowerCase()}`}>{String(request.status)}</span>{request.latest_event_payload?.message && <small className="warn">{String(request.latest_event_payload.message)}</small>}</td><td>{pending ? <div className="queue-actions"><button className="button" disabled={busy} onClick={approve}>Approve</button><button className="button secondary" disabled={busy} onClick={reject}>Reject</button></div> : failed ? <button className="button secondary" disabled={busy} onClick={reject}>Reject</button> : <span className="muted">{message || "—"}</span>}</td></tr>;
}

function Summary({ title, value }: { title: string; value: string }) { return <div className="card"><h3>{title}</h3><div className="stat">{value}</div></div>; }
