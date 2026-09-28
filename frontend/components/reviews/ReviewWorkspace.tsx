"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api/client";
import { reviews, type ImportPlan, type Confirmation } from "@/lib/api/reviews";
import type { Decision, ReviewDocument, ReviewNode, ReviewSnapshot, RevisionInfo } from "@/types/reviews";
import { questionTypeLabel, reviewIssueLabel, reviewStateLabel } from "@/lib/reviewLabels";
import { PdfPreview } from "./PdfPreview";
import { NodeEditor } from "./NodeEditor";
import { EvidencePanel } from "./EvidencePanel";
import { WarningPanel } from "./WarningPanel";

function renumber(nodes: ReviewNode[]) {
  const counts = new Map<string | null, number>();
  return nodes.map(n => { const order = counts.get(n.parent_key) || 0; counts.set(n.parent_key, order + 1); return { ...n, sort_order: order }; });
}
function newReviewKey() {
  if (globalThis.crypto.randomUUID) return `teacher-${globalThis.crypto.randomUUID()}`;
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `teacher-${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function ordered(nodes: ReviewNode[], parent: string | null = null, depth = 0): { node: ReviewNode; depth: number }[] {
  if (depth > nodes.length) return [];
  return nodes.filter(n => n.parent_key === parent).sort((a, b) => a.sort_order - b.sort_order)
    .flatMap(node => [{ node, depth }, ...ordered(nodes, node.stable_key, depth + 1)]);
}
function message(e: unknown) {
  if (e instanceof ApiRequestError && e.status === 409 && e.code === "revision_conflict") return "別の画面で新しい修正版が保存されています。未保存内容を控え、最新の内容を再読み込みしてください。";
  if (e instanceof ApiRequestError) {
    if (e.status === 422) return `保存できませんでした。${reviewIssueLabel(e.code || "validation_error")}。該当する設問の入力欄を確認してください。`;
    if (e.status === 403) return "この操作を行う権限がありません。";
    if (e.status === 404) return "確認内容が見つかりませんでした。";
    return "処理に失敗しました。再試行してください。";
  }
  return e instanceof Error ? e.message : "処理に失敗しました";
}

export function ReviewWorkspace({ id }: { id: string }) {
  const [data, setData] = useState<ReviewDocument>();
  const [snapshot, setSnapshot] = useState<ReviewSnapshot>();
  const [selected, setSelected] = useState("");
  const [regionId, setRegionId] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [fieldIssues, setFieldIssues] = useState<Record<string, Record<string, string[]>>>({});
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<RevisionInfo[]>([]);
  const [historical, setHistorical] = useState(false);
  const [plan, setPlan] = useState<ImportPlan>();
  const [confirmation, setConfirmation] = useState<Confirmation | null>();
  const dirty = !!data && !!snapshot && JSON.stringify(snapshot) !== JSON.stringify(data.snapshot);
  const install = useCallback((d: ReviewDocument) => { setData(d); setSnapshot(structuredClone(d.snapshot)); setSelected(prev => prev || d.snapshot.nodes[0]?.stable_key || ""); }, []);
  const load = useCallback(async (revision?: number) => {
    setBusy(true); setError(""); setFieldIssues({});
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
  if (!data || !snapshot) return <section className="panel">{error ? <p role="alert" className="error">{error}</p> : "確認内容を読み込み中…"}<button onClick={() => load()}>再読み込み</button></section>;
  const document = data, current = snapshot;
  const node = current.nodes.find(n => n.stable_key === selected) || current.nodes[0];
  const readonly = historical || busy || current.state === "reviewed";
  const region = document.regions.find(r => r.region_id === regionId);
  const owner = region && current.nodes.find(n => n.source_draft_stable_key === region.assigned_question_key);
  function updateNode(next: ReviewNode) { setFieldIssues(previous => ({ ...previous, [next.stable_key]: {} })); setSnapshot({ ...current, nodes: current.nodes.map(n => n.review_node_id === next.review_node_id ? next : n) }); }
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
    if (!mark) {
      const found: Record<string, Record<string, string[]>> = {};
      for (const candidate of current.nodes.filter(item => item.included)) {
        const fields: Record<string, string[]> = {};
        if (!candidate.label.raw.trim()) fields.label = ["設問番号・見出しを入力してください。"];
        candidate.ordered_content.forEach((item, index) => { if (item.type === "text" && typeof item.text === "string" && !item.text.trim()) fields[`text:${index}`] = ["問題文が空です。不要な項目は削除してください。"] });
        if (["direct", "each_child"].includes(candidate.score_semantics) && candidate.score_points === null) fields.score = ["配点を入力してください。"];
        for (const [key, value] of Object.entries(candidate.formula_decisions)) if (value.decision === "teacher_edit" && !value.teacher_transcription?.trim()) fields[`formula:${key}`] = ["修正した数式を入力してください。"];
        if (Object.keys(fields).length) found[candidate.stable_key] = fields;
      }
      if (Object.keys(found).length) {
        setFieldIssues(found);
        const first = current.nodes.find(candidate => found[candidate.stable_key]);
        if (first) { setSelected(first.stable_key); setRegionId(""); }
        setError(`保存前に確認が必要な入力欄が ${Object.values(found).reduce((sum, fields) => sum + Object.keys(fields).length, 0)} 件あります。${first?.label.raw || "設問"}の印が付いた項目を確認してください。`);
        return;
      }
    }
    setBusy(true); setError("");
    try {
      const d = mark ? await reviews.reviewed(id, document.current_revision) : await reviews.save(id, current, document.current_revision);
      install(d); setFieldIssues({}); setHistory((await reviews.history(id)).revisions);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function prepareImport() { setBusy(true); setError(""); try { setPlan(await reviews.importPlan(id)); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  async function confirmImport() { if (!plan || plan.blockers?.length) return; if (!window.confirm("確認済みの内容を、この試験の問題として追加しますか？")) return; setBusy(true); setError(""); try { setConfirmation(await reviews.confirm(id, { expected_revision: plan.revision, expected_revision_sha256: plan.revision_sha256, import_plan_sha256: plan.plan_sha256, mode: "append" })); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  function add(child: boolean) {
    const key = newReviewKey();
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
  function warningTarget(warning: typeof document.warnings[number]) {
    const relevant = document.regions.find(r => r.region_id === warning.source_id);
    const target = current.nodes.find(n => n.source_draft_stable_key === (relevant?.assigned_question_key || warning.owner || warning.source_id));
    if (relevant && target) {
      const kind = relevant.region_type === "formula" ? "formula_region" : "figure_region";
      const number = target.ordered_content.filter(item => item.type === kind).findIndex(item => "region_id" in item && item.region_id === relevant.region_id) + 1;
      return `${target.label.raw}・${relevant.region_type === "formula" ? "数式" : "図"} ${Math.max(1, number)}`;
    }
    return target?.label.raw || (warning.scope === "draft" ? "試験全体" : "該当する設問");
  }
  function jumpToWarning(warning: typeof document.warnings[number]) {
    const relevant = document.regions.find(r => r.region_id === warning.source_id);
    const target = current.nodes.find(n => n.source_draft_stable_key === (relevant?.assigned_question_key || warning.owner || warning.source_id));
    if (target) chooseNode(target);
    if (relevant) chooseRegion(relevant.region_id);
    window.setTimeout(() => {
      const element = relevant ? window.document.getElementById(`review-field-region-${relevant.region_id}`) : window.document.querySelector("[aria-label='選択問題エディタ']");
      element?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 50);
  }
  return <div className="teacher-review">
    <Link href={`/tests/${document.test_id}?section=questions`}>← 試験の問題画面に戻る</Link>
    <header className="review-toolbar"><h1>教師による確認</h1><span className="badge badge-draft">{reviewStateLabel(current.state)}</span><span>修正版 {document.revision_number}</span>{dirty && <strong className="warn">未保存の変更</strong>}</header>
    <p className="muted">元の問題用紙と自動解析結果を比較し、設問構造や内容を確認・修正します。ここでの確認は、設問の最終確定とは別の操作です。</p>
    <div className="review-summary" aria-label="確認状況">
      <span>設問 {counts.included_questions} / 除外 {counts.excluded_questions}</span><button type="button" onClick={() => { const first = document.warnings.find(w => (current.warning_states?.[w.id]?.state || "unreviewed") === "unreviewed"); if (first) jumpToWarning(first); }}>警告 未確認 {counts.unresolved_warnings} · 対象へ移動</button>
      <span>数式 確認済み {counts.formula_reviewed} / 未確認 {counts.formula_unreviewed}</span><span>図 確認済み {counts.figure_reviewed} / 未確認 {counts.figure_unreviewed}</span>
      <span>配点 未解決 {counts.score_unresolved} · 合計点候補 {counts.total_points_candidate ?? "要確認"}</span>
      {dirty && <span>集計は保存済みの修正版の値です</span>}
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="review-toolbar">
      <button className="button" disabled={readonly || !dirty} onClick={() => save()}>変更を保存</button>
      <button className="button secondary" disabled={readonly || dirty} onClick={() => save(true)}>確認済みにする</button>
      {!historical && current.state === "reviewed" && <button onClick={() => setSnapshot({ ...current, state: "editing", reviewed: false })}>新しい修正版で編集を再開</button>}
      <button disabled={busy} onClick={() => { if (!dirty || window.confirm("未保存内容を破棄して最新版を読み込みますか？")) void load(); }}>最新の内容を再読み込み</button>
      {current.state === "reviewed" && !historical && !confirmation && <button className="button" disabled={busy} onClick={() => void prepareImport()}>問題への取り込み内容を確認</button>}
      {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <button className="button" disabled={busy || !!plan.blockers?.length} onClick={() => void confirmImport()}>問題として追加</button>}
      {confirmation && <span className="badge badge-success">問題への取り込み済み</span>}
      {busy && <span role="status">処理中…</span>}
    </div>
    {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <section className="panel"><h2>問題への取り込み確認</h2><p>修正版 {plan.revision} · 設問 {plan.nodes?.length} · 構造用 {plan.structural_count} · 採点対象 {plan.gradable_count} · 数式 {plan.formula_count} · 図 {plan.figure_count} · 登録済みの問題 {plan.existing_question_count} · 合計点 {plan.total_points ?? "要確認"}</p>{plan.blockers?.length ? <div className="error">取り込み前に解決が必要な項目が {plan.blockers.length} 件あります。<ul>{plan.blockers.map(code => <li key={code}>{reviewIssueLabel(code)}</li>)}</ul><details><summary>技術情報</summary>{plan.blockers.join(", ")}</details></div> : <div className="notice">取り込み可能です。既存の問題に追加されます。</div>}{plan.warnings?.length > 0 && <div className="warn">確認事項が {plan.warnings.length} 件あります。<ul>{plan.warnings.map(code => <li key={code}>{reviewIssueLabel(code)}</li>)}</ul><details><summary>技術情報</summary>{plan.warnings.join(", ")}</details></div>}</section>}
    <div className="review-layout">
      <PdfPreview id={id} page={page} pages={document.page_count} selected={regionId || node.source_draft_stable_key || ""} onPage={setPage} />
      <div className="review-panel">
        <section className="panel"><h2>設問構成</h2><nav className="review-tree" aria-label="設問構成">
          {ordered(current.nodes).map(({ node: n, depth }) => <button key={n.review_node_id} data-source-key={n.source_draft_stable_key || undefined} aria-pressed={n.stable_key === node.stable_key}
            className={n.stable_key === node.stable_key ? "active" : ""} style={{ paddingLeft: `${12 + depth * 18}px` }} onClick={() => chooseNode(n)}>
            {n.label.raw} <small>{questionTypeLabel(n.node_type)} {!n.included && "（除外）"}</small></button>)}
        </nav><div className="review-toolbar"><button disabled={readonly} onClick={() => add(false)}>大問を追加</button><button disabled={readonly} onClick={() => add(true)}>小問を追加</button></div></section>
        <div className="review-toolbar">{[...new Set((document.source_regions[node.source_draft_stable_key || ""] || []).map(r => r.page_index))].map(p => <button key={p} onClick={() => { setPage(p); setRegionId(""); }}>元の問題用紙 {p + 1}ページ</button>)}</div>
        <NodeEditor node={node} nodes={current.nodes} automatic={document.automatic_nodes.find(n => n.stable_key === node.source_draft_stable_key)} regions={activeRegions}
          readonly={readonly} onChange={updateNode} onParent={reparent} onMove={move} onRegion={chooseRegion} activeRegionId={regionId} issues={fieldIssues[node.stable_key]}
          renderEvidence={key => region?.region_id === key && owner ? <EvidencePanel key={key} id={id} regionId={key} ownerLabel={owner.label.raw || "未割当"} readonly={readonly} onDecision={decision}
            decision={owner[region.region_type === "formula" ? "formula_decisions" : "figure_decisions"][key] || { decision: "unreviewed" }} /> : null} />
        <WarningPanel warnings={document.warnings} states={current.warning_states || {}} readonly={readonly}
          onChange={(key, resolution) => setSnapshot({ ...current, warning_states: { ...current.warning_states, [key]: resolution } })} targetLabel={warningTarget} onJump={jumpToWarning} />
      </div>
    </div>
    <section className="panel section"><h2>変更履歴</h2>{historical && <p className="notice">過去の修正版を読み取り専用で表示しています。</p>}
      <ul>{history.map(r => <li key={r.revision_number}><button disabled={busy} onClick={() => { if (!dirty || window.confirm("未保存内容を破棄して履歴を表示しますか？")) void load(r.revision_number); }}>修正版 {r.revision_number}</button> {r.created_at} · {reviewStateLabel(r.state)} <details><summary>変更の技術情報</summary>{r.change_metadata.changed_nodes?.join(", ") || "状態または警告の変更"}</details></li>)}</ul>
    </section>
    <details className="section"><summary>技術情報</summary><pre>{JSON.stringify({ draft: current.source_draft_sha256, pdf: document.source_pdf_sha256, ir: document.source_ir_sha256, revision: document.revision_sha256, vision_run: current.vision_pin.run_id }, null, 2)}</pre></details>
  </div>;
}
