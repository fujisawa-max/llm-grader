"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { grading, type GradingDetail, type ReviewQueue } from "@/lib/api/grading";
import { TeacherActionForm } from "@/components/TeacherActionForm";
import { TechnicalDetails, friendlyStatus, friendlyWarning } from "@/components/ui";
import { MathText } from "@/components/MathText";

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
  if (!data) return <AppShell><div className="loading">採点結果の確認画面を読み込んでいます…</div></AppShell>;
  return <AppShell>
    <div className="breadcrumbs"><Link href={`/tests/${testId}/grading`}>採点結果</Link><span className="sep">/</span>採点結果の確認</div>
    <div className="page-header"><div><h1>採点結果の確認</h1><p className="muted">J/Kまたは↑/↓で移動、Enterで詳細、Aで教師確定、Rで再採点依頼。</p></div><Link className="button secondary" href={`/tests/${testId}/grading/regrade-queue`}>再採点依頼</Link></div>
    <section className="cards grading-summary"><Summary title="確認済み" value={`${data.progress.reviewed} / ${data.progress.total}`} /><Summary title="未確認" value={String(data.progress.remaining)} /><Summary title="警告" value={String(data.progress.warnings)} /><Summary title="再採点待ち" value={String(data.progress.regrade_pending)} /><Summary title="教師確定" value={String(data.progress.teacher_adjudicated)} /></section>
    <div className="review-toolbar"><label>絞り込み <select value={filter} onChange={(event) => { setFilter(event.target.value); setIndex(0); }}>{filters.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><span className="muted">{data.items.length} 件</span></div>
    <section className="review-workspace-grid">
      <div className="panel review-target-list"><h2>確認対象</h2>{data.items.length === 0 ? <p className="empty">対象はありません。</p> : data.items.map((row, rowIndex) => <button className={`review-target ${rowIndex === index ? "selected" : ""}`} key={row.target} onClick={() => setIndex(rowIndex)}><strong>{row.student_display_label || "学生情報未確認"} / {row.question_label}</strong><span>{row.score == null ? "—" : `${row.score} / ${row.max_score}`}</span><small>{row.flags?.length ? row.flags.map((flag: string) => friendlyWarning(flag)).join(" · ") : friendlyStatus(row.status || "REVIEW_REQUIRED")}</small></button>)}</div>
      {selected && detailItem ? <ReviewDetail row={selected} item={detailItem} testId={testId} onChanged={refresh} /> : <div className="panel review-empty">左の対象を選択してください。</div>}
    </section>
  </AppShell>;
}

