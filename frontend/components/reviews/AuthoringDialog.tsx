"use client";
import {useEffect,useId,useRef,type ReactNode} from "react";

/** Native modal lifecycle shared by authoring confirmations and proposal review. */
export function AuthoringDialog({title,children,actions,onCancel,busy=false}:{title:string;children:ReactNode;actions:ReactNode;onCancel:()=>void;busy?:boolean}) {
  const dialog=useRef<HTMLDialogElement>(null),titleId=useId(),descriptionId=useId();
  useEffect(()=>{
    const element=dialog.current,previous=document.activeElement as HTMLElement|null;
    const previousOverflow=document.body.style.overflow;
    document.body.style.overflow="hidden";
    element?.showModal();
    return()=>{element?.close();document.body.style.overflow=previousOverflow;if(previous?.isConnected)previous.focus();};
  },[]);
  return <dialog ref={dialog} className="authoring-analysis-dialog authoring-proposal-dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} onKeyDown={event=>{
    if(event.key!=="Tab")return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'));
    if(!controls.length){event.preventDefault();return;}
    if(event.shiftKey&&document.activeElement===controls[0]){event.preventDefault();controls.at(-1)?.focus();}
    else if(!event.shiftKey&&document.activeElement===controls.at(-1)){event.preventDefault();controls[0].focus();}
  }} onCancel={event=>{event.preventDefault();if(!busy)onCancel();}}>
    <h2 id={titleId}>{title}</h2><div id={descriptionId} className="authoring-dialog-body">{children}</div><div className="authoring-analysis-dialog-actions">{actions}</div>
  </dialog>;
}
