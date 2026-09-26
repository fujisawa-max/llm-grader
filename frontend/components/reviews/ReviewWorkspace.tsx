"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api/client";
import { reviews, type ImportPlan, type Confirmation } from "@/lib/api/reviews";
import type { Decision, ReviewDocument, ReviewNode, ReviewSnapshot, RevisionInfo } from "@/types/reviews";
import { PdfPreview } from "./PdfPreview";
import { NodeEditor } from "./NodeEditor";
import { EvidencePanel } from "./EvidencePanel";
import { WarningPanel } from "./WarningPanel";

function renumber(nodes: ReviewNode[]) {
  const counts = new Map<string | null, number>();
  return nodes.map(n => { const order = counts.get(n.parent_key) || 0; counts.set(n.parent_key, order + 1); return { ...n, sort_order: order }; });
}
function ordered(nodes: ReviewNode[], parent: string | null = null, depth = 0): { node: ReviewNode; depth: number }[] {
  if (depth > nodes.length) return [];
  return nodes.filter(n => n.parent_key === parent).sort((a, b) => a.sort_order - b.sort_order)
    .flatMap(node => [{ node, depth }, ...ordered(nodes, node.stable_key, depth + 1)]);
}
function message(e: unknown) {
  if (e instanceof ApiRequestError && e.status === 409 && e.code === "revision_conflict") return "A newer revision exists. 別の画面で更新されています。未保存内容を控え、最新版を再読み込みしてください。";
  if (e instanceof ApiRequestError) return `${e.message} (${e.code || e.status})`;
  return e instanceof Error ? e.message : "処理に失敗しました";
}

