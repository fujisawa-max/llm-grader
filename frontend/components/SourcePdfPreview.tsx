"use client";

import { useEffect, useState } from "react";
import type { Material } from "@/types/domain";
import { PdfPaneViewer } from "./PdfPaneViewer";

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "");
type PdfState = "checking" | "ready" | "error";

function PdfFrame({ url, label, state, onRetry, onFrameError }: { url: string; label: string; state: PdfState; onRetry: () => void; onFrameError: () => void }) {
  if (state === "checking") return <p className="loading">PDFを読み込んでいます…</p>;
  if (state === "error") return <div className="error" role="alert"><p>{label}を表示できませんでした。</p><button type="button" className="button secondary" onClick={onRetry}>再試行</button></div>;
  return <iframe className="pdf-frame" src={url} title={label} onError={onFrameError} />;
}

export function SourcePdfPreview({ testId, material, label, inline = false, paneZoom = false }: { testId: string; material?: Material; label: string; inline?: boolean; paneZoom?: boolean }) {
  const [open, setOpen] = useState(false);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<PdfState>(material ? "checking" : "error");
  const url = material ? `${apiBase}/tests/${encodeURIComponent(testId)}/materials/${encodeURIComponent(material.id)}/file` : "";
  const checkedUrl = url ? `${url}?preview=${retry}` : "";
  useEffect(() => {
    if (!url) { setState("error"); return; }
    let active = true;
    setState("checking");
    fetch(checkedUrl, { headers: { Accept: "application/pdf" } }).then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (active) setState("ready");
    }).catch(() => { if (active) setState("error"); });
    return () => { active = false; };
  }, [url, checkedUrl]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  const retryPreview = () => setRetry(value => value + 1);
  if (!material) return <p className="muted">{label}は登録されていません。</p>;
  if (paneZoom) return <PdfPaneViewer url={url} label={label} />;
  if (inline) return <>
    <section className="source-pdf-inline" aria-label={label}><header className="source-pdf-inline-header"><h3>{label}</h3><button type="button" className="button secondary" onClick={() => setOpen(true)} aria-haspopup="dialog">拡大表示</button></header><PdfFrame url={checkedUrl} label={label} state={state} onRetry={retryPreview} onFrameError={() => setState("error")} /></section>
    {open && <div className="pdf-modal" role="dialog" aria-modal="true" aria-label={label} onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="pdf-modal-card"><header className="pdf-modal-header"><h2>{label}</h2><button type="button" className="button secondary" onClick={() => setOpen(false)} autoFocus>閉じる</button></header><PdfFrame url={checkedUrl} label={label} state={state} onRetry={retryPreview} onFrameError={() => setState("error")} /></section>
    </div>}
  </>;
  return <>
    <button type="button" className="button secondary" onClick={() => setOpen(true)} aria-haspopup="dialog">{label}を表示</button>
    {open && <div className="pdf-modal" role="dialog" aria-modal="true" aria-label={label} onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="pdf-modal-card"><header className="pdf-modal-header"><h2>{label}</h2><button type="button" className="button secondary" onClick={() => setOpen(false)} autoFocus>閉じる</button></header><PdfFrame url={checkedUrl} label={label} state={state} onRetry={retryPreview} onFrameError={() => setState("error")} /></section>
    </div>}
  </>;
}
