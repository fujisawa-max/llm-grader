"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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
} from "@/lib/api/modelAnswerImports";
import { testData, tests } from "@/lib/api/domain";
import type { Material, Test } from "@/types/domain";
import { buildReviewTargets, dispositionOf, resolveReviewTarget } from "@/lib/modelAnswerReviewTargets";

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

export default function ModelAnswerImportReviewPage() {
  const draftId = String(useParams().draftId);
  const router = useRouter();
  const [draft, setDraft] = useState<ModelAnswerImportDraft | null>(null);
  const [test, setTest] = useState<Test | null>(null);
  const [material, setMaterial] = useState<Material | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedTargetId, setSelectedTargetId] = useState("");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const current = await modelAnswerImports.get(draftId);
        const [testRow, materials] = await Promise.all([
          tests.get(current.test_id), testData.materials(current.test_id),
        ]);
        if (!active) return;
        setDraft(current);
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

  const questionLabels = useMemo(() => new Map((draft?.questions || []).map((item) => [item.id, questionBreadcrumb(item, draft?.questions || [])])), [draft]);
  if (loading) return <LoadingState />;
  if (error && (!draft || !test)) return <ErrorState message={error} />;
  if (!draft || !test) return <ErrorState message="模範解答の確認内容が見つかりません" />;
  const targets = buildReviewTargets(draft);
  const selectedTarget = resolveReviewTarget(targets, selectedTargetId);
  const selectedQuestionId = selectedTarget?.kind === "question" ? selectedTarget.questionId : null;
  const selectedQuestion = draft.questions.find((question) => question.id === selectedQuestionId);
  const visibleEntries = draft.entries.filter((entry) => selectedTarget?.kind === "question"
    ? entry.question_id === selectedQuestionId && dispositionOf(entry) !== "unassigned"
    : selectedTarget?.entryId === entry.id);
  const selectedSavedAnswer = draft.saved_answers?.find((answer) => answer.question_id === selectedQuestionId);
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
        id: `teacher-entry-${globalThis.crypto.randomUUID()}`,
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
    if (!window.confirm("保存済み模範解答を今回の編集欄へ読み込みます。現在編集中の本文を置き換える場合があります。続行しますか？")) return;
    const primary = draft?.entries.find((entry) => entry.question_id === questionId &&
      dispositionOf(entry) === "include" && (entry.answer_kind || "primary") === "primary" &&
      !draft.confirmed_entry_ids?.includes(entry.id));
    if (primary) updateEntry(primary.id, { answer_text: saved.answer_text, loaded_model_answer: {
      id: saved.id, version: saved.version, question_id: questionId } });
    else addManualEntry(questionId, saved.answer_text, saved.id);
    setNotice(`保存済み模範解答 v${saved.version} を編集欄へ読み込みました。今回のPDF出典情報は保持されています。`);
  }

  const entryPayload = (entries: ModelAnswerDraftEntry[]) => entries.map((entry) => ({
    id: entry.id,
    question_id: entry.question_id,
    answer_text: entry.answer_text,
    disposition: entry.disposition || (entry.question_id ? "include" : "unassigned"),
    answer_kind: entry.answer_kind || "primary",
    loaded_model_answer_id: entry.loaded_model_answer?.id || null,
    ...(entry.semantic_classification ? {
      classification_segments: entry.semantic_classification.segments.map(({ id, category, text }) => ({ id, category, text })),
      classification_reviewed: entry.semantic_classification.status === "teacher_reviewed",
      ...(entry.semantic_classification.manual_alternative_answers !== undefined
        ? { manual_alternative_answers: entry.semantic_classification.manual_alternative_answers } : {}),
    } : {}),
  }));

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
        return { ...entry, semantic_classification: { ...entry.semantic_classification, segments, status } };
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
    updateManualAlternatives(entry, [...current, { id: `teacher-alt-${globalThis.crypto.randomUUID()}`, text: "" }]);
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
      setDraft(updated);
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
      setDraft(classified);
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
    const active = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "include" && !draft.confirmed_entry_ids?.includes(entry.id));
    const empty = active.filter((entry) => !entry.answer_text.trim()).length;
    const pending = active.filter((entry) => entry.semantic_classification?.status === "needs_teacher_review").length;
    if (!active.length || empty || pending) {
      setError([
        !active.length ? "登録する模範解答候補を選んでください。" : "",
        empty ? `模範解答本文が空の項目が${empty}件あります。` : "",
        pending ? `分類結果を確認していない項目が${pending}件あります。` : "",
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
      setDraft(updated);
      const result = await modelAnswerImports.confirm(updated.id, updated.revision);
      setDraft(result.draft);
      setNotice(`模範解答${result.model_answers.length}件を登録しました。`);
      const firstQuestion = selectedQuestionId && result.model_answers.some((answer) => answer.question_id === selectedQuestionId)
        ? selectedQuestionId : result.model_answers[0]?.question_id;
      if (firstQuestion) router.push(`/tests/${draft.test_id}?section=answers&question=${encodeURIComponent(firstQuestion)}&registered=1`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模範解答を登録できませんでした");
    } finally {
      setBusy(false);
    }
  }

  const unresolved = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "unassigned").length;
  const classificationReviewCount = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "include" && entry.semantic_classification?.status === "needs_teacher_review").length;
  const eligible = draft.entries.filter((entry) => (entry.disposition || (entry.question_id ? "include" : "unassigned")) === "include" && !draft.confirmed_entry_ids?.includes(entry.id));
  const runtime = draft.entries.find((entry) => entry.semantic_classification?.runtime_type)?.semantic_classification?.runtime_type;
  const pages = (entry: ModelAnswerDraftEntry) => [...new Set(entry.source.segments.map((segment) => segment.page_index + 1))];

  return <main className="container section model-answer-import-review">
    <Breadcrumbs items={[
      { label: "試験", href: `/tests/${test.id}` },
      { label: test.name, href: `/tests/${test.id}?section=answers` },
      { label: "模範解答の確認" },
    ]} />
    <PageHeader title="模範解答の確認" />
    <p className="muted">登録済みPDFから読み取った内容を既存の設問へ対応付け、本文を確認して登録します。新しい設問は作成されません。</p>
    <p className="muted">PDF {material?.original_filename || "登録済み資料"}　/　{draft.page_count}ページ　/　読取方法: {draft.parser.library || "PDF文字抽出"}</p>
    {draft.extraction?.status === "used" && <p className="muted">本文抽出: 問題PDFとの差分から追加領域を特定</p>}
    {draft.pipeline && <section aria-label="解析の状態">
      <p>意味分類: {draft.pipeline.status === "complete" ? "完了" : draft.pipeline.status === "partial" ? "一部要確認" : "機械抽出へ切替"}
        {draft.pipeline.profile_id && `　/　使用profile: ${draft.pipeline.profile_id}`} {runtime && ` / runtime: ${runtime}`}　/　位置優先の設問対応</p>
      {draft.pipeline.semantic_classification_fallback && <p className="warn">意味分類を利用できなかった項目は、位置情報と機械抽出結果を使用しています。元の文章は分類欄に保持されています。</p>}
    </section>}
    {draft.state === "editing" && <div className="model-answer-review-toolbar" role="toolbar" aria-label="模範解答の操作">
      <button type="button" className="button secondary" disabled={busy || classifying} onClick={() => void save()}>下書き保存</button>
      <button type="button" className="button" disabled={busy || classifying || !eligible.length || classificationReviewCount > 0 || eligible.some((entry) => !entry.answer_text.trim())}
        onClick={() => void confirm()}>{busy ? "登録中…" : "模範解答として登録"}</button>
      <button type="button" className="button secondary" disabled={busy || classifying || draft.entries.length === 0} onClick={() => void classify()}>
        {classifying ? "意味分類中…" : "意味分類を再実行"}</button>
      <Link className="button secondary" href={`/tests/${test.id}?section=answers`}>戻る</Link>
    </div>}
    {unresolved > 0 && <p className="warn" role="status">対応する設問が未確定の候補が{unresolved}件あります。レビューに保持され、模範解答には登録されません。</p>}
    {classificationReviewCount > 0 && <p className="warn" role="status">意味分類の確認が必要な項目が{classificationReviewCount}件あります。要確認の文章を分類し、分類結果を確認済みにしてください。</p>}
    {draft.entries.length === 0 && <p className="warn" role="status">PDFから読み取れる本文がありません。PDFの文字データを確認するか、設問別編集欄で手入力してください。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <ModelAnswerQuestionSelector label="編集対象" options={targets} selectedId={selectedTarget?.id || ""} onChange={setSelectedTargetId}>
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
        {selectedQuestionId && selectedSavedAnswer && <section className="saved-model-answers">
          <h2>保存済み模範解答</h2>
          <p>{questionLabels.get(selectedQuestionId)}・版 {selectedSavedAnswer.version}</p>
          <MathPreview source={selectedSavedAnswer.answer_text || ""} />
          {draft.state === "editing" && <button type="button" className="button secondary" disabled={busy || classifying}
            onClick={() => loadSavedAnswer(selectedQuestionId)}>保存済み模範解答を読み込む</button>}
        </section>}
        <h2>{draft.saved_answers?.length ? "今回のLLM取り込み結果" : "LLM取り込み結果"}</h2>
        {selectedQuestionId && draft.state === "editing" && <div className="model-answer-manual-add">
          <button type="button" className="button secondary" onClick={() => addManualEntry(selectedQuestionId)}>
            {questionLabels.get(selectedQuestionId)} に模範解答を追加</button>
        </div>}
        {selectedTarget?.kind === "question" && visibleEntries.length === 0 && <p className="muted">この設問の取り込み候補はありません。必要なら模範解答を追加してください。</p>}
        {draft.entries.map((entry, index) => visibleEntries.includes(entry) ? <article className="panel model-answer-import-entry" key={entry.id} data-entry-id={entry.id}>
          <header className="model-answer-import-entry-heading">
            <h3>{entry.source.kind === "teacher_manual" ? "教師が追加した候補" : "取り込み候補"} {index + 1}</h3>
            <span className={entry.mapping_state === "needs_review" ? "review-needs-check" : "review-confirmed"}>
              {entry.mapping_state === "automatic" ? "自動で対応" : entry.mapping_state === "manual_mapped" ? "教師が対応" : "対応先を確認"}
            </span>
          </header>
          {entry.disposition === "excluded" ? <div className="model-answer-excluded-compact">
            <p>模範解答ではない文章として除外されています。</p>
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
          <label className="field">模範解答本文
            <textarea aria-label={`模範解答本文 ${index + 1}`} value={entry.answer_text} maxLength={100000} rows={6}
              disabled={busy || classifying || draft.state !== "editing" || draft.confirmed_entry_ids?.includes(entry.id)}
              onChange={(event) => updateEntry(entry.id, { answer_text: event.target.value })} />
          </label>
          {entry.semantic_classification && <section className="model-answer-classification" aria-label={`模範解答 ${index + 1} の意味分類`}>
            <header className="model-answer-entry-heading">
              <h4>意味分類</h4>
              <span className={entry.semantic_classification.status === "classified" || entry.semantic_classification.status === "teacher_reviewed" ? "review-confirmed" : "review-needs-check"}>
                {entry.semantic_classification.status === "classified" ? "分類済み" : entry.semantic_classification.status === "teacher_reviewed" ? "教師確認済み" : entry.semantic_classification.status === "fallback" ? "元の本文を保持" : "要確認"}
              </span>
            </header>
            {entry.semantic_classification.status === "fallback" && <p className="warn">意味分類を利用できませんでした。抽出本文を変更せず保持しています。分類機能が復旧した後に再実行するか、本文を手動で編集してください。</p>}
            {entry.semantic_classification.status === "needs_teacher_review" && <p className="warn">信頼度が低い、または判断できない文章があります。内容を確認し、必要なら分類を変更してください。</p>}
            {entry.semantic_classification.confidence !== null && <p className="muted">分類信頼度: {Math.round(entry.semantic_classification.confidence * 100)}%</p>}
            <div className="model-answer-classification-groups">
              <div><strong>LLM取り込み結果</strong>
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
                if (!groups.length) return null;
                const heading = category === "rubric" ? "採点基準候補（自動登録されません）"
                  : category === "question" ? "除外された問題文" : categoryLabels[category];
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
          <details open><summary>数式・Markdownプレビュー</summary><MathPreview source={entry.answer_text} /></details>
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
