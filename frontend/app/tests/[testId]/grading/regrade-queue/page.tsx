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
  if (!data) return <AppShell><div className="loading">再採点依頼を読み込んでいます…</div></AppShell>;
  return <AppShell><div className="breadcrumbs"><Link href={`/tests/${testId}/grading`}>採点結果</Link><span className="sep">/</span>再採点依頼</div><div className="page-header"><div><h1>再採点依頼</h1><p className="muted">教師が承認した依頼のみ、再採点処理へ進みます。</p></div><Link className="button secondary" href={`/tests/${testId}/grading/review`}>採点結果の確認</Link></div><section className="cards grading-summary"><Summary title="処理待ち" value={String(data.pending_count)} /><Summary title="依頼件数" value={String(data.requests.length)} /></section><section className="panel section"><div className="review-toolbar"><label><input type="checkbox" checked={includeCompleted} onChange={(event) => setIncludeCompleted(event.target.checked)} /> 完了・却下済みも表示</label></div><h2>再採点依頼</h2>{data.requests.length === 0 ? <p className="empty">未解決の依頼はありません。</p> : <table className="table"><thead><tr><th>学生</th><th>問題</th><th>依頼理由</th><th>依頼日時</th><th>得点</th><th>技術情報</th><th>状態</th><th>操作</th></tr></thead><tbody>{data.requests.map((request) => <QueueRow key={String(request.request_id)} testId={testId} request={request} onDone={refresh} />)}</tbody></table>}</section></AppShell>;
}

function QueueRow({ testId, request, onDone }: { testId: string; request: Record<string, any>; onDone: () => void }) {
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const approve = async () => { setBusy(true); setMessage(""); try { await grading.approveRegrade(testId, String(request.request_id)); setMessage("承認済み"); onDone(); } catch (e) { setMessage(e instanceof Error ? e.message : "承認に失敗しました"); } finally { setBusy(false); } };
  const reject = async () => { const reason = window.prompt("却下理由"); if (!reason?.trim()) return; setBusy(true); setMessage(""); try { await grading.rejectRegrade(testId, String(request.request_id), reason); setMessage("却下済み"); onDone(); } catch (e) { setMessage(e instanceof Error ? e.message : "却下に失敗しました"); } finally { setBusy(false); } };
  const pending = String(request.status) === "PENDING"; const failed = String(request.status) === "FAILED";
  return <tr><td>{String(request.student_display_label || "学生情報未確認")}</td><td>{String(request.question_label || request.question_id || "—")}</td><td>{String(request.reason || "—")}</td><td>{String(request.created_at || "—")}</td><td>{request.score == null ? "—" : `${String(request.score)} / ${String(request.max_score || "—")}`}</td><td><details><summary>詳細を表示</summary>読み取り版 v{String(request.reconstruction?.version || request.current_reconstruction_version || "—")} / 採点基準版 v{String(request.current_rubric_version || "—")}</details></td><td><span className={`badge badge-${String(request.status).toLowerCase()}`}>{({ PENDING: "処理待ち", FAILED: "失敗", APPROVED: "承認済み", REJECTED: "却下済み", COMPLETED: "完了" } as Record<string, string>)[String(request.status)] || "確認が必要"}</span>{request.latest_event_payload?.message && <small className="warn">{String(request.latest_event_payload.message)}</small>}</td><td>{pending ? <div className="queue-actions"><button className="button" disabled={busy} onClick={approve}>承認</button><button className="button secondary" disabled={busy} onClick={reject}>却下</button></div> : failed ? <button className="button secondary" disabled={busy} onClick={reject}>却下</button> : <span className="muted">{message || "—"}</span>}</td></tr>;
}

function Summary({ title, value }: { title: string; value: string }) { return <div className="card"><h3>{title}</h3><div className="stat">{value}</div></div>; }
