"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { grading, type GradingOverview } from "@/lib/api/grading";
import { AppShell } from "@/components/AppShell";
import { TechnicalDetails, friendlyStatus, friendlyWarning } from "@/components/ui";

const statusLabel: Record<string, string> = { COMPLETE: "完了", REVIEW_REQUIRED: "要確認", REGRADING_REQUESTED: "再採点依頼済み", INCOMPLETE: "未完了" };

export default function GradingOverviewPage() {
  const testId = String(useParams().testId);
  const [data, setData] = useState<GradingOverview | null>(null);
  const [error, setError] = useState("");
  const refresh = () => grading.overview(testId).then(setData).catch((e) => setError(e instanceof Error ? e.message : "読み込みに失敗しました"));
  useEffect(() => { refresh(); }, [testId]);
  if (error) return <AppShell><div className="error">{error}</div></AppShell>;
  if (!data) return <AppShell><div className="loading">採点結果を読み込んでいます…</div></AppShell>;
  return <AppShell><div className="breadcrumbs"><Link href={`/tests/${testId}`}>テスト</Link><span className="sep">/</span>採点結果</div>
    <div className="page-header"><div><h1>{data.test.name} — 採点結果</h1><p className="muted">教師確定と履歴を確認できます。</p></div><div className="detail-actions"><Link className="button secondary" href={`/tests/${testId}/grading/review`}>確認ワークスペース</Link><Link className="button secondary" href={`/tests/${testId}/grading/regrade-queue`}>再採点依頼</Link><a className="button" href={grading.exportUrl(testId)}>CSVを出力</a><FinalizeTestButton testId={testId} finalized={data.students.length > 0 && data.students.every((row) => row.finalized)} onDone={refresh} /><PublishTestButton testId={testId} published={data.students.length > 0 && data.students.every((row) => row.published)} onDone={refresh} /></div></div>
    <section className="cards grading-summary" aria-label="採点概要">
      <Summary title="学生" value={`${data.totals.student_count}名`} />
      <Summary title="完了" value={`${data.totals.completed_students}名`} detail={`${data.totals.question_count}問`} />
      <Summary title="要確認" value={`${data.totals.review_required_count}名`} />
      <Summary title="教師確定" value={`${data.totals.teacher_adjudicated_count}名`} />
      <Summary title="テスト配点" value={`${data.test.total_points}点`} />
    </section>
    <section className="panel section"><h2>学生別一覧</h2>{data.students.length === 0 ? <p className="empty">答案がありません。</p> : <table className="table"><thead><tr><th>学生</th><th>得点</th><th>割合</th><th>状態</th><th>確定</th><th>公開</th><th>確認事項</th><th>公開操作</th></tr></thead><tbody>{data.students.map((row) => <tr key={row.submission_id}><td><Link href={`/tests/${testId}/grading/${row.submission_id}`}>{row.student_display_label || "学生情報未確認"}</Link>{row.student_identity_review_required && <small className="warn">学生情報を確認</small>}</td><td>{row.score} / {row.max}</td><td>{row.percentage === null ? "—" : `${row.percentage.toFixed(2)}%`}</td><td><span className={`badge badge-${row.status.toLowerCase()}`}>{statusLabel[row.status] || friendlyStatus(row.status)}</span></td><td>{row.finalized ? "確定済み" : "未確定"}</td><td><span className={`badge ${row.published ? "badge-published" : "badge-unpublished"}`}>{row.published ? "公開済み" : "未公開"}</span>{row.published_at && <small className="muted">{row.published_at}</small>}</td><td>{row.review_flags.length ? <div className="flag-list">{row.review_flags.map((flag) => <TechnicalDetails label={friendlyWarning(flag)} key={flag}><code>{flag}</code></TechnicalDetails>)}</div> : <span className="muted">なし</span>}</td><td><PublishSubmissionButton testId={testId} submissionId={row.submission_id} published={Boolean(row.published)} onDone={refresh} /></td></tr>)}</tbody></table>}</section>
  </AppShell>;
}

function Summary({ title, value, detail }: { title: string; value: string; detail?: string }) { return <div className="card"><h3>{title}</h3><div className="stat">{value}</div>{detail && <p className="muted">{detail}</p>}</div>; }

function FinalizeTestButton({ testId, finalized, onDone }: { testId: string; finalized: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const finalize = async () => { setBusy(true); setError(""); try { await grading.finalizeTest(testId); onDone(); } catch (e) { setError(e instanceof Error ? e.message : "確定に失敗しました"); } finally { setBusy(false); } };
  return <div className="finalize-control"><button className="button secondary" disabled={finalized || busy} onClick={finalize}>{finalized ? "採点確定済み" : busy ? "保存中…" : "採点を確定"}</button>{error && <small className="warn">{error}</small>}</div>;
}

function PublishTestButton({ testId, published, onDone }: { testId: string; published: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const toggle = async () => { setBusy(true); setError(""); try { if (published) await grading.unpublishTest(testId); else await grading.publishTest(testId); onDone(); } catch (e) { setError(e instanceof Error ? e.message : "公開状態を変更できません"); } finally { setBusy(false); } };
  return <div className="finalize-control"><button className="button" disabled={busy} onClick={toggle}>{busy ? "保存中…" : published ? "公開を取り消す" : "結果を公開"}</button>{error && <small className="warn">{error}</small>}</div>;
}

function PublishSubmissionButton({ testId, submissionId, published, onDone }: { testId: string; submissionId: string; published: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const toggle = async () => { setBusy(true); setError(""); try { if (published) await grading.unpublishSubmission(testId, submissionId); else await grading.publishSubmission(testId, submissionId); onDone(); } catch (e) { setError(e instanceof Error ? e.message : "公開状態を変更できません"); } finally { setBusy(false); } };
  return <div><button className="button secondary" disabled={busy} onClick={toggle}>{busy ? "保存中…" : published ? "公開を取り消す" : "公開する"}</button>{error && <small className="warn">{error}</small>}</div>;
}
