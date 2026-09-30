"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Breadcrumbs, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import { MathPreview, mathInputHelp } from "@/components/MathText";
import { SourcePdfPreview } from "@/components/SourcePdfPreview";
import { modelAnswerImports, type ModelAnswerDraftEntry, type ModelAnswerImportDraft } from "@/lib/api/modelAnswerImports";
import { testData, tests } from "@/lib/api/domain";
import type { Material, Test } from "@/types/domain";

export default function ModelAnswerImportReviewPage() {
  const draftId = String(useParams().draftId);
  const router = useRouter();
  const [draft, setDraft] = useState<ModelAnswerImportDraft | null>(null);
  const [test, setTest] = useState<Test | null>(null);
  const [material, setMaterial] = useState<Material | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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

  const questionLabels = useMemo(() => new Map((draft?.questions || []).map((item) => [item.id, item.label])), [draft]);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!draft || !test) return <ErrorState message="模範解答の確認内容が見つかりません" />;

  function updateEntry(entryId: string, patch: Partial<ModelAnswerDraftEntry>) {
    setDraft((current) => current ? {
      ...current,
      entries: current.entries.map((entry) => entry.id === entryId ? { ...entry, ...patch } : entry),
    } : current);
    setNotice("");
  }

  async function save(): Promise<ModelAnswerImportDraft | null> {
    if (!draft) return null;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await modelAnswerImports.update(draft.id, {
        expected_revision: draft.revision,
        entries: draft.entries.map(({ id, question_id, answer_text }) => ({ id, question_id, answer_text })),
      });
      setDraft(updated);
      setNotice("変更を保存しました。");
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "変更を保存できませんでした");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!draft) return;
    const unmapped = draft.entries.filter((entry) => !entry.question_id).length;
    const empty = draft.entries.filter((entry) => !entry.answer_text.trim()).length;
    if (unmapped || empty) {
      setError([
        unmapped ? `対応先が未設定の模範解答が${unmapped}件あります。` : "",
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
        entries: draft.entries.map(({ id, question_id, answer_text }) => ({ id, question_id, answer_text })),
      });
      setDraft(updated);
      const result = await modelAnswerImports.confirm(updated.id, updated.revision);
      setDraft(result.draft);
      setNotice(`模範解答${result.model_answers.length}件を登録しました。設問ごとの模範解答一覧へ戻ります。`);
      window.setTimeout(() => router.push(`/tests/${draft.test_id}?section=answers`), 700);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模範解答を登録できませんでした");
    } finally {
      setBusy(false);
    }
  }

  const unresolved = draft.entries.filter((entry) => !entry.question_id).length;
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
    {unresolved > 0 && <p className="warn" role="status">対応先が未設定の模範解答が{unresolved}件あります。すべての対応先を選ぶまで登録できません。</p>}
    {draft.entries.length === 0 && <p className="warn" role="status">PDFから読み取れる本文がありません。PDFの文字データを確認するか、設問別編集欄で手入力してください。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <div className="model-answer-import-layout">
      <section className="panel model-answer-import-entries" aria-label="模範解答の確認項目">
        <h2>設問ごとの模範解答</h2>
        {draft.entries.map((entry, index) => <article className="panel model-answer-import-entry" key={entry.id} data-entry-id={entry.id}>
          <header className="model-answer-import-entry-heading">
            <h3>模範解答 {index + 1}</h3>
            <span className={entry.mapping_state === "needs_review" ? "review-needs-check" : "review-confirmed"}>
              {entry.mapping_state === "automatic" ? "自動で対応" : entry.mapping_state === "manual_mapped" ? "教師が対応" : "対応先を確認"}
            </span>
          </header>
          <label className="field">対応先の設問
            <select aria-label={`模範解答 ${index + 1} の対応先`} value={entry.question_id || ""} disabled={busy || draft.state !== "editing"}
              onChange={(event) => updateEntry(entry.id, {
                question_id: event.target.value || null,
                mapping_state: event.target.value ? "manual_mapped" : "needs_review",
              })}>
              <option value="">対応先を選択してください</option>
              {draft.questions.map((question) => <option key={question.id} value={question.id}>{question.label}</option>)}
            </select>
          </label>
          <p className="model-answer-source-info">出典ページ: {pages(entry).length ? pages(entry).map((page) => `p.${page}`).join("、") : "ページ情報なし"}</p>
          <label className="field">模範解答本文
            <textarea aria-label={`模範解答本文 ${index + 1}`} value={entry.answer_text} maxLength={100000} rows={6}
              disabled={busy || draft.state !== "editing"}
              onChange={(event) => updateEntry(entry.id, { answer_text: event.target.value })} />
          </label>
          <small className="math-help">{mathInputHelp}</small>
          <MathPreview source={entry.answer_text} />
          {entry.question_id && <p className="muted">対応先: {questionLabels.get(entry.question_id) || "設問"}</p>}
        </article>)}
        {draft.state === "confirmed" && <p className="review-confirmed">登録済み</p>}
        {draft.state === "editing" && <div className="actions">
          <button type="button" className="button secondary" disabled={busy} onClick={() => void save()}>変更を保存</button>
          <button type="button" className="button" disabled={busy || draft.entries.length === 0 || unresolved > 0 || draft.entries.some((entry) => !entry.answer_text.trim())}
            onClick={() => void confirm()}>確認した模範解答を登録</button>
          <Link className="button secondary" href={`/tests/${test.id}?section=answers`}>模範解答画面へ戻る</Link>
        </div>}
      </section>
      <aside className="panel model-answer-import-source" aria-label="模範解答PDF">
        <h2>元の模範解答PDF</h2>
        <SourcePdfPreview testId={test.id} material={material || undefined} label="模範解答PDF" inline />
      </aside>
    </div>
  </main>;
}
