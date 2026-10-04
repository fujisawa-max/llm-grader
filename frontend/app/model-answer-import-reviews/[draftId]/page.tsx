"use client";
import { LatexNormalizationControl } from "@/components/LatexNormalizationControl";

import Link from "next/link";
import { reviewCandidateId } from "@/lib/reviewCandidateId";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Breadcrumbs, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { MathPreview, mathInputHelp } from "@/components/MathText";
import { SourcePdfPreview } from "@/components/SourcePdfPreview";
import { MarkdownMathText } from "@/components/MarkdownMathText";
import { ModelAnswerQuestionSelector } from "@/components/ModelAnswerQuestionSelector";
import { questionBreadcrumb } from "@/lib/modelAnswerQuestionNavigation";
import {
  modelAnswerImports,
  type ModelAnswerClassifiedSegment,
  type ModelAnswerContentCategory,
  type ModelAnswerDraftEntry,
  type ModelAnswerImportDraft,
  type RubricConsolidatedGroup,
  type RubricSplitProposal,
} from "@/lib/api/modelAnswerImports";
import { testData, tests } from "@/lib/api/domain";
import type { Material, Test } from "@/types/domain";
import { buildReviewTargets, dispositionOf, resolveReviewTarget } from "@/lib/modelAnswerReviewTargets";
import { isEffectivelyBlank, isModelAnswerRegistrationEntry, validateModelAnswerRegistration } from "@/lib/modelAnswerRegistrationValidation";

const categoryLabels: Record<ModelAnswerContentCategory, string> = {
  question: "問題文",
  model_answer: "模範解答候補",
  alternative_answer: "別解・別の正答例",
  rubric: "採点基準候補",
  note: "補足・その他",
  uncertain: "要確認",
};

const categoryOrder: ModelAnswerContentCategory[] = [
  "question", "model_answer", "alternative_answer", "rubric", "note", "uncertain",
];

function pointHint(text: string): { description: string; points: number } {
  const prefix = text.match(/^\s*(\d+(?:\.\d+)?)\s*(?:点|points?)\s*[:：-]\s*/i);
  if (prefix) return { description: text.slice(prefix[0].length).trim(), points: Number(prefix[1]) };
  const match = text.match(/[（(]\s*(\d+(?:\.\d+)?)\s*(?:点|points?)\s*[）)]\s*$|\s+(\d+(?:\.\d+)?)\s*(?:点|points?)\s*$/i);
  const points = Number(match?.[1] || match?.[2] || 0);
  return { description: match ? text.slice(0, match.index).trim() : text.trim(), points };
}

function groupsFor(segments: ModelAnswerClassifiedSegment[], category: ModelAnswerContentCategory) {
  const groups: ModelAnswerClassifiedSegment[][] = [];
  for (const segment of segments) {
    if (segment.category !== category) continue;
    const previous = groups.at(-1)?.at(-1);
    if (!previous || previous.end !== segment.start) groups.push([segment]);
    else groups.at(-1)!.push(segment);
  }
  return groups.map((items, index) => ({
    label: category === "model_answer" ? `模範解答候補 ${index + 1}`
      : category === "alternative_answer" ? `別解 ${index + 1}` : categoryLabels[category],
    text: items.map((item) => item.text).join(""),
    segmentIds: items.map((item) => item.id),
  }));
}

type RubricEdit = NonNullable<ModelAnswerDraftEntry["rubric_edits"]>[number];
function rubricRows(entry: ModelAnswerDraftEntry): RubricEdit[] {
  const saved = entry.rubric_edits;
  if (saved !== undefined) return saved;
  const segments = entry.semantic_classification?.segments || [];
  const segmentsById = new Map((entry.semantic_classification?.segments || []).map((segment) => [segment.id, segment]));
  const groups = entry.semantic_classification?.rubric_groups?.filter((group) => group.kind === "rubric"
    && group.segment_ids.every((id) => segmentsById.get(id)?.category === "rubric")) || [];
  if (groups.length) return groups.map((group: RubricConsolidatedGroup) => ({
    id: group.id, source_text: group.source_text, segment_ids: group.segment_ids, description: group.description, points: group.points,
    confidence: group.confidence, points_conflict: group.points_conflict, points_confirmed: false,
    grouping_confirmed: !group.needs_teacher_review,
    grouping_method: group.merge_type,
  }));
  return segments.filter((segment) => segment.category === "rubric").map((segment) => ({
    id: segment.id, source_text: segment.source_text || segment.text, segment_ids: [segment.id], ...pointHint(segment.text), grouping_confirmed: true,
    grouping_method: "legacy",
  }));
}

function joinRubricDescriptions(items: string[]) {
  return items.reduce((result, item) => {
    if (!result) return item.trim();
    const left = result.trimEnd(); const right = item.trimStart();
    if (!left || !right) return left + right;
    if (/^[、。，．！？!?：；:;）)】』」]/.test(right) || /[（(「『【]$/.test(left)) return left + right;
    if (/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]$/u.test(left)
        && /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u.test(right)) return left + right;
    return `${left} ${right}`;
  }, "");
}

