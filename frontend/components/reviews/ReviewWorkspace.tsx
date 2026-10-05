"use client";
import Link from "next/link";
import { NextActionPanel } from "@/components/NextActionPanel";
import { testWorkflowHref } from "@/lib/testWorkflowNavigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiRequestError } from "@/lib/api/client";
import { reviews, type ImportPlan, type Confirmation } from "@/lib/api/reviews";
import type { Decision, ReviewDocument, ReviewNode, ReviewSnapshot, RevisionInfo } from "@/types/reviews";
import { reviewIssueLabel, reviewSaveIssueLabel, reviewStateLabel, scoreSemanticsLabel } from "@/lib/reviewLabels";
import { buildQuestionPath, reviewFieldErrors, reviewFieldId, validateReviewFields, type FieldIssues, type ReviewFieldError } from "@/lib/reviewValidation";
import { PdfPreview } from "./PdfPreview";
import { NodeEditor } from "./NodeEditor";
import { EvidencePanel } from "./EvidencePanel";
import { WarningPanel } from "./WarningPanel";
import { MarkdownMathText } from "@/components/MarkdownMathText";
import { clearTextSourceMapping, mapCandidateToSources, suggestSubquestions, type SplitProposal } from "@/lib/questionSplit";
import { questionReviewIssues } from "@/lib/questionReviewIssues";
import { focusReviewIssue, type ReviewIssueTarget } from "@/lib/reviewIssues";
import { ReviewIssueList } from "./ReviewIssueList";
import { questionTextBuffer, bufferChanged, reconcileQuestionText, type QuestionTextBuffer } from "@/lib/questionEditing";
import type { LatexProposal } from "@/lib/api/textTools";
import { collectScoreGuidance, isDetailedScoreGuidanceCode, scoreDifference, scoreDisplay, uncoveredScoreWarnings } from "@/lib/importPlanGuidance";

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
  const [textBuffers, setTextBuffers] = useState<Record<string, QuestionTextBuffer>>({});
  const [selected, setSelected] = useState("");
  const [regionId, setRegionId] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [showIssues, setShowIssues] = useState(false);
  const [blockingIssueType, setBlockingIssueType] = useState("");
  const [internalError, setInternalError] = useState<{ path: string; code: string } | null>(null);
  const [fieldIssues, setFieldIssues] = useState<FieldIssues>({});
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<RevisionInfo[]>([]);
  const [historical, setHistorical] = useState(false);
  const [plan, setPlan] = useState<ImportPlan>();
  const [confirmation, setConfirmation] = useState<Confirmation | null>();
  const [splitProposal, setSplitProposal] = useState<SplitProposal | null>(null);
  const [splitMessage, setSplitMessage] = useState("");
  const [pendingUnmappedOverride, setPendingUnmappedOverride] = useState<number | null>(null);
  const snapshotChanged = useMemo(() => !!data && !!snapshot && JSON.stringify(snapshot) !== JSON.stringify(data.snapshot), [data, snapshot]);
  const dirty = snapshotChanged || Object.values(textBuffers).some(bufferChanged);
  const install = useCallback((d: ReviewDocument) => { setData(d); setSnapshot(structuredClone(d.snapshot));
    setTextBuffers(Object.fromEntries(d.snapshot.nodes.map(n => [n.stable_key, questionTextBuffer(n, d.regions)])));
    setSelected(prev => {
    const desired = prev || sessionStorage.getItem(`question-review-selection:${id}`);
    return d.snapshot.nodes.some(node => node.stable_key === desired) ? desired! : d.snapshot.nodes[0]?.stable_key || "";
  }); }, [id]);
  const load = useCallback(async (revision?: number) => {
    setBusy(true); setError(""); setFieldIssues({}); setInternalError(null); setBlockingIssueType("");
    try {
      const [saved, confirmation, history] = await Promise.all([reviews.get(id, revision), reviews.confirmation(id), reviews.history(id)]);
      install(saved); setPlan(undefined); setSplitProposal(null); setPendingUnmappedOverride(null);
      setConfirmation(confirmation); setHistorical(!!revision); setHistory(history.revisions);
    }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }, [id, install]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {if(selected) sessionStorage.setItem(`question-review-selection:${id}`, selected);}, [id, selected]);
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
      if (candidate.source_review_owner) return candidate.source_review_owner;
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
      ? { ...previous, [next.stable_key]: validateReviewFields(current.nodes.map(n => n.stable_key === next.stable_key ? next : n))[next.stable_key] || {} }
      : previous);
    setError("");
    setSnapshot({ ...current, nodes: current.nodes.map(n => n.review_node_id === next.review_node_id ? next : n) });
  }
  function changeContent(text: string, proposal?: LatexProposal) {
    setTextBuffers(previous => {
      const old = previous[node.stable_key] || questionTextBuffer(node, document.regions);
      return {...previous, [node.stable_key]: {...old, text,
        ocrEdits: proposal?.apply_provenance ? [...old.ocrEdits, proposal.apply_provenance].slice(-16) : old.ocrEdits}};
    });
    setSplitProposal(null); setPendingUnmappedOverride(null);
  }
  function reconciled(target: ReviewNode): ReviewNode | null {
    const next = reconcileQuestionText(target, document.regions, textBuffers[target.stable_key]);
    if (!next) {
      setSelected(target.stable_key);
      setFieldIssues({[target.stable_key]: {content: ["元資料との対応を確認できません。図の位置や数式の対応を保って編集してください。未保存の本文は保持されています。"]}});
    }
    return next;
  }
  function confirmContent(confirm: (target: ReviewNode) => ReviewNode) {
    const next = reconciled(node);
    if (!next) return;
    const confirmed = confirm(next);
    updateNode(confirmed);
    setTextBuffers(previous => ({...previous, [node.stable_key]: questionTextBuffer(confirmed, document.regions)}));
  }
  function jumpToField(issue: ReviewFieldError) {
    navigateIssue({id: `${issue.nodeKey}:${issue.fieldKey}`, domain: "question", questionKey: issue.nodeKey,
      path: issue.path, issueType: issue.fieldKey, message: issue.message,
      targetId: issue.fieldKey.startsWith("text:") || issue.fieldKey.startsWith("formula:")
        ? reviewFieldId(issue.nodeKey, "content") : issue.targetId});
  }
  function navigateIssue(issue: ReviewIssueTarget) {
    const target = current.nodes.find(candidate => candidate.stable_key === issue.questionKey);
    if (target) chooseNode(target);
    if (issue.itemId) chooseRegion(issue.itemId);
    focusReviewIssue(issue);
  }

  function chooseNode(n: ReviewNode) {
    setSelected(n.stable_key); setRegionId(""); setSplitProposal(null); setSplitMessage(""); setPendingUnmappedOverride(null);
    const key = sourceKey(n);
    const first = document.source_regions[n.stable_key]?.[0] || (key && document.source_regions[key]?.[0]);
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
    let saving = current;
    if (!mark) {
      const nodes: ReviewNode[] = [];
      for (const target of current.nodes) {
        const next = reconciled(target);
        if (!next) return;
        nodes.push(next);
      }
      saving = {...current, nodes};
      const found = validateReviewFields(nodes);
      if (Object.keys(found).length) {
        setFieldIssues(found);
        setError("");
        return;
      }
    }
    setBusy(true); setError(""); setBlockingIssueType("");
    try {
      const d = mark ? await reviews.reviewed(id, document.current_revision) : await reviews.save(id, saving, document.current_revision);
      install(d); setFieldIssues({}); setInternalError(null); setHistory((await reviews.history(id)).revisions);
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 422) {
        const blockingType = ({formula_review_required: "formula", figure_review_required: "figure", warning_review_required: "warning", warning_acknowledgement_required: "warning"} as Record<string, string>)[e.code || ""];
        if (blockingType) { setBlockingIssueType(blockingType); setFieldIssues({}); setShowIssues(true); return; }
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
  function resumeEditingAtQuestion(key: string) {
    const target = current.nodes.find(candidate => candidate.stable_key === key);
    if (!target) return;
    if (current.state === "reviewed") {
      if (!window.confirm("確認を解除して新しい修正版で編集を再開しますか？修正後は保存して、もう一度確認済みにする必要があります。")) return;
      setSnapshot({ ...current, state: "editing", reviewed: false });
    }
    setPlan(undefined);
    navigateIssue({id: `score:${key}`, domain: "question", questionKey: key,
      path: buildQuestionPath(key, current.nodes), issueType: "score", message: "配点を確認",
      targetId: reviewFieldId(key, "score_method")});
  }

  function add(child: boolean) {
    const key = newReviewKey();
    const n: ReviewNode = { review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
      parent_key: child ? node.stable_key : null, node_type: child ? "subquestion" : "major_question", depth: child ? node.depth + 1 : 0,
      sort_order: 0, label: { raw: "追加問題", normalized: "追加問題" }, body_text: "", ordered_content: [{ type: "text", order: 0, text: "" }],
      included: true, score_semantics: "unset", score_points: null, review_flags: [], formula_decisions: {}, figure_decisions: {}, warning_states: {} };
    let nodes = ordered(current.nodes).map(x => x.node);
    if (child && !nodes.some(entry => entry.included && entry.parent_key === node.stable_key) &&
        node.score_semantics === "unset" && node.score_points === null) {
      nodes = nodes.map(entry => entry.stable_key === node.stable_key
        ? { ...entry, score_semantics: "sum_children", score_points: null } : entry);
    }
    setSnapshot({ ...current, nodes: renumber([...nodes, n]) }); setSelected(key); setRegionId("");
  }
  function reparent(key: string | null) {
    let nodes = ordered(current.nodes).map(x => x.node);
    const oldParentKey = node.parent_key;
    const newParentHadChildren = key !== null && nodes.some(entry => entry.included && entry.parent_key === key && entry.stable_key !== node.stable_key);
    const oldParentHasOnlyMovingChild = oldParentKey !== null && nodes.filter(candidate =>
      candidate.included && candidate.parent_key === oldParentKey).length === 1;
    nodes = nodes.map(entry => {
      if (entry.stable_key === node.stable_key) {
        return { ...entry, parent_key: key, node_type: key ? "subquestion" : "major_question" };
      }
      if (key && entry.stable_key === key && !newParentHadChildren &&
          entry.score_semantics === "unset" && entry.score_points === null) {
        return { ...entry, score_semantics: "sum_children", score_points: null };
      }
      if (oldParentKey && entry.stable_key === oldParentKey &&
          oldParentHasOnlyMovingChild &&
          entry.score_semantics === "sum_children") {
        return { ...entry, score_semantics: "unset", score_points: null };
      }
      return entry;
    });
    setSnapshot({ ...current, nodes: renumber(nodes) });
  }
  function move(direction: number) {
    const siblings = current.nodes.filter(n => n.parent_key === node.parent_key).sort((a, b) => a.sort_order - b.sort_order);
    const at = siblings.findIndex(n => n.stable_key === node.stable_key), other = siblings[at + direction];
    if (!other) return;
    setSnapshot({ ...current, nodes: current.nodes.map(n => n.stable_key === node.stable_key ? { ...n, sort_order: other.sort_order } : n.stable_key === other.stable_key ? { ...n, sort_order: node.sort_order } : n) });
  }
  function startSplit() {
    const next = reconciled(node);
    if (!next) return;
    updateNode(next);
    setTextBuffers(previous => ({...previous, [node.stable_key]: questionTextBuffer(next, document.regions)}));
    setPendingUnmappedOverride(null);
    const sourceStableKey = sourceKey(node);
    const sourceNode = document.automatic_nodes.find(entry => entry.stable_key === sourceStableKey);
    const proposal = suggestSubquestions(next, sourceNode);
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
  function chooseSplitSource(index: number, sourceId: string, checked: boolean) {
    if (!splitProposal) return;
    const children = splitProposal.children.map((child, at) => at === index ? {
      ...child,
      selectedSourceIds: checked
        ? [...new Set([...child.selectedSourceIds, sourceId])]
        : child.selectedSourceIds.filter(value => value !== sourceId),
    } : child);
    setSplitProposal({ ...splitProposal, children });
  }
  function applyManualMapping(index: number) {
    if (!splitProposal) return;
    const candidate = splitProposal.children[index];
    const items = mapCandidateToSources(candidate.items, candidate.selectedSourceIds, splitProposal.sourceOptions);
    if (!items) return;
    const children = splitProposal.children.map((child, at) => at === index ? {
      ...child, items, mappingStatus: "manual_mapped" as const, included: true,
      mappingMessage: "選択した元読み取り項目との対応を保存します。",
    } : child);
    setSplitProposal({ ...splitProposal, children, canApply: true });
  }
  function confirmUnmappedOverride(index: number) {
    if (!splitProposal) return;
    const children = splitProposal.children.map((child, at) => at === index ? {
      ...child, items: clearTextSourceMapping(child.items), mappingStatus: "unmapped_override" as const,
      included: true, selectedSourceIds: [],
      mappingMessage: "元資料との詳細な対応情報を持たない小問として作成します。",
    } : child);
    setSplitProposal({ ...splitProposal, children, canApply: true });
    setPendingUnmappedOverride(null);
  }
  function applySplit() {
    if (!splitProposal) return;
    const chosen = splitProposal.children.filter(child => child.included);
    const eligible = new Set(["automatic", "manual_mapped", "unmapped_override"]);
    if (!chosen.length || chosen.some(child => !eligible.has(child.mappingStatus) || !child.contentValid || !child.label.trim())) return;
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
      const childItems = child.mappingStatus === "unmapped_override" ? clearTextSourceMapping(child.items) : child.items;
      const formulas = assigned(childItems, "formula"), figures = assigned(childItems, "figure");
      formulas.forEach(value => movedFormula.add(value)); figures.forEach(value => movedFigure.add(value));
      return { review_node_id: key, stable_key: key, source_draft_stable_key: null, source_draft_node_id: null,
        parent_key: node.stable_key, node_type: "subquestion", depth: node.depth + 1, sort_order: index,
        label: { raw: child.label, normalized: child.label }, body_text: childItems.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
        ordered_content: copy(childItems), included: true, score_semantics: "unset", score_points: null,
        review_flags: [], formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => formulas.has(key))),
        figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => figures.has(key))),
        source_mapping_decision: child.mappingStatus === "automatic" ? "automatic"
          : child.mappingStatus === "manual_mapped" ? "teacher_manual_mapping" : "teacher_unmapped_override",
        warning_states: {} };
    });
    const parentItems = copy(retained);
    const updated: ReviewNode = { ...node, ordered_content: parentItems,
      body_text: parentItems.map(item => item.type === "text" && "text" in item ? String(item.text) : "").filter(Boolean).join("\n"),
      score_semantics: node.score_semantics === "each_child" ? "each_child" : "sum_children",
      score_points: node.score_semantics === "each_child" ? node.score_points : null,
      formula_decisions: Object.fromEntries(Object.entries(node.formula_decisions).filter(([key]) => !movedFormula.has(key))),
      figure_decisions: Object.fromEntries(Object.entries(node.figure_decisions).filter(([key]) => !movedFigure.has(key))) };
    const parentHasTextMapping = parentItems.some(item => item.type === "text" && (
      Object.keys(item).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
      "source_slice" in item || Array.isArray(item.merged_source_segments) &&
      item.merged_source_segments.some(segment => segment.type !== "formula_region" &&
        Object.keys(segment).some(key => !["type", "order", "text", "merged_source_segments"].includes(key)) ||
        segment.type !== "formula_region" && "source_slice" in segment)));
    if (!parentHasTextMapping) delete updated.source_mapping_decision;
    setSnapshot({ ...current, nodes: renumber([...ordered(current.nodes).map(entry => entry.node).map(entry =>
      entry.stable_key === node.stable_key ? updated : entry), ...children]) });
    setTextBuffers(previous => ({...previous, [updated.stable_key]: questionTextBuffer(updated, document.regions),
      ...Object.fromEntries(children.map(child => [child.stable_key, questionTextBuffer(child, document.regions)]))}));
    setSplitProposal(null); setSplitMessage(""); setPendingUnmappedOverride(null); setSelected(children[0].stable_key);
  }
  const counts = document.summary;
  const activeSourceOwners = new Set(current.nodes.filter(entry => entry.included).map(entry => sourceKey(entry)).filter(Boolean));
  const formulaRegions = document.regions.filter(entry => entry.region_type === "formula" && entry.assigned_question_key &&
    activeSourceOwners.has(entry.assigned_question_key));
  const reviewIssues = questionReviewIssues(document, current, sourceKey, regionOwner);
  const formulaUnreviewed = reviewIssues.filter(issue => issue.issueType === "formula").length;
  const formulaReviewed = formulaRegions.length - formulaUnreviewed;
  const blockingIssues = reviewIssues.filter(issue => issue.issueType === blockingIssueType);
  const saveErrors = reviewFieldErrors(current.nodes, fieldIssues);
  const activeSourceKey = sourceKey(node);
  const activeRegions = document.regions.filter(r => r.assigned_question_key === activeSourceKey &&
    (node.ordered_content.some(item => "region_id" in item && item.region_id === r.region_id) ||
      !!node.formula_decisions[r.region_id] || !!node.figure_decisions[r.region_id]));
  const planCodes = [...(plan?.blockers || []), ...(plan?.warnings || [])];
  const scoreGuidance = collectScoreGuidance(planCodes, current.nodes);
  const blockerScoreGuidance = scoreGuidance.filter(issue => issue.codes.some(code => plan?.blockers.includes(code)));
  const warningScoreGuidance = scoreGuidance.filter(issue => issue.codes.some(code => plan?.warnings.includes(code)));
  const independentWarningScoreGuidance = uncoveredScoreWarnings(blockerScoreGuidance, warningScoreGuidance);
  const detailedScoreCodes = new Set(planCodes.filter(isDetailedScoreGuidanceCode));
  const generalBlockers = (plan?.blockers || []).filter(code => !detailedScoreCodes.has(code));
  const generalWarnings = (plan?.warnings || []).filter(code => !detailedScoreCodes.has(code));
  const blockerCount = generalBlockers.length + blockerScoreGuidance.length;
  const warningCount = generalWarnings.length + independentWarningScoreGuidance.length;
  function warningTarget(warning: typeof document.warnings[number]) {
    const issue = reviewIssues.find(issue => issue.id === warning.id);
    if (issue) return issue.path;
    const relevant = document.regions.find(region => region.region_id === warning.source_id);
    const target = relevant && regionOwner(relevant.region_id) || current.nodes.find(candidate =>
      candidate.stable_key === warning.owner || sourceKey(candidate) === warning.owner);
    return target ? buildQuestionPath(target.stable_key, current.nodes) : "試験全体";
  }
  function jumpToWarning(warning: typeof document.warnings[number]) {
    const issue = reviewIssues.find(issue => issue.id === warning.id);
    if (issue) navigateIssue(issue);
  }
  return <div className="teacher-review">
    <Link href={testWorkflowHref(document.test_id, "questions")}>← 試験の問題画面に戻る</Link>
    <header className="review-toolbar"><h1>教師による確認</h1><span className="badge badge-draft">{reviewStateLabel(current.state)}</span><span>修正版 {document.revision_number}</span>{dirty && <strong className="warn">未保存の変更</strong>}</header>
    {confirmation?.state === "completed" && confirmation.test_id === document.test_id && <NextActionPanel
      description="問題の登録が完了しました。次は解答・採点基準を確認・登録してください。"
      label="解答・採点基準へ進む" href={testWorkflowHref(document.test_id, "answers")} />}
    <p className="muted">元の問題用紙と自動解析結果を比較し、設問構造や内容を確認・修正します。ここでの確認は、設問の最終確定とは別の操作です。</p>
    <div className="review-summary" aria-label="確認状況">
      <span>設問 {counts.included_questions} / 除外 {counts.excluded_questions}</span><button type="button" onClick={() => setShowIssues(value => !value)}>警告 未確認 {reviewIssues.filter(issue => issue.issueType === "warning").length} · 未確認を表示</button>
      {formulaUnreviewed > 0
        ? <button type="button" onClick={() => setShowIssues(value => !value)}>数式 確認済み {formulaReviewed} / {formulaRegions.length} · 未確認 {formulaUnreviewed} · 未確認を表示</button>
        : <span>数式 確認済み {formulaReviewed} / {formulaRegions.length} · 未確認 0</span>}
      <button type="button" onClick={() => setShowIssues(value => !value)}>図 未確認 {reviewIssues.filter(issue => issue.issueType === "figure").length} · 未確認を表示</button>
      <button type="button" onClick={() => setShowIssues(value => !value)}>配点 未解決 {reviewIssues.filter(issue => issue.issueType === "score").length} · 合計点候補 {counts.total_points_candidate ?? "要確認"}</button>
      {dirty && <span>集計は保存済みの修正版の値です</span>}
    </div>
    {showIssues && <section className="panel" aria-label="未確認の設問一覧">
      <h2>確認が必要な設問</h2>
      {reviewIssues.length ? <ReviewIssueList issues={reviewIssues} onNavigate={navigateIssue} /> : <p>未確認の項目はありません。</p>}
    </section>}
    {blockingIssues.length > 0 && <section className="error" role="alert" aria-label="確認エラー">
      <strong>確認を完了できませんでした。未確認の項目が{blockingIssues.length}件あります。</strong>
      <ReviewIssueList issues={blockingIssues} onNavigate={navigateIssue} label="確認を妨げる項目" />
    </section>}
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
      {current.state === "reviewed" && !historical && !confirmation && <button className="button" disabled={busy} onClick={() => void prepareImport()}>問題登録前の最終確認へ</button>}
      {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <button className="button" disabled={busy || !!plan.blockers?.length} onClick={() => void confirmImport()}>確認した問題を登録</button>}
      {confirmation && <span className="badge badge-success">問題登録済み</span>}
      {busy && <span role="status">処理中…</span>}
    </div>
    {plan && !confirmation && current.state === "reviewed" && !dirty && !historical && <section className="panel final-question-check" aria-label="問題登録前の最終確認">
      <h2>問題登録前の最終確認</h2>
      <p>確認・編集した設問構成、配点、確認事項をチェックし、問題として確定する前の最終確認を行います。</p>
      <p>修正版 {plan.revision} · 設問 {plan.nodes?.length} · 構造用 {plan.structural_count} · 採点対象 {plan.gradable_count} · 数式 {plan.formula_count} · 図 {plan.figure_count} · 登録済みの問題 {plan.existing_question_count} · 合計点 {plan.total_points ?? "要確認"}</p>
      {plan.blockers?.length ? <div className="error" aria-label="問題登録前に修正が必要な項目">
        <strong>問題登録前に修正が必要な項目が {blockerCount} 件あります。</strong>
        {blockerScoreGuidance.map(issue => {
          const children = issue.children;
          const knownChildTotal = children.reduce((sum, child) => sum + (child.score_points ?? 0), 0);
          const unsetChildren = children.filter(child => child.score_points === null);
          const difference = scoreDifference(issue.node.score_points, knownChildTotal);
          return <article className="score-guidance" key={issue.id}>
            <h3>{issue.code === "parent_direct_score" ? "小問を持つ設問の配点" : issue.code === "score_conflict" ? "旧方式の配点" : "配点の確認"}: {buildQuestionPath(issue.node.stable_key, current.nodes)}</h3>
            {issue.code === "parent_direct_score" ? <>
              <p>設問自身の配点: {scoreDisplay(issue.node.score_points)}（配点方式: {scoreSemanticsLabel(issue.node.score_semantics)}）</p>
              <p>小問ごとの配点:</p>
              {children.length ? <ul>{children.map(child => <li key={child.stable_key}>{buildQuestionPath(child.stable_key, current.nodes)}: {scoreDisplay(child.score_points)}</li>)}</ul> : <p>小問が見つかりません。</p>}
              <p>入力済み小問の配点合計: {knownChildTotal}点 / 設問自身: {scoreDisplay(issue.node.score_points)}</p>
              {difference && <p>{difference}です。{unsetChildren.length > 0 && ` ${unsetChildren.map(child => buildQuestionPath(child.stable_key, current.nodes)).join("、")}の配点が未設定です。`}</p>}
              {!difference && unsetChildren.length > 0 && <p>合計には未設定の小問が含まれていません。{unsetChildren.map(child => buildQuestionPath(child.stable_key, current.nodes)).join("、")}の配点を確認してください。</p>}
              <p>小問がある設問では、設問自身と小問の点数を重ねて登録できません。「小問の個別配点の合計」に変更すると、小問の点数から合計を計算できます。</p>
            </> : issue.code === "score_conflict" ? <>
              <p>親設問: {buildQuestionPath(issue.node.stable_key, current.nodes)}（旧設定: 小問ごとに {scoreDisplay(issue.node.score_points)}）</p>
              <p>小問ごとの配点:</p>
              {children.length ? <ul>{children.map(child => {
                const mismatch = child.score_points !== null && issue.node.score_points !== null && child.score_points !== issue.node.score_points;
                return <li key={child.stable_key}>{buildQuestionPath(child.stable_key, current.nodes)}: {scoreDisplay(child.score_points)}{mismatch ? `（親の${scoreDisplay(issue.node.score_points)}と不一致）` : child.score_points === null ? `（親から${scoreDisplay(issue.node.score_points)}を適用）` : ""}</li>;
              })}</ul> : <p>{buildQuestionPath(issue.node.stable_key, current.nodes)}の配点が親設問の設定と一致しません。</p>}
              <p>この修正版には小問へ同じ点数を適用する旧設定があります。小問ごとに異なる点数を使う場合は「小問の個別配点の合計」へ変更してください。</p>
            </> : issue.code === "each_child_structural_child" ? <p>{buildQuestionPath(issue.node.stable_key, current.nodes)}には同じ点数を各小問に適用する旧設定があります。入れ子の設問には適用できないため、新しい配点方法へ変更してください。</p>
              : <p>{buildQuestionPath(issue.node.stable_key, current.nodes)}の配点方式または配点を見直してください。</p>}
            <button type="button" className="button secondary" onClick={() => resumeEditingAtQuestion(issue.node.stable_key)}>確認を解除して編集</button>
          </article>;
        })}
        {generalBlockers.length > 0 && <ul>{generalBlockers.map(code => <li key={code}>{reviewIssueLabel(code)}</li>)}</ul>}
        <details><summary>技術情報</summary>{plan.blockers.join(", ")}</details>
      </div> : <div className="notice">問題を登録できます。登録すると、この試験の問題として確定されます。</div>}
      {independentWarningScoreGuidance.filter(issue => issue.code === "score_unset" || issue.code === "score_method_unset").map(issue => <article className="score-guidance warn" key={issue.id}>
        <h3>{issue.code === "score_method_unset" ? "配点方法未設定" : "配点未設定"}: {buildQuestionPath(issue.node.stable_key, current.nodes)}</h3>
        <p>{issue.code === "score_method_unset" ? `${buildQuestionPath(issue.node.stable_key, current.nodes)}には小問があります。小問の配点合計を確定する場合は「小問の個別配点の合計」を選んでください。未設定のままでは試験全体の合計点は確定しません。` : `${buildQuestionPath(issue.node.stable_key, current.nodes)}の配点は未設定です。採点対象にする場合は配点を入力してください。`}</p>
        <button type="button" className="button secondary" onClick={() => resumeEditingAtQuestion(issue.node.stable_key)}>確認を解除して編集</button>
      </article>)}
      {warningCount > 0 && <div className="warn">確認事項が {warningCount} 件あります。{generalWarnings.length > 0 && <ul>{generalWarnings.map(code => <li key={code}>{reviewIssueLabel(code)}</li>)}</ul>}<details><summary>技術情報</summary>{generalWarnings.join(", ")}</details></div>}
    </section>}
    <div className="review-layout">
      <PdfPreview id={id} page={page} pages={document.page_count} revision={document.revision_number} selected={regionId || node.stable_key} onPage={setPage} />
      <div className="review-panel">
        <section className="panel review-question-selector"><label>対象設問<select aria-label="対象設問" value={node.stable_key} onChange={event => {
          const next = current.nodes.find(n => n.stable_key === event.target.value); if (next) chooseNode(next);
        }}>{ordered(current.nodes).map(({node: n}) => <option key={n.stable_key} value={n.stable_key}>
          {buildQuestionPath(n.stable_key, current.nodes)}{!n.included ? "（除外）" : ""}
        </option>)}</select></label>
          <div className="review-toolbar"><button disabled={readonly} onClick={() => add(false)}>大問を追加</button><button disabled={readonly} onClick={() => add(true)}>小問を追加</button></div>
        </section>
        <section className="panel" aria-label="小問への分割">
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
              <p className={child.mappingStatus === "automatic" && child.contentValid || child.mappingStatus === "manual_mapped"
                ? "ok" : child.mappingStatus === "unmapped_override" ? "notice" : "warn"} role="status">
                元資料との対応: {child.mappingStatus === "automatic" ? "自動確認済み"
                  : child.mappingStatus === "manual_mapped" ? "手動確認済み"
                    : child.mappingStatus === "unmapped_override" ? "対応情報なしで分割"
                      : "要対応"}
              </p>
              {child.mappingMessage && <p className="notice">{child.mappingMessage}</p>}
              {child.mappingStatus === "manual_required" && <fieldset className="review-source-mapping">
                <legend>元資料との対応を指定</legend>
                {splitProposal.sourceOptions.length ? <>
                  <p className="muted">この小問に含まれる元の読み取り項目を1つ以上選択してください。選んだ項目の出典情報だけを使用し、文字位置は推測しません。</p>
                  {splitProposal.sourceOptions.map(option => <label key={option.id} className="review-source-option">
                    <input type="checkbox" aria-label={`${child.label}の元読み取り項目 ${option.label} ${option.excerpt}`} checked={child.selectedSourceIds.includes(option.id)}
                      onChange={event => chooseSplitSource(index, option.id, event.target.checked)} />
                    <span><strong>{option.label}</strong><small>{option.excerpt}</small></span>
                  </label>)}
                  <button type="button" disabled={!child.selectedSourceIds.length || !child.contentValid}
                    onClick={() => applyManualMapping(index)}>選択した項目を対応付ける</button>
                </> : <p className="muted">対応付けに使える元の読み取り項目がありません。対応情報なしで分割するか、手動で小問を追加してください。</p>}
                <button type="button" className="button secondary" disabled={!child.contentValid}
                  onClick={() => setPendingUnmappedOverride(index)}>対応情報なしで分割</button>
                {pendingUnmappedOverride === index && <div role="dialog" aria-modal="true" aria-label="対応情報なしで分割する確認" className="review-confirm-dialog">
                  <p>この小問は元問題用紙との詳細な対応情報を持たずに作成されます。小問の構造と本文は保存されますが、元資料上の範囲を自動追跡できません。続行しますか？</p>
                  <button type="button" className="button" onClick={() => confirmUnmappedOverride(index)}>対応情報なしで分割</button>
                  <button type="button" onClick={() => setPendingUnmappedOverride(null)}>キャンセル</button>
                </div>}
              </fieldset>}
              <label><input type="checkbox" checked={child.included} disabled={child.mappingStatus === "manual_required" || !child.contentValid} onChange={event => setSplitProposal({
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
            {splitProposal.children.some(child => child.included && child.mappingStatus === "manual_required") &&
              <p className="warn">{splitProposal.children.filter(child => child.included && child.mappingStatus === "manual_required").map(child => `${child.label} の元資料との対応方法を選択してください。`).join(" ")}</p>}
            <div className="review-toolbar"><button className="button" type="button" disabled={!splitProposal.children.some(child => child.included && ["automatic", "manual_mapped", "unmapped_override"].includes(child.mappingStatus) && child.contentValid && !!child.label.trim()) || splitProposal.children.some(child => child.included && (child.mappingStatus === "manual_required" || !child.contentValid || !child.label.trim()))} onClick={applySplit}>この内容で分割</button><button type="button" onClick={() => { setSplitProposal(null); setPendingUnmappedOverride(null); }}>キャンセル</button></div>
          </div>}
        </section>
        <div className="review-toolbar">{[...new Set((document.source_regions[node.stable_key] || []).map(r => r.page_index))].map(p => <button key={p} onClick={() => { setPage(p); setRegionId(""); }}>元の問題用紙 {p + 1}ページ</button>)}</div>
        {node.source_mapping_decision === "teacher_unmapped_override" && <p className="notice" role="status">この小問は元資料との詳細な対応情報なしで作成されています。</p>}
        {node.source_mapping_decision === "teacher_manual_mapping" && <p className="notice" role="status">この小問の元資料との対応は教師が指定しました。</p>}
        <NodeEditor content={(textBuffers[node.stable_key] || questionTextBuffer(node, document.regions)).text}
          contentChanged={!!textBuffers[node.stable_key] && bufferChanged(textBuffers[node.stable_key])}
          onContentChange={changeContent} onConfirmContent={confirmContent} node={node} nodes={current.nodes} automatic={document.automatic_nodes.find(n => n.stable_key === activeSourceKey)} regions={activeRegions}
          mathContext={{reviewId: id, revision: document.current_revision, savedNode: document.snapshot.nodes.find(n => n.stable_key === node.stable_key)}}
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
