"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { reviews } from "@/lib/api/reviews";
import type { ReviewEntry } from "@/types/reviews";
import { TechnicalDetails } from "@/components/ui";

export function ReviewEntries({ testId }: { testId: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<ReviewEntry[]>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { reviews.list(testId).then(setRows).catch((e: unknown) => { if ((e as {status?: number}).status === 404) setRows([]); else setError("確認情報を取得できませんでした。"); }); }, [testId]);
  async function open(row: ReviewEntry) {
    setBusy(true); setError("");
    try { if (row.id) await reviews.get(row.id); const id = row.id || (await reviews.create(row.draft_id)).id; router.push(`/question-import-reviews/${id}`); }
    catch { setError("問題の読み取り確認を開始できませんでした。元の問題用紙と通信状態を確認してください。"); setBusy(false); }
  }
  return <section className="panel section"><h2>問題の読み取り確認</h2>
    {error && <><p role="alert" className="error">{error}</p><TechnicalDetails label="詳細を表示"><p>Question import review endpoint did not respond.</p></TechnicalDetails></>}{!rows && !error && <p>読み込み中…</p>}
    {rows?.length === 0 && <p className="muted">確認が必要な項目はありません。</p>}
    {rows?.map(row => <article className="review-entry" key={row.draft_id}><h3>{row.source_filename}</h3>
      <p>{row.question_count}問 · 図の読み取り {row.has_vision ? "あり" : "なし"}</p>
      <p>{row.warning_count ? `確認事項 ${row.warning_count}件` : "確認事項なし"}</p>
      <TechnicalDetails label="技術情報"><p>取り込み状態: {row.state} · 更新履歴: {row.current_revision ?? "—"}</p><p>{row.parser_version} · {row.draft_created_at}</p></TechnicalDetails>
      {row.resume_error_code && <p role="status">元資料または保存済み内容の整合性を確認できないため再開できません。</p>}
      <button className="button secondary" disabled={busy || !!row.resume_error_code} onClick={() => open(row)}>{row.id ? "前回の解析結果を編集" : "確認を開始"}</button>
    </article>)}
  </section>;
}
