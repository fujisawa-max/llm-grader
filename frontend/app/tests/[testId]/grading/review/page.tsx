"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { grading, type GradingDetail, type ReviewQueue } from "@/lib/api/grading";
import { TeacherActionForm } from "@/components/TeacherActionForm";

const filters = [
  ["unresolved", "要確認"], ["warnings", "警告"], ["regrade", "再採点依頼"],
  ["adjudicated", "教師確定"], ["reconstruction", "再構成履歴"], ["visual", "画像答案"],
  ["zero", "0点"], ["partial", "部分点"], ["full", "満点"], ["all", "すべて"],
];

export default function ReviewWorkspacePage() {
  const testId = String(useParams().testId);
  const [filter, setFilter] = useState("unresolved");
  const [data, setData] = useState<ReviewQueue | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const refresh = () => grading.reviewQueue(testId, filter).then((value) => {
    setData(value); setIndex((current) => Math.min(current, Math.max(0, value.items.length - 1)));
  }).catch((e) => setError(e instanceof Error ? e.message : "レビューキューを読み込めません"));
  useEffect(() => { refresh(); }, [testId, filter]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName)) return;
      if (event.key === "j" || event.key === "ArrowDown") setIndex((value) => Math.min(value + 1, (data?.items.length || 1) - 1));
      if (event.key === "k" || event.key === "ArrowUp") setIndex((value) => Math.max(value - 1, 0));
      if (event.key === "Enter") document.getElementById("review-detail")?.scrollIntoView({ behavior: "smooth" });
      if (event.key.toLowerCase() === "a") document.getElementById("teacher-actions")?.scrollIntoView({ behavior: "smooth" });
      if (event.key.toLowerCase() === "r") document.getElementById("regrade-actions")?.scrollIntoView({ behavior: "smooth" });
      if (event.key === "+" || event.key === "=") (document.querySelector("[aria-label='zoom-in']") as HTMLButtonElement | null)?.click();
      if (event.key === "-") (document.querySelector("[aria-label='zoom-out']") as HTMLButtonElement | null)?.click();
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [data?.items.length]);
  const selected = data?.items[index] as Record<string, any> | undefined;
  const detailItem = useMemo(() => selected?.question_review as GradingDetail["questions"][number] | undefined, [selected]);
  if (error) return <AppShell><div className="error">{error}</div></AppShell>;
  if (!data) return <AppShell><div className="loading">Review Workspaceを読み込んでいます…</div></AppShell>;
  return <AppShell>
    <div className="breadcrumbs"><Link href={`/tests/${testId}/grading`}>採点結果</Link><span className="sep">/</span>Review Workspace</div>
    <div className="page-header"><div><h1>Review Workspace</h1><p className="muted">J/Kまたは↑/↓で移動、Enterで詳細、Aで教師確定、Rで再採点依頼。</p></div><Link className="button secondary" href={`/tests/${testId}/grading/regrade-queue`}>Regrade Queue</Link></div>
    <section className="cards grading-summary"><Summary title="Reviewed" value={`${data.progress.reviewed} / ${data.progress.total}`} /><Summary title="Remaining" value={String(data.progress.remaining)} /><Summary title="Warnings" value={String(data.progress.warnings)} /><Summary title="Regrade pending" value={String(data.progress.regrade_pending)} /><Summary title="Teacher adjudicated" value={String(data.progress.teacher_adjudicated)} /></section>
    <div className="review-toolbar"><label>Filter <select value={filter} onChange={(event) => { setFilter(event.target.value); setIndex(0); }}>{filters.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><span className="muted">{data.items.length} targets</span></div>
    <section className="review-workspace-grid">
      <div className="panel review-target-list"><h2>Review targets</h2>{data.items.length === 0 ? <p className="empty">対象はありません。</p> : data.items.map((row, rowIndex) => <button className={`review-target ${rowIndex === index ? "selected" : ""}`} key={row.target} onClick={() => setIndex(rowIndex)}><strong>{row.student_display_label || "学生情報未確認"} / {row.question_label}</strong><span>{row.score == null ? "—" : `${row.score} / ${row.max_score}`}</span><small>{row.flags?.join(" · ") || row.status || "要確認"}</small></button>)}</div>
      {selected && detailItem ? <ReviewDetail row={selected} item={detailItem} testId={testId} onChanged={refresh} /> : <div className="panel review-empty">左の対象を選択してください。</div>}
    </section>
  </AppShell>;
}

