"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api/client";
import { reviews, type ImportPlan, type Confirmation } from "@/lib/api/reviews";
import type { Decision, ReviewDocument, ReviewNode, ReviewSnapshot, RevisionInfo } from "@/types/reviews";
import { questionTypeLabel, reviewIssueLabel, reviewSaveIssueLabel, reviewStateLabel } from "@/lib/reviewLabels";
import { buildQuestionPath, reviewFieldErrors, reviewFieldId, validateReviewFields, type FieldIssues, type ReviewFieldError } from "@/lib/reviewValidation";
import { PdfPreview } from "./PdfPreview";
import { NodeEditor } from "./NodeEditor";
import { EvidencePanel } from "./EvidencePanel";
import { WarningPanel } from "./WarningPanel";
import { MarkdownMathText } from "@/components/MarkdownMathText";
import { suggestSubquestions, type SplitProposal } from "@/lib/questionSplit";

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
    if (e.status === 422) return `保存できませんでした。${reviewSaveIssueLabel(e.code || "validation_error")}`;
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
  const [internalError, setInternalError] = useState<{ path: string; code: string } | null>(null);
  const [fieldIssues, setFieldIssues] = useState<FieldIssues>({});
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<RevisionInfo[]>([]);
  const [historical, setHistorical] = useState(false);
  const [plan, setPlan] = useState<ImportPlan>();
  const [confirmation, setConfirmation] = useState<Confirmation | null>();
  const [splitProposal, setSplitProposal] = useState<SplitProposal | null>(null);
  const [splitMessage, setSplitMessage] = useState("");
  const dirty = !!data && !!snapshot && JSON.stringify(snapshot) !== JSON.stringify(data.snapshot);
  const install = useCallback((d: ReviewDocument) => { setData(d); setSnapshot(structuredClone(d.snapshot)); setSelected(prev => prev || d.snapshot.nodes[0]?.stable_key || ""); }, []);
  const load = useCallback(async (revision?: number) => {
    setBusy(true); setError(""); setFieldIssues({}); setInternalError(null);
    try { install(await reviews.get(id, revision)); setPlan(undefined); setSplitProposal(null); setConfirmation(await reviews.confirmation(id)); setHistorical(!!revision); setHistory((await reviews.history(id)).revisions); }
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
  function sourceKey(target: ReviewNode): string | null {
    let candidate: ReviewNode | undefined = target;
    while (candidate) {
      if (candidate.source_draft_stable_key) return candidate.source_draft_stable_key;
      candidate = current.nodes.find(entry => entry.stable_key === candidate?.parent_key);
    }
    return null;
  }
  function regionOwner(key: string): ReviewNode | undefined {
    return current.nodes.find(entry => entry.ordered_content.some(item =>
      ("region_id" in item && item.region_id === key) ||
      (item.type === "text" && Array.isArray(item.merged_source_segments) && item.merged_source_segments.some(segment => segment.region_id === key)))) ||
      current.nodes.find(entry => entry.formula_decisions[key] || entry.figure_decisions[key]);
  }
  const owner = region && (regionOwner(region.region_id) || current.nodes.find(n => n.source_draft_stable_key === region.assigned_question_key));
  function updateNode(next: ReviewNode) {
    setFieldIssues(previous => previous[next.stable_key]
      ? { ...previous, [next.stable_key]: validateReviewFields([next])[next.stable_key] || {} }
      : previous);
    setError("");
    setSnapshot({ ...current, nodes: current.nodes.map(n => n.review_node_id === next.review_node_id ? next : n) });
  }
  function jumpToField(issue: ReviewFieldError) {
    setSelected(issue.nodeKey); setRegionId("");
    window.setTimeout(() => {
      const target = window.document.getElementById(issue.targetId);
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
      const focusable = target?.matches("input,textarea,select") ? target : target?.querySelector("input,textarea,select,button");
      (focusable as HTMLElement | null)?.focus({ preventScroll: true });
    }, 50);
  }
  function chooseNode(n: ReviewNode) {
    setSelected(n.stable_key); setRegionId(""); setSplitProposal(null); setSplitMessage("");
    const key = sourceKey(n);
    const first = key && document.source_regions[key]?.[0];
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
      const found = validateReviewFields(current.nodes);
      if (Object.keys(found).length) {
        setFieldIssues(found);
        setError("");
        return;
      }
    }
    setBusy(true); setError("");
    try {
      const d = mark ? await reviews.reviewed(id, document.current_revision) : await reviews.save(id, current, document.current_revision);
      install(d); setFieldIssues({}); setInternalError(null); setHistory((await reviews.history(id)).revisions);
    } catch (e) {
      if (!mark && e instanceof ApiRequestError && e.status === 422) {
        const details = e.details && typeof e.details === "object" ? e.details as Record<string, unknown> : {};
        if (details.category === "internal_consistency" || ["invalid_source_slice", "source_anchor_changed"].includes(e.code || "")) {
          const key = typeof details.node_key === "string" && current.nodes.some(n => n.stable_key === details.node_key)
            ? details.node_key : node.stable_key;
          setFieldIssues({});
          setInternalError({ path: buildQuestionPath(key, current.nodes), code: e.code || "internal_consistency_error" });
          setError("");
          return;
        }
        const key = typeof details.node_key === "string" && current.nodes.some(n => n.stable_key === details.node_key)
          ? details.node_key : node.stable_key;
        const field = typeof details.field_key === "string" ? details.field_key : "node";
        setFieldIssues({ [key]: { [field]: [reviewSaveIssueLabel(e.code || "validation_error")] } });
        setError("");
      } else setError(message(e));
    } finally { setBusy(false); }
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
  function startSplit() {
    if (current.nodes.some(candidate => candidate.parent_key === node.stable_key)) {
      setSplitMessage("既に小問があります。設問構成を確認し、必要なら手動で小問を追加してください。");
      return;
    }
    const sourceNode = document.automatic_nodes.find(entry => entry.stable_key === node.source_draft_stable_key);
    const proposal = suggestSubquestions(node, sourceNode);
    setSplitProposal(proposal);
    setSplitMessage(proposal ? "" : "小問候補を検出できませんでした。必要なら「小問を追加」を使用してください。");
  }
  function moveSplitFigure(item: ReviewNode["ordered_content"][number], owner: number | null) {
    if (!splitProposal) return;
    const placements = splitProposal.placements.map(place => place.item === item ? { ...place, owner } : place);
    const children = splitProposal.children.map(child => ({ ...child, items: [] as ReviewNode["ordered_content"] }));
    const parentItems: ReviewNode["ordered_content"] = [];
    for (const place of placements) {
      if (place.owner === null) parentItems.push(place.item);
      else children[place.owner].items.push(place.item);
    }
    setSplitProposal({ ...splitProposal, placements, children, parentItems });
  }
  function applySplit() {
    if (!splitProposal || !splitProposal.canApply) return;
    const chosen = splitProposal.children.filter(child => child.included);
    if (!chosen.length || chosen.some(child => child.mappingStatus !== "valid" || !child.contentValid || !child.label.trim())) return;
    const copy = (items: ReviewNode["ordered_content"]) => items.map((item, order) => ({ ...item, order }));
    const retained = splitProposal.placements.filter(place => place.owner === null ||
      !splitProposal.children[place.owner].included).map(place => place.item);
    const assigned = (items: ReviewNode["ordered_content"], kind: "formula" | "figure") => new Set(items.flatMap(item => {
      const type = `${kind}_region`;
      if (item.type === type && "region_id" in item && typeof item.region_id === "string") return [item.region_id];
      if (item.type === "text" && Array.isArray(item.merged_source_segments)) {
        return item.merged_source_segments.filter(segment => segment.type === type).map(segment => String(segment.region_id));
      }
      return [];
    }));
    const movedFormula = new Set<string>(), movedFigure = new Set<string>();
    const children = splitProposal.children.filter(child => child.included).map((child, index): ReviewNode => {
      const key = newReviewKey();
      const formulas = assigned(child.items, "formula"), figures = assigned(child.items, "figure");
      formulas.forEach(value => movedFormula.add(value)); figures.forEach(value => movedFigure.add(value));
      return { review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
        parent_key: node.stable_key, node_type: "subquestion", depth: node.depth + 1, sort_order: index,
        label: { raw: child.label, normalized: child.label }, body_text: child.items.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
        ordered_content: copy(child.items), included: true, score_semantics: "unset", score_points: null,
        review_flags: [], formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => formulas.has(key))),
        figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => figures.has(key))),
        warning_states: {} };
    });
    const parentItems = copy(retained);
    const updated: ReviewNode = { ...node, ordered_content: parentItems,
      body_text: parentItems.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
      score_semantics: node.score_semantics === "direct" ? "unset" : node.score_semantics,
      score_points: node.score_semantics === "direct" ? null : node.score_points,
      formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => !movedFormula.has(key))),
      figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => !movedFigure.has(key))) };
    setSnapshot({ ...current, nodes: renumber([...ordered(current.nodes).map(entry => entry.node).map(entry =>
      entry.stable_key === node.stable_key ? updated : entry), ...children]) });
    setSplitProposal(null); setSplitMessage(""); setSelected(children[0].stable_key);
  }
  const counts = document.summary;
  const saveErrors = reviewFieldErrors(current.nodes, fieldIssues);
  const activeSourceKey = sourceKey(node);
  const activeRegions = document.regions.filter(r => r.assigned_question_key === activeSourceKey &&
    (node.ordered_content.some(item => "region_id" in item && item.region_id === r.region_id) ||
      !!node.formula_decisions[r.region_id] || !!node.figure_decisions[r.region_id]));
  function warningTarget(warning: typeof document.warnings[number]) {
    const relevant = document.regions.find(r => r.region_id === warning.source_id);
    const target = relevant && regionOwner(relevant.region_id) || current.nodes.find(n => n.source_draft_stable_key === (relevant?.assigned_question_key || warning.owner || warning.source_id));
    if (relevant && target) {
      const kind = relevant.region_type === "formula" ? "formula_region" : "figure_region";
      const number = target.ordered_content.filter(item => item.type === kind).findIndex(item => "region_id" in item && item.region_id === relevant.region_id) + 1;
      if (!number && relevant.region_type === "formula") {
        const decision = target.formula_decisions[relevant.region_id]?.decision;
        if (decision === "merged_into_text") return `${target.label.raw}・問題文に結合した数式`;
        if (decision === "excluded") return `${target.label.raw}・問題内容から除外した数式`;
      }
      return `${target.label.raw}・${relevant.region_type === "formula" ? "数式" : "図"} ${Math.max(1, number)}`;
    }
    return target?.label.raw || (warning.scope === "draft" ? "試験全体" : "該当する設問");
  }
  function jumpToWarning(warning: typeof document.warnings[number]) {
    const relevant = document.regions.find(r => r.region_id === warning.source_id);
    const target = relevant && regionOwner(relevant.region_id) || current.nodes.find(n => n.source_draft_stable_key === (relevant?.assigned_question_key || warning.owner || warning.source_id));
    if (target) chooseNode(target);
    if (relevant) chooseRegion(relevant.region_id);
    window.setTimeout(() => {
      const mergedIndex = target?.ordered_content.findIndex(item => item.type === "text" &&
        Array.isArray(item.merged_source_segments) && item.merged_source_segments.some(
          segment => segment.type === "formula_region" && segment.region_id === relevant?.region_id));
      const element = (mergedIndex !== undefined && mergedIndex >= 0
        ? window.document.getElementById(reviewFieldId(target?.stable_key || "", `text:${mergedIndex}`)) : null)
        || (relevant && target ? window.document.getElementById(reviewFieldId(target.stable_key, `${relevant.region_type}:${relevant.region_id}`)) : null)
        || window.document.querySelector("[aria-label='選択問題エディタ']");
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
    {saveErrors.length > 0 && <section className="review-save-errors error" role="alert" aria-label="保存エラー">
      <strong>保存できませんでした。{saveErrors.length}件の項目を確認してください。</strong>
      <ol>{saveErrors.map((issue, index) => <li key={`${issue.nodeKey}-${issue.fieldKey}-${index}`}>
        <button type="button" onClick={() => jumpToField(issue)}>{issue.path} &gt; {issue.fieldLabel}</button>
        <span>{issue.message}</span>
      </li>)}</ol>
    </section>}
    {internalError && <section className="review-internal-error" role="alert" aria-label="内部データの整合性エラー">
      <strong>保存処理中に内部データの整合性エラーが発生しました。</strong>
      <p><b>対象:</b> {internalError.path} &gt; 元資料との対応情報</p>
      <p>元の問題用紙と、分割・結合した問題文の対応情報に不整合があります。入力欄を直接修正しても解消しない可能性があります。</p>
      <p>現在の未保存編集は保持されています。最新の内容を読み込むと、この編集は破棄されます。</p>
      <button type="button" disabled={busy} onClick={() => {
        if (!dirty || window.confirm("最新の内容を読み込むと、現在の未保存編集は失われます。読み込みますか？")) void load();
      }}>最新の内容を再読み込み</button>
      <details><summary>技術情報</summary>{internalError.code}</details>
    </section>}
    {current.state === "reviewed" && !historical && <p className="notice">確認済みのため編集操作は停止しています。内容を直す場合は「新しい修正版で編集を再開」を押してください。</p>}
    {historical && <p className="notice">過去の修正版は編集できません。最新版を再読み込みすると編集できます。</p>}
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
      <PdfPreview id={id} page={page} pages={document.page_count} selected={regionId || activeSourceKey || ""} onPage={setPage} />
      <div className="review-panel">
        <section className="panel"><h2>設問構成</h2><nav className="review-tree" aria-label="設問構成">
          {ordered(current.nodes).map(({ node: n, depth }) => <button key={n.review_node_id} data-source-key={n.source_draft_stable_key || undefined} aria-pressed={n.stable_key === node.stable_key}
            className={n.stable_key === node.stable_key ? "active" : ""} style={{ paddingLeft: `${12 + depth * 18}px` }} onClick={() => chooseNode(n)}>
            {n.label.raw} <small>{questionTypeLabel(n.node_type)} {!n.included && "（除外）"}</small></button>)}
        </nav><div className="review-toolbar"><button disabled={readonly} onClick={() => add(false)}>大問を追加</button><button disabled={readonly} onClick={() => add(true)}>小問を追加</button></div></section>
        {node.node_type === "major_question" && <section className="panel" aria-label="小問への分割">
          <button type="button" className="button secondary" disabled={readonly} onClick={startSplit}>小問に分割</button>
          {splitMessage && <p className="notice">{splitMessage}</p>}
          {splitProposal && <div className="review-split-preview">
            <h3>小問への分割候補</h3>
            <p className="muted">読み取り済みの番号と順序から作成した候補です。内容と所属を確認してから適用してください。配点は割り振りません。</p>
            <h4>大問に残す内容</h4>
            {splitProposal.parentItems.length ? splitProposal.parentItems.map((item, index) =>
              <div key={index} className="review-content-item">{item.type === "text" ? <MarkdownMathText source={String(item.text)} /> : item.type === "figure_region" ? "図" : item.type === "formula_region" ? "数式" : "その他の内容"}
                {item.type === "figure_region" && <label>図の所属<select aria-label="図の所属" value="parent" onChange={event => moveSplitFigure(item, event.target.value === "parent" ? null : Number(event.target.value))}>
                  <option value="parent">大問で共通利用する</option>{splitProposal.children.map((child, at) => <option key={at} value={at}>{child.label}</option>)}
                </select></label>}</div>) : <p className="muted">共通の導入文はありません。</p>}
            {splitProposal.children.map((child, index) => <section className="review-content-item" key={index}>
              <p className={child.mappingStatus === "valid" && child.contentValid ? "ok" : "warn"} role="status">
                元資料との対応: {child.mappingStatus === "valid" && child.contentValid ? "確認済み" : "要手動確認"}
              </p>
              {child.mappingMessage && <p className="notice">{child.mappingMessage}</p>}
              <label><input type="checkbox" checked={child.included} disabled={child.mappingStatus !== "valid" || !child.contentValid} onChange={event => setSplitProposal({
                ...splitProposal, children: splitProposal.children.map((entry, at) => at === index ? { ...entry, included: event.target.checked } : entry),
              })} /> この候補を小問にする</label>
              <label>小問名<input value={child.label} maxLength={200} onChange={event => setSplitProposal({
                ...splitProposal, children: splitProposal.children.map((entry, at) => at === index ? { ...entry, label: event.target.value } : entry),
              })} /></label>
              {child.items.map((item, at) => <div key={at}>{item.type === "text" ? <MarkdownMathText source={String(item.text)} /> : item.type === "formula_region" ? "数式" : item.type === "figure_region" ? <label>図の所属<select aria-label="図の所属" value={index} onChange={event => moveSplitFigure(item, event.target.value === "parent" ? null : Number(event.target.value))}>
                <option value="parent">大問で共通利用する</option>{splitProposal.children.map((candidate, candidateIndex) => <option key={candidateIndex} value={candidateIndex}>{candidate.label}</option>)}
              </select></label> : "配点の記載"}</div>)}
            </section>)}
            {splitProposal.notes.map(note => <p className="notice" key={note}>{note}</p>)}
            {node.score_semantics === "direct" && <p className="notice">現在の大問への直接配点は小問へ自動配分しません。分割後に配点を確認してください。</p>}
            <div className="review-toolbar"><button className="button" type="button" disabled={!splitProposal.canApply || !splitProposal.children.some(child => child.included) || splitProposal.children.some(child => child.included && (child.mappingStatus !== "valid" || !child.contentValid || !child.label.trim()))} onClick={applySplit}>この内容で分割</button><button type="button" onClick={() => setSplitProposal(null)}>キャンセル</button></div>
          </div>}
        </section>}
        <div className="review-toolbar">{[...new Set((document.source_regions[activeSourceKey || ""] || []).map(r => r.page_index))].map(p => <button key={p} onClick={() => { setPage(p); setRegionId(""); }}>元の問題用紙 {p + 1}ページ</button>)}</div>
        <NodeEditor node={node} nodes={current.nodes} automatic={document.automatic_nodes.find(n => n.stable_key === activeSourceKey)} regions={activeRegions}
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
