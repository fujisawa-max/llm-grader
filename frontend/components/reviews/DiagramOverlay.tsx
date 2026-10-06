"use client";
import { useRef, useState } from "react";
import type { DiagramSelection } from "./DiagramReview";

export function DiagramOverlay({selection}: {selection: DiagramSelection}) {
  const {record, manual, onBounds} = selection;
  const width = Number(record.page_width || 0), height = Number(record.page_height || 0), rotation = Number(record.page_rotation || 0);
  const swapped = rotation === 90 || rotation === 270, vw = swapped ? height : width, vh = swapped ? width : height;
  const start = useRef<number[] | undefined>(undefined), [draft, setDraft] = useState<number[]>();
  const transform = rotation === 90 ? `translate(${height} 0) rotate(90)` : rotation === 180 ? `translate(${width} ${height}) rotate(180)` : rotation === 270 ? `translate(0 ${width}) rotate(270)` : undefined;
  function position(event: React.PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(vw, (event.clientX-rect.left)*vw/rect.width)), y = Math.max(0, Math.min(vh, (event.clientY-rect.top)*vh/rect.height));
    return rotation === 90 ? [y, height-x] : rotation === 180 ? [width-x, height-y] : rotation === 270 ? [width-y, x] : [x, y];
  }
  const box = draft || record.final_bbox || record.automatic_bbox;
  if (!width || !height || !box) return null;
  return <svg className={`diagram-overlay ${manual ? "diagram-selecting" : ""}`} viewBox={`0 0 ${vw} ${vh}`} aria-label={manual ? "図の範囲を矩形選択" : "図の選択範囲"}
    onPointerDown={e => {if (!manual || e.button !== 0) return; e.stopPropagation(); start.current = position(e); e.currentTarget.setPointerCapture(e.pointerId); setDraft(undefined);}}
    onPointerMove={e => {if (!start.current) return; const p = position(e), a = start.current; setDraft([Math.min(a[0], p[0]), Math.min(a[1], p[1]), Math.max(a[0], p[0]), Math.max(a[1], p[1])]);}}
    onPointerUp={e => {if (!start.current) return; const p = position(e), a = start.current; const b = [Math.min(a[0], p[0]), Math.min(a[1], p[1]), Math.max(a[0], p[0]), Math.max(a[1], p[1])]; start.current = undefined; setDraft(b); if(b[2]>b[0] && b[3]>b[1]) onBounds?.(b);}}
    onPointerCancel={() => {start.current = undefined; setDraft(undefined);}}>
    <g transform={transform}><rect data-diagram-highlight={record.id} x={box[0]} y={box[1]} width={box[2]-box[0]} height={box[3]-box[1]} /></g>
  </svg>;
}
