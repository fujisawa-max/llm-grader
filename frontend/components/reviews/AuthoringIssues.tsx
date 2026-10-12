"use client";
import {useEffect, useRef, useState} from "react";
import type {AuthoringIssue} from "@/lib/api/testAuthoring";

export function AuthoringIssueCards({issues,pathFor,onAction}:{issues:AuthoringIssue[];pathFor:(key:string)=>string;onAction:(issue:AuthoringIssue)=>void}){
  return <div className="authoring-issue-cards">{issues.map((issue,index)=>{
    const category=issue.field==="score"||issue.field==="total"?"配点":issue.field==="source"||issue.correction_type?"出典":({question:"問題",answer:"模範解答",rubric:"採点基準",source:"出典",metadata:"配点",save:"保存",publication:"確定"}[issue.section]||"内容");
    return <article key={`${issue.question_key}:${issue.entry_id}:${issue.code}:${index}`}>
      <h3>{issue.question_key?`${pathFor(issue.question_key)} — `:""}{category}</h3><p>{issue.message}</p>
      {issue.current_state&&<p className="authoring-issue-current">{issue.current_state}</p>}
      <p>{issue.expected_state||"該当する編集欄で内容を確認・修正し、保存してください。"}</p>
      <button type="button" onClick={()=>onAction(issue)}>{issue.action_label||({question:"問題を修正",answer:"模範解答を確認",rubric:"採点基準を修正",source:"出典を確認",metadata:"合計点を修正",save:"保存する"}[issue.section]||"内容を確認")}</button>
    </article>;
  })}</div>;
}

export function QuestionIssueOverlay({questionKey,label,issues,onAction,pathFor}:{questionKey:string;label:string;issues:AuthoringIssue[];onAction:(issue:AuthoringIssue)=>void;pathFor:(key:string)=>string}){
  const [open,setOpen]=useState(false),trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLElement>(null);
  useEffect(()=>{setOpen(false);},[questionKey]);
  useEffect(()=>{
    if(!open)return;
    const escape=(event:KeyboardEvent)=>{if(event.key==="Escape"){event.preventDefault();setOpen(false);trigger.current?.focus({preventScroll:true});}};
    document.addEventListener("keydown",escape);return()=>document.removeEventListener("keydown",escape);
  },[open]);
  if(!issues.length)return null;
  return <div className="authoring-question-issues">
    <button ref={trigger} type="button" className="authoring-question-issues-tab" aria-label={`要修正 ${issues.length}件`} aria-expanded={open} aria-controls="authoring-question-issues-panel" onClick={()=>setOpen(value=>!value)}><span aria-hidden="true">要<br/>修<br/>正<br/>({issues.length})</span></button>
    {open&&<section ref={panel} id="authoring-question-issues-panel" className="authoring-question-issues-panel" aria-label={`${label}の要修正`}><header><strong>{label}の要修正 {issues.length}件</strong><button type="button" aria-label="要修正を閉じる" onClick={()=>{setOpen(false);trigger.current?.focus({preventScroll:true});}}>×</button></header><AuthoringIssueCards issues={issues} pathFor={pathFor} onAction={issue=>{setOpen(false);onAction(issue);}}/></section>}
  </div>;
}
