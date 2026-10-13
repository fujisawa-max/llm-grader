"use client";
import {useEffect, useRef, useState, type ReactNode} from "react";
import {CompactModelAnswerText,ModelAnswerTextDialog} from "./CompactModelAnswerText";
import type {LatexProposal} from "@/lib/api/textTools";
import {AuthoringDialog} from "./AuthoringDialog";
import {testAuthoring} from "@/lib/api/testAuthoring";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {AuthoringPreviewEditor, AcceptedDiagramPreview} from "./AuthoringPreviewEditor";
import {AuthoringFigure} from "./AuthoringFigure";
import {DiagramReview, type DiagramSelection} from "./DiagramReview";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import {apiFetch, json} from "@/lib/api/client";
import {canonicalQuestionRoot} from "@/lib/canonicalQuestionPath";
import {acceptedAnswerDiagramPatch} from "@/lib/authoringAnswerInclusion";
import {manualClassificationPatch} from "@/lib/authoringClassification";
import {scrollReviewContent} from "@/lib/reviewIssues";
import {reviewCandidateId} from "@/lib/reviewCandidateId";
import {webRubricRows, rubricGroupRows, mergeRubricRows, rubricCriterionLabel, rubricSplitOffset} from "@/lib/rubricEditing";
import {derivedRubricMaximum,initialRubricLevels,withCanonicalRubricMaximum} from "@/lib/rubricLevels";
import type {ModelAnswerDraftEntry, ModelAnswerContentCategory, RubricCandidateEdit, RubricSplitProposal, RubricConsolidatedGroup} from "@/lib/api/modelAnswerImports";

function AnswerOperations({children}:{children:ReactNode}){const [expanded,setExpanded]=useState(false);return <details data-answer-operations onToggle={e=>setExpanded(e.currentTarget.open)}><summary aria-expanded={expanded}><span aria-hidden="true">{expanded?"▼":"▶"}</span> 解答の操作</summary>{children}</details>;}

function RubricScoreDisclosure({label,summary,children,criterionId}:{label:string;summary:ReactNode;children:ReactNode;criterionId:string}) {
  const [expanded,setExpanded]=useState(false);
  return <details className="compact-rubric-levels" aria-label="得点段階" data-rubric-levels={criterionId} onToggle={event=>setExpanded(event.currentTarget.open)}>
    <summary aria-label={label} aria-expanded={expanded}><span className="compact-rubric-chevron" aria-hidden="true">{expanded?"▼":"▶"}</span>{summary}</summary>{children}
  </details>;
}

