"use client";
import {type ReactNode,useEffect,useRef,useState} from "react";
import type {DiagramRecord} from "@/types/diagrams";
import {AcceptedDiagramPreview} from "./AuthoringPreviewEditor";
/** Presentation only: record ownership, review and persistence stay with DiagramReview. */
export function AuthoringFigure({records=[],path,questionKey,sourceStale=false,reviewRequired=false,scopeKey,children}:{records?:DiagramRecord[];path?:string;questionKey?:string;sourceStale?:boolean;reviewRequired?:boolean;scopeKey:string;children?:ReactNode}){
  const details=useRef<HTMLDetailsElement>(null),[expanded,setExpanded]=useState(false);
  useEffect(()=>{if(details.current)details.current.open=false;setExpanded(false);},[scopeKey]);
  const accepted=records.filter(r=>r.state==="accepted"&&r.trust_state!=="hard_invalid");
  const pending=reviewRequired||sourceStale||records.some(r=>r.state==="candidate"||r.trust_state==="hard_invalid"&&r.state!=="excluded");
  return <section className="authoring-current-figure" aria-label="現在の図">
    <h3>図</h3>
    {accepted.length&&!sourceStale?<AcceptedDiagramPreview records={accepted} path={path} questionKey={questionKey}/>:<p className="muted">図は登録されていません。</p>}
    {pending&&<p role="status">図の出典・範囲に確認が必要です。</p>}
    {children&&<details ref={details} data-authoring-figure-operations onToggle={e=>setExpanded(e.currentTarget.open)}><summary aria-expanded={expanded}>{expanded?"▼":"▶"} 図を編集・確認</summary>{children}</details>}
  </section>;
}
