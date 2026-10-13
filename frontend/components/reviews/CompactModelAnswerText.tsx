"use client";
import {useState} from "react";
import {AuthoringDialog} from "./AuthoringDialog";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import type {LatexProposal,MathSource} from "@/lib/api/textTools";
import {reviewCandidateId} from "@/lib/reviewCandidateId";
export function ModelAnswerTextDialog({text,disabled,source,latexDisabled=false,onCancel,onDone}:{text:string;disabled:boolean;source?:MathSource;latexDisabled?:boolean;onCancel:()=>void;onDone:(text:string,proposal?:LatexProposal)=>void}){
  const [draft,setDraft]=useState(text),[applied,setApplied]=useState<LatexProposal>();
  return <AuthoringDialog title="模範解答本文" onCancel={onCancel} actions={<><button onClick={onCancel}>キャンセル</button><button disabled={disabled} onClick={()=>onDone(draft,applied)}>完了</button></>}>
    <label>模範解答本文<textarea aria-label="模範解答本文" autoFocus rows={4} maxLength={100000} disabled={disabled} value={draft} onChange={e=>setDraft(e.target.value)} style={{resize:"vertical"}}/></label>
    <LatexNormalizationControl text={draft} contextType="model_answer" source={source} disabled={disabled||latexDisabled} onApply={(value,proposal)=>{setDraft(value);setApplied(proposal);}}/>
  </AuthoringDialog>;
}
export function CompactModelAnswerText({text,label,alternatives=[],disabled,source,onText,onAlternatives,latexDisabled=false,addLabel="別解を追加"}:{text:string;label:string;alternatives?:{id:string;text:string}[];disabled:boolean;source?:MathSource;latexDisabled?:boolean;addLabel?:string;onText:(text:string,proposal?:LatexProposal)=>void;onAlternatives:(values:{id:string;text:string}[])=>void}){
  const [edit,setEdit]=useState<{id:string|null;text:string;create?:boolean}|null>(null);
  return <div className="compact-model-answer-text">
    <div className="compact-rubric-criterion-header authoring-content-header"><h3>{label}</h3><button data-answer-edit disabled={disabled} onClick={()=>setEdit({id:null,text})}>編集</button></div>
    <div className="authoring-question-preview-frame authoring-answer-preview-frame"><MarkdownMathText source={text||"本文なし"}/></div>
    {alternatives.map((a,index)=><section className="compact-model-answer-alternative" key={a.id} aria-label={`${label} 別解${index+1}`}><div className="compact-rubric-criterion-header authoring-content-header"><h3>{label} — 別解{index+1}</h3><button disabled={disabled} onClick={()=>setEdit({id:a.id,text:a.text})}>編集</button></div><div className="authoring-question-preview-frame authoring-answer-preview-frame"><MarkdownMathText source={a.text||"本文なし"}/></div><details><summary>別解の操作</summary><button disabled={disabled} onClick={()=>onAlternatives(alternatives.filter(value=>value.id!==a.id))}>この別解を削除</button></details></section>)}
    <button disabled={disabled} onClick={()=>setEdit({id:reviewCandidateId("teacher-alternative"),text:"",create:true})}>{addLabel}</button>
    {edit&&<ModelAnswerTextDialog text={edit.text} disabled={disabled} latexDisabled={latexDisabled} source={edit.id===null?source:undefined} onCancel={()=>setEdit(null)} onDone={(value,proposal)=>{if(edit.id===null)onText(value,proposal);else if(edit.create||value!==edit.text)onAlternatives(edit.create?[...alternatives,{id:edit.id,text:value}]:alternatives.map(a=>a.id===edit.id?{...a,text:value}:a));setEdit(null);}}/>}
  </div>;
}
