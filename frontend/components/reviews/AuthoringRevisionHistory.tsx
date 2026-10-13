"use client";
import {useEffect,useState} from "react";
import {AuthoringDialog} from "./AuthoringDialog";
import {AcceptedDiagramPreview} from "./AuthoringPreviewEditor";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {testAuthoring,type AuthoringRevision,type ConfirmedAuthoringRevision} from "@/lib/api/testAuthoring";
import {canonicalQuestionPath} from "@/lib/canonicalQuestionPath";
import {derivedRubricMaximum} from "@/lib/rubricLevels";
import type {DiagramRecord} from "@/types/diagrams";

export function AuthoringRevisionHistory({testId,dirty,onClose,onFork}:{testId:string;dirty:boolean;onClose:()=>void;onFork:(parent:string)=>Promise<void>}){
  const [history,setHistory]=useState<{active_confirmed_revision_id:string|null;draft:AuthoringRevision|null;revisions:ConfirmedAuthoringRevision[]}|null>(null);
  const [selected,setSelected]=useState<ConfirmedAuthoringRevision|null>(null);
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  useEffect(()=>{let active=true;testAuthoring.history(testId).then(data=>{if(active)setHistory(data);}).catch(e=>{if(active)setError(e instanceof Error?e.message:"版の履歴を取得できませんでした。");});return()=>{active=false;};},[testId]);
  function records(values:DiagramRecord[]=[],owner?:string){return values.map(record=>({...record,preview_url:`/api/v1/tests/${encodeURIComponent(testId)}/authoring/confirmed/${selected?.id}/diagrams/${encodeURIComponent(record.id)}/crop?owner=${encodeURIComponent(owner||"")}`}));}
  const parent=selected?.parent_confirmed_revision_id&&history?.revisions.find(r=>r.id===selected.parent_confirmed_revision_id);
  return <AuthoringDialog title="版の履歴" onCancel={onClose} busy={busy} actions={<button onClick={onClose} disabled={busy}>閉じる</button>}>
    {error&&<p role="alert">{error}</p>}
    {!history&&<p role="status">履歴を読み込んでいます…</p>}
    {history&&<>
      {history.draft&&<p>現在の下書き{history.draft.parent_confirmed_revision_id&&` — ${history.revisions.find(r=>r.id===history.draft?.parent_confirmed_revision_id)?.label||"確定版"}から作成`}。編集は現在のワークスペースで続けられます。{history.draft.updated_at&&` 最終保存: ${new Date(history.draft.updated_at).toLocaleString("ja-JP")}`}</p>}
      {!history.revisions.length&&<p>確定済みの版はありません。</p>}
      <ul>{history.revisions.map(row=><li key={row.id}><button onClick={()=>setSelected(row)} aria-pressed={selected?.id===row.id}>{row.label} — {row.id===history.active_confirmed_revision_id?"現在の確定版":"確定済み"}</button><p>{new Date(row.confirmed_at).toLocaleString("ja-JP")} ／ {row.confirmed_by||"確認者未記録"}</p></li>)}</ul>
      {selected&&<section aria-label={`${selected.label}の確定内容`}>
        <h3>{selected.label} — {selected.id===history.active_confirmed_revision_id?"現在の確定版":"過去の確定版"}</h3><p>確定済み。この版は編集できません。</p>{parent&&<p>{parent.label}から作成</p>}
        <p>{selected.snapshot.metadata.name} ／ 合計{selected.snapshot.metadata.total_points}点</p>
        <p>{selected.snapshot.metadata.description}</p><p>{selected.grading_definition_complete?"採点定義は保存されています。":"この版には完全な採点定義が保存されていません。"}</p>
        {selected.snapshot.nodes.filter(n=>n.included).map(node=>{
          const entries=selected.snapshot.domains?.answer?.entries.filter(entry=>entry.authoring_question_key===node.stable_key&&(entry.disposition||"include")==="include")||[];
          const answer=selected.snapshot.answers[node.stable_key];
          return <article key={node.stable_key} className="panel" style={{marginLeft:Math.max(0,node.depth)*16}}>
            <h4>{canonicalQuestionPath(node.stable_key,selected.snapshot.nodes.map(n=>({key:n.stable_key,parentKey:n.parent_key,label:n.label.raw})))} ／ {node.score_semantics==="sum_children"?"小問合計":`${node.score_points??"－"}点`}</h4>
            <h5>問題</h5><MarkdownMathText source={node.body_text}/><AcceptedDiagramPreview records={records(node.diagram_records,node.stable_key)}/>
            <h5>模範解答</h5>{entries.length?entries.map((entry,answerIndex)=><div key={entry.id}><h6>模範解答{answerIndex+1}</h6><MarkdownMathText source={entry.answer_text||"本文なし"}/>{(entry.manual_alternative_answers||entry.semantic_classification?.alternative_answers||[]).map((alternative,index)=><MarkdownMathText key={index} source={alternative.text}/>)}<AcceptedDiagramPreview records={records(entry.diagram_records,entry.id)}/></div>):answer&&<><MarkdownMathText source={answer.primary}/>{answer.alternatives.map((text,index)=><MarkdownMathText key={index} source={text}/>)}<AcceptedDiagramPreview records={records(answer.diagram_records)}/></>}
            <h5>採点基準</h5>{(selected.snapshot.rubrics[node.stable_key]||[]).map(criterion=><div key={criterion.id}><MarkdownMathText source={criterion.description}/><p>最高点 {criterion.levels?.length?derivedRubricMaximum(criterion):criterion.points}点</p>{criterion.levels?.length?<ul>{criterion.levels.map((level,index)=><li key={index}>{level.score??"未設定"}点: {level.condition||"条件が未設定"}</li>)}</ul>:<p>得点段階が未設定です。</p>}</div>)}
          </article>;
        })}
        <details><summary>出典情報</summary><ul>{selected.snapshot.materials.map(material=><li key={material.id}><a href={`/api/v1/tests/${encodeURIComponent(testId)}/materials/${encodeURIComponent(material.id)}/file`} target="_blank" rel="noopener noreferrer">{material.role==="question_sheet"?"問題用紙":material.role==="model_answer_source"?"模範解答資料":material.role==="rubric_source"?"採点基準資料":"元資料"}を開く</a></li>)}</ul><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify({materials:selected.snapshot.materials,provenance:selected.snapshot.source_provenance,diagrams:selected.snapshot.domains?.answer?.entries.flatMap(entry=>entry.diagram_records||[])},null,2)}</pre></details>
        {history.draft?<p>編集可能な下書きがあります。現在の下書きで編集を続けてください。</p>:<button disabled={dirty||busy} onClick={async()=>{setBusy(true);try{await onFork(selected.id);}catch(e){setError(e instanceof Error?e.message:"修正版を作成できませんでした。");}finally{setBusy(false);}}}>修正版を作成</button>}
      </section>}
    </>}
  </AuthoringDialog>;
}
