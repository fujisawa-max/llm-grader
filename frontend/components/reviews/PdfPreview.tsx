"use client";
import { useEffect, useState } from "react";
import { reviews } from "@/lib/api/reviews";
import type { PreviewMetadata } from "@/types/reviews";

export function PdfPreview({ id, page, pages, selected, onPage, revision }: {
  revision?: number; id: string; page: number; pages: number; selected: string; onPage: (page: number) => void;
}) {
  const [meta, setMeta] = useState<PreviewMetadata>();
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    setMeta(undefined); setError(""); setLoaded(false);
    reviews.metadata(id, page, revision).then(m => { if (active) setMeta(m); })
      .catch(() => { if (active) setError("原PDFプレビューを読み込めません。再読み込みしてください。"); });
    return () => { active = false; };
  }, [id, page, revision]);
  return <section className="panel review-preview" aria-label="原PDFプレビュー">
    <div className="review-toolbar"><h2>元の問題用紙</h2><button disabled={page === 0} onClick={() => onPage(page - 1)}>前のページ</button>
      <span>{page + 1} / {pages} ページ</span><button disabled={page + 1 === pages} onClick={() => onPage(page + 1)}>次のページ</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!loaded && !error && <p role="status">ページを読み込み中…</p>}
    <div className="review-preview-viewport">{meta && <div className="review-preview-image">
      {/* Native PNG uses the hash-checked review endpoint, not Next image optimization. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={reviews.previewUrl(id, page)} alt={`原PDF ${page + 1}ページ`} width={meta.preview_width} height={meta.preview_height}
        onLoad={() => setLoaded(true)} onError={() => setError("プレビュー画像の取得に失敗しました。")} />
      <svg viewBox={`0 0 ${meta.preview_width} ${meta.preview_height}`} aria-label="選択範囲" className="review-highlights">
        {meta.regions.filter(r => r.source_id === selected).map((r, i) => <rect key={i} data-source-id={r.source_id}
          x={r.pixel_bbox[0]} y={r.pixel_bbox[1]} width={r.pixel_bbox[2] - r.pixel_bbox[0]} height={r.pixel_bbox[3] - r.pixel_bbox[1]}
          className={r.source_type === "node" ? "highlight-node" : "highlight-region"} />)}
      </svg>
    </div>}</div>
    <p className="muted">選択した問題・数式・図の原文位置。出典情報を持たない追加問題には原文位置がありません。</p>
  </section>;
}