function ReviewDetail({ row, item, testId, onChanged }: { row: Record<string, any>; item: GradingDetail["questions"][number]; testId: string; onChanged: () => void }) {
  const visual = item.visual_assets.filter((asset) => asset.role === "student_visual_answer");
  const [zoom, setZoom] = useState(1);
  return <div className="panel review-detail" id="review-detail"><div className="review-detail-header"><h2>{row.student_display_label || "学生情報未確認"} — {row.question_label}</h2><span className="badge">{row.score == null ? "結果なし" : `${row.score} / ${row.max_score}`}</span></div><div className="side-by-side">
    <section className="review-pane"><h3>Student Answer</h3><div className="zoom-controls"><button aria-label="zoom-out" className="button secondary" onClick={() => setZoom((value) => Math.max(.5, value - .25))}>−</button><span>{Math.round(zoom * 100)}%</span><button aria-label="zoom-in" className="button secondary" onClick={() => setZoom((value) => Math.min(3, value + .25))}>＋</button></div>{(item.student_answer.page_ids || []).map((pageId) => <img style={{ width: `${zoom * 100}%` }} className="evidence-asset-image" key={pageId} src={`/api/v1/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(item.student_answer.submission_id || "")}/answer-artifacts/${encodeURIComponent(pageId)}`} alt="Original student answer page" />)}<pre className="answer-text">{item.student_answer.answer_text || "（本文なし）"}</pre>{item.student_answer.reconstruction && <p className="muted">Reconstruction v{String(item.student_answer.reconstruction.version)} / {String(item.student_answer.reconstruction.artifact_ref || "artifact")}</p>}{visual.map((asset) => <div className="asset-row" key={String(asset.asset_id)}><strong>student_visual_answer</strong><span>SHA {String(asset.sha256 || "—")}</span><span>BBox {JSON.stringify(asset.bbox || "—")}</span><img style={{ width: `${zoom * 100}%` }} className="evidence-asset-image" src={`/api/v1/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(item.student_answer.submission_id || "")}/questions/${encodeURIComponent(item.question.id)}/visual-assets/${encodeURIComponent(String(asset.asset_id))}`} alt="Student visual answer" /></div>)}</section>
    <section className="review-pane"><h3>Selected Reconstruction / Criteria</h3><pre className="answer-text">{item.student_answer.answer_text || "（本文なし）"}</pre><Criteria criteria={item.criteria} definitions={item.rubric?.entry?.criteria} /><div id="teacher-actions"><TeacherActionForm item={item} testId={testId} onDone={onChanged} /></div></section>
    <section className="review-pane"><h3>Question / Reference / Result</h3><h4>Question</h4><p>{item.question.context?.effective_text || item.question.text || "—"}</p><h4>ModelAnswer</h4><pre className="answer-text">{item.model_answer?.content || "—"}</pre>{item.visual_assets.length > 0 && <><h4>Visual roles</h4><ul className="rubric-list">{item.visual_assets.map((asset) => <li key={`${String(asset.role)}-${String(asset.asset_id)}`}><strong>{String(asset.role)}</strong> — SHA {String(asset.sha256 || "—")}</li>)}</ul></>}<h4>Approved Rubric</h4><Rubric entry={item.rubric?.entry} /><h4>Feedback</h4><pre className="answer-text">{format(item.feedback)}</pre>{item.warnings.length > 0 && <div className="flag-list">{item.warnings.map((warning) => <span className="flag" key={warning}>{warning}</span>)}</div>}</section>
  </div></div>;
}

function Summary({ title, value }: { title: string; value: string }) { return <div className="card"><h3>{title}</h3><div className="stat">{value}</div></div>; }
function Criteria({ criteria, definitions }: { criteria: Array<Record<string, unknown>>; definitions?: unknown }) { const definitionMap = new Map((Array.isArray(definitions) ? definitions : []).map((definition) => { const value = definition as Record<string, unknown>; return [String(value.id), value]; })); return criteria.length ? <ul className="rubric-list">{criteria.map((criterion, index) => { const definition = definitionMap.get(String(criterion.criterion_id)); return <li key={String(criterion.criterion_id || index)}><strong>{String(criterion.criterion_id || "criterion")}</strong>: {String(criterion.score ?? "—")} / {String(criterion.max_score ?? definition?.points ?? "—")} {definition?.description ? <span> — {String(definition.description)}</span> : null} {String(criterion.reason || "")} {criterion.evidence ? <small>Evidence: {format(criterion.evidence)}</small> : null}</li>; })}</ul> : <p className="muted">criterion結果なし</p>; }
function Rubric({ entry }: { entry: Record<string, unknown> | null | undefined }) { const criteria = Array.isArray(entry?.criteria) ? entry.criteria as Array<Record<string, unknown>> : []; return criteria.length ? <ul className="rubric-list">{criteria.map((criterion, index) => <li key={String(criterion.id || index)}><strong>{String(criterion.id || "criterion")}</strong> ({String(criterion.points || "—")}点) {String(criterion.description || "")}</li>)}</ul> : <p className="muted">基準なし</p>; }
function format(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value, null, 2) || "—"; }
