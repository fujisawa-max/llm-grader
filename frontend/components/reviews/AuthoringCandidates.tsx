"use client";
import {useEffect, useRef, useState} from "react";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {AuthoringPreviewEditor, AcceptedDiagramPreview} from "./AuthoringPreviewEditor";
import {DiagramReview, type DiagramSelection} from "./DiagramReview";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import {apiFetch, json} from "@/lib/api/client";
import {reviewCandidateId} from "@/lib/reviewCandidateId";
import {rubricRows, rubricGroupRows, mergeRubricRows, rubricCriterionLabel, rubricSplitOffset} from "@/lib/rubricEditing";
import type {ModelAnswerDraftEntry, ModelAnswerContentCategory, RubricCandidateEdit, RubricSplitProposal, RubricConsolidatedGroup} from "@/lib/api/modelAnswerImports";

export type AuthoringEntry=ModelAnswerDraftEntry & {authoring_question_key?:string|null;manual_alternative_answers?:{id:string;text:string}[]};
export function AuthoringCandidates({testId, draftId, revision, questionKey, entries, savedEntries, questions, disabled, showAnswer, showRubric, sourceStale = false, answerEditing, rubricEditing, onAnswerEditing, onRubricEditing, onChange, onSelect}: {
  testId:string; draftId:string; revision:number; questionKey:string; entries:AuthoringEntry[]; savedEntries:AuthoringEntry[];
  questions:{key:string;label:string;gradable:boolean;sourceId?:string}[]; disabled:boolean; showAnswer:boolean; showRubric:boolean;
  sourceStale?:boolean;
  answerEditing:boolean; rubricEditing:boolean; onAnswerEditing:(value:boolean)=>void; onRubricEditing:(value:boolean)=>void;
  onChange:(entries:AuthoringEntry[],domain?:"answer"|"rubric"|"diagram")=>void; onSelect:(selection:DiagramSelection)=>void;
}) {
  const [selected,setSelected]=useState<Record<string,string[]>>({});
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [proposal,setProposal]=useState<{entryId:string;item:RubricCandidateEdit;original:string;baseline:string;split:RubricSplitProposal}|null>(null);
  const [groups,setGroups]=useState<{entryId:string;rows:RubricCandidateEdit[];baseline:string}|null>(null);
  const textareas=useRef<Record<string,HTMLTextAreaElement|null>>({});
  const activeCriterion=useRef<string|null>(null);
  const [splitting,setSplitting]=useState<string|null>(null);
  const splitInFlight=useRef(false);
  const epoch=useRef("");const requestEpoch=useRef(0);
  const nextScope=`${questionKey}:${revision}`;
  if(epoch.current!==nextScope){epoch.current=nextScope;requestEpoch.current++;}
  useEffect(()=>{setProposal(null);setGroups(null);setError("");setBusy(false);},[questionKey,revision]);
  const current=useRef(entries);current.current=entries;
  const changeRef=useRef(onChange);changeRef.current=onChange;
  const update=(id:string,patch:Partial<AuthoringEntry>)=>changeRef.current(current.current.map(e=>e.id===id?{...e,...patch}:e),patch.diagram_records?"diagram":patch.rubric_edits||patch.rubric_merge_history?"rubric":"answer");
  const rows=(entry:AuthoringEntry,next:RubricCandidateEdit[])=>update(entry.id,{rubric_edits:next,
    rubric_merge_history:[...(entry.rubric_merge_history||[]),rubricRows(entry)].slice(-50)});
  async function split(entry:AuthoringEntry,item:RubricCandidateEdit,manual:boolean){
    if(splitInFlight.current)return;
    const token=requestEpoch.current;setError("");setProposal(null);
    const text=item.description;
    try {
      const target=`${entry.id}:${item.id}`,control=textareas.current[target];
      if(manual&&(!control||activeCriterion.current!==target))throw new Error("分割する基準の本文欄にカーソルを置いてください。");
      const offset=manual?rubricSplitOffset(text,control!.selectionStart):undefined;
      splitInFlight.current=true;setBusy(true);setSplitting(target);
      const result=await apiFetch<RubricSplitProposal>(`/tests/${testId}/authoring/entries/${entry.id}/rubric-split`,json({expected_revision:revision,candidate_id:item.id,text,question_key:questionKey,...(manual?{offset}:{})}));
      if(requestEpoch.current===token){if(result.split)setProposal({entryId:entry.id,item,original:text,baseline:JSON.stringify(item),split:result});else setError("この候補は1つの採点基準として扱う提案です。");}
    }catch(e){if(requestEpoch.current===token)setError(e instanceof Error?e.message:"分割案を取得できませんでした。");}
    finally{splitInFlight.current=false;if(requestEpoch.current===token){setBusy(false);setSplitting(null);}}
  }
  async function consolidate(entry:AuthoringEntry){const token=requestEpoch.current;setBusy(true);setError("");try{
    const result=await apiFetch<{groups:RubricConsolidatedGroup[]}>(`/tests/${testId}/authoring/entries/${entry.id}/rubric-consolidate`,json({expected_revision:revision,criteria:rubricRows(entry).filter(c=>!c.excluded).map(c=>({id:c.id,description:c.description,points:c.points}))}));
    const original=rubricRows(entry);
    const projected=rubricGroupRows(result.groups).map(group=>{
      const inputs=original.filter(c=>group.segment_ids?.includes(c.id));
      const ids=[...new Set(inputs.flatMap(c=>c.segment_ids||[]))];
      const merged=inputs.length>1?mergeRubricRows(entry,inputs.map(c=>c.id),"manual_multi")?.rubric_edits.find(c=>!original.some(o=>o.id===c.id)):inputs[0];
      return {...group,segment_ids:ids,provenance:{...merged?.provenance,...(!ids.length?{source:"teacher_manual"}:{}),source_candidate_ids:inputs.map(c=>c.id),previous_operations:inputs.map(c=>c.provenance||{}),merge_type:"llm_consolidation"}};
    });
    if(requestEpoch.current===token)setGroups({entryId:entry.id,rows:projected,baseline:JSON.stringify(original)});
  }catch(e){if(requestEpoch.current===token)setError(e instanceof Error?e.message:"統合案を取得できませんでした。");}finally{if(requestEpoch.current===token)setBusy(false);}}
  const visible=entries.filter(e=>e.authoring_question_key===questionKey||(questionKey==="unassigned"&&!e.authoring_question_key));
  const addAnswer=<button disabled={disabled||questionKey==="unassigned"} onClick={()=>onChange([...entries,{id:reviewCandidateId("teacher-entry"),question_id:null,authoring_question_key:questionKey,
      mapping_state:"manual_mapped",disposition:"include",answer_kind:visible.some(e=>(e.answer_kind||"primary")==="primary"&&e.disposition!=="ignored")?"alternative":"primary",answer_text:"",
      source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]}}])}>模範解答を追加</button>;
  return <div aria-label="出典付き解答・採点基準">
    {error&&<p role="alert">{error}</p>}
    {visible.map((entry,entryIndex)=><article key={entry.id} id={`authoring-candidate-${entry.id}`}>
      {showAnswer&&<section aria-label="模範解答候補"><h3>模範解答候補</h3><AuthoringPreviewEditor editLabel="本文編集" label="解答" editing={answerEditing} onEditing={onAnswerEditing} preview={<><MarkdownMathText source={entry.answer_text||"本文なし"}/><AcceptedDiagramPreview records={sourceStale?[]:entry.diagram_records} path={`/tests/${testId}/authoring/entries/${entry.id}/diagrams`} questionKey={entry.authoring_question_key||undefined}/>{(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers||[]).map((a,i)=><div key={i}><h4>別解{i+1}</h4><MarkdownMathText source={a.text}/></div>)}</>}><fieldset disabled={disabled||busy}>
        <label>候補の扱い<select value={entry.disposition||"include"} onChange={e=>update(entry.id,{disposition:e.target.value as AuthoringEntry["disposition"],...(e.target.value==="unassigned"?{authoring_question_key:null}:{})})}><option value="include">使用する</option><option value="ignored">対象外</option><option value="unassigned">設問未割当</option></select></label>
        <label>解答の種類<select value={entry.answer_kind||"primary"} onChange={e=>update(entry.id,{answer_kind:e.target.value as AuthoringEntry["answer_kind"]})}><option value="primary">模範解答</option><option value="alternative">別解</option></select></label>
        <label>対応する設問<select aria-label="対応する設問" value={entry.authoring_question_key||""} onChange={e=>update(entry.id,{authoring_question_key:e.target.value||null,disposition:e.target.value?"include":"unassigned",mapping_state:e.target.value?"manual_mapped":"needs_review"})}><option value="">設問未割当</option>{questions.filter(q=>q.gradable).map(q=><option key={q.key} value={q.key}>{q.label}</option>)}</select></label>
        <label>模範解答本文<textarea aria-label="模範解答本文" rows={4} maxLength={100000} value={entry.answer_text} onChange={e=>update(entry.id,{answer_text:e.target.value})}/></label>
      </fieldset>
      <LatexNormalizationControl text={entry.answer_text} contextType="model_answer" disabled={disabled||busy||sourceStale}
        source={entry.source.segments.length&&savedEntries.some(e=>e.id===entry.id)?{draftId,entryId:entry.id,revision,authoringTestId:testId}:undefined}
        onApply={(text,proposal)=>update(entry.id,{answer_text:text,teacher_correction:{...entry.teacher_correction,teacher_confirmed:true,latex_normalization:{status:proposal.status,profile:proposal.profile,model:proposal.model,source:proposal.source,regions:proposal.math_regions?.map(r=>({page_index:r.page_index,bbox:r.bbox,crop_bbox:r.crop_bbox,segment_ids:r.segment_ids,grouping_method:r.grouping_method,ricoh_used:r.ricoh_used,ornith_used:r.ornith_used})),timestamp:new Date().toISOString()}}})}/>
      {(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers?.map(a=>({id:`source-alternative:${a.segment_ids.join(":")}`,text:a.text}))||[]).map((alternative,index,all)=><label key={alternative.id}>別解{index+1}<textarea aria-label={`別解${index+1}`} disabled={disabled||busy} value={alternative.text} onChange={e=>update(entry.id,{manual_alternative_answers:all.map(a=>a.id===alternative.id?{...a,text:e.target.value}:a)})}/></label>)}
      <button disabled={disabled||busy} onClick={()=>update(entry.id,{manual_alternative_answers:[...(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers?.map(a=>({id:`source-alternative:${a.segment_ids.join(":")}`,text:a.text}))||[]),{id:reviewCandidateId("teacher-alternative"),text:""}]})}>別解を追加</button>
      <details><summary>保存済みの本文</summary><pre>{savedEntries.find(e=>e.id===entry.id)?.answer_text||"本文なし"}</pre></details>
      <DiagramReview path={`/tests/${testId}/authoring/entries/${entry.id}/diagrams`} revision={revision} targetQuestionId={entry.authoring_question_key||undefined} assignmentQuestionId={questions.find(q=>q.key===entry.authoring_question_key)?.sourceId}
        records={entry.diagram_records} sourceStale={sourceStale} disabled={disabled||busy||!entry.authoring_question_key} disabledReason={!entry.authoring_question_key?"図の対応先の設問を選択してください。":undefined} label="模範解答の図"
        onChange={records=>update(entry.id,{diagram_records:records})} onSelect={onSelect}/></AuthoringPreviewEditor>
      {entry.semantic_classification&&showAnswer&&answerEditing&&<details><summary>候補の分類を確認</summary>{entry.semantic_classification.segments.map(segment=><label key={segment.id}>{segment.text}<select disabled={disabled||busy} value={segment.category} onChange={e=>update(entry.id,{semantic_classification:{...entry.semantic_classification!,segments:entry.semantic_classification!.segments.map(s=>s.id===segment.id?{...s,category:e.target.value as ModelAnswerContentCategory}:s)}})}>{([['question','問題文'],['model_answer','模範解答'],['alternative_answer','別解'],['rubric','採点基準'],['note','補足'],['uncertain','要確認']] as const).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>)}<button disabled={disabled||busy} onClick={()=>update(entry.id,{semantic_classification:{...entry.semantic_classification!,status:"teacher_reviewed"}})}>この分類を確認</button></details>}
      {entryIndex===visible.length-1&&addAnswer}
      </section>}
      {showRubric&&<section aria-label="採点基準候補"><h3>採点基準候補</h3><AuthoringPreviewEditor label="採点基準" editing={rubricEditing} onEditing={onRubricEditing} preview={<>{rubricRows(entry).filter(c=>!c.excluded).map((c,i)=><article className="panel" key={c.id}><h4>{rubricCriterionLabel(i)}</h4><MarkdownMathText source={c.description}/><p>{c.points}点</p></article>)}</>}>
        <button disabled={disabled||busy} onClick={()=>rows(entry,[...rubricRows(entry),{id:reviewCandidateId("teacher-rubric"),description:"",points:0,segment_ids:[],grouping_confirmed:true,grouping_method:"teacher_manual",provenance:{source:"teacher_manual",manual_add:true}}])}>基準を追加</button>
        <button disabled={disabled||busy||!entry.rubric_merge_history?.length} onClick={()=>update(entry.id,{rubric_edits:entry.rubric_merge_history!.at(-1),rubric_merge_history:entry.rubric_merge_history!.slice(0,-1)})}>編集を元に戻す</button>
        <button disabled={disabled||busy||(selected[entry.id]||[]).length<2} onClick={()=>{const result=mergeRubricRows(entry,selected[entry.id],"manual_multi");if(result)update(entry.id,result);setSelected(s=>({...s,[entry.id]:[]}));}}>選択した基準を結合</button>
        <button disabled={disabled||busy||!rubricRows(entry).some(c=>!c.excluded&&c.description.trim())} onClick={()=>void consolidate(entry)}>採点基準の統合案を作成</button>
        {rubricRows(entry).map((item,index,all)=><fieldset key={item.id} disabled={disabled||busy} id={`authoring-rubric-${item.id}`}>
          <label><input type="checkbox" checked={(selected[entry.id]||[]).includes(item.id)} onChange={e=>setSelected(s=>({...s,[entry.id]:e.target.checked?[...(s[entry.id]||[]),item.id]:(s[entry.id]||[]).filter(id=>id!==item.id)}))}/>{rubricCriterionLabel(index)}</label>
          <label>本文<textarea aria-label={`${rubricCriterionLabel(index)}の本文`} ref={element=>{textareas.current[`${entry.id}:${item.id}`]=element;}} value={item.description} onFocus={()=>{activeCriterion.current=`${entry.id}:${item.id}`;}} onChange={e=>update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,description:e.target.value}:c)})}/></label>
          <label>配点<input aria-label={`${rubricCriterionLabel(index)}の配点`} type="number" min="0" value={item.points} onChange={e=>update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,points:Number(e.target.value),points_confirmed:true}:c)})}/></label>
          <LatexNormalizationControl text={item.description} contextType="rubric" disabled={disabled||busy} onApply={text=>update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,description:text}:c)})}/>
          {item.grouping_confirmed===false&&<button onClick={()=>update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,grouping_confirmed:true,provenance:{...c.provenance,teacher_confirmed:true}}:c)})}>この採点基準を確認</button>}
          {item.points_conflict&&!item.points_confirmed&&<p>配点の確認が必要です。点数を入力して確認してください。</p>}
          <button onClick={()=>{const next=[...all];next.splice(index+1,0,{id:reviewCandidateId("teacher-rubric"),description:"",points:0,segment_ids:[],provenance:{source:"teacher_manual",inserted_after:item.id}});rows(entry,next);}}>後に追加</button>
          <button onClick={()=>{const next=[...all];next.splice(index+1,0,{...item,id:reviewCandidateId("teacher-rubric"),provenance:{...item.provenance,manual_duplicate_from:item.id,teacher_confirmed:true}});rows(entry,next);}}>複製</button>
          <button disabled={index===0} onClick={()=>{const next=[...all];[next[index-1],next[index]]=[next[index],next[index-1]];rows(entry,next);}}>上へ</button>
          <button disabled={index===0} onClick={()=>{const result=mergeRubricRows(entry,[all[index-1].id,item.id],"manual_above");if(result)update(entry.id,result);}}>上と結合</button>
          <button onPointerDown={e=>e.preventDefault()} onClick={()=>void split(entry,item,true)}>カーソル位置で分割</button><button aria-busy={splitting===`${entry.id}:${item.id}`} onClick={()=>void split(entry,item,false)}>{splitting===`${entry.id}:${item.id}`?<><span className="spinner" aria-hidden="true"/>分割案を作成中…</>:"分割案を作成"}</button>
          <label><input type="checkbox" checked={!!item.excluded} onChange={e=>update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,excluded:e.target.checked}:c)})}/>対象外</label>
        </fieldset>)}
      </AuthoringPreviewEditor>
    {proposal?.entryId===entry.id&&<section hidden={!rubricEditing} aria-label="採点基準の分割案"><h3>採点基準の分割案</h3>{proposal.split.parts.some(p=>p.points_conflict)&&<p>配点は自動配分しません。元の配点: {proposal.item.points}点。適用後に各基準の配点を確認してください。</p>}{proposal.split.parts.map((p,i)=><p key={i}>{p.description} — {p.points}点</p>)}
      <button disabled={disabled||busy} onClick={()=>{const entry=entries.find(e=>e.id===proposal.entryId);const found=entry&&rubricRows(entry).find(c=>c.id===proposal.item.id);if(!entry||JSON.stringify(found)!==proposal.baseline){setError("候補が変更されています。分割案を作り直してください。");return;}
        try{for(const part of proposal.split.parts.slice(1))rubricSplitOffset(proposal.original,Array.from(proposal.original).slice(0,part.start).join("").length);}catch(e){setError(e instanceof Error?e.message:"数式の分割位置を確認してください。");return;}
        const parts=proposal.split.parts.map(p=>({id:reviewCandidateId("split"),description:p.description,points:p.points,source_text:p.source_text,segment_ids:proposal.item.segment_ids||[],grouping_confirmed:true,grouping_method:"split",points_conflict:p.points_conflict,points_confirmed:false,provenance:{...(proposal.item.segment_ids?.length?{}:{source:"teacher_manual"}),split_from_candidate_id:proposal.item.id,original_text:proposal.original,original_points:proposal.item.points,source_sha256:proposal.split.source_sha256,start:p.start,end:p.end,previous_operation:proposal.item.provenance||{},teacher_confirmed:true}}));
        rows(entry,rubricRows(entry).flatMap(c=>c.id===proposal.item.id?parts:[c]));setProposal(null);
      }}>この分割を適用</button><button onClick={()=>setProposal(null)}>キャンセル</button></section>}
    {groups?.entryId===entry.id&&<section hidden={!rubricEditing} aria-label="採点基準の統合案"><h3>採点基準の統合案</h3>{groups.rows.map(c=><p key={c.id}>{c.description} — {c.points}点</p>)}<button disabled={disabled||busy} onClick={()=>{const entry=entries.find(e=>e.id===groups.entryId);if(!entry||JSON.stringify(rubricRows(entry))!==groups.baseline){setError("採点基準が変更されています。統合案を作り直してください。");return;}rows(entry,groups.rows);setGroups(null);}}>この統合を適用</button><button onClick={()=>setGroups(null)}>キャンセル</button></section>}
      </section>}
    </article>)}
    {showAnswer&&visible.length===0&&<section aria-label="模範解答候補">{addAnswer}</section>}
    {showRubric&&visible.length===0&&<section aria-label="採点基準候補"><button disabled={disabled||busy||questionKey==="unassigned"} onClick={()=>onChange([...entries,{id:reviewCandidateId("teacher-entry"),question_id:null,authoring_question_key:questionKey,mapping_state:"manual_mapped",disposition:"include",answer_kind:"alternative",answer_text:"",source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]},rubric_edits:[]}],"rubric")}>採点基準を追加</button></section>}
  </div>;
}
