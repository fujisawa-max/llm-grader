"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from "pdfjs-dist";
import { DiagramOverlay } from './reviews/DiagramOverlay';
import type { DiagramSelection } from './reviews/DiagramReview';

type ZoomMode = "manual" | "width" | "page";

export function PdfPaneViewer({ url, label, targetLocation, diagramSelection }: { diagramSelection?: DiagramSelection; url: string; label: string; targetLocation?: { id: string; page: number; bbox?: number[] } }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [mode, setMode] = useState<ZoomMode>("width");
  const [zoom, setZoom] = useState(100);
  const [shownZoom, setShownZoom] = useState(100);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRef = useRef<ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | null>(null);
  const pointerRef = useRef<{ id: number; x: number; y: number; left: number; top: number; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (document && targetLocation && targetLocation.page >= 1 && targetLocation.page <= document.numPages) {
      setPage(targetLocation.page);
    }
  }, [document, targetLocation?.id, targetLocation?.page]);

  useEffect(() => {
    let active = true;
    let loadingTask: PDFDocumentLoadingTask | null = null;
    const controller = new AbortController();
    setDocument(null);
    setError("");
    void (async () => {
      try {
        const response = await fetch(url, { credentials: "include", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        loadingTask = pdfjs.getDocument({ data: bytes });
        const loaded = await loadingTask.promise;
        if (active) { setDocument(loaded); setPage(1); }
      } catch (cause) {
        if (active) { console.error("PDF pane load failed:", cause instanceof Error ? `${cause.name}: ${cause.message}` : String(cause)); setError("PDFを表示できませんでした。"); }
      }
    })();
    return () => { active = false; controller.abort(); if (loadingTask) void loadingTask.destroy(); };
  }, [url, retry]);

  useEffect(() => {
    const target = viewportRef.current;
    if (!target) return;
    const observer = new ResizeObserver(() => setSize({ width: target.clientWidth, height: target.clientHeight }));
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!document || !canvasRef.current || !size.width || !size.height) return;
    let active = true;
    let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | undefined;
    void (async () => {
      try {
        if (renderRef.current) {
          renderRef.current.cancel();
          try { await renderRef.current.promise; } catch { /* cancelled render */ }
          renderRef.current = null;
        }
        const pdfPage = await document.getPage(page);
        if (!active) return;
        const base = pdfPage.getViewport({ scale: 1 });
        const scale = mode === "width" ? Math.max(0.1, (size.width - 28) / base.width)
          : mode === "page" ? Math.max(0.1, Math.min((size.width - 28) / base.width, (size.height - 28) / base.height))
            : zoom / 100;
        const viewport = pdfPage.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.ceil(viewport.width * dpr);
        canvas.height = Math.ceil(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const canvasContext = canvas.getContext("2d");
        if (!canvasContext) throw new Error("Canvas unavailable");
        task = pdfPage.render({ canvasContext, viewport, transform: [dpr, 0, 0, dpr, 0, 0] });
        renderRef.current = task;
        await task.promise;
        if (active) {
          setShownZoom(Math.round(scale * 100));
          setError("");
          if (targetLocation?.page === page && viewportRef.current) {
            const box = targetLocation.bbox;
            viewportRef.current.scrollLeft = box ? Math.max(0, box[0] * scale - viewportRef.current.clientWidth / 3) : 0;
            viewportRef.current.scrollTop = box ? Math.max(0, box[1] * scale - viewportRef.current.clientHeight / 3) : 0;
          }
        }
      } catch (cause) {
        if (active && !(cause instanceof Error && cause.name === "RenderingCancelledException")) {
          console.error("PDF pane render failed", cause);
          setError("PDFを表示できませんでした。");
        }
      } finally {
        if (renderRef.current === task) renderRef.current = null;
      }
    })();
    return () => { active = false; task?.cancel(); };
  }, [document, page, mode, zoom, size, targetLocation?.id]);

  const step = (direction: number) => { setZoom(Math.max(25, Math.min(400, shownZoom + direction * 25))); setMode("manual"); };
  const endPan = (pointerId: number) => {
    if (pointerRef.current?.id !== pointerId) return;
    pointerRef.current = null;
    setDragging(false);
    if (viewportRef.current?.hasPointerCapture(pointerId)) viewportRef.current.releasePointerCapture(pointerId);
  };
  return <section className="pdf-pane-viewer" aria-label={label}>
    <div className="pdf-pane-toolbar" role="toolbar" aria-label="PDF表示操作">
      <button type="button" aria-label="縮小" onClick={() => step(-1)} disabled={!document}>−</button>
      <span aria-label={`表示倍率 ${shownZoom}%`}>{shownZoom}%</span>
      <button type="button" aria-label="拡大" onClick={() => step(1)} disabled={!document}>＋</button>
      <button type="button" onClick={() => setMode("width")}>幅に合わせる</button>
      <button type="button" onClick={() => setMode("page")}>ページに合わせる</button>
      <button type="button" aria-label="倍率をリセット" onClick={() => { setZoom(100); setMode("manual"); }}>リセット</button>
      <button type="button" aria-label="前のページ" onClick={() => setPage(value => Math.max(1, value - 1))} disabled={!document || page <= 1}>‹</button>
      <span>{page} / {document?.numPages || "–"}</span>
      <button type="button" aria-label="次のページ" onClick={() => setPage(value => Math.min(document?.numPages || 1, value + 1))} disabled={!document || page >= (document?.numPages || 1)}>›</button>
    </div>
    {error && <p className="error" role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>再試行</button></p>}
    {!document && !error && <p className="loading" role="status">PDFを読み込んでいます…</p>}
    <div className={`pdf-pane-viewport ${dragging ? "pdf-pane-dragging" : ""}`} ref={viewportRef}
      onPointerDown={(event) => {
        if (event.button !== 0 || event.target !== canvasRef.current) return;
        pointerRef.current = { id: event.pointerId, x: event.clientX, y: event.clientY,
          left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop, moved: false };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const origin = pointerRef.current;
        if (!origin || origin.id !== event.pointerId) return;
        const dx = event.clientX - origin.x;
        const dy = event.clientY - origin.y;
        if (!origin.moved && Math.hypot(dx, dy) < 4) return;
        origin.moved = true;
        setDragging(true);
        event.currentTarget.scrollLeft = origin.left - dx;
        event.currentTarget.scrollTop = origin.top - dy;
      }}
      onPointerUp={(event) => endPan(event.pointerId)} onPointerCancel={(event) => endPan(event.pointerId)}>
      <div className="pdf-pane-canvas"><canvas ref={canvasRef} aria-label={`${label} ${page}ページ`} role="img" />
        {diagramSelection?.record.page_index === page-1 && <DiagramOverlay key={`${diagramSelection.record.id}:${diagramSelection.manual}:${diagramSelection.record.final_bbox}`} selection={diagramSelection} />}
      </div>
    </div>
  </section>;
}