export function ReviewWorkspace({ id }: { id: string }) {
  const [data, setData] = useState<ReviewDocument>();
  const [snapshot, setSnapshot] = useState<ReviewSnapshot>();
  const [selected, setSelected] = useState("");
  const [regionId, setRegionId] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<RevisionInfo[]>([]);
  const [historical, setHistorical] = useState(false);
  const [plan, setPlan] = useState<ImportPlan>();
  const [confirmation, setConfirmation] = useState<Confirmation | null>();
  const dirty = !!data && !!snapshot && JSON.stringify(snapshot) !== JSON.stringify(data.snapshot);
  const install = useCallback((d: ReviewDocument) => { setData(d); setSnapshot(structuredClone(d.snapshot)); setSelected(prev => prev || d.snapshot.nodes[0]?.stable_key || ""); }, []);
  const load = useCallback(async (revision?: number) => {
    setBusy(true); setError("");
    try { install(await reviews.get(id, revision)); setPlan(undefined); setConfirmation(await reviews.confirmation(id)); setHistorical(!!revision); setHistory((await reviews.history(id)).revisions); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }, [id, install]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const navigate = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest("a") && !window.confirm("未保存の変更があります。画面を移動しますか？")) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload); window.document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", unload); window.document.removeEventListener("click", navigate, true); };
  }, [dirty]);
  if (!data || !snapshot) return <section className="panel">{error ? <p role="alert" className="error">{error}</p> : "Reviewを読み込み中…"}<button onClick={() => load()}>再読み込み</button></section>;
  const document = data, current = snapshot;
  const node = current.nodes.find(n => n.stable_key === selected) || current.nodes[0];
  const readonly = historical || busy || current.state === "reviewed";
  const region = document.regions.find(r => r.region_id === regionId);
  const owner = region && current.nodes.find(n => n.source_draft_stable_key === region.assigned_question_key);
  function updateNode(next: ReviewNode) { setSnapshot({ ...current, nodes: current.nodes.map(n => n.review_node_id === next.review_node_id ? next : n) }); }
  function chooseNode(n: ReviewNode) {
    setSelected(n.stable_key); setRegionId("");
    const first = n.source_draft_stable_key && document.source_regions[n.source_draft_stable_key]?.[0];
    if (first) setPage(first.page_index);
  }
  function chooseRegion(key: string) {
    const r = document.regions.find(r => r.region_id === key);
    if (r) { setRegionId(key); setPage(r.page_index); }
  }
  function decision(d: Decision) {
    if (!region || !owner) return;
    const field = region.region_type === "formula" ? "formula_decisions" : "figure_decisions";
    updateNode({ ...owner, [field]: { ...owner[field], [regionId]: d } });
  }
  async function save(mark = false) {
    setBusy(true); setError("");
    try {
      const d = mark ? await reviews.reviewed(id, document.current_revision) : await reviews.save(id, current, document.current_revision);
      install(d); setHistory((await reviews.history(id)).revisions);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function prepareImport() { setBusy(true); setError(""); try { setPlan(await reviews.importPlan(id)); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  async function confirmImport() { if (!plan || plan.blockers?.length) return; if (!window.confirm("このreviewed RevisionをTestQuestionへappend importしますか？")) return; setBusy(true); setError(""); try { setConfirmation(await reviews.confirm(id, { expected_revision: plan.revision, expected_revision_sha256: plan.revision_sha256, import_plan_sha256: plan.plan_sha256, mode: "append" })); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  function add(child: boolean) {
    const key = `teacher-${crypto.randomUUID()}`;
    const n: ReviewNode = { review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
      parent_key: child ? node.stable_key : null, node_type: child ? "subquestion" : "major_question", depth: child ? node.depth + 1 : 0,
      sort_order: 0, label: { raw: "追加問題", normalized: "追加問題" }, body_text: "", ordered_content: [{ type: "text", order: 0, text: "" }],
      included: true, score_semantics: "unset", score_points: null, review_flags: [], formula_decisions: {}, figure_decisions: {}, warning_states: {} };
    setSnapshot({ ...current, nodes: renumber([...ordered(current.nodes).map(x => x.node), n]) }); setSelected(key); setRegionId("");
  }
  function reparent(key: string | null) {
    setSnapshot({ ...current, nodes: renumber(ordered(current.nodes).map(x => x.node).map(n => n.stable_key === node.stable_key ? { ...n, parent_key: key, node_type: key ? "subquestion" : "major_question" } : n)) });
  }
  function move(direction: number) {
    const siblings = current.nodes.filter(n => n.parent_key === node.parent_key).sort((a, b) => a.sort_order - b.sort_order);
    const at = siblings.findIndex(n => n.stable_key === node.stable_key), other = siblings[at + direction];
    if (!other) return;
    setSnapshot({ ...current, nodes: current.nodes.map(n => n.stable_key === node.stable_key ? { ...n, sort_order: other.sort_order } : n.stable_key === other.stable_key ? { ...n, sort_order: node.sort_order } : n) });
  }
  const counts = document.summary;
  const activeRegions = document.regions.filter(r => r.assigned_question_key === node.source_draft_stable_key);
  return <div className="teacher-review">
    <Link href={`/tests/${document.test_id}?section=questions`}>← Test Workspace / Questions</Link>
    <header className="review-toolbar"><h1>Teacher Review</h1><span className="badge badge-draft">{current.state}</span><span>Revision {document.revision_number}</span>{dirty && <strong className="warn">未保存の変更</strong>}</header>
    <p className="muted">原PDF・Native・Visionを比較して教師の判断を保存します。ReviewedはTestQuestionへの確定ではありません。</p>
    <div className="review-summary" aria-label="Review summary">
      <span>Questions {counts.included_questions} / excluded {counts.excluded_questions}</span><span>Warnings 未確認 {counts.unresolved_warnings}</span>
      <span>Formula 確認 {counts.formula_reviewed} / 未確認 {counts.formula_unreviewed}</span><span>Figure 確認 {counts.figure_reviewed} / 未確認 {counts.figure_unreviewed}</span>
      <span>Score unresolved {counts.score_unresolved} · Total candidate {counts.total_points_candidate ?? "unresolved"}</span>
      {dirty && <span>集計は保存済みRevisionの値です</span>}
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="review-toolbar">
      <button className="button" disabled={readonly || !dirty} onClick={() => save()}>Revisionを保存</button>
      <button className="button secondary" disabled={readonly || dirty} onClick={() => save(true)}>Mark Reviewed</button>
      {!historical && current.state === "reviewed" && <button onClick={() => setSnapshot({ ...current, state: "editing", reviewed: false })}>新Revisionで編集を再開</button>}
      <button disabled={busy} onClick={() => { if (!dirty || window.confirm("未保存内容を破棄して最新版を読み込みますか？")) void load(); }}>最新版を再読み込み</button>
      {current.state === "reviewed" && !historical && !confirmation && <button className="button" disabled={busy} onClick={() => void prepareImport()}>Prepare Import</button>}
      {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <button className="button" disabled={busy || !!plan.blockers?.length} onClick={() => void confirmImport()}>Confirm &amp; Import</button>}
      {confirmation && <span className="badge badge-success">Imported {confirmation.id}</span>}
      {busy && <span role="status">処理中…</span>}
    </div>
    {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <section className="panel"><h2>Import preflight</h2><p>Revision {plan.revision} · nodes {plan.nodes?.length} · Structural {plan.structural_count} · Gradable {plan.gradable_count} · Formula {plan.formula_count} · Figure {plan.figure_count} · existing questions {plan.existing_question_count} · total {plan.total_points ?? "unresolved"}</p>{plan.blockers?.length ? <div className="error">Blockers: {plan.blockers.join(", ")}</div> : <div className="notice">No blockers. Mode: append</div>}{plan.warnings?.length > 0 && <p className="warn">Warnings: {plan.warnings.join(", ")}</p>}</section>}
    <div className="review-layout">
      <PdfPreview id={id} page={page} pages={document.page_count} selected={regionId || node.source_draft_stable_key || ""} onPage={setPage} />
      <div className="review-panel">
        <section className="panel"><h2>Question tree</h2><nav className="review-tree" aria-label="Question tree">
          {ordered(current.nodes).map(({ node: n, depth }) => <button key={n.review_node_id} aria-pressed={n.stable_key === node.stable_key}
            className={n.stable_key === node.stable_key ? "active" : ""} style={{ paddingLeft: `${12 + depth * 18}px` }} onClick={() => chooseNode(n)}>
            {n.label.raw} <small>{n.source_draft_stable_key || "Teacher-created"} {!n.included && "(Excluded)"}</small></button>)}
        </nav><div className="review-toolbar"><button disabled={readonly} onClick={() => add(false)}>Major questionを追加</button><button disabled={readonly} onClick={() => add(true)}>Subquestionを追加</button></div></section>
        <div className="review-toolbar">{[...new Set((document.source_regions[node.source_draft_stable_key || ""] || []).map(r => r.page_index))].map(p => <button key={p} onClick={() => { setPage(p); setRegionId(""); }}>Source page {p + 1}</button>)}</div>
        <NodeEditor node={node} nodes={current.nodes} automatic={document.automatic_nodes.find(n => n.stable_key === node.source_draft_stable_key)} regions={activeRegions}
          readonly={readonly} onChange={updateNode} onParent={reparent} onMove={move} onRegion={chooseRegion} />
        {region && <EvidencePanel key={regionId} id={id} regionId={regionId} readonly={readonly || !owner} onDecision={decision}
          decision={owner?.[region.region_type === "formula" ? "formula_decisions" : "figure_decisions"][regionId] || { decision: "unreviewed" }} />}
        <WarningPanel warnings={document.warnings} states={current.warning_states || {}} readonly={readonly}
          onChange={(key, resolution) => setSnapshot({ ...current, warning_states: { ...current.warning_states, [key]: resolution } })} />
      </div>
    </div>
    <section className="panel section"><h2>Revision history</h2>{historical && <p className="notice">過去Revisionを読み取り専用で表示しています。</p>}
      <ul>{history.map(r => <li key={r.revision_number}><button disabled={busy} onClick={() => { if (!dirty || window.confirm("未保存内容を破棄して履歴を表示しますか？")) void load(r.revision_number); }}>Revision {r.revision_number}</button> {r.created_at} · {r.state} · changed: {r.change_metadata.changed_nodes?.join(", ") || "state / warnings"}</li>)}</ul>
    </section>
    <details className="section"><summary>Source hashes / review provenance</summary><pre>{JSON.stringify({ draft: current.source_draft_sha256, pdf: document.source_pdf_sha256, ir: document.source_ir_sha256, revision: document.revision_sha256, vision_run: current.vision_pin.run_id }, null, 2)}</pre></details>
  </div>;
}
