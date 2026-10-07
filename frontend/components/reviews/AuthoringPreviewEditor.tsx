"use client";
import {useId, useRef, type ReactNode} from "react";
import type {DiagramRecord} from "@/types/diagrams";

/** Switching presentation keeps the active editor DOM and native editing history. */
export function AuthoringPreviewEditor({label, editing, onEditing, preview, children}:{
  label:string; editing:boolean; onEditing:(value:boolean)=>void; preview:ReactNode; children:ReactNode;
}) {
  const id=useId(),body=useRef<HTMLDivElement>(null);
  const lastEditor=useRef<HTMLTextAreaElement|null>(null);
  return <div className="authoring-preview-editor" aria-label={`${label}の表示切替`}>
    <button type="button" aria-expanded={editing} aria-controls={id} onClick={()=>{
      onEditing(!editing);
      if(!editing)requestAnimationFrame(()=>{
        const target=lastEditor.current?.isConnected?lastEditor.current:body.current?.querySelector<HTMLTextAreaElement>("textarea");
        target?.focus({preventScroll:true});
      });
    }}>{editing?"プレビューを見る":"編集する"}</button>
    <div hidden={editing} className="authoring-current-preview" aria-label={`${label}プレビュー`}>{preview}</div>
    <div ref={body} id={id} hidden={!editing} className="authoring-edit-body" onFocusCapture={e=>{
      if(e.target instanceof HTMLTextAreaElement)lastEditor.current=e.target;
    }}>{children}</div>
  </div>;
}
export function AcceptedDiagramPreview({records=[],path,questionKey}:{records?:DiagramRecord[];path?:string;questionKey?:string}) {
  return <div className="authoring-accepted-diagrams">{records.filter(r=>r.state==="accepted"&&r.trust_state!=="hard_invalid").map((r,index)=>{
    const params=new URLSearchParams({crop_sha:r.crop_sha256||"",scope:r.scope||"exact"});
    if(questionKey)params.set("question_id",questionKey);if(r.reuse_ref)params.set("reuse_ref",r.reuse_ref);
    const url=path&&r.crop_sha256?`/api/v1${path}/${encodeURIComponent(r.id)}/crop?${params}`:r.preview_url;
    return <figure key={r.id}>{url&&<img className="review-crop" src={url} alt={`使用中の図${index+1}`} /* eslint-disable-line @next/next/no-img-element */ />}
      <figcaption>使用中の図{index+1} — ページ {r.page_index+1}</figcaption></figure>;
  })}</div>;
}