export default function ModelAnswerImportReviewPage() {
  const draftId = String(useParams().draftId);
  const router = useRouter();
  const [draft, setDraft] = useState<ModelAnswerImportDraft | null>(null);
  const [savedDraft, setSavedDraft] = useState<ModelAnswerImportDraft | null>(null);
  const [test, setTest] = useState<Test | null>(null);
  const [material, setMaterial] = useState<Material | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const splitCursors = useRef<Record<string, number>>({});
  const [splittingCandidateId, setSplittingCandidateId] = useState<string | null>(null);
  const splitting = splittingCandidateId !== null;
  const [activeRubricId, setActiveRubricId] = useState<string | null>(null);
  const rubricTextareas = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const [rubricFeedback, setRubricFeedback] = useState<Record<string, {kind: "error" | "success"; text: string}>>({});
  const [splitPreview, setSplitPreview] = useState<{entryId: string; sourceRevision: number; questionId: string | null; item: RubricEdit; text: string; proposal: RubricSplitProposal; method: "llm" | "manual"} | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [rubricRegistering, setRubricRegistering] = useState(false);
  const [selectedRubricGroups, setSelectedRubricGroups] = useState<Record<string, string[]>>({});

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const current = await modelAnswerImports.get(draftId);
        const [testRow, materials] = await Promise.all([
          tests.get(current.test_id), testData.materials(current.test_id),
        ]);
        if (!active) return;
        setDraft(current); setSavedDraft(current);
        setTest(testRow);
        setMaterial(materials.find((item) => item.id === current.material_id) || null);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "模範解答を読み込めませんでした");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [draftId]);

  useEffect(() => {
    if (!activeRubricId) return;
    const frame = requestAnimationFrame(() => {
      const control = rubricTextareas.current[activeRubricId];
      if (control && !control.disabled) {
        control.focus({preventScroll: true});
        control.scrollIntoView({block: "nearest", behavior: "smooth"});
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [activeRubricId]);

  useEffect(() => {
    if (!splitPreview) return;
    const frame = requestAnimationFrame(() => document.getElementById(`rubric-proposal-${splitPreview.item.id}`)?.scrollIntoView({block: "nearest", behavior: "smooth"}));
    return () => cancelAnimationFrame(frame);
  }, [splitPreview]);

  const questionLabels = useMemo(() => new Map((draft?.questions || []).map((item) => [item.id, questionBreadcrumb(item, draft?.questions || [])])), [draft]);
  if (loading) return <LoadingState />;
  if (error && (!draft || !test)) return <ErrorState message={error} />;
  if (!draft || !test) return <ErrorState message="模範解答の確認内容が見つかりません" />;
  const targets = buildReviewTargets(draft);
  const targetLabels = new Map(targets.map((target) => [target.id,
    target.kind === "question" && target.questionId ? questionLabels.get(target.questionId) || target.label : target.label]));
  const selectedTarget = resolveReviewTarget(targets, selectedTargetId);
  const selectedQuestionId = selectedTarget?.kind === "question" ? selectedTarget.questionId : null;
  const selectedQuestion = draft.questions.find((question) => question.id === selectedQuestionId);
  const visibleEntries = draft.entries.filter((entry) => dispositionOf(entry) !== "ignored" && (selectedTarget?.kind === "question"
    ? entry.question_id === selectedQuestionId && dispositionOf(entry) !== "unassigned"
    : selectedTarget?.entryId === entry.id));
  const selectedSavedAnswer = savedDraft?.saved_answers?.find((answer) => answer.question_id === selectedQuestionId);
  const pdfEntry = visibleEntries.find((entry) => entry.source.segments.length > 0);
  const pdfSegment = pdfEntry?.source.segments.find((segment) => segment.bbox) || pdfEntry?.source.segments[0];
  const pdfLocation = pdfSegment ? { id: `${selectedTarget?.id}:${pdfSegment.id || pdfSegment.page_index}`,
    page: pdfSegment.page_index + 1, bbox: pdfSegment.bbox || undefined } : undefined;

  function updateEntry(entryId: string, patch: Partial<ModelAnswerDraftEntry>) {
    setDraft((current) => current ? {
      ...current,
      entries: current.entries.map((entry) => entry.id === entryId ? { ...entry, ...patch } : entry),
    } : current);
    setNotice("");
  }

  function addManualEntry(questionId: string, answerText = "", loadedAnswerId?: string) {
    setDraft((current) => {
      if (!current) return current;
      const hasPrimary = current.entries.some((entry) => entry.question_id === questionId &&
        (entry.disposition || "include") === "include" && (entry.answer_kind || "primary") === "primary");
      return { ...current, entries: [...current.entries, {
        id: reviewCandidateId("teacher-entry"),
        question_id: questionId,
        mapping_state: "manual_mapped",
        disposition: "include",
        answer_kind: hasPrimary ? "alternative" : "primary",
        answer_text: answerText,
        ...(loadedAnswerId ? { loaded_model_answer: { id: loadedAnswerId, version: current.saved_answers?.find((answer) => answer.id === loadedAnswerId)?.version || 1, question_id: questionId } } : {}),
        source: { kind: "teacher_manual", material_id: null, source_sha256: null, segments: [] },
      }] };
    });
    setNotice("手入力の模範解答候補を追加しました。本文を入力して保存してください。");
    setSelectedTargetId(`question:${questionId}`);
  }

  function loadSavedAnswer(questionId: string) {
    const saved = draft?.saved_answers?.find((answer) => answer.question_id === questionId);
    if (!saved?.answer_text) return;
    if (!window.confirm("登録済み模範解答を今回の編集欄へ読み込みます。現在編集中の本文を置き換える場合があります。続行しますか？")) return;
    const primary = draft?.entries.find((entry) => entry.question_id === questionId &&
      dispositionOf(entry) === "include" && (entry.answer_kind || "primary") === "primary" &&
      !draft.confirmed_entry_ids?.includes(entry.id));
    if (primary) updateEntry(primary.id, { answer_text: saved.answer_text, loaded_model_answer: {
      id: saved.id, version: saved.version, question_id: questionId } });
    else addManualEntry(questionId, saved.answer_text, saved.id);
    setNotice(`登録済み模範解答 v${saved.version} を編集欄へ読み込みました。今回のPDF出典情報は保持されています。`);
  }

  const entryPayload = (entries: ModelAnswerDraftEntry[]) => entries.map((entry) => ({
    id: entry.id,
    question_id: entry.question_id,
    answer_text: entry.answer_text,
    disposition: entry.disposition || (entry.question_id ? "include" : "unassigned"),
    answer_kind: entry.answer_kind || "primary",
    loaded_model_answer_id: entry.loaded_model_answer?.id || null,
    ...(entry.teacher_correction?.latex_normalization ? {latex_normalization: entry.teacher_correction.latex_normalization as Record<string, unknown>} : {}),
    ...(entry.rubric_edits ? { rubric_edits: entry.rubric_edits } : {}),
    ...(entry.rubric_merge_history ? { rubric_merge_history: entry.rubric_merge_history } : {}),
    ...(entry.semantic_classification ? {
      classification_segments: entry.semantic_classification.segments.map(({ id, category, text }) => ({ id, category, text })),
      classification_reviewed: entry.semantic_classification.status === "teacher_reviewed",
      ...(entry.semantic_classification.manual_alternative_answers !== undefined
        ? { manual_alternative_answers: entry.semantic_classification.manual_alternative_answers } : {}),
    } : {}),
  }));

  function updateRubricEdit(entry: ModelAnswerDraftEntry, id: string, patch: Partial<RubricEdit>) {
    const existing = rubricRows(entry);
    updateEntry(entry.id, { rubric_edits: existing.map((item) => item.id === id ? { ...item, ...patch } : item) });
  }

  function rubricMessage(candidateId: string, kind: "error" | "success", text: string) {
    setRubricFeedback(current => ({ ...current, [candidateId]: {kind, text} }));
  }

  function replaceRubricRows(entry: ModelAnswerDraftEntry, rows: RubricEdit[]) {
    setDraft(current => current ? { ...current, entries: current.entries.map(value => value.id === entry.id
      ? { ...value, rubric_edits: rows, rubric_merge_history: [...(value.rubric_merge_history || []), rubricRows(value)].slice(-50) }
      : value) } : current);
    setSelectedRubricGroups((current) => ({ ...current, [entry.id]: [] }));
  }

  function insertRubric(entry: ModelAnswerDraftEntry, item: RubricEdit, duplicate: boolean) {
    const rows = rubricRows(entry);
    const index = rows.findIndex(row => row.id === item.id);
    if (index < 0) { rubricMessage(item.id, "error", "採点基準を追加できませんでした。候補を選び直してください。"); return; }
    const id = reviewCandidateId("teacher-rubric");
    const created: RubricEdit = duplicate ? { ...item, id, grouping_confirmed: true,
      excluded: false, provenance: { ...item.provenance, manual_duplicate_from: item.id, teacher_confirmed: true, timestamp: new Date().toISOString() } }
      : { id, description: "", points: 0, segment_ids: [], grouping_method: "teacher_manual", grouping_confirmed: true,
        provenance: { source: "teacher_manual", manual_add: true, inserted_after: item.id, timestamp: new Date().toISOString() } };
    const next = [...rows]; next.splice(index + 1, 0, created);
    replaceRubricRows(entry, next); setSplitPreview(null); setActiveRubricId(id);
    rubricMessage(id, "success", duplicate ? "採点基準を複製しました。下書き保存で変更を保存できます。" : "採点基準を追加しました。本文と配点を入力してください。");
  }

  function manualSplit(entry: ModelAnswerDraftEntry, item: RubricEdit) {
    if (!draft) return;
    const text = item.description;
    const offset = splitCursors.current[item.id] ?? 0;
    const characters = Array.from(text);
    if (offset <= 0 || offset >= characters.length || !characters.slice(0, offset).join("").trim() || !characters.slice(offset).join("").trim()) {
      rubricMessage(item.id, "error", "本文欄の分割したい位置にカーソルを置いてください。先頭・末尾や空白だけの部分では分割できません。"); return;
    }
    const markPattern = /[（(【]\s*(\d+)\s*点\s*[）)】]|(\d+)\s*(?:点|points?)\s*[:：-]\s*|(\d+)\s*点/gi;
    const marks = [...text.matchAll(markPattern)];
    const ambiguousPoints = marks.length === 1;
    const parts = [{start: 0, end: offset}, {start: offset, end: characters.length}].map((range) => {
      const source_text = characters.slice(range.start, range.end).join("");
      const partMarks = [...source_text.matchAll(markPattern)];
      const description = source_text.replace(markPattern, "").trim();
      const points = partMarks.length === 1 && !ambiguousPoints ? Number(partMarks[0][1] || partMarks[0][2] || partMarks[0][3]) : 0;
      return { ...range, source_text, description, points, points_conflict: !points || partMarks.length > 1 };
    });
    rubricMessage(item.id, "success", "分割案を確認して適用してください。");
    setSplitPreview({ entryId: entry.id, sourceRevision: draft.revision, questionId: entry.question_id, item, text, method: "manual", proposal: {
      candidate_id: item.id, split: true, confidence: 1, reason: "semantic_boundary", source_sha256: "", parts } });
  }

  async function suggestSplit(entry: ModelAnswerDraftEntry, item: RubricEdit) {
    if (!draft) return;
    setSplittingCandidateId(item.id); setSplitPreview(null); setBusy(true); setError(""); setNotice("");
    rubricMessage(item.id, "success", "分割案を作成しています…");
    try {
      const prepared = draft.entries.map((value) => ({ ...value, rubric_edits: rubricRows(value) }));
      const updated = await modelAnswerImports.update(draft.id, { expected_revision: draft.revision, entries: entryPayload(prepared) });
      setDraft(updated); setSavedDraft(updated);
      const savedEntry = updated.entries.find(value => value.id === entry.id);
      const savedItem = savedEntry?.rubric_edits?.find(value => value.id === item.id);
      if (!savedEntry || !savedItem) throw new Error("分割する候補を保存できませんでした。候補を確認して再試行してください。");
      const proposal = await modelAnswerImports.suggestRubricSplit(updated.id, savedItem.id, updated.revision);
      if (!proposal.split) { rubricMessage(item.id, "success", "この候補は1つの採点観点として扱う提案です。分割は行いません。"); return; }
      setSplitPreview({entryId: savedEntry.id, sourceRevision: updated.revision, questionId: savedEntry.question_id,
        item: savedItem, text: savedItem.source_text ?? savedItem.description, proposal, method: "llm"});
      rubricMessage(item.id, "success", "分割案を確認して適用してください。");
    } catch (cause) { rubricMessage(item.id, "error", cause instanceof Error ? cause.message : "分割提案を取得できませんでした。手動分割をご利用ください。"); }
    finally { setSplittingCandidateId(null); setBusy(false); }
  }

  function applySplit() {
    if (!draft || !splitPreview) return;
    const {entryId, item, text, proposal, method} = splitPreview;
    const entry = draft.entries.find((value) => value.id === entryId);
    if (!entry) { setError("分割する候補が見つかりません。編集対象を選び直してください。"); setSplitPreview(null); return; }
    const rows = rubricRows(entry); const index = rows.findIndex((value) => value.id === item.id);
    if (index < 0 || draft.state !== "editing" || draft.revision !== splitPreview.sourceRevision || entry.question_id !== splitPreview.questionId
      || rows[index].description !== item.description || rows[index].points !== item.points
      || (rows[index].source_text ?? null) !== (item.source_text ?? null)) {
      rubricMessage(item.id, "error", "候補が変更されたため分割案を適用できませんでした。分割案を作り直してください。"); setSplitPreview(null); return;
    }
    const parts: RubricEdit[] = proposal.parts.map((part) => ({
      id: reviewCandidateId("split"), description: part.description, points: part.points,
      source_text: part.source_text, segment_ids: item.segment_ids || [],
      confidence: proposal.confidence, grouping_confirmed: true, grouping_method: `split_${method}`,
      points_conflict: part.points_conflict, points_confirmed: false,
      provenance: { split_from_candidate_id: item.id, split_method: method,
        original_text: text, start: part.start, end: part.end, original_points: item.points,
        original_points_conflict: item.points_conflict, source_sha256: proposal.source_sha256,
        previous_operation: item.provenance || {}, split_from_merged_candidate: item.grouping_method,
        teacher_confirmed: true, ...(item.segment_ids?.length ? {} : {source: "teacher_manual"}), timestamp: new Date().toISOString() },
    }));
    const next = [...rows]; next.splice(index, 1, ...parts); replaceRubricRows(entry, next); setSplitPreview(null);
    setActiveRubricId(parts[0].id); rubricMessage(parts[0].id, "success", `${parts.length}件に分割しました。下書き保存で変更を保存できます。`);
  }

  function mergeRubricGroups(entry: ModelAnswerDraftEntry, ids: string[], type: "manual_above" | "manual_multi") {
    const rows = rubricRows(entry);
    if (ids.length < 2) return;
    const chosen = rows.filter((row) => ids.includes(row.id));
    if (chosen.length !== ids.length) return;
    const history = [...(entry.rubric_merge_history || []), rows].slice(-50);
    const segments = entry.semantic_classification?.segments || [];
    const rank = new Map(segments.map((segment, index) => [segment.id, index]));
    const orderedIds = [...new Set(chosen.flatMap((row) => row.segment_ids || [row.id]))].sort((a, b) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0));
    const descriptions = chosen.map((row) => row.description);
    const pointValues = chosen.map((row) => row.points).filter((value) => value > 0);
    const distinctPoints = [...new Set(pointValues)];
    const merged: RubricEdit = {
      id: reviewCandidateId("merged"), segment_ids: orderedIds,
      description: joinRubricDescriptions(descriptions), source_text: joinRubricDescriptions(chosen.map((row) => row.source_text ?? row.description)),
      provenance: { ...(orderedIds.length ? {} : {source: "teacher_manual"}), merge_type: type, source_candidate_ids: chosen.map((row) => row.id), previous_operations: chosen.map((row) => row.provenance || {}), teacher_confirmed: true, timestamp: new Date().toISOString(),
        ...(chosen.every((row) => row.provenance?.split_from_candidate_id === chosen[0].provenance?.split_from_candidate_id) && chosen[0].provenance?.split_from_candidate_id
          ? { ...chosen[0].provenance, start: Math.min(...chosen.map((row) => Number(row.provenance?.start))), end: Math.max(...chosen.map((row) => Number(row.provenance?.end))) } : {}) },
      points: distinctPoints.length === 1 && pointValues.length === chosen.length ? distinctPoints[0] : 0,
      confidence: Math.min(...chosen.map((row) => row.confidence ?? 0)),
      points_conflict: chosen.some((row) => row.points_conflict) || distinctPoints.length > 1 || pointValues.length > 1,
      points_confirmed: false, grouping_confirmed: true, grouping_method: type,
    };
    const firstIndex = Math.min(...chosen.map((row) => rows.findIndex((rowItem) => rowItem.id === row.id)));
    const next = rows.filter((row) => !ids.includes(row.id));
    next.splice(firstIndex, 0, merged);
    updateEntry(entry.id, { rubric_edits: next, rubric_merge_history: history });
    setSelectedRubricGroups((current) => ({ ...current, [entry.id]: [] }));
  }

  function undoRubricMerge(entry: ModelAnswerDraftEntry) {
    const history = entry.rubric_merge_history || [];
    if (!history.length) return;
    setSplitPreview(null); setActiveRubricId(history[history.length - 1].find(item => !item.excluded)?.id || null);
    setRubricFeedback({}); setNotice("採点基準の編集操作を元に戻しました。");
    updateEntry(entry.id, { rubric_edits: history[history.length - 1], rubric_merge_history: history.slice(0, -1) });
  }

  async function registerRubric() {
    if (!draft) return;
    const preparedEntries = draft.entries.map((entry) => entry.rubric_edits === undefined && rubricRows(entry).length
      ? { ...entry, rubric_edits: rubricRows(entry) } : entry);
    const hasRubric = preparedEntries.some((entry) => entry.rubric_edits?.some((item) => !item.excluded));
    if (!hasRubric) { setError("登録する採点基準候補がありません。"); return; }
    setRubricRegistering(true); setError(""); setNotice("");
    try {
      const updated = await modelAnswerImports.update(draft.id, {
        expected_revision: draft.revision, entries: entryPayload(preparedEntries),
      });
      setDraft(updated); setSavedDraft(updated);
      const result = await modelAnswerImports.registerRubric(updated.id, updated.revision);
      setDraft(result.draft); setSavedDraft(result.draft);
      setNotice(`採点基準 v${result.rubric.version} を登録しました。現在の状態: ${result.rubric.status === "approved" ? "承認済み" : "未承認"}。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "採点基準を登録できませんでした");
    } finally { setRubricRegistering(false); }
  }

  function updateClassificationSegment(
    entryId: string,
    segmentId: string,
    patch: Partial<Pick<ModelAnswerClassifiedSegment, "category" | "text">>,
    acknowledge = false,
  ) {
    setDraft((current) => current ? {
      ...current,
      entries: current.entries.map((entry) => {
        if (entry.id !== entryId || !entry.semantic_classification) return entry;
        const segments = entry.semantic_classification.segments.map((segment) =>
          segment.id === segmentId ? { ...segment, ...patch } : segment);
        const hasUncertain = segments.some((segment) => segment.category === "uncertain");
        const status = hasUncertain ? "needs_teacher_review"
          : (acknowledge || entry.semantic_classification.status === "teacher_reviewed") ? "teacher_reviewed"
            : entry.semantic_classification.status;
        const rubricIds = new Set(segments.filter((segment) => segment.category === "rubric").map((segment) => segment.id));
        const rubricEdits = entry.rubric_edits?.filter((edit) =>
          (edit.segment_ids || [edit.id]).every((id) => rubricIds.has(id)));
        return { ...entry, ...(entry.rubric_edits ? { rubric_edits: rubricEdits } : {}),
          semantic_classification: { ...entry.semantic_classification, segments, status } };
      }),
    } : current);
    setNotice("");
  }

  function setEntryAnswerFromClassification(entry: ModelAnswerDraftEntry, text: string) {
    if (!text.trim()) {
      setError("模範解答本文が空です。分類を見直すか、本文を入力してください。");
      return;
    }
    updateEntry(entry.id, { answer_text: text });
    setNotice("分類した内容を模範解答本文へ反映しました。保存後に登録できます。");
  }

  function updateManualAlternatives(entry: ModelAnswerDraftEntry, alternatives: Array<{ id: string; text: string }>) {
    if (!entry.semantic_classification) return;
    updateEntry(entry.id, {
      semantic_classification: {
        ...entry.semantic_classification,
        manual_alternative_answers: alternatives,
      },
    });
  }

  function addManualAlternative(entry: ModelAnswerDraftEntry) {
    const current = entry.semantic_classification?.manual_alternative_answers || [];
    updateManualAlternatives(entry, [...current, { id: reviewCandidateId("teacher-alt"), text: "" }]);
  }

  async function save(): Promise<ModelAnswerImportDraft | null> {
    if (!draft) return null;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await modelAnswerImports.update(draft.id, {
        expected_revision: draft.revision,
        entries: entryPayload(draft.entries),
      });
      setDraft(updated); setSavedDraft(updated);
      setNotice("下書きを保存しました。正式な模範解答はまだ登録されていません。");
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "下書きを保存できませんでした");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function classify() {
    if (!draft) return;
    if (!window.confirm("元PDFの文章を再分類します。保存済みの教師編集は保持し、分類候補を更新しますか？")) return;
    setClassifying(true);
    setError("");
    setNotice("");
    try {
      const saved = await save();
      if (!saved) return;
      const classified = await modelAnswerImports.classify(saved.id, saved.revision);
      setDraft(classified); setSavedDraft(classified);
      const counts = classified.entries.reduce((result, entry) => {
        const classification = entry.semantic_classification;
        if (!classification || classification.status === "fallback") result.fallback += 1;
        else result.classified += 1;
        return result;
      }, { classified: 0, fallback: 0 });
      setNotice(counts.fallback
        ? `意味分類を実行しました。分類できた項目 ${counts.classified}件、元の本文を保持した項目 ${counts.fallback}件です。`
        : `意味分類を実行しました。${counts.classified}件をTeacher Reviewへ反映しました。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "意味分類を実行できませんでした");
    } finally {
      setClassifying(false);
    }
  }

  async function confirm() {
    if (!draft) return;
    const active = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "include" && !draft.confirmed_entry_ids?.includes(entry.id)
      && isModelAnswerRegistrationEntry(entry)
      && (entry.source.kind === "teacher_manual"
        || !(isEffectivelyBlank(entry.answer_text) && isEffectivelyBlank(entry.candidate_text))));
    const empty = active.filter((entry) => isEffectivelyBlank(entry.answer_text)).length;
    if (!active.length || empty) {
      setError([
        !active.length ? "登録する模範解答候補を選んでください。" : "",
        empty ? `模範解答本文が空の項目が${empty}件あります。` : "",
      ].filter(Boolean).join(" "));
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await modelAnswerImports.update(draft.id, {
        expected_revision: draft.revision,
        entries: entryPayload(draft.entries),
      });
      setDraft(updated); setSavedDraft(updated);
      const result = await modelAnswerImports.confirm(updated.id, updated.revision);
      setDraft(result.draft); setSavedDraft(result.draft);
      setNotice(`模範解答${result.model_answers.length}件を登録しました。`);
      const firstQuestion = selectedQuestionId && result.model_answers.some((answer) => answer.question_id === selectedQuestionId)
        ? selectedQuestionId : result.model_answers[0]?.question_id;
      if (firstQuestion && result.model_answers.length > 0) router.push(`/tests/${draft.test_id}?section=answers&question=${encodeURIComponent(firstQuestion)}&registered=1`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模範解答を登録できませんでした");
    } finally {
      setBusy(false);
    }
  }

  const unresolved = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "unassigned").length;
  const eligible = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "include" && !draft.confirmed_entry_ids?.includes(entry.id));
  const registrationValidation = validateModelAnswerRegistration(draft, targetLabels);
  const validationByCandidate = new Map<string, typeof registrationValidation>();
  for (const item of registrationValidation) if (item.candidateId) {
    validationByCandidate.set(item.candidateId, [...(validationByCandidate.get(item.candidateId) || []), item]);
  }
  function jumpToValidation(item: typeof registrationValidation[number]) {
    const target = item.reviewTargetId && targets.some((candidate) => candidate.id === item.reviewTargetId)
      ? item.reviewTargetId
      : item.questionId && targets.some((candidate) => candidate.id === `question:${item.questionId}`)
        ? `question:${item.questionId}` : targets[0]?.id || "";
    setSelectedTargetId(target);
    if (item.candidateId) window.setTimeout(() => {
      const article = document.getElementById(`review-entry-${item.candidateId}`);
      article?.scrollIntoView({ behavior: "smooth", block: "center" });
      article?.focus({ preventScroll: true });
    }, 0);
  }
  const runtime = draft.entries.find((entry) => entry.semantic_classification?.runtime_type)?.semantic_classification?.runtime_type;
  const pages = (entry: ModelAnswerDraftEntry) => [...new Set(entry.source.segments.map((segment) => segment.page_index + 1))];

  return <main className="container section model-answer-import-review">
    <Breadcrumbs items={[
      { label: "試験", href: `/tests/${test.id}` },
      { label: test.name, href: `/tests/${test.id}?section=answers` },
      { label: "解答・採点基準の確認" },
    ]} />
    <PageHeader title="解答・採点基準の確認" />
    <p className="muted">登録済みPDFから読み取った模範解答と採点基準を既存の設問へ対応付け、確認したものをそれぞれ登録します。新しい設問は作成されません。</p>
    <p className="muted">PDF {material?.original_filename || "登録済み資料"}　/　{draft.page_count}ページ　/　読取方法: {draft.parser.library || "PDF文字抽出"}</p>
    {draft.extraction?.status === "used" && <p className="muted">本文抽出: 問題PDFとの差分から追加領域を特定</p>}
    {draft.pipeline && <section aria-label="解析の状態">
      <p>意味分類: {draft.pipeline.status === "complete" ? "完了" : draft.pipeline.status === "partial" ? "一部要確認" : "機械抽出へ切替"}
        {draft.pipeline.profile_id && `　/　使用profile: ${draft.pipeline.profile_id}`} {runtime && ` / runtime: ${runtime}`}　/　位置優先の設問対応</p>
      {draft.pipeline.semantic_classification_fallback && <p className="warn">意味分類を利用できなかった項目は、位置情報と機械抽出結果を使用しています。元の文章は分類欄に保持されています。</p>}
    </section>}
    {draft.state === "editing" && <div className="model-answer-review-toolbar" role="toolbar" aria-label="模範解答の操作">
      <button type="button" className="button secondary" disabled={busy || classifying} onClick={() => void save()}>下書き保存</button>
      <button type="button" className="button" disabled={busy || classifying || registrationValidation.length > 0}
        onClick={() => void confirm()}>{busy ? "登録中…" : "模範解答として登録"}</button>
      <button type="button" className="button secondary" disabled={busy || classifying || rubricRegistering || !draft.entries.some((entry) => rubricRows(entry).length)}
        onClick={() => void registerRubric()}>{rubricRegistering ? "採点基準を登録中…" : "採点基準として登録"}</button>
      <button type="button" className="button secondary" disabled={busy || classifying || draft.entries.length === 0} onClick={() => void classify()}>
        {classifying ? "意味分類中…" : "意味分類を再実行"}</button>
      <Link className="button secondary" href={`/tests/${test.id}?section=answers`}>戻る</Link>
    </div>}
    {draft.state === "editing" && registrationValidation.length > 0 && <section className="warn" aria-label="登録できない理由" role="status">
      <strong>登録前に確認が必要な項目が{registrationValidation.length}件あります</strong>
      <ul>{registrationValidation.map((item, index) => <li key={`${item.reasonCode}:${item.candidateId || index}`}>
        {item.candidateId ? <button type="button" className="registration-validation-jump" aria-label={`${item.message}。該当候補を表示`}
          onClick={() => jumpToValidation(item)}>{item.message}</button> : item.message}
      </li>)}</ul>
      <p>未割当・除外の候補は登録対象に含まれません。登録する候補だけを対応付けてください。</p>
    </section>}
    {unresolved > 0 && <p className="warn" role="status">対応する設問が未確定の候補が{unresolved}件あります。レビューに保持され、模範解答には登録されません。</p>}
    {draft.entries.length === 0 && <p className="warn" role="status">PDFから読み取れる本文がありません。PDFの文字データを確認するか、設問別編集欄で手入力してください。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <ModelAnswerQuestionSelector label="編集対象" options={targets} selectedId={selectedTarget?.id || ""} onChange={id => { setSelectedTargetId(id); setSplitPreview(null); }}>
          <optgroup label="設問">{targets.filter((target) => target.kind === "question").map((target) =>
            <option key={target.id} value={target.id}>{questionLabels.get(target.questionId || "") || target.label}</option>)}</optgroup>
          {targets.some((target) => target.kind === "unassigned") && <optgroup label="対応する設問なし">{targets.filter((target) => target.kind === "unassigned").map((target) =>
            <option key={target.id} value={target.id}>{target.label}</option>)}</optgroup>}
          {targets.some((target) => target.kind === "excluded") && <optgroup label="除外済み">{targets.filter((target) => target.kind === "excluded").map((target) =>
            <option key={target.id} value={target.id}>{target.label}</option>)}</optgroup>}
    </ModelAnswerQuestionSelector>
    <div className="model-answer-import-layout">
      <section className="panel model-answer-import-entries" aria-label="模範解答の確認項目">
        {selectedQuestion && <section className="model-answer-question-text" aria-label="登録済み問題文">
          <h2>{questionLabels.get(selectedQuestion.id)}</h2><h3>問題文</h3>
          <MarkdownMathText source={selectedQuestion.question_text || "問題文は登録されていません。"} />
        </section>}
        {selectedQuestionId && <details className="saved-model-answers" aria-label="登録済み模範解答">
          <summary>登録済み模範解答{selectedSavedAnswer ? `・版 ${selectedSavedAnswer.version}` : "・未登録"}</summary>
          {selectedSavedAnswer ? <><MarkdownMathText source={selectedSavedAnswer.answer_text || ""} />
          {draft.state === "editing" && <button type="button" className="button secondary" disabled={busy || classifying}
            onClick={() => loadSavedAnswer(selectedQuestionId)}>登録済み模範解答を読み込む</button>}</> : <p>未登録</p>}
        </details>}
        <h2>編集中の下書き</h2>
        {selectedQuestionId && draft.state === "editing" && <div className="model-answer-manual-add">
          <button type="button" className="button secondary" onClick={() => addManualEntry(selectedQuestionId)}>
            {questionLabels.get(selectedQuestionId)} に模範解答を追加</button>
        </div>}
        {selectedTarget?.kind === "question" && visibleEntries.length === 0 && <p className="muted">この設問の取り込み候補はありません。必要なら模範解答を追加してください。</p>}
        {draft.entries.map((entry, index) => visibleEntries.includes(entry) ? <article id={`review-entry-${entry.id}`} tabIndex={-1} className="panel model-answer-import-entry" key={entry.id} data-entry-id={entry.id}>
          <header className="model-answer-import-entry-heading">
            <h3>{entry.source.kind === "teacher_manual" ? "教師が追加した候補" : "取り込み候補"} {index + 1}</h3>
            <span className={entry.mapping_state === "needs_review" ? "review-needs-check" : "review-confirmed"}>
              {entry.mapping_state === "automatic" ? "自動で対応" : entry.mapping_state === "manual_mapped" ? "教師が対応" : "対応先を確認"}
            </span>
          </header>
          {validationByCandidate.get(entry.id)?.map((item) => <p className="warn model-answer-candidate-validation" role="status" key={`${item.reasonCode}:${entry.id}`}>
            ⚠ {item.message}
          </p>)}
          {entry.disposition === "excluded" ? <div className="model-answer-excluded-compact">
            <p>{entry.ignore_reason === "blank_or_whitespace" ? "空の抽出候補として無視されています。"
              : entry.ignore_reason === "classified_as_non_answer" ? "模範解答以外の候補として取り込み対象外です。"
                : "取り込み対象外として除外されています。"}</p>
            <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
              onClick={() => {
                updateEntry(entry.id, { disposition: entry.question_id ? "include" : "unassigned" });
                setSelectedTargetId(entry.question_id ? `question:${entry.question_id}` : `unassigned:${entry.id}`);
              }}>取り込み対象に戻す</button>
          </div> : <>
          <label className="field">候補の扱い・対応先
            <select aria-label={`模範解答 ${index + 1} の対応先`} value={(entry.disposition === "unassigned" || !entry.question_id) ? "__unassigned__" : entry.question_id} disabled={busy || classifying || draft.state !== "editing" || draft.confirmed_entry_ids?.includes(entry.id)}
              onChange={(event) => {
                const value = event.target.value;
                updateEntry(entry.id, value === "__excluded__" ? { disposition: "excluded" }
                  : value === "__unassigned__" ? { disposition: "unassigned", question_id: null, mapping_state: "needs_review", loaded_model_answer: undefined }
                    : { disposition: "include", question_id: value, mapping_state: "manual_mapped", loaded_model_answer: undefined });
                if (value === "__excluded__") setSelectedTargetId(`excluded:${entry.id}`);
                else if (value === "__unassigned__") setSelectedTargetId(`unassigned:${entry.id}`);
                else setSelectedTargetId(`question:${value}`);
              }}>
              <option value="__unassigned__">対応する設問なし</option>
              <option value="__excluded__">模範解答ではない文章</option>
              {draft.questions.map((question) => <option key={question.id} value={question.id}>{question.label}</option>)}
            </select>
          </label>
          <button type="button" className="button secondary" disabled={draft.state !== "editing"}
            onClick={() => { updateEntry(entry.id, { disposition: "excluded" }); setSelectedTargetId(`excluded:${entry.id}`); }}>取り込み対象外にする</button>
          <p className="model-answer-source-info">{entry.source.kind === "teacher_manual" ? "出典: 教師入力" : `出典ページ: ${pages(entry).length ? pages(entry).map((page) => `p.${page}`).join("、") : "ページ情報なし"}`}</p>
          <label className="field">解答の種類
            <select aria-label={`模範解答 ${index + 1} の種類`} value={entry.answer_kind || "primary"} disabled={busy || classifying || draft.state !== "editing" || draft.confirmed_entry_ids?.includes(entry.id)} onChange={(event) => updateEntry(entry.id, { answer_kind: event.target.value as "primary" | "alternative" })}>
              <option value="primary">主な模範解答</option><option value="alternative">別解</option>
            </select>
          </label>
          {entry.geometry && <details>
            <summary>位置判定: {entry.geometry.assignment_status === "automatic" ? "高信頼" : "未確定"}（{Math.round(entry.geometry.confidence * 100)}%）</summary>
            <p>位置根拠: {entry.geometry.evidence}</p>
            {entry.geometry.region && <p>見出し: {entry.geometry.region.heading} / p.{entry.geometry.region.page_index + 1} / 縦位置: {Math.round(entry.geometry.region.top)}〜{Math.round(entry.geometry.region.bottom)}</p>}
            {entry.source.segments.map((segment, segmentIndex) => <p key={segment.id || segmentIndex}>
              p.{segment.page_index + 1} {segment.bbox && `座標: ${segment.bbox.map(Math.round).join(", ")}`} — {segment.original_text}
            </p>)}
          </details>}
          {entry.extraction_method === "visual_difference_guided_native_text" &&
            <p className="muted">抽出方法: 問題PDFとの差分</p>}
          <details aria-label="保存済み下書き模範解答">
            <summary>保存済み下書き模範解答・revision {savedDraft?.revision || "—"}</summary>
            {savedDraft?.entries.some(saved => saved.id === entry.id) ? <MarkdownMathText source={savedDraft.entries.find(saved => saved.id === entry.id)?.answer_text || "本文なし"} /> : <p>なし</p>}
          </details>
          {entry.answer_text !== savedDraft?.entries.find(saved => saved.id === entry.id)?.answer_text && <p role="status">未保存の変更があります</p>}
          <label className="field">編集中の下書き本文
            <textarea aria-label={`模範解答本文 ${index + 1}`} value={entry.answer_text} maxLength={100000} rows={6}
              disabled={busy || classifying || draft.state !== "editing" || draft.confirmed_entry_ids?.includes(entry.id)}
              onChange={(event) => updateEntry(entry.id, { answer_text: event.target.value })} />
          </label>
          <LatexNormalizationControl text={entry.answer_text} contextType="model_answer" contextLabel={questionLabels.get(entry.question_id || "") || ""}
            disabled={busy || classifying || draft.state !== "editing" || draft.confirmed_entry_ids?.includes(entry.id)}
            onApply={(text, proposal) => updateEntry(entry.id, { answer_text: text, teacher_correction: {
              ...entry.teacher_correction, teacher_confirmed: true, latex_normalization: {...proposal, timestamp: new Date().toISOString()}
            } })} />
          {entry.semantic_classification && <section className="model-answer-classification" aria-label={`模範解答 ${index + 1} の意味分類`}>
            <header className="model-answer-entry-heading">
              <h4>意味分類</h4>
              <span className={entry.semantic_classification.status === "classified" || entry.semantic_classification.status === "teacher_reviewed" ? "review-confirmed" : "review-needs-check"}>
                {entry.semantic_classification.status === "classified" ? "分類済み" : entry.semantic_classification.status === "teacher_reviewed" ? "教師確認済み" : entry.semantic_classification.status === "fallback" ? "元の本文を保持" : "要確認"}
              </span>
            </header>
            {entry.semantic_classification.status === "fallback" && <p className="warn">意味分類を利用できませんでした。抽出本文を変更せず保持しています。分類機能が復旧した後に再実行するか、本文を手動で編集してください。</p>}
            {entry.semantic_classification.status === "needs_teacher_review" && !entry.teacher_correction?.teacher_confirmed && entry.source.kind !== "teacher_manual" && <p className="muted">分類は参考情報です。正式登録される本文と設問の対応を確認してください。</p>}
            {entry.semantic_classification.confidence !== null && <p className="muted">分類信頼度: {Math.round(entry.semantic_classification.confidence * 100)}%</p>}
            <div className="model-answer-classification-groups">
              <div><strong>元の分類結果（編集本文とは別）</strong>
                {groupsFor(entry.semantic_classification.segments, "model_answer").length === 0 && <p className="muted">模範解答候補がありません。</p>}
                <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
                  onClick={() => setEntryAnswerFromClassification(entry, groupsFor(entry.semantic_classification!.segments, "model_answer").map((group) => group.text).join(""))}>
                  分類結果を本文へ反映
                </button>
              </div>
              <div><strong>別解・複数正答候補</strong>
                {groupsFor(entry.semantic_classification.segments, "alternative_answer").map((group, groupIndex) => <div key={`alternative-${groupIndex}`}>
                  <p>{group.label}</p><MathPreview source={group.text} />
                  <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
                    onClick={() => setEntryAnswerFromClassification(entry, group.text)}>この別解を主な模範解答として使う</button>
                </div>)}
                {(entry.semantic_classification.manual_alternative_answers || []).map((candidate, candidateIndex) => <div key={candidate.id}>
                  <label className="field">教師が追加した別解 {candidateIndex + 1}
                    <textarea aria-label={`模範解答 ${index + 1} 教師追加別解 ${candidateIndex + 1}`} rows={3} maxLength={100000}
                      value={candidate.text} disabled={busy || classifying || draft.state !== "editing"}
                      onChange={(event) => updateManualAlternatives(entry,
                        (entry.semantic_classification?.manual_alternative_answers || []).map((item) =>
                          item.id === candidate.id ? { ...item, text: event.target.value } : item))} />
                  </label>
                  <MathPreview source={candidate.text} />
                  <div className="actions">
                    <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing" || !candidate.text.trim()}
                      onClick={() => setEntryAnswerFromClassification(entry, candidate.text)}>この別解を主な模範解答として使う</button>
                    <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
                      onClick={() => updateManualAlternatives(entry,
                        (entry.semantic_classification?.manual_alternative_answers || []).filter((item) => item.id !== candidate.id))}>別解候補を削除</button>
                  </div>
                </div>)}
                <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
                  onClick={() => addManualAlternative(entry)}>別解候補を追加</button>
              </div>
              {(["rubric", "question", "note", "uncertain"] as ModelAnswerContentCategory[]).map((category) => {
                const groups = groupsFor(entry.semantic_classification!.segments, category);
                if (!groups.length && !(category === "rubric" && rubricRows(entry).length)) return null;
                const heading = category === "rubric" ? "採点基準候補"
                  : category === "question" ? "除外された問題文" : categoryLabels[category];
                if (category === "rubric") {
                  const candidates = rubricRows(entry).filter((item) => !item.excluded);
                  const selectedIds = selectedRubricGroups[entry.id] || [];
                  return <details key={category} open>
                    <summary>{heading}（{candidates.length}件）</summary>
                    <p className="muted">元segment {entry.semantic_classification!.segments.filter((item) => item.category === "rubric").length}件・グルーピング: {entry.semantic_classification?.rubric_grouping_method || "既存候補"}</p>
                    <div className="actions">
                      <button type="button" className="button secondary" disabled={busy || selectedIds.length < 2}
                        onClick={() => mergeRubricGroups(entry, selectedIds, "manual_multi")}>選択した項目をマージ</button>
                      <button type="button" className="button secondary" disabled={busy || !(entry.rubric_merge_history?.length)}
                        onClick={() => undoRubricMerge(entry)}>マージを解除（元に戻す）</button>
                      <button type="button" className="button secondary" disabled={busy || !(entry.rubric_merge_history?.length)} onClick={() => undoRubricMerge(entry)}>分割・追加を元に戻す</button>
                    </div>
                    {candidates.map((edit, groupIndex) => {
                      const sourceIds = edit.segment_ids || [edit.id];
                      const sourceText = sourceIds.map((sourceId) => entry.semantic_classification!.segments.find((item) => item.id === sourceId)?.source_text || "").join("");
                      return <div className="rubric-candidate-edit" key={edit.id} data-candidate-id={edit.id}
                        data-active={activeRubricId === edit.id ? "true" : undefined} aria-busy={splittingCandidateId === edit.id}>
                        <label><input type="checkbox" aria-label={`採点基準候補 ${index + 1}-${groupIndex + 1} を選択`}
                          checked={selectedIds.includes(edit.id)} onChange={(event) => setSelectedRubricGroups((current) => ({
                            ...current, [entry.id]: event.target.checked ? [...selectedIds, edit.id] : selectedIds.filter((id) => id !== edit.id),
                          }))} /> 採点基準 {groupIndex + 1}</label>
                        {groupIndex > 0 && <button type="button" className="button secondary" disabled={busy || classifying}
                          onClick={() => mergeRubricGroups(entry, [candidates[groupIndex - 1].id, edit.id], "manual_above")}>上とマージ</button>}
                        <div className="actions">
                          <button type="button" className="button secondary" disabled={busy || splitting || classifying || draft.state !== "editing"}
                            onClick={() => suggestSplit(entry, edit)}>LLMで分割を試す</button>
                          <button type="button" className="button secondary" disabled={busy || splitting || draft.state !== "editing"}
                            onClick={() => manualSplit(entry, edit)}>カーソルの位置で分割</button>
                          <button type="button" className="button secondary" disabled={busy || splitting || draft.state !== "editing"}
                            onClick={() => insertRubric(entry, edit, false)}>下に採点基準を追加</button>
                          <button type="button" className="button secondary" disabled={busy || splitting || draft.state !== "editing"}
                            onClick={() => insertRubric(entry, edit, true)}>複製して下に追加</button>
                          <button type="button" className="button secondary" disabled={busy || splitting || draft.state !== "editing"}
                            onClick={() => replaceRubricRows(entry, rubricRows(entry).map((row) => row.id === edit.id ? { ...row, excluded: true } : row))}>採点基準を除外</button>
                        </div>
                        <label className="field">本文
                          <textarea aria-label={`採点基準候補 ${index + 1}-${groupIndex + 1} 本文`} value={edit.description}
                            ref={element => { rubricTextareas.current[edit.id] = element; }}
                            onFocus={() => { setActiveRubricId(edit.id); }}
                            onSelect={(event) => { const control = event.currentTarget; splitCursors.current[edit.id] = Array.from(control.value.slice(0, control.selectionStart)).length; }}
                            onBlur={(event) => { const control = event.currentTarget; splitCursors.current[edit.id] = Array.from(control.value.slice(0, control.selectionStart)).length; }}
                            disabled={busy || classifying || draft.state !== "editing"}
                            onChange={(event) => updateRubricEdit(entry, edit.id, { description: event.target.value, source_text: event.target.value, grouping_confirmed: true, grouping_method: edit.grouping_method || "teacher_edit" })} />
                          <LatexNormalizationControl text={edit.description} contextType="rubric" contextLabel={questionLabels.get(entry.question_id || "") || ""} disabled={busy || classifying || splitting || draft.state !== "editing"}
                            onApply={(text, proposal) => updateRubricEdit(entry, edit.id, {description: text, source_text: text, grouping_confirmed: true,
                              provenance: {...edit.provenance, teacher_confirmed: true, latex_normalization: {...proposal, timestamp: new Date().toISOString()}}})} />
                        </label>
                        <label className="field">配点
                          <input type="number" min="1" step="1" aria-label={`採点基準候補 ${index + 1}-${groupIndex + 1} の配点`}
                            value={edit.points || ""} disabled={busy || classifying || draft.state !== "editing"}
                            onChange={(event) => updateRubricEdit(entry, edit.id, { points: Number(event.target.value), points_confirmed: true })} />
                        </label>
                        {edit.points_conflict && <p className="warn">{edit.grouping_method?.startsWith("split_") ? "配点の確認が必要です。各採点観点の配点を入力してください。" : "複数の配点記述があります。原文の配点を確認してください。"}
                          <label><input type="checkbox" checked={!!edit.points_confirmed} onChange={(event) => updateRubricEdit(entry, edit.id, { points_confirmed: event.target.checked })} /> 配点を確認しました</label>
                        </p>}
                        {edit.confidence !== undefined && <p className="muted">グルーピング信頼度: {Math.round((edit.confidence || 0) * 100)}%</p>}
                        {(edit.confidence ?? 1) < 0.82 && <p className={edit.grouping_confirmed ? "success" : "warn"}>
                          {edit.grouping_confirmed ? "グルーピングを確認しました。" : "グルーピングの確認が必要です。"}
                          <label><input type="checkbox" aria-label="グルーピングを確認しました" checked={!!edit.grouping_confirmed}
                            onChange={(event) => updateRubricEdit(entry, edit.id, { grouping_confirmed: event.target.checked })} /> この候補のまとまりを確認しました</label>
                        </p>}
                        <details><summary>元segment（{sourceIds.length}件）</summary><MathPreview source={edit.source_text ?? sourceText} />
                          {sourceIds.map((sourceId) => { const segment = entry.semantic_classification!.segments.find((item) => item.id === sourceId); return segment && <p key={sourceId} className="muted">{sourceId} · {segment.text}</p>; })}
                        </details>
                        {rubricFeedback[edit.id] && <p className={rubricFeedback[edit.id].kind === "error" ? "error" : "success"}
                          role={rubricFeedback[edit.id].kind === "error" ? "alert" : "status"}>{rubricFeedback[edit.id].text}</p>}
                        {splitPreview?.entryId === entry.id && splitPreview.item.id === edit.id && <section id={`rubric-proposal-${edit.id}`} className="rubric-split-proposal" aria-label="採点基準の分割案">
                          <h3>採点基準 {groupIndex + 1} の分割案</h3>
                          <p>信頼度: {Math.round(splitPreview.proposal.confidence * 100)}%。元文章をそのまま分割します。</p>
                          {splitPreview.proposal.parts.map((part, partIndex) => <div key={part.start}>
                            <h4>採点基準 {groupIndex + 1}-{partIndex + 1}</h4><MathPreview source={part.source_text} /><p>配点: {part.points || "要確認"}</p>
                          </div>)}
                          <div className="actions">
                            <button type="button" className="button" disabled={busy || classifying} onClick={applySplit}>この分割案を適用</button>
                            <button type="button" className="button secondary" onClick={() => { setSplitPreview(null); rubricMessage(edit.id, "success", "分割案をキャンセルしました。元の採点基準は保持されています。"); }}>キャンセル</button>
                          </div>
                        </section>}
                      </div>;
                    })}
                    <p className="muted">登録すると採点基準の新しい未承認版を作成します。採点前に既存の承認操作が必要です。</p>
                  </details>;
                }
                return <details key={category}>
                  <summary>{heading}（{groups.length}件）</summary>
                  {groups.map((group, groupIndex) => <div key={`${category}-${groupIndex}`}><MathPreview source={group.text} /></div>)}
                </details>;
              })}
            </div>
            <details className="model-answer-classification-editor">
              <summary>分類内容を確認・修正</summary>
              <p className="muted">分類を変更すると「分類結果を本文へ反映」で模範解答本文を更新できます。文章は抽出元の内容から編集できます。</p>
              {entry.semantic_classification.segments.map((segment, segmentIndex) => <div className="model-answer-classification-segment" key={segment.id}>
                <label className="field">抽出箇所 {segmentIndex + 1} の分類
                  <select aria-label={`模範解答 ${index + 1} 抽出箇所 ${segmentIndex + 1} の分類`} value={segment.category}
                    disabled={busy || classifying || draft.state !== "editing"}
                    onChange={(event) => updateClassificationSegment(entry.id, segment.id, { category: event.target.value as ModelAnswerContentCategory }, true)}>
                    {categoryOrder.map((category) => <option key={category} value={category}>{categoryLabels[category]}</option>)}
                  </select>
                </label>
                <label className="field">抽出本文
                  <textarea aria-label={`模範解答 ${index + 1} 抽出箇所 ${segmentIndex + 1} の本文`} rows={3} maxLength={100000}
                    value={segment.text} disabled={busy || classifying || draft.state !== "editing"}
                    onChange={(event) => updateClassificationSegment(entry.id, segment.id, { text: event.target.value })} />
                </label>
                <small className="muted">分類信頼度: {Math.round(segment.confidence * 100)}%</small>
              </div>)}
              {entry.semantic_classification.status === "needs_teacher_review" && !entry.semantic_classification.segments.some((segment) => segment.category === "uncertain") &&
                <button type="button" className="button secondary" disabled={busy || classifying || draft.state !== "editing"}
                  onClick={() => updateEntry(entry.id, { semantic_classification: { ...entry.semantic_classification!, status: "teacher_reviewed" } })}>
                  分類結果を確認済みにする
                </button>}
            </details>
          </section>}
          {entry.question_text_removal?.status === "removed" && <p className="muted">重複していた問題文を除去しました。</p>}
          {entry.question_text_removal?.status === "removed" && !entry.answer_text.trim() &&
            <p className="warn" role="alert">問題文以外の模範解答を抽出できませんでした。PDFを確認し、本文を入力してください。</p>}
          <small className="math-help">{mathInputHelp}</small>
          <details open><summary>編集中プレビュー</summary><MathPreview source={entry.answer_text} /></details>
          {entry.question_id && <p className="muted">対応先: {questionLabels.get(entry.question_id) || "設問"}</p>}
          </>}
        </article> : null)}
        {draft.state === "confirmed" && <p className="review-confirmed">登録済み</p>}
      </section>
      <aside className="panel model-answer-import-source" aria-label="模範解答PDF">
        <h2>元の模範解答PDF</h2>
        <SourcePdfPreview testId={test.id} material={material || undefined} label="模範解答PDF" paneZoom targetLocation={pdfLocation} />
      </aside>
    </div>
  </main>;
}