function ReviewDetail({ row, item, testId, onChanged }: { row: Record<string, any>; item: GradingDetail["questions"][number]; testId: string; onChanged: () => void }) {
  const visual = item.visual_assets.filter((asset) => asset.role === "student_visual_answer");
  const [zoom, setZoom] = useState(1);
  return <div className="panel review-detail" id="review-detail"><div className="review-detail-header"><h2>{row.student_display_label || "学生情報未確認"} — {row.question_label}</h2><span className="badge">{row.score == null ? "結果なし" : `${row.score} / ${row.max_score}`}</span></div><div className="side-by-side">
    <section className="review-pane"><h3>学生答案</h3><div className="zoom-controls"><button aria-label="zoom-out" className="button secondary" onClick={() => setZoom((value) => Math.max(.5, value - .25))}>−</button><span>{Math.round(zoom * 100)}%</span><button aria-label="zoom-in" className="button secondary" onClick={() => setZoom((value) => Math.min(3, value + .25))}>＋</button></div>{(item.student_answer.page_ids || []).map((pageId) => <img style={{ width: `${zoom * 100}%` }} className="evidence-asset-image" key={pageId} src={`/api/v1/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(item.student_answer.submission_id || "")}/answer-artifacts/${encodeURIComponent(pageId)}`} alt="学生答案の原画像" />)}<pre className="answer-text">{item.student_answer.answer_text || "（本文なし）"}</pre>{item.student_answer.reconstruction && <TechnicalDetails label="読み取りの技術情報"><p>Version {String(item.student_answer.reconstruction.version)} / {String(item.student_answer.reconstruction.artifact_ref || "artifact")}</p></TechnicalDetails>}{visual.map((asset) => <div className="asset-row" key={String(asset.asset_id)}><strong>学生の図答案</strong><TechnicalDetails label="画像の技術情報"><span>SHA {String(asset.sha256 || "—")} · BBox {JSON.stringify(asset.bbox || "—")}</span></TechnicalDetails><img style={{ width: `${zoom * 100}%` }} className="evidence-asset-image" src={`/api/v1/tests/${encodeURIComponent(testId)}/submissions/${encodeURIComponent(item.student_answer.submission_id || "")}/questions/${encodeURIComponent(item.question.id)}/visual-assets/${encodeURIComponent(String(asset.asset_id))}`} alt="学生の図答案" /></div>)}</section>
    <section className="review-pane"><h3>読み取り内容と採点基準</h3><pre className="answer-text">{item.student_answer.answer_text || "（本文なし）"}</pre><Criteria criteria={item.criteria} definitions={item.rubric?.entry?.criteria} /><div id="teacher-actions"><TeacherActionForm item={item} testId={testId} onDone={onChanged} /></div></section>
    <section className="review-pane"><h3>問題・模範解答・採点結果</h3><h4>問題</h4><MathText source={item.question.context?.effective_text || item.question.text || "—"} /><h4>模範解答</h4><MathText className="answer-text" source={item.model_answer?.content || "—"} />{item.visual_assets.length > 0 && <><TechnicalDetails label="画像資料の技術情報"><ul className="rubric-list">{item.visual_assets.map((asset) => <li key={`${String(asset.role)}-${String(asset.asset_id)}`}><strong>{String(asset.role)}</strong> — SHA {String(asset.sha256 || "—")}</li>)}</ul></TechnicalDetails></>}<h4>承認済みの採点基準</h4><Rubric entry={item.rubric?.entry} /><h4>採点コメント</h4><pre className="answer-text">{format(item.feedback)}</pre>{item.warnings.length > 0 && <div className="flag-list">{item.warnings.map((warning) => <TechnicalDetails label={friendlyWarning(warning)} key={warning}><code>{warning}</code></TechnicalDetails>)}</div>}</section>
  </div></div>;
}

function Summary({ title, value }: { title: string; value: string }) { return <div className="card"><h3>{title}</h3><div className="stat">{value}</div></div>; }
function Criteria({ criteria, definitions }: { criteria: Array<Record<string, unknown>>; definitions?: unknown }) { const definitionMap = new Map((Array.isArray(definitions) ? definitions : []).map((definition) => { const value = definition as Record<string, unknown>; return [String(value.id), value]; })); return criteria.length ? <ul className="rubric-list">{criteria.map((criterion, index) => { const definition = definitionMap.get(String(criterion.criterion_id)); return <li key={String(criterion.criterion_id || index)}><MathText source={String(definition?.description || `採点基準 ${index + 1}`)} />: {String(criterion.score ?? "—")} / {String(criterion.max_score ?? definition?.points ?? "—")} {String(criterion.reason || "")} {criterion.evidence ? <small>根拠: {format(criterion.evidence)}</small> : null}</li>; })}</ul> : <p className="muted">採点基準別の結果はありません</p>; }
function Rubric({ entry }: { entry: Record<string, unknown> | null | undefined }) { const criteria = Array.isArray(entry?.criteria) ? entry.criteria as Array<Record<string, unknown>> : []; return criteria.length ? <ul className="rubric-list">{criteria.map((criterion, index) => <li key={String(criterion.id || index)}><MathText source={String(criterion.description || `採点基準 ${index + 1}`)} /> ({String(criterion.points || "—")}点)</li>)}</ul> : <p className="muted">基準なし</p>; }
function format(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value, null, 2) || "—"; }
