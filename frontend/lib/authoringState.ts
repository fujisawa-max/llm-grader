import type {AuthoringSnapshot,AnalysisReadiness} from "./api/testAuthoring";
import {editQuestionContent,questionContent} from "./questionContent";
import {parseMathText} from "./mathText";

/** Exact teacher buffers are draft content, separate from validated PDF anchors. */
export function authoringBuffers(snapshot:AuthoringSnapshot){
  return Object.fromEntries(snapshot.nodes.map(n=>[n.stable_key,snapshot.question_text_buffers?.[n.stable_key]??questionContent(n,snapshot.domains?.question?.document.regions||[]).text]));
}
export function prepareAuthoringSave(snapshot:AuthoringSnapshot,buffers:Record<string,string>):AuthoringSnapshot {
  const regions=snapshot.domains?.question?.document.regions||[];
  const exact=Object.fromEntries(snapshot.nodes.map(n=>[n.stable_key,buffers[n.stable_key]??snapshot.question_text_buffers?.[n.stable_key]??questionContent(n,regions).text]));
  return {...snapshot,question_text_buffers:exact,nodes:snapshot.nodes.map(n=>{
    const text=exact[n.stable_key],next=editQuestionContent(n,regions,text);
    const invalidFormula=next&&Object.entries(next.formula_decisions).some(([id,d])=>{
      if(d.decision!=="merged_into_text")return false;
      if(next.ordered_content.some(i=>i.type==="text"&&parseMathText(String(i.text||""),false).some(p=>p.kind!=="text"&&p.value.trim()===d.teacher_transcription?.trim())))return false;
      // Saved teacher transcriptions can be ordinary text (for example a
      // punctuation correction to an automatic formula region). A prose edit
      // may preserve that exact saved mapping; it cannot introduce one here.
      const transcription=d.teacher_transcription?.trim();
      if(!transcription||JSON.stringify(d)!==JSON.stringify(n.formula_decisions[id]))return true;
      const anchor=(item:typeof n.ordered_content[number])=>item.type==="text"&&
        item.merged_source_segments?.some(segment=>segment.type==="formula_region"&&segment.region_id===id);
      const old=n.ordered_content.find(anchor),updated=next.ordered_content.find(anchor);
      const math=(item:typeof n.ordered_content[number])=>parseMathText(String("text" in item?item.text||"":""),false)
        .filter(part=>part.kind!=="text").map(part=>[part.kind,part.value.trim()]);
      return !old||!updated||!String("text" in old?old.text||"":"").includes(transcription)||
        !String("text" in updated?updated.text||"":"").includes(transcription)||JSON.stringify(math(old))!==JSON.stringify(math(updated));
    });
    // Keep the last safe anchors when a draft edit cannot yet be source-mapped.
    // The server independently validates them and reports pending source review.
    return {...(next&&!invalidFormula?next:n),body_text:text};
  })};
}
export function analysisReadiness(base:AnalysisReadiness|undefined,{editable,dirty,busy,selected,supported}:{editable:boolean;dirty:boolean;busy:boolean;selected:boolean;supported:boolean}):AnalysisReadiness {
  if(!editable)return {state:"readonly",reason:"修正版を作成すると編集できます。"};
  if(busy)return {state:"busy",reason:"処理中です。完了までお待ちください。"};
  if(!selected)return {state:"missing_material",reason:"資料を選択してください。"};
  if(!supported)return {state:"unsupported",reason:"この資料は解析対象ではありません。"};
  if(dirty)return {state:"unsaved_changes",reason:"変更を保存してから解析してください。"};
  return base||{state:"ready",reason:""};
}