export type AuthoringEntry=ModelAnswerDraftEntry & {source_draft_id?:string;authoring_question_key?:string|null;manual_alternative_answers?:{id:string;text:string}[];material_role?:string;rubric_only_preserved?:boolean};
export function AuthoringCandidates({testId, draftId, revision, questionKey, entries, savedEntries, questions, disabled, showAnswer, showRubric, compactAnswer=false, figureReviewEntryIds=[], staleSourceDraftIds = [], answerEditing, rubricEditing, onAnswerEditing, onRubricEditing, onChange, onSelect}: {
  testId:string; draftId:string; revision:number; questionKey:string; entries:AuthoringEntry[]; savedEntries:AuthoringEntry[];
  questions:{key:string;parentKey?:string|null;label:string;gradable:boolean;sourceId?:string}[]; disabled:boolean; showAnswer:boolean; showRubric:boolean;
  staleSourceDraftIds?:string[];compactAnswer?:boolean;figureReviewEntryIds?:string[];
  answerEditing:boolean; rubricEditing:boolean; onAnswerEditing:(value:boolean)=>void; onRubricEditing:(value:boolean)=>void;
  onChange:(entries:AuthoringEntry[],domain?:"answer"|"rubric"|"diagram")=>void; onSelect:(selection:DiagramSelection)=>void;
}) {
  const majorKey=canonicalQuestionRoot(questionKey,questions);
  const unsavedMajorDiagramChanges=!!majorKey && entries.some(candidate=>
    !!candidate.authoring_question_key &&
    canonicalQuestionRoot(candidate.authoring_question_key,questions)===majorKey &&
    candidate.diagram_records?.some(record=>record.state==="accepted" &&
      JSON.stringify(record)!==JSON.stringify(savedEntries.find(saved=>saved.id===candidate.id)?.diagram_records?.find(saved=>saved.id===record.id)))
  );
  // Only persisted same-major records drive reuse refresh, never dirty guidance.
  const savedReuseVersion=JSON.stringify(savedEntries.filter(candidate=>
    !!majorKey && !!candidate.authoring_question_key &&
    canonicalQuestionRoot(candidate.authoring_question_key,questions)===majorKey
  ).map(candidate=>({id:candidate.id,source:candidate.source_draft_id,disposition:candidate.disposition,
    diagrams:candidate.diagram_records?.filter(record=>record.state==="accepted")})));
  const [newAnswer,setNewAnswer]=useState(false);
  const [expandedExcluded,setExpandedExcluded]=useState<Record<string,boolean>>({});
  const [selected,setSelected]=useState<Record<string,string[]>>({});
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [proposal,setProposal]=useState<{entryId:string;revisionId:string;item:RubricCandidateEdit;original:string;baseline:string;split:RubricSplitProposal}|null>(null);
  const [proposalError,setProposalError]=useState("");
  const [proposalStale,setProposalStale]=useState(false);
  const [applying,setApplying]=useState(false);
  const applyInFlight=useRef(false);
  const splitTrigger=useRef<HTMLElement|null>(null);
  const [groups,setGroups]=useState<{entryId:string;rows:RubricCandidateEdit[];baseline:string}|null>(null);
  const [criterionDialog,setCriterionDialog]=useState<{entryId:string;criterionId:string;draft:string;mode:"edit"|"split"}|null>(null);
  const [levelDialog,setLevelDialog]=useState<{entryId:string;criterionId:string;index:number|null;score:string;condition:string}|null>(null);
  const [levelDialogError,setLevelDialogError]=useState("");
  const textareas=useRef<Record<string,HTMLTextAreaElement|null>>({});
  const activeCriterion=useRef<string|null>(null);
  const [splitting,setSplitting]=useState<string|null>(null);
  const splitInFlight=useRef(false);
  const epoch=useRef("");const requestEpoch=useRef(0);
  const nextScope=`${testId}:${draftId}:${questionKey}:${revision}`;
  if(epoch.current!==nextScope){epoch.current=nextScope;requestEpoch.current++;}
  useEffect(()=>{setProposal(null);setGroups(null);setError("");setBusy(false);},[testId,draftId,questionKey,revision]);
  const current=useRef(entries);current.current=entries;
  const changeRef=useRef(onChange);changeRef.current=onChange;
  const update=(id:string,patch:Partial<AuthoringEntry>)=>changeRef.current(current.current.map(e=>e.id===id?{...e,...patch}:e),patch.diagram_records?"diagram":patch.rubric_edits||patch.rubric_merge_history?"rubric":"answer");
  const setRubricEditing=(value:boolean)=>{
    if(value){
      const prepared=current.current.map(entry=>entry.authoring_question_key===questionKey&&webRubricRows(entry).length
        ? {...entry,rubric_edits:webRubricRows(entry)} : entry);
      if(JSON.stringify(prepared)!==JSON.stringify(current.current))changeRef.current(prepared,"rubric");
    }
    onRubricEditing(value);
  };
  const openCriterionDialog=(entry:AuthoringEntry,item:RubricCandidateEdit,mode:"edit"|"split"="edit")=>{
    splitTrigger.current=document.activeElement as HTMLElement;
    setCriterionDialog({entryId:entry.id,criterionId:item.id,draft:item.description,mode});
  };
  const splitCriterionDialog=()=>{
    if(!criterionDialog)return;
    const entry=current.current.find(value=>value.id===criterionDialog.entryId),item=entry&&webRubricRows(entry).find(value=>value.id===criterionDialog.criterionId);
    if(!entry||!item)return;
    const updated=current.current.map(value=>value.id===entry.id?{...value,rubric_edits:webRubricRows(value).map(row=>row.id===item.id?{...row,description:criterionDialog.draft}:row)}:value);
    current.current=updated;changeRef.current(updated,"rubric");
    void split({...entry,rubric_edits:updated.find(value=>value.id===entry.id)?.rubric_edits},{...item,description:criterionDialog.draft},true);
    setCriterionDialog(null);
  };
  const completeCriterionDialog=()=>{
    if(!criterionDialog)return;
    const entry=current.current.find(value=>value.id===criterionDialog.entryId);
    if(entry)rows(entry,webRubricRows(entry).map(item=>item.id===criterionDialog.criterionId?{...item,description:criterionDialog.draft}:item));
    setCriterionDialog(null);
  };
  const openLevelDialog=(entry:AuthoringEntry,item:RubricCandidateEdit,index:number|null)=>{
    setLevelDialogError("");
    const level=index===null?null:(item.levels||[])[index];
    setLevelDialog({entryId:entry.id,criterionId:item.id,index,score:level?.score==null?"":String(level.score),condition:level?.condition||""});
  };
  const completeLevelDialog=()=>{
    if(!levelDialog)return;
    const scoreText=levelDialog.score.trim(),score=scoreText===""?null:Number(scoreText);
    if(score!==null&&(!Number.isFinite(score)||score<0)){setLevelDialogError("0以上の数値を入力してください。");return;}
    const entry=current.current.find(value=>value.id===levelDialog.entryId),item=entry&&webRubricRows(entry).find(value=>value.id===levelDialog.criterionId);
    if(entry&&item){
      const levels=[...(item.levels||[])],next={score,condition:levelDialog.condition};
      if(levelDialog.index===null)levels.push(next);else levels[levelDialog.index]=next;
      const changedScores=JSON.stringify(levels.map(level=>level.score))!==JSON.stringify((item.levels||[]).map(level=>level.score));
      rows(entry,webRubricRows(entry).map(value=>value.id===item.id?withCanonicalRubricMaximum({...value,levels,...(changedScores?{points_confirmed:true}:{})}):value));
    }
    setLevelDialog(null);
  };
  const deleteLevelDialog=()=>{
    if(!levelDialog||levelDialog.index===null)return;
    const entry=current.current.find(value=>value.id===levelDialog.entryId),item=entry&&webRubricRows(entry).find(value=>value.id===levelDialog.criterionId);
    if(entry&&item&&(item.levels||[])[levelDialog.index]?.score!==0){
      const levels=(item.levels||[]).filter((_,index)=>index!==levelDialog.index);
      rows(entry,webRubricRows(entry).map(value=>value.id===item.id?withCanonicalRubricMaximum({...value,levels}):value));
    }
    setLevelDialog(null);
  };
  const classify=(entry:AuthoringEntry,patch:Partial<AuthoringEntry>)=>update(entry.id,manualClassificationPatch(entry,patch));
  const assign=(entry:AuthoringEntry,key:string)=>classify(entry,{authoring_question_key:key||null,
    disposition:key?"include":"unassigned",mapping_state:key?"manual_mapped":"needs_review"});
  const rows=(entry:AuthoringEntry,next:RubricCandidateEdit[])=>update(entry.id,{rubric_edits:next.map(withCanonicalRubricMaximum),
    rubric_merge_history:[...(entry.rubric_merge_history||[]),webRubricRows(entry)].slice(-50)});
  async function split(entry:AuthoringEntry,item:RubricCandidateEdit,manual:boolean){
    if(splitInFlight.current||proposal)return;
    setProposalError("");setProposalStale(false);
    const token=requestEpoch.current;setError("");setProposal(null);
    const text=item.description;
    try {
      const target=`${entry.id}:${item.id}`,control=textareas.current[target];
      if(manual&&(!control||activeCriterion.current!==target))throw new Error("分割する基準の本文欄にカーソルを置いてください。");
      const offset=manual?rubricSplitOffset(text,control!.selectionStart):undefined;
      splitInFlight.current=true;setBusy(true);setSplitting(target);
      const baselineRevision=(await testAuthoring.get(testId)).revision;
      if(!baselineRevision||baselineRevision.edit_version!==revision)throw new Error("保存状態が変更されています。再読み込みしてください。");
      const result=await apiFetch<RubricSplitProposal>(`/tests/${testId}/authoring/entries/${entry.id}/rubric-split`,json({expected_revision:revision,candidate_id:item.id,text,question_key:questionKey,...(manual?{offset}:{})}));
      if(requestEpoch.current===token){if(result.split)setProposal({entryId:entry.id,revisionId:baselineRevision.id,item,original:text,baseline:JSON.stringify(item),split:result});else setError("この候補は1つの採点基準として扱う提案です。");}
    }catch(e){if(requestEpoch.current===token)setError(e instanceof Error?e.message:"分割案を取得できませんでした。");}
    finally{splitInFlight.current=false;if(requestEpoch.current===token){setBusy(false);setSplitting(null);}}
  }
  async function consolidate(entry:AuthoringEntry){const token=requestEpoch.current;setBusy(true);setError("");try{
    const result=await apiFetch<{groups:RubricConsolidatedGroup[]}>(`/tests/${testId}/authoring/entries/${entry.id}/rubric-consolidate`,json({expected_revision:revision,criteria:webRubricRows(entry).filter(c=>!c.excluded).map(c=>({id:c.id,description:c.description,points:c.points}))}));
    const original=webRubricRows(entry);
    const projected=rubricGroupRows(result.groups).map(group=>{
      const inputs=original.filter(c=>group.segment_ids?.includes(c.id));
      const ids=[...new Set(inputs.flatMap(c=>c.segment_ids||[]))];
      const merged=inputs.length>1?mergeRubricRows(entry,inputs.map(c=>c.id),"manual_multi")?.rubric_edits.find(c=>!original.some(o=>o.id===c.id)):inputs[0];
      return {...group,segment_ids:ids,provenance:{...merged?.provenance,...(!ids.length?{source:"teacher_manual"}:{}),source_candidate_ids:inputs.map(c=>c.id),previous_operations:inputs.map(c=>c.provenance||{}),merge_type:"llm_consolidation"}};
    });
    if(requestEpoch.current===token)setGroups({entryId:entry.id,rows:projected,baseline:JSON.stringify(original)});
  }catch(e){if(requestEpoch.current===token)setError(e instanceof Error?e.message:"統合案を取得できませんでした。");}finally{if(requestEpoch.current===token)setBusy(false);}}
  const cancelProposal=()=>{setProposal(null);requestAnimationFrame(()=>splitTrigger.current?.focus());};
  async function applyProposal(){
    if(!proposal||applyInFlight.current)return;
    const token=requestEpoch.current;
    applyInFlight.current=true;setApplying(true);setProposalError("");
    try{const entry=current.current.find(e=>e.id===proposal.entryId);const found=entry&&webRubricRows(entry).find(c=>c.id===proposal.item.id);if(!entry||JSON.stringify(found)!==proposal.baseline){setProposalStale(true);setProposalError("候補が変更されています。分割案を作り直してください。");return;}
        try{for(const part of proposal.split.parts.slice(1))rubricSplitOffset(proposal.original,Array.from(proposal.original).slice(0,part.start).join("").length);}catch(e){setProposalError(e instanceof Error?e.message:"数式の分割位置を確認してください。");return;}
        const latest=(await testAuthoring.get(testId)).revision;
        if(!latest||latest.id!==proposal.revisionId||latest.edit_version!==revision){setProposalStale(true);setProposalError("保存状態が別の画面で変更されています。再読み込みして分割案を作り直してください。");return;}
        if(requestEpoch.current!==token)return;
        if(JSON.stringify(current.current.find(e=>e.id===proposal.entryId)&&webRubricRows(current.current.find(e=>e.id===proposal.entryId)!).find(c=>c.id===proposal.item.id))!==proposal.baseline){setProposalStale(true);setProposalError("候補が変更されています。分割案を作り直してください。");return;}
        const parts=proposal.split.parts.map(p=>({id:reviewCandidateId("split"),description:p.description,points:p.points,
          levels:initialRubricLevels(p.points,p.description,p.points_conflict),source_text:p.source_text,segment_ids:proposal.item.segment_ids||[],grouping_confirmed:true,grouping_method:"split",points_conflict:p.points_conflict,points_confirmed:false,provenance:{...(proposal.item.segment_ids?.length?{}:{source:"teacher_manual"}),split_from_candidate_id:proposal.item.id,original_text:proposal.original,original_points:proposal.item.points,source_sha256:proposal.split.source_sha256,start:p.start,end:p.end,previous_operation:proposal.item.provenance||{},teacher_confirmed:true}}));
        rows(entry,webRubricRows(entry).flatMap(c=>c.id===proposal.item.id?parts:[c]));setProposal(null);requestAnimationFrame(()=>{const control=textareas.current[`${entry.id}:${parts[0].id}`];control?.focus();control?.scrollIntoView({block:"nearest"});});
      }catch(e){setProposalError(e instanceof Error?e.message:"分割案を適用できませんでした。");}
    finally{applyInFlight.current=false;setApplying(false);}
  }
  const visible=entries.filter(e=>e.authoring_question_key===questionKey||(questionKey==="unassigned"&&!e.authoring_question_key));
  const answerVisibleEntries=visible.filter(e=>e.material_role!=="rubric_source"&&!e.rubric_only_preserved);
  const rubricVisibleEntries=visible.filter(e=>webRubricRows(e).length>0);
  const legacyAddAnswer=<button disabled={disabled||questionKey==="unassigned"} onClick={()=>onChange([...entries,{id:reviewCandidateId("teacher-entry"),question_id:null,authoring_question_key:questionKey,
      mapping_state:"manual_mapped",disposition:"include",answer_kind:visible.some(e=>(e.answer_kind||"primary")==="primary"&&e.disposition!=="ignored")?"alternative":"primary",answer_text:"",material_role:"model_answer_source",
      source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]}}])}>模範解答を追加</button>;
  const addAnswer=compactAnswer?<button disabled={disabled||questionKey==="unassigned"} onClick={()=>setNewAnswer(true)}>模範解答を追加</button>:legacyAddAnswer;
  const normalizationPatch=(entry:Pick<AuthoringEntry,"teacher_correction">,proposal?:LatexProposal)=>proposal?{teacher_correction:{...entry.teacher_correction,teacher_confirmed:true,latex_normalization:{status:proposal.status,profile:proposal.profile,model:proposal.model,source:proposal.source,regions:proposal.math_regions?.map(r=>({page_index:r.page_index,bbox:r.bbox,crop_bbox:r.crop_bbox,segment_ids:r.segment_ids,grouping_method:r.grouping_method,ricoh_used:r.ricoh_used,ornith_used:r.ornith_used})),timestamp:new Date().toISOString()}}}:{};
  const normalizedText=(entry:AuthoringEntry,text:string,proposal?:LatexProposal)=>{if(text!==entry.answer_text||proposal)update(entry.id,{answer_text:text,...normalizationPatch(entry,proposal)});};
  return <div aria-label="出典付き解答・採点基準">
    {newAnswer&&<ModelAnswerTextDialog text="" disabled={disabled||busy} onCancel={()=>setNewAnswer(false)} onDone={(text,proposal)=>{onChange([...current.current,{id:reviewCandidateId("teacher-entry"),question_id:null,authoring_question_key:questionKey,mapping_state:"manual_mapped",disposition:"include",answer_kind:visible.some(e=>(e.answer_kind||"primary")==="primary"&&e.disposition!=="ignored")?"alternative":"primary",answer_text:text,...normalizationPatch({},proposal),material_role:"model_answer_source",source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]}}]);setNewAnswer(false);}}/>}
    {error&&<p role="alert">{error}</p>}
    {questionKey==="unassigned"&&<p className="notice">この候補を対応する設問へ割り当てるか、不要な候補として除外してください。</p>}
    {visible.map((entry,entryIndex)=>{const entryAnswerVisible=showAnswer&&entry.material_role!=="rubric_source",entryRubricVisible=showRubric&&(entry.material_role==="rubric_source"||webRubricRows(entry).length>0||!!entry.semantic_classification?.segments.some(segment=>segment.category==="rubric"||segment.category==="uncertain"));const entrySourceStale=staleSourceDraftIds.includes(entry.source_draft_id||draftId);const unresolved=questionKey==="unassigned"&&!entry.authoring_question_key&&!['ignored','excluded'].includes(entry.disposition||'include');const diagram=<DiagramReview path={`/tests/${testId}/authoring/entries/${entry.id}/diagrams`} revision={revision} targetQuestionId={entry.authoring_question_key||undefined} allowManualCrop assignmentQuestionId={questions.find(q=>q.key===entry.authoring_question_key)?.sourceId} autoParentFallback
        unsavedDiagramChanges={unsavedMajorDiagramChanges} savedReuseVersion={savedReuseVersion}
        records={entry.diagram_records} sourceStale={entrySourceStale} disabled={disabled||busy||entrySourceStale||!entry.authoring_question_key} disabledReason={!entry.authoring_question_key?"図の対応先の設問を選択してください。":undefined} label="模範解答の図"
        onChange={records=>{const active=current.current.find(candidate=>candidate.id===entry.id);if(active)update(entry.id,acceptedAnswerDiagramPatch(active,records,questions.some(question=>question.key===active.authoring_question_key&&question.gradable)));}} onSelect={onSelect}/>;return <article key={entry.id} id={`authoring-candidate-${entry.id}`}>
      {unresolved&&<section className="authoring-candidate-resolution" aria-label="未割当候補の処理">
        <div className="authoring-candidate-resolution-text" aria-label="未割当候補の本文"><MarkdownMathText source={entry.candidate_text||entry.answer_text||webRubricRows(entry).map(item=>item.description).join("\n")||"本文なし"}/></div>
        <p>対応する設問を選ぶと割当できます。使用しない候補は除外してください。</p>
        <label>対応する設問<select aria-label="対応する設問" disabled={disabled||busy} value="" onChange={event=>assign(entry,event.target.value)}><option value="">設問を選択</option>{questions.filter(q=>q.gradable).map(q=><option key={q.key} value={q.key}>{q.label}</option>)}</select></label>
        <button type="button" disabled={disabled||busy} onClick={()=>classify(entry,{disposition:"ignored"})}>不要として除外</button>
      </section>}
      {questionKey==="unassigned"&&!unresolved&&<p role="status">不要な候補として除外済みです。元資料と候補は保持されています。</p>}
      {entryAnswerVisible&&!entry.rubric_only_preserved&&<section aria-label={compactAnswer?"模範解答":"模範解答候補"}>{compactAnswer?<><CompactModelAnswerText label={`模範解答${answerVisibleEntries.findIndex(e=>e.id===entry.id)+1}${entry.answer_kind==="alternative"?"（別解）":""}`} text={entry.answer_text} latexDisabled={entrySourceStale} alternatives={entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers?.map(a=>({id:`source-alternative:${a.segment_ids.join(":")}`,text:a.text}))||[]} disabled={disabled||busy} source={!entrySourceStale&&entry.source.segments.length&&savedEntries.some(e=>e.id===entry.id)?{draftId:entry.source_draft_id||draftId,entryId:entry.id,revision,authoringTestId:testId}:undefined} onText={(text,proposal)=>normalizedText(entry,text,proposal)} onAlternatives={values=>update(entry.id,{manual_alternative_answers:values})}/>
      <p className="muted" role="status">{["ignored","excluded"].includes(entry.disposition||"")?"対象外":entry.answer_kind==="alternative"?"別解":"模範解答"}</p><AnswerOperations><fieldset disabled={disabled||busy}><label>候補の扱い<select value={entry.disposition||"include"} onChange={e=>classify(entry,{disposition:e.target.value as AuthoringEntry["disposition"],...(e.target.value==="unassigned"?{authoring_question_key:null}:{})})}><option value="include">使用する</option><option value="ignored">対象外</option><option value="unassigned">設問未割当</option></select></label><label>解答の種類<select aria-label="解答の種類" value={entry.answer_kind||"primary"} onChange={e=>classify(entry,{answer_kind:e.target.value as AuthoringEntry["answer_kind"]})}><option value="primary">模範解答</option><option value="alternative">別解</option></select></label><label>対応する設問<select aria-label="対応する設問" value={entry.authoring_question_key||""} onChange={e=>assign(entry,e.target.value)}><option value="">設問未割当</option>{questions.filter(q=>q.gradable).map(q=><option key={q.key} value={q.key}>{q.label}</option>)}</select></label><button onClick={()=>classify(entry,{disposition:"ignored"})}>この模範解答を対象外にする</button></fieldset></AnswerOperations>
      <AuthoringFigure reviewRequired={figureReviewEntryIds.includes(entry.id)} records={entry.diagram_records} sourceStale={entrySourceStale} path={`/tests/${testId}/authoring/entries/${entry.id}/diagrams`} questionKey={entry.authoring_question_key||undefined} scopeKey={entry.id}>{diagram}</AuthoringFigure></>:<><h3>模範解答候補</h3><AuthoringPreviewEditor editLabel="本文編集" label="解答" editing={answerEditing} onEditing={onAnswerEditing} preview={<><div className="authoring-question-preview-frame authoring-answer-preview-frame"><MarkdownMathText source={entry.answer_text||"本文なし"}/>{(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers||[]).map((a,i)=><div key={i}><h4>別解{i+1}</h4><MarkdownMathText source={a.text}/></div>)}</div><AcceptedDiagramPreview records={entrySourceStale?[]:entry.diagram_records} path={`/tests/${testId}/authoring/entries/${entry.id}/diagrams`} questionKey={entry.authoring_question_key||undefined}/></>}><fieldset disabled={disabled||busy}>
        <label>候補の扱い<select value={entry.disposition||"include"} onChange={e=>classify(entry,{disposition:e.target.value as AuthoringEntry["disposition"],...(e.target.value==="unassigned"?{authoring_question_key:null}:{})})}><option value="include">使用する</option><option value="ignored">対象外</option><option value="unassigned">設問未割当</option></select></label>
        <label>解答の種類<select aria-label="解答の種類" value={entry.answer_kind||"primary"} onChange={e=>classify(entry,{answer_kind:e.target.value as AuthoringEntry["answer_kind"]})}><option value="primary">模範解答</option><option value="alternative">別解</option></select></label>
        {!unresolved&&<label>対応する設問<select aria-label="対応する設問" value={entry.authoring_question_key||""} onChange={e=>assign(entry,e.target.value)}><option value="">設問未割当</option>{questions.filter(q=>q.gradable).map(q=><option key={q.key} value={q.key}>{q.label}</option>)}</select></label>}
        <label>模範解答本文<textarea aria-label="模範解答本文" rows={4} maxLength={100000} value={entry.answer_text} onChange={e=>update(entry.id,{answer_text:e.target.value})}/></label>
      </fieldset>
      <LatexNormalizationControl text={entry.answer_text} contextType="model_answer" disabled={disabled||busy||entrySourceStale}
        source={entry.source.segments.length&&savedEntries.some(e=>e.id===entry.id)?{draftId:entry.source_draft_id||draftId,entryId:entry.id,revision,authoringTestId:testId}:undefined}
        onApply={(text,proposal)=>update(entry.id,{answer_text:text,teacher_correction:{...entry.teacher_correction,teacher_confirmed:true,latex_normalization:{status:proposal.status,profile:proposal.profile,model:proposal.model,source:proposal.source,regions:proposal.math_regions?.map(r=>({page_index:r.page_index,bbox:r.bbox,crop_bbox:r.crop_bbox,segment_ids:r.segment_ids,grouping_method:r.grouping_method,ricoh_used:r.ricoh_used,ornith_used:r.ornith_used})),timestamp:new Date().toISOString()}}})}/>
      {(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers?.map(a=>({id:`source-alternative:${a.segment_ids.join(":")}`,text:a.text}))||[]).map((alternative,index,all)=><label key={alternative.id}>別解{index+1}<textarea aria-label={`別解${index+1}`} disabled={disabled||busy} value={alternative.text} onChange={e=>update(entry.id,{manual_alternative_answers:all.map(a=>a.id===alternative.id?{...a,text:e.target.value}:a)})}/></label>)}
      <button disabled={disabled||busy} onClick={()=>update(entry.id,{manual_alternative_answers:[...(entry.manual_alternative_answers||entry.semantic_classification?.manual_alternative_answers||entry.semantic_classification?.alternative_answers?.map(a=>({id:`source-alternative:${a.segment_ids.join(":")}`,text:a.text}))||[]),{id:reviewCandidateId("teacher-alternative"),text:""}]})}>別解を追加</button>
      <details><summary>保存済みの本文</summary><pre>{savedEntries.find(e=>e.id===entry.id)?.answer_text||"本文なし"}</pre></details>
      {diagram}</AuthoringPreviewEditor></>}
      {entry.semantic_classification&&entryAnswerVisible&&(compactAnswer||answerEditing)&&<details data-authoring-classification><summary>候補の分類を確認</summary>{entry.semantic_classification.segments.map(segment=><label key={segment.id}>{segment.text}<select disabled={disabled||busy} value={segment.category} onChange={e=>classify(entry,{semantic_classification:{...entry.semantic_classification!,segments:entry.semantic_classification!.segments.map(s=>s.id===segment.id?{...s,category:e.target.value as ModelAnswerContentCategory}:s)}})}>{([['question','問題文'],['model_answer','模範解答'],['alternative_answer','別解'],['rubric','採点基準'],['note','補足'],['uncertain','要確認']] as const).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>)}<button disabled={disabled||busy} onClick={event=>{const content=event.currentTarget.closest("details");update(entry.id,{semantic_classification:{...entry.semantic_classification!,status:"teacher_reviewed"}});if(content)requestAnimationFrame(()=>scrollReviewContent(content));}}>この分類を確認</button></details>}
      {entryAnswerVisible&&!entry.rubric_only_preserved&&entry.id===answerVisibleEntries.at(-1)?.id&&addAnswer}
      </section>}
      {entryRubricVisible&&<section aria-label="採点基準の一覧" className="compact-rubric-editor">
        <div className="compact-rubric-toolbar">
          <button type="button" disabled={disabled||busy} onClick={()=>{setRubricEditing(true);rows(entry,[...webRubricRows(entry),{id:reviewCandidateId("teacher-rubric"),description:"",points:0,levels:initialRubricLevels(0,"",true),segment_ids:[],grouping_confirmed:true,grouping_method:"teacher_manual",provenance:{source:"teacher_manual",manual_add:true}}]);}}>基準を追加</button>
          <details><summary>基準一覧の操作</summary><div className="compact-rubric-actions">
            <button disabled={disabled||busy||!entry.rubric_merge_history?.length} onClick={()=>update(entry.id,{rubric_edits:entry.rubric_merge_history!.at(-1),rubric_merge_history:entry.rubric_merge_history!.slice(0,-1)})}>編集を元に戻す</button>
            <button disabled={disabled||busy||(selected[entry.id]||[]).length<2} onClick={()=>{const result=mergeRubricRows(entry,selected[entry.id],"manual_multi",true);if(result)update(entry.id,result);setSelected(s=>({...s,[entry.id]:[]}));}}>選択した基準を結合</button>
            <button disabled={disabled||busy||!webRubricRows(entry).some(c=>!c.excluded&&c.description.trim())} onClick={()=>void consolidate(entry)}>採点基準の統合案を作成</button>
          </div></details>
        </div>
        {webRubricRows(entry).map((item,index,all)=>{
          const levels=item.levels||[],sorted=[...levels].sort((a,b)=>(a.score??Number.POSITIVE_INFINITY)-(b.score??Number.POSITIVE_INFINITY));
          const scores=sorted.map(level=>level.score==null?"未設定":`${level.score}点`).join(" / ");
          const maximum=derivedRubricMaximum(item);
          return <article className={`compact-rubric-criterion${item.excluded?" is-excluded":""}${item.excluded&&expandedExcluded[item.id]?" is-expanded":""}`} key={item.id} id={`authoring-rubric-${item.id}`}>
            <header className="compact-rubric-criterion-header"><div className="compact-rubric-title"><input aria-label={`${rubricCriterionLabel(index)}を選択`} type="checkbox" checked={(selected[entry.id]||[]).includes(item.id)} onChange={e=>setSelected(s=>({...s,[entry.id]:e.target.checked?[...(s[entry.id]||[]),item.id]:(s[entry.id]||[]).filter(id=>id!==item.id)}))}/>{item.excluded?<button type="button" className="compact-rubric-excluded-title" aria-expanded={!!expandedExcluded[item.id]} onClick={()=>setExpandedExcluded(value=>({...value,[item.id]:!value[item.id]}))}>{rubricCriterionLabel(index)}本文</button>:<span>{rubricCriterionLabel(index)}本文</span>}</div><div className="compact-rubric-header-actions">{(!item.excluded||expandedExcluded[item.id])&&<button type="button" disabled={disabled||busy} onClick={()=>openCriterionDialog(entry,item)}>編集</button>}<label><input type="checkbox" disabled={disabled||busy} checked={!!item.excluded} onChange={e=>{setExpandedExcluded(value=>({...value,[item.id]:false}));update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,excluded:e.target.checked}:c)});}}/>対象外</label></div></header>
            <div className="compact-rubric-body"><MarkdownMathText source={item.description||"本文がありません。"}/></div>
            {item.grouping_confirmed===false&&<p className="notice">基準の分類を確認してください。 <button type="button" onClick={event=>{const content=event.currentTarget.closest("article");update(entry.id,{rubric_edits:all.map(c=>c.id===item.id?{...c,grouping_confirmed:true,provenance:{...c.provenance,teacher_confirmed:true}}:c)});if(content)requestAnimationFrame(()=>scrollReviewContent(content));}}>この採点基準を確認</button></p>}
            {item.points_conflict&&!item.points_confirmed&&<p className="notice">得点段階の最高点に確認が必要です。得点段階を編集すると確認が記録されます。</p>}
            <RubricScoreDisclosure criterionId={item.id} label={`${rubricCriterionLabel(index)}、得点段階 ${levels.length?`${levels.length}段階 ${scores}`:"未設定"}、最高点${maximum}点`} summary={<><span>得点段階</span><span>{levels.length?`${levels.length}段階: ${scores}`:"未設定"}</span><span>最高点: {maximum}点</span></>}>
              <div className="compact-rubric-level-table-wrap"><table className="compact-rubric-level-table"><thead><tr><th scope="col">点数</th><th scope="col">条件</th><th scope="col"><span className="visually-hidden">操作</span></th></tr></thead><tbody>
                {sorted.map(level=>{const originalIndex=levels.indexOf(level);return <tr key={`${originalIndex}:${level.score}`} className="rubric-level-edit"><th scope="row">{level.score==null?"未設定":`${level.score}点`}</th><td><div className="compact-rubric-level-condition"><MarkdownMathText source={level.condition||"条件が未設定です。"}/></div></td><td><button type="button" disabled={disabled||busy} onClick={()=>openLevelDialog(entry,item,originalIndex)}>編集</button></td></tr>;})}
              </tbody></table></div>
              <button type="button" disabled={disabled||busy} onClick={()=>openLevelDialog(entry,item,null)}>+ 得点段階を追加</button>
            </RubricScoreDisclosure>
            <details className="compact-rubric-criterion-operations"><summary>基準の操作</summary><div className="compact-rubric-actions">
              <button type="button" disabled={disabled||busy} onClick={()=>{const next=[...all];next.splice(index+1,0,{id:reviewCandidateId("teacher-rubric"),description:"",points:0,levels:initialRubricLevels(0,"",true),segment_ids:[],provenance:{source:"teacher_manual",inserted_after:item.id}});rows(entry,next);}}>後に追加</button>
              <button type="button" disabled={disabled||busy} onClick={()=>{const next=[...all];next.splice(index+1,0,{...item,id:reviewCandidateId("teacher-rubric"),provenance:{...item.provenance,manual_duplicate_from:item.id,teacher_confirmed:true}});rows(entry,next);}}>複製</button>
              <button type="button" disabled={disabled||busy||index===0} onClick={()=>{const next=[...all];[next[index-1],next[index]]=[next[index],next[index-1]];rows(entry,next);}}>上へ</button>
              <button type="button" disabled={disabled||busy||index===0} onClick={()=>{const result=mergeRubricRows(entry,[all[index-1].id,item.id],"manual_above",true);if(result)update(entry.id,result);}}>上と結合</button>
              <button type="button" disabled={disabled||busy} onClick={()=>openCriterionDialog(entry,item,"split")}>位置を指定して2分割</button>
              <button type="button" disabled={disabled||busy||splitting===`${entry.id}:${item.id}`} aria-busy={splitting===`${entry.id}:${item.id}`} onClick={()=>{splitTrigger.current=document.activeElement as HTMLElement;void split(entry,item,false);}}>{splitting===`${entry.id}:${item.id}`?"分割案を作成中…":"分割案を作成"}</button>
            </div></details>
          </article>;
        })}
      </section>}
    {groups?.entryId===entry.id&&<section hidden={!rubricEditing} aria-label="採点基準の統合案"><h3>採点基準の統合案</h3>{groups.rows.map(c=><p key={c.id}>{c.description} — 最高点 {derivedRubricMaximum(c)}点</p>)}<button disabled={disabled||busy} onClick={()=>{const entry=entries.find(e=>e.id===groups.entryId);if(!entry||JSON.stringify(webRubricRows(entry))!==groups.baseline){setError("採点基準が変更されています。統合案を作り直してください。");return;}rows(entry,groups.rows);setGroups(null);}}>この統合を適用</button><button onClick={()=>setGroups(null)}>キャンセル</button></section>}
    </article>})}
    {showAnswer&&answerVisibleEntries.length===0&&<section aria-label={compactAnswer?"模範解答":"模範解答候補"}>{addAnswer}</section>}
    {showRubric&&rubricVisibleEntries.length===0&&<section aria-label="採点基準の一覧" className="compact-rubric-empty"><p>採点基準はまだありません。</p><button disabled={disabled||busy||questionKey==="unassigned"} onClick={()=>{onRubricEditing(true);onChange([...entries,{id:reviewCandidateId("teacher-entry"),question_id:null,authoring_question_key:questionKey,mapping_state:"manual_mapped",disposition:"include",answer_kind:"alternative",answer_text:"",material_role:"rubric_source",source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]},rubric_edits:[{id:reviewCandidateId("teacher-rubric"),description:"",points:0,levels:initialRubricLevels(0,"",true),segment_ids:[],grouping_confirmed:true,grouping_method:"teacher_manual",provenance:{source:"teacher_manual",manual_add:true}}]}],"rubric");}}>基準を追加</button></section>}
    {criterionDialog&&<AuthoringDialog title={criterionDialog.mode==="split"?"採点基準を分割":"採点基準本文"} onCancel={()=>setCriterionDialog(null)} actions={<><button type="button" disabled={disabled||busy} onClick={()=>setCriterionDialog(null)}>キャンセル</button><button type="button" disabled={disabled||busy} onClick={splitCriterionDialog}>カーソルの位置で分割</button><button type="button" disabled={disabled||busy} onClick={completeCriterionDialog}>完了</button></>}>
      {criterionDialog.mode==="split"&&<p>分割位置にカーソルを置いてください。</p>}
      <label className="compact-rubric-dialog-field">採点基準本文<textarea disabled={disabled||busy} autoFocus rows={4} ref={element=>{if(element)textareas.current[`${criterionDialog.entryId}:${criterionDialog.criterionId}`]=element;else textareas.current[`${criterionDialog.entryId}:${criterionDialog.criterionId}`]=null;}} onFocus={()=>{activeCriterion.current=`${criterionDialog.entryId}:${criterionDialog.criterionId}`;}} value={criterionDialog.draft} onChange={event=>setCriterionDialog(value=>value?{...value,draft:event.target.value}:value)}/></label>
      <div className="compact-rubric-dialog-conversion"><LatexNormalizationControl text={criterionDialog.draft} contextType="rubric" disabled={disabled||busy} onApply={text=>setCriterionDialog(value=>value?{...value,draft:text}:value)}/></div>
    </AuthoringDialog>}
    {levelDialog&&<AuthoringDialog title={levelDialog.index===null?"得点段階を追加":"得点段階を編集"} onCancel={()=>setLevelDialog(null)} actions={<>{levelDialog.index!==null&&Number(levelDialog.score)!==0&&<button type="button" className="danger" disabled={disabled||busy} onClick={deleteLevelDialog}>得点段階を削除</button>}<button type="button" disabled={disabled||busy} onClick={()=>setLevelDialog(null)}>キャンセル</button><button type="button" disabled={disabled||busy} onClick={completeLevelDialog}>完了</button></>}>{levelDialogError&&<p role="alert">{levelDialogError}</p>}<label className="compact-rubric-dialog-field">点数<input disabled={disabled||busy} autoFocus type="number" min="0" step="1" value={levelDialog.score} onChange={event=>{setLevelDialogError("");setLevelDialog(value=>value?{...value,score:event.target.value}:value);}}/></label><label className="compact-rubric-dialog-field">条件<textarea disabled={disabled||busy} rows={4} value={levelDialog.condition} onChange={event=>setLevelDialog(value=>value?{...value,condition:event.target.value}:value)}/></label></AuthoringDialog>}
    {proposal&&<AuthoringDialog title={`${rubricCriterionLabel(Math.max(0,webRubricRows(entries.find(e=>e.id===proposal.entryId)||{...visible[0],rubric_edits:[]}).findIndex(c=>c.id===proposal.item.id)))}の分割案`} busy={applying} onCancel={cancelProposal} actions={<><button disabled={applying} onClick={cancelProposal}>取消</button><button disabled={disabled||applying||proposalStale} onClick={()=>void applyProposal()}>{applying?"適用中…":"分割案を適用"}</button></>}>
      <h3>元の基準</h3><MarkdownMathText source={proposal.original}/><p>元の最高点: {derivedRubricMaximum(proposal.item)}点</p>
      <h3>分割後</h3>{proposal.split.parts.map((part,index)=><section className="panel" key={index}><h4>分割候補{index+1}</h4><MarkdownMathText source={part.description}/><p>{part.points}点</p></section>)}
      {proposal.split.parts.some(part=>part.points_conflict)&&<p className="notice">得点段階は自動配分しません。適用後に各基準の得点段階を確認してください。</p>}
      {proposalError&&<p role="alert">{proposalError}</p>}
    </AuthoringDialog>}
  </div>;
}
