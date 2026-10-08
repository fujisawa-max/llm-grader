"use client";
import {useId,type ReactNode} from "react";

/** Disabled controls cannot receive keyboard focus; their hint wrapper can. */
export function DisabledActionHint({reason,children}:{reason?:string;children:ReactNode}){
  const id=useId();
  return <span className="disabled-action-hint" tabIndex={reason?0:undefined} role={reason?"group":undefined} aria-label={reason?"解析できない理由":undefined} aria-describedby={reason?id:undefined}>
    {children}
    {reason&&<span id={id} role="tooltip" className="disabled-action-tooltip">{reason}</span>}
  </span>;
}
