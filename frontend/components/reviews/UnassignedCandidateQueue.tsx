"use client";
import {useState} from "react";
import {AcceptedDiagramPreview} from "./AuthoringPreviewEditor";
import type {DiagramRecord} from "@/types/diagrams";
import {AuthoringDialog} from "./AuthoringDialog";
import {MarkdownMathText} from "@/components/MarkdownMathText";
export interface QueueCandidate {key:string;id:string;domain:"answer"|"rubric";text:string;source:string;excluded:boolean;recovery?:boolean;diagrams?:DiagramRecord[]}
/** Presentation only: all decisions go through the owning domain's existing draft operation. */
export function UnassignedCandidateQueue({candidates,questions,disabled,onAssign,onExclude,onRestore}:{candidates:QueueCandidate[];questions:{key:string;label:string}[];disabled:boolean;onAssign:(candidate:QueueCandidate,key:string)=>void;onExclude:(candidates:QueueCandidate[])=>void;onRestore:(candidate:QueueCandidate)=>void}) {
  const [filter,setFilter]=useState("all"),[selection,setSelection]=useState<string[]>([]),[confirm,setConfirm]=useState(false),[feedback,setFeedback]=useState("");
  const shown=candidates.filter(c=>filter==="all"||c.domain===filter);
  const selected=candidates.filter(c=>!c.excluded&&selection.includes(c.key));
  const label=(domain:string)=>domain==="answer"?"模範解答":"採点基準";
  const count=(domain:string)=>candidates.filter(c=>!c.excluded&&(domain==="all"||c.domain===domain)).length;
  return <section id="authoring-unassigned" aria-label="設問未割当の候補">
    <h2>設問未割当の候補 ({count("all")})</h2>
    <p>この候補を対応する設問へ割り当てるか、不要な候補として除外してください。</p>
    <div className="review-toolbar" aria-label="候補の種類">{[["all","すべて"],["answer","模範解答"],["rubric","採点基準"]].map(([key,title])=><button key={key} type="button" aria-pressed={filter===key} onClick={()=>setFilter(key)}>{title}({count(key)})</button>)}</div>
    <div className="review-toolbar"><span role="status">{selected.length}件選択中</span><button disabled={disabled} onClick={()=>setSelection([...new Set([...selection,...shown.filter(c=>!c.excluded).map(c=>c.key)])])}>すべて選択</button><button disabled={disabled||!selected.length} onClick={()=>setSelection([])}>選択解除</button><button disabled={disabled||!selected.length} onClick={()=>setConfirm(true)}>選択した候補を不要として除外</button></div>
    {feedback&&<p role="status">{feedback}</p>}
    {shown.map(c=><article key={c.key} className="panel" id={`${c.recovery?"authoring-recovery":"authoring-candidate"}-${c.id}`}>
      <label><input type="checkbox" aria-label={`${label(c.domain)}候補 ${c.id}を選択`} disabled={disabled||c.excluded} checked={!c.excluded&&selection.includes(c.key)} onChange={e=>setSelection(v=>e.target.checked?[...v,c.key]:v.filter(k=>k!==c.key))}/>{label(c.domain)} — <span role="status">{c.excluded?"除外済み":"未割当"}</span></label>
      <section className="authoring-candidate-resolution"><div className="authoring-candidate-resolution-text" aria-label="未割当候補の本文"><MarkdownMathText source={c.text||"本文なし"}/></div>{c.diagrams&&<AcceptedDiagramPreview records={c.diagrams}/>}<p className="muted">{c.source}</p>
      {!c.excluded?<><label>対応する設問<select aria-label="対応する設問" value="" disabled={disabled} onChange={e=>{onAssign(c,e.target.value);setSelection(v=>v.filter(k=>k!==c.key));}}><option value="">設問を選択</option>{questions.map(q=><option key={q.key} value={q.key}>{q.label}</option>)}</select></label><button disabled={disabled} onClick={()=>{onExclude([c]);setSelection(v=>v.filter(k=>k!==c.key));}}>{c.recovery?"不要として除外（無視）":"不要として除外"}</button></>:<button disabled={disabled} onClick={()=>onRestore(c)}>未割当に戻す</button>}
    </section></article>)}
    {!shown.length&&<p>該当する候補はありません。</p>}
    {confirm&&<AuthoringDialog title={`${selected.length}件の候補を不要として除外しますか？`} onCancel={()=>setConfirm(false)} actions={<><button onClick={()=>setConfirm(false)}>キャンセル</button><button disabled={disabled||!selected.length} onClick={()=>{onExclude(selected);setFeedback(`${selected.length}件を除外しました。保存すると記録されます。`);setSelection([]);setConfirm(false);}}>{selected.length}件を除外</button></>}><p>模範解答: {selected.filter(c=>c.domain==="answer").length}件</p><p>採点基準: {selected.filter(c=>c.domain==="rubric").length}件</p></AuthoringDialog>}
  </section>;
}
