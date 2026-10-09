"use client";
import {Fragment, useCallback, useEffect, useRef, useState} from "react";
import {useParams} from "next/navigation";
import Link from "next/link";
import {AuthoringDialog} from "@/components/reviews/AuthoringDialog";
import {ReviewWorkspaceLayout} from "@/components/reviews/ReviewWorkspaceLayout";
import {AuthoringPreviewEditor, AcceptedDiagramPreview} from "@/components/reviews/AuthoringPreviewEditor";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {NodeEditor} from "@/components/reviews/NodeEditor";
import {SourcePdfPreview} from "@/components/SourcePdfPreview";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import {LoadingState, ErrorState} from "@/components/ui";
import {testAuthoring, type AuthoringRevision, type AuthoringSnapshot, type AuthoringIssue} from "@/lib/api/testAuthoring";
import {authoringBuffers,prepareAuthoringSave,analysisReadiness} from "@/lib/authoringState";
import {testData} from "@/lib/api/domain";
import {apiFetch, json} from "@/lib/api/client";
import {canonicalQuestionPath} from "@/lib/canonicalQuestionPath";
import {localId} from "@/lib/localId";
import {editQuestionContent, questionContent} from "@/lib/questionContent";
import {DiagramReview, type DiagramSelection} from "@/components/reviews/DiagramReview";
import {suggestSubquestions, splitQuestionAtCaret, splitQuestionRanges, mapCandidateToSources, type SplitProposal} from "@/lib/questionSplit";
import {applyQuestionSplit,reviewQuestionSplit,splitDuplicate} from "@/lib/questionSplitApply";
import {AuthoringCandidates, type AuthoringEntry} from "@/components/reviews/AuthoringCandidates";
import {rubricRows} from "@/lib/rubricEditing";
import {effectiveQuestionScore} from "@/lib/questionScores";
import {DisabledActionHint} from "@/components/reviews/DisabledActionHint";
import {useAuthoringNotifications} from "@/components/reviews/AuthoringNotificationCenter";
import {WarningPanel} from "@/components/reviews/WarningPanel";
import {EvidencePanel} from "@/components/reviews/EvidencePanel";
import type {ReviewNode, ReviewWarning} from "@/types/reviews";
import type {Material} from "@/types/domain";

const roles: Record<string,string> = {question_sheet:"問題用紙", model_answer_source:"模範解答", rubric_source:"採点基準", supplementary_source:"補足資料"};
function newNode(order: number): ReviewNode {
  const id = localId();
  return {review_node_id:id, stable_key:id, source_draft_stable_key:null, source_draft_node_id:null,
    parent_key:null, node_type:"major_question", depth:0, sort_order:order,
    label:{raw:`問題${order+1}`, normalized:`問題${order+1}`}, body_text:"",
    ordered_content:[{type:"text", order:0, text:""}], included:true, score_semantics:"direct", score_points:null,
    review_flags:[], formula_decisions:{}, figure_decisions:{}, warning_states:{}};
}
export default function TestAuthoringPage() {
  const id = String(useParams().testId);
  const [sourceProblems,setSourceProblems]=useState<{domain:string;code:string}[]>([]);
  const [externalChange,setExternalChange]=useState(false);
  const [continueExternal,setContinueExternal]=useState(false);
  const [diagramSelection,setDiagramSelection]=useState<DiagramSelection>();
  const saveInFlight=useRef(false),editEpoch=useRef(0),issueEpoch=useRef(0);
  const [saveStatus,setSaveStatus]=useState<"idle"|"saving"|"success"|"error">("idle");
  const splitInFlight=useRef(false);
  const [splitRunning,setSplitRunning]=useState(false);
  const [splitProposal,setSplitProposal]=useState<SplitProposal|null>(null);
  const [regionId,setRegionId]=useState("");
  const [revision,setRevision]=useState<AuthoringRevision|null>(null);
  const [snapshot,setSnapshot]=useState<AuthoringSnapshot>();
  const [dirty,setDirty]=useState(false);
  const [dirtyDomains,setDirtyDomains]=useState<Record<string,boolean>>({});
  const [buffers,setBuffers]=useState<Record<string,string>>({});
  const [selected,setSelected]=useState("");
  const [materials,setMaterials]=useState<Material[]>([]),[materialId,setMaterialId]=useState("");
  const [editing,setEditing]=useState({question:false,answer:false,rubric:false});
  const [analyzing,setAnalyzing]=useState(false);
  const [analysisProgress,setAnalysisProgress]=useState<string|null>(null);
  const [sourceMode,setSourceMode]=useState<"pdf"|"add"|"manage">("pdf");
  const [questionSettings,setQuestionSettings]=useState(false);
  const [replacement,setReplacement]=useState<string|null>(null);
  const [role,setRole]=useState("question_sheet");
  const [reuseFiles,setReuseFiles]=useState(false),[reuseMaterialId,setReuseMaterialId]=useState("");
  const currentEditVersion=revision?.edit_version;
  const [visible,setVisible]=useState({question:true,answer:true,rubric:true});
  const [issues,setIssues]=useState<AuthoringIssue[]>([]);
  const [issuesOpen,setIssuesOpen]=useState(false);
  const [analysisRequest,setAnalysisRequest]=useState<{domain:"question"|"answer";materialId:string}|null>(null);
  const [registrationPrompt,setRegistrationPrompt]=useState<{materialId:string;role:string}|null>(null);
  const [registrationError,setRegistrationError]=useState("");
  const [deleteMaterial,setDeleteMaterial]=useState<Material|null>(null);
  const [materialRoleChanges,setMaterialRoleChanges]=useState<Record<string,string>>({});
  const [recoveryTargets,setRecoveryTargets]=useState<Record<string,string>>({});
  const [saving,setSaving]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const {notify,view:notificationView}=useAuthoringNotifications();
  const questionCaret=useRef(0);
  const analysisTrigger=useRef<HTMLButtonElement|null>(null);
  const questionToolScope=useRef("");questionToolScope.current=`${selected}:${revision?.edit_version}:${buffers[selected]}`;
  const fileInput=useRef<HTMLInputElement>(null);
  const readonly=!revision || revision.state==="confirmed";
  const closeAnalysis=useCallback(()=>{setAnalysisRequest(null);requestAnimationFrame(()=>analysisTrigger.current?.focus());},[]);
  useEffect(()=>{
    let active=true;
    void Promise.all([testAuthoring.get(id),testData.materials(id)]).then(async ([data,files])=>{
      if(!active)return;
      if(!data.revision){data={...data,revision:await testAuthoring.begin(id)};}
      if(!active)return;
      const value=data.revision?.snapshot||data.legacy;
      setRevision(data.revision);setSnapshot(value);setDirty(false);setDirtyDomains({});setExternalChange(data.external_source_change);setSourceProblems(data.source_problems||[]);
      setBuffers(authoringBuffers(value));
      setSelected(value.nodes[0]?.stable_key||"all");
      setMaterials(files.filter(m=>m.material_type!=="student_answer_source"));
      void testAuthoring.review(id).then(result=>{if(active)setIssues(result.issues);}).catch(()=>{/* Review issues can be refreshed from the Test-wide review action. */});
      const superseded=new Set(value.materials.map(m=>m.replaces_material_id));
      const activeFiles=files.filter(m=>m.material_type!=="student_answer_source"&&!superseded.has(m.id));
      setMaterialId(activeFiles.find(m=>m.material_type==="question_sheet")?.id||activeFiles[0]?.id||"");
    }).catch(e=>{if(active)setError(`編集内容を再開できませんでした。認証・保存競合・出典状態を確認してください。 (${e.message})`);});
    try{const prefs=localStorage.getItem("test-authoring-visible");if(prefs)setVisible(JSON.parse(prefs));}catch{}
    return()=>{active=false;};
  },[id]);
  const nodes=snapshot?.nodes||[];
  const orderedNodes=(parent:string|null=null,depth=0):ReviewNode[]=>depth>nodes.length?[]:nodes
    .filter(n=>n.parent_key===parent).sort((a,b)=>a.sort_order-b.sort_order||a.stable_key.localeCompare(b.stable_key))
    .flatMap(n=>[n,...orderedNodes(n.stable_key,depth+1)]);
  const node=nodes.find(n=>n.stable_key===selected);
  const pathFor=(key:string)=>canonicalQuestionPath(key,nodes.map(n=>({key:n.stable_key,parentKey:n.parent_key,label:n.label.raw})));
  useEffect(()=>{
    if(!dirty&&!saving)return;
    const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue="";};
    window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);
  },[dirty,saving]);
  useEffect(()=>{
    if(!snapshot||currentEditVersion===undefined)return;
    const epoch=++issueEpoch.current;
    const timer=window.setTimeout(()=>{
      const request=dirty?testAuthoring.reviewLocal(id,prepareAuthoringSave(snapshot,buffers),currentEditVersion):testAuthoring.review(id);
      void request.then(result=>{if(issueEpoch.current===epoch)setIssues(result.issues);}).catch(()=>{/* Keep the last known actionable issue list on transient review failures. */});
    },350);
    return()=>window.clearTimeout(timer);
  },[snapshot,buffers,currentEditVersion,dirty,id]);
  function markDirty(){editEpoch.current++;setDirty(true);setSaveStatus("idle");}
  function synchronize(row:AuthoringRevision){
    setRevision(row);setSnapshot(row.snapshot);setBuffers(authoringBuffers(row.snapshot));
    setDirty(false);setDirtyDomains({});
  }
  function change(value:AuthoringSnapshot,domain?:string){setSnapshot(value);markDirty();setDirtyDomains(d=>({...d,...(domain?{[domain]:true}:{question:value.nodes!==snapshot?.nodes||value.domains?.question!==snapshot?.domains?.question||d.question,answer:value.answers!==snapshot?.answers||d.answer,rubric:value.rubrics!==snapshot?.rubrics||d.rubric})}));}
  function updateNode(value:ReviewNode){markDirty();setDirtyDomains(d=>({...d,question:true}));setSnapshot(s=>s?{...s,nodes:s.nodes.map(n=>n.stable_key===value.stable_key?value:n)}:s);}
  function moveNode(value:ReviewNode,direction:number){
    if(!snapshot)return;
    const siblings=nodes.filter(n=>n.parent_key===value.parent_key).sort((a,b)=>a.sort_order-b.sort_order||a.stable_key.localeCompare(b.stable_key));
    const index=siblings.findIndex(n=>n.stable_key===value.stable_key),other=siblings[index+direction];
    if(!other)return;
    [siblings[index],siblings[index+direction]]=[other,value];
    const orders=new Map(siblings.map((n,i)=>[n.stable_key,i]));
    change({...snapshot,nodes:nodes.map(n=>orders.has(n.stable_key)?{...n,sort_order:orders.get(n.stable_key)!}:n)});
  }
  function reparentNode(value:ReviewNode,parent:string|null){
    const order=Math.max(-1,...nodes.filter(n=>n.parent_key===parent&&n.stable_key!==value.stable_key).map(n=>n.sort_order))+1;
    updateNode({...value,parent_key:parent,sort_order:order,node_type:parent?"subquestion":"major_question"});
  }
  function navigate(issue:AuthoringIssue){
    if(!issue.question_key&&issue.section!=="answer")return;
    setSelected(issue.question_key||"unassigned");setDiagramSelection(undefined);setRegionId("");setVisible(v=>({...v,[issue.section]:true}));setEditing(v=>({...v,[issue.section]:issue.field!=="score"}));if(issue.section==="question")setQuestionSettings(issue.field==="score");
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      const marker=document.getElementById(`authoring-${issue.section}`);
      const container=marker?.tagName==="SPAN"?marker.parentElement:marker;
      const target=issue.section==="rubric"?container?.querySelector<HTMLElement>('[aria-label="採点基準候補"]')||container:container;
      target?.scrollIntoView({block:"center"});
      const control=issue.field==="score"?target?.querySelector<HTMLElement>('input[type="number"]'):Array.from(target?.querySelectorAll<HTMLElement>('textarea,input,select,button')||[]).find(el=>el.getClientRects().length>0);
      (control||marker)?.focus({preventScroll:true});
    }));
  }
  async function suggestQuestionSplit(){
    if(!node||!snapshot||!revision||splitInFlight.current)return;
    if(!revision.snapshot.nodes.some(n=>n.stable_key===node.stable_key)){setError("新しく追加・分割した設問は、保存してからAIの分割案を作成してください。本文は保持されています。");return;}
    const scope=questionToolScope.current,text=buffers[selected]??questionContent(node,regions).text;
    const reconciled=editQuestionContent(node,regions,text);
    if(!reconciled){setError("元資料との対応を確認してください。");return;}
    splitInFlight.current=true;setSplitRunning(true);setBusy(true);setError("");
    try{
      const result=await apiFetch<{split:boolean;parts:{start:number;end:number}[]}>(`/tests/${id}/authoring/nodes/${selected}/split-suggest`,json({expected_revision:revision.edit_version,candidate_id:selected,text}));
      if(questionToolScope.current!==scope){notify("warning","分割案を適用しませんでした","対象設問または本文が変わりました。現在の本文で再実行してください。");return;}
      if(!result.split){notify("info","分割案はありませんでした","必要ならカーソル位置を指定してください。");return;}
      const codepoints=Array.from(text),toOffset=(n:number)=>codepoints.slice(0,n).join("").length;
      const boundaries=[0,...result.parts.map(p=>toOffset(p.end))];
      const proposal=suggestSubquestions(reconciled,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key))||splitQuestionRanges(reconciled,boundaries,questionContent(reconciled,regions).spans,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key)?.ordered_content);
      if(!proposal){setError("分割案は元資料の範囲を安全に分けられません。カーソル位置や対応する読み取り項目を確認してください。");return;}
      updateNode(reconciled);setSplitProposal(reviewQuestionSplit(proposal,node,true));
    }catch(e){if(questionToolScope.current===scope)setError(`分割案を取得できませんでした。本文は保持されています。時間をおいて再実行してください。${e instanceof Error?` (${e.message})`:""}`);}finally{splitInFlight.current=false;setSplitRunning(false);setBusy(false);}
  }
  function applyQuestionSplitProposal(){
    if(!snapshot||!splitProposal)return;
    const target=nodes.find(candidate=>candidate.stable_key===splitProposal.targetKey);
    if(!target){setError("対象設問が見つかりません。分割案を作り直してください。");setSplitProposal(null);return;}
    if(splitDuplicate(target,splitProposal,nodes)){setError("同じ本文・出典の小問が既に存在するか、選択中の小問を重複して切り出そうとしています。親本文に残すか、分割範囲を見直してください。");return;}
    const result=applyQuestionSplit(target,splitProposal,()=>`teacher-${localId()}`,nodes);
    if(!result){setError("小問にする部分と元資料の対応を確認してください。");return;}
    const orderOffset=Math.max(-1,...snapshot.nodes.filter(candidate=>candidate.parent_key===target.stable_key).map(candidate=>candidate.sort_order))+1;
    result.children.forEach(child=>{child.sort_order+=orderOffset;});
    change({...snapshot,nodes:[...snapshot.nodes.map(candidate=>candidate.stable_key===target.stable_key?result.updated:candidate),...result.children]});
    const targetRegions=questionDomain?.document.regions||[];
    setBuffers(current=>({...current,[target.stable_key]:questionContent(result.updated,targetRegions).text,...Object.fromEntries(result.children.map(child=>[child.stable_key,questionContent(child,targetRegions).text]))}));
    setSelected(result.children[0]?.stable_key||target.stable_key);setSplitProposal(null);
  }
  async function analyzeSource(domain:"question"|"answer",requestedMaterialId:string){
    if(splitProposal){setError("分割案を適用またはキャンセルしてから資料を解析してください。分割案は保持されています。");return;}
    if(!revision||!requestedMaterialId||dirty){setError("資料を選び、現在の変更を保存してから解析してください。");return;}
    const requestedMaterial=materials.find(m=>m.id===requestedMaterialId);
    const materialRole=requestedMaterial?.material_type;
    setBusy(true);setAnalyzing(true);setAnalysisProgress(materialRole==="question_sheet"?"問題":materialRole==="rubric_source"?"採点基準":"模範解答");setError("");
    try{
      let row:AuthoringRevision;
      if(domain==="answer")row=await testAuthoring.analyzeAnswer(id,requestedMaterialId,revision.edit_version,true);
      else{
        const response=await fetch(`/api/v1/tests/${id}/materials/${requestedMaterialId}/file`,{credentials:"include"});
        if(!response.ok)throw new Error("元PDFを取得できませんでした。");
        const extraction=await apiFetch<{id:string}>(`/tests/${id}/question-materials`,{method:"POST",headers:{"Content-Type":"application/pdf","X-Filename":requestedMaterial?.original_filename||"question.pdf"},body:await response.blob()});
        const draft=await apiFetch<{id:string}>(`/question-imports/${extraction.id}/draft`,json({}));
        await apiFetch(`/question-import-drafts/${draft.id}/reviews`,json({}));
        row=await testAuthoring.importSources(id,revision.edit_version,true,requestedMaterialId);
      }
      setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});setExternalChange(false);setContinueExternal(false);
      setBuffers(authoringBuffers(row.snapshot));
      setSelected(current=>row.snapshot.nodes.some(n=>n.stable_key===current)?current:row.snapshot.nodes[0]?.stable_key||"all");
      const roleDomain=materialRole==="rubric_source"?row.snapshot.domains?.rubric:row.snapshot.domains?.answer;
      const outcome=materialRole==="question_sheet"?undefined:(roleDomain?.analysis_results?.[materialRole||"model_answer_source"]||roleDomain?.analysis_result);
      const recoveryCount=materialRole&&["model_answer_source","rubric_source"].includes(materialRole)
        ?(row.snapshot.domains?.recovery?.rubric_candidates||[]).filter(candidate=>!candidate.dismissed&&!candidate.promoted&&candidate.origin_role===materialRole&&candidate.source_binding_id===requestedMaterialId).length:0;
      const refreshed=await testAuthoring.review(id);setIssues(refreshed.issues);
      if(domain==="answer"&&outcome){
        setVisible(v=>({...v,answer:true,rubric:true}));
        const detail=[`対応済み${outcome.assigned_count}件 / 未対応${outcome.unresolved_count}件`,...(recoveryCount?[`未割当の採点基準候補が${recoveryCount}件あります。`]:[])].join("。 ");
        const title=materialRole==="rubric_source"?"採点基準を解析しました":"模範解答を解析しました";
        if(!outcome.candidate_count){const target=row.snapshot.nodes.find(n=>n.included&&!row.snapshot.nodes.some(child=>child.included&&child.parent_key===n.stable_key))?.stable_key||row.snapshot.nodes[0]?.stable_key||"all";setSelected(target);const message=materialRole==="rubric_source"?"自動抽出できる採点基準候補がありませんでした。設問を選択し、採点基準を手動で追加してください。":"自動抽出できる模範解答候補がありませんでした。必要なら設問ごとに手動で追加してください。";setError(message);notify("warning",title,message);}
        else if(outcome.fallback_count){if(!outcome.assigned_count)setSelected("unassigned");const message=`${outcome.fallback_count}件の候補を自動分類できませんでした。${outcome.assigned_count?"候補を確認してください。":"設問未割当の候補から確認・割当してください。"}`;setError(message);notify("warning",title,`${detail}。${message}`);}
        else if(!outcome.assigned_count){setSelected("unassigned");const message=`解析結果を設問へ対応付けできませんでした。設問未割当の候補から${materialRole==="rubric_source"?"採点基準":"模範解答"}を選択してください。`;setError(message);notify("warning",title,`${detail}。未対応候補を確認してください。`);}
        else if(outcome.unresolved_count)notify("warning",title,detail);
        else notify("success",title,detail);
      }else if(materialRole==="rubric_source")notify("success","採点基準を解析しました");
      else notify("success","問題用紙の解析が完了しました","問題文・小問構成を更新する場合があります。模範解答・採点基準は保持されます。");
    }catch(e){const message=`資料を解析できませんでした。保存済みの下書きは保持されています。資料を確認して再試行してください。${e instanceof Error?` (${e.message})`:""}`;setError(message);notify("error","解析に失敗しました",message);}finally{setBusy(false);setAnalyzing(false);setAnalysisProgress(null);}
  }
  async function begin(){setBusy(true);setError("");try{
    const row=await testAuthoring.begin(id);setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});
    setSelected(current=>row.snapshot.nodes.some(n=>n.stable_key===current)?current:row.snapshot.nodes[0]?.stable_key||"all");
    setBuffers(authoringBuffers(row.snapshot));
    notify("info","編集用ワークスペースを開きました","保存しても正式な問題・解答・採点基準は変更されません。");
  }catch(e){setError(e instanceof Error?e.message:"下書きを開けませんでした。");}finally{setBusy(false);}}
  async function importSources(){if(!revision)return;
    if(dirty){setError("先に現在の編集内容を保存してください。保存済みレビューは自動では取り込みません。");return;}
    if(!window.confirm("最新の解答・採点基準レビューを取り込みます。現在の設問本文・分割・階層は保持し、取り込み前の編集版も残します。問題レビューの変更は確認事項として扱います。続行しますか？"))return;
    setBusy(true);setError("");try{
      const row=await testAuthoring.importSources(id,revision.edit_version,true);setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});
      setBuffers(authoringBuffers(row.snapshot));
      setSelected(current=>row.snapshot.nodes.some(n=>n.stable_key===current)?current:row.snapshot.nodes[0]?.stable_key||"all");setExternalChange(false);setContinueExternal(false);notify("success","保存済みレビューを取り込みました","現在の設問本文・分割・階層は保持されています。");
    }catch(e){const message=e instanceof Error?e.message:"取り込めませんでした。";setError(message);notify("error","レビューを取り込めませんでした",message);}finally{setBusy(false);}
  }
  async function save():Promise<boolean>{
    if(!snapshot||!revision||saveInFlight.current)return false;
    if(!dirty){setSaveStatus("success");return true;}
    saveInFlight.current=true;const epoch=editEpoch.current;
    setBusy(true);setSaving(true);setSaveStatus("saving");setError("");
    try{
      const value=prepareAuthoringSave(snapshot,buffers);
      const row=await testAuthoring.save(id,value,revision.edit_version,continueExternal);
      if(editEpoch.current===epoch){
        synchronize(row);setSaveStatus("success");notify("success","保存しました");
        void testAuthoring.get(id).then(data=>{
          if(data.revision?.id===row.id&&data.revision.edit_version===row.edit_version&&editEpoch.current===epoch){setSourceProblems(data.source_problems||[]);setExternalChange(data.external_source_change);}
        }).catch(()=>{/* Persisted response remains authoritative even if status refresh fails. */});
      }
      else {setRevision(row);setSnapshot(current=>current?{...current,source_provenance:row.snapshot.source_provenance}:current);notify("warning","送信した内容は保存しました","その後の変更は未保存です。もう一度保存してください。");}
      return editEpoch.current===epoch;
    }catch(e){setSaveStatus("error");const message=`保存できませんでした。編集内容は画面に保持されています。${e instanceof Error?` (${e.message})`:""}`;setError(message);notify("error","保存に失敗しました",message);return false;}
    finally{saveInFlight.current=false;setBusy(false);setSaving(false);}
  }
  async function finalReview(){
    setBusy(true);try{
      if(dirty&&snapshot&&revision){
        const value=prepareAuthoringSave(snapshot,buffers);setIssues((await testAuthoring.reviewLocal(id,value,revision.edit_version)).issues);
      }else setIssues((await testAuthoring.review(id)).issues);
      setSelected("all");
    }
    catch(e){setError(e instanceof Error?e.message:"確認できませんでした。");}finally{setBusy(false);}}
  async function upload(files:FileList|null){if(!files||!snapshot)return;
    const old=replacement?materials.find(m=>m.id===replacement):undefined;
    if(old&&!window.confirm(`${old.original_filename}を差し替えます。元資料は保持されますが、出典付きの確認結果は再確認が必要になります。自動で再解析しません。続行しますか？`)){if(fileInput.current)fileInput.current.value="";return;}setBusy(true);setError("");try{
    const uploaded:Material[]=[];
    for(const file of Array.from(files).slice(0,old?1:files.length)){
      if(!/\.pdf$/i.test(file.name)||file.size>25*1024*1024)throw new Error("25MB以内のPDFを選択してください。");
      uploaded.push(await apiFetch<Material>(`/tests/${id}/materials/upload`,{method:"POST",body:file,
        headers:{"Content-Type":"application/pdf","X-Source-Role":old?.material_type||role,"X-Filename":encodeURIComponent(file.name)}}));
    }
    if(old&&uploaded[0].sha256===old.sha256)throw new Error("同じ内容の資料です。差し替えは行いませんでした。");
    setMaterials(current=>[...current,...uploaded.filter(m=>!current.some(old=>old.id===m.id))]);
    setSnapshot(current=>current?{...current,materials:[...current.materials.filter(ref=>!uploaded.some(m=>m.id===ref.id)),...uploaded.map(m=>({...current.materials.find(ref=>ref.id===m.id),id:m.id,sha256:m.sha256||null,role:m.material_type,...(old?{replaces_material_id:old.id}:{})}))]}:current);
    markDirty();setMaterialId(uploaded[0].id);setSourceMode("pdf");notify("info",old?"資料を差し替えました":"資料を追加しました",old?"元資料と出典情報は保持されています。保存後に明示的に再解析してください。":"既存の資料と解析結果は保持されています.");setReplacement(null);
    if(!old)setRegistrationPrompt({materialId:uploaded[0].id,role:uploaded[0].material_type});
  }catch(e){const message=e instanceof Error?e.message:"資料を追加できませんでした。";setError(message);notify("error","資料を追加できませんでした",message);}finally{setBusy(false);if(fileInput.current)fileInput.current.value="";}}
  async function reuseMaterial(){
    if(!reuseMaterialId||!snapshot)return;
    setBusy(true);setError("");
    try{
      const material=await apiFetch<Material>(`/tests/${id}/materials/${reuseMaterialId}/reuse`,json({material_type:role}));
      setMaterials(current=>current.some(m=>m.id===material.id)?current:[...current,material]);
      setSnapshot(current=>current&&!current.materials.some(m=>m.id===material.id)?{...current,materials:[...current.materials,{id:material.id,sha256:material.sha256||null,role:material.material_type}]}:current);
      markDirty();setMaterialId(material.id);setSourceMode("pdf");setReuseFiles(false);
      notify("info","資料を追加しました","既存ファイルを共有しています。解析は明示操作で開始してください。");
      setRegistrationPrompt({materialId:material.id,role:material.material_type});
    }catch(e){const message=e instanceof Error?e.message:"資料を追加できませんでした。";setError(message);notify("error","資料を追加できませんでした",message);}finally{setBusy(false);}
  }
  async function removeMaterial(material:Material){
    setBusy(true);setError("");try{
      await apiFetch(`/tests/${id}/materials/${material.id}`,{method:"DELETE"});
      setMaterials(current=>current.filter(item=>item.id!==material.id));
      setSnapshot(current=>current?{...current,materials:current.materials.filter(ref=>ref.id!==material.id)}:current);
      if(materialId===material.id){setMaterialId("");setSourceMode("manage");}
      markDirty();setDeleteMaterial(null);notify("success","資料を削除しました","資料の登録だけを解除しました。保存済みの解答・採点基準本文は保持されています。");
    }catch(e){const message=e instanceof Error?e.message:"資料を削除できませんでした。";setError(message);notify("error","資料を削除できませんでした",message);}finally{setBusy(false);}
  }
  async function changeMaterialRole(material:Material,nextRole:string){
    if(nextRole===material.material_type)return;
    setBusy(true);setError("");try{
      const replacement=await apiFetch<Material>(`/tests/${id}/materials/${material.id}/role`,{...json({material_type:nextRole}),method:"PATCH"});
      setMaterials(current=>[...current.filter(item=>item.id!==material.id),replacement]);
      setSnapshot(current=>current?{...current,materials:[...current.materials.filter(ref=>ref.id!==material.id),{id:replacement.id,sha256:replacement.sha256||null,role:replacement.material_type}]}:current);
      setMaterialId(replacement.id);setRole(replacement.material_type);setMaterialRoleChanges({});markDirty();notify("success","資料の種類を変更しました","元ファイルを共有し、新しい種類では未解析として登録しました。");
    }catch(e){const message=e instanceof Error?e.message:"資料の種類を変更できませんでした。";setError(message);notify("error","資料の種類を変更できませんでした",message);}finally{setBusy(false);}
  }
  async function saveThenAnalyzeRegistered(){
    if(!registrationPrompt)return;
    setRegistrationError("");const pending=registrationPrompt;
    const persisted=await save();
    if(!persisted){setRegistrationError("保存できませんでした。編集内容を確認して、もう一度お試しください。");return;}
    setRegistrationPrompt(null);
    const domain=pending.role==="question_sheet"?"question":pending.role==="model_answer_source"||pending.role==="rubric_source"?"answer":null;
    if(domain)setAnalysisRequest({domain,materialId:pending.materialId});
  }
  if(error&&!snapshot)return <ErrorState message={error}/>;
  if(!snapshot)return <LoadingState/>;
  const questionDomain=snapshot.domains?.question;
  const warningQuestion=(warning:ReviewWarning)=>{
    const region=questionDomain?.document.regions.find(r=>r.region_id===warning.source_id);
    const owner=warning.owner||region?.assigned_question_key||warning.source_id;
    const exact=nodes.find(n=>n.included&&n.stable_key===owner);
    if(exact)return exact;
    const sourceOwners=nodes.filter(n=>n.included&&n.source_draft_stable_key===owner);
    return sourceOwners.length===1?sourceOwners[0]:undefined;
  };
  const questionWarnings=(questionDomain?.document.warnings||[]).filter(w=>warningQuestion(w)?.stable_key===node?.stable_key&&!!node);
  const previewScore=node?effectiveQuestionScore(node.stable_key,nodes).points:null;
  const regions=questionDomain?.document.regions||[];
  const activeRegions=regions.filter(r=>node?.ordered_content.some(item=>"region_id" in item&&item.region_id===r.region_id)||!!node?.formula_decisions[r.region_id]||!!node?.figure_decisions[r.region_id]);
  const answer=snapshot.answers[selected]||{primary:"",alternatives:[],diagram_records:[]};
  const criteria=snapshot.rubrics[selected]||[];
  const rubricDomain=snapshot.domains?.rubric;
  const rubricRecovery=(snapshot.domains?.recovery?.rubric_candidates||[]).filter(candidate=>!candidate.dismissed&&!candidate.promoted);
  const rubricEntries:AuthoringEntry[]=(rubricDomain?.entries||[]).map(entry=>({id:entry.id,
    question_id:entry.question_id||null,authoring_question_key:entry.authoring_question_key||null,mapping_state:"manual_mapped",
    answer_text:"",answer_kind:"alternative",source:entry.source,source_draft_id:entry.source_draft_id||undefined,
    material_role:entry.material_role,disposition:entry.disposition||"include",
    semantic_classification:entry.semantic_classification,rubric_edits:entry.criteria,
    rubric_merge_history:entry.operation_history,diagram_records:[]}));
  const supersededMaterialIds=new Set(snapshot.materials.map(m=>m.replaces_material_id).filter((id):id is string=>!!id));
  const questionStale=!!questionDomain&&snapshot.materials.some(m=>m.role==="question_sheet"&&m.sha256===questionDomain.document.source_pdf_sha256&&supersededMaterialIds.has(m.id));
  const answerSources=snapshot.domains?.answer?{[snapshot.domains.answer.draft_id]:snapshot.domains.answer,...snapshot.domains.answer.sources}:{};
  const staleAnswerSourceDraftIds=Object.entries(answerSources).filter(([,source])=>supersededMaterialIds.has(source.material_id)||materials.find(m=>m.id===source.material_id)?.material_type!=="model_answer_source").map(([draftId])=>draftId);
  const answerStale=staleAnswerSourceDraftIds.length>0;
  function updateRecovery(candidateId:string,patch:Record<string,unknown>){
    if(!snapshot?.domains?.recovery)return;
    change({...snapshot,domains:{...snapshot.domains,recovery:{...snapshot.domains.recovery,
      rubric_candidates:snapshot.domains.recovery.rubric_candidates.map(candidate=>candidate.id===candidateId?{...candidate,...patch}:candidate)}}},"rubric");
  }
  function promoteRecovery(candidateId:string){
    if(!snapshot||!rubricDomain)return;
    const candidate=rubricRecovery.find(item=>item.id===candidateId);if(!candidate)return;
    const target=recoveryTargets[candidate.id]||candidate.question_key||orderedNodes().find(item=>!nodes.some(child=>child.included&&child.parent_key===item.stable_key))?.stable_key;
    if(!target){setError("採点基準の追加先となる設問を選択してください。");return;}
    const criterionId=`teacher-rubric-${localId()}`;
    const criterion={id:criterionId,description:candidate.text,points:0,source_text:candidate.text,segment_ids:[candidate.segment_id],
      grouping_confirmed:false,grouping_method:"teacher_recovery",points_conflict:true,points_confirmed:false,
      provenance:{teacher_recovered:true,origin_role:candidate.origin_role,source_draft_id:candidate.source_draft_id,
        source_binding_id:candidate.source_binding_id,source_sha256:candidate.source_sha256,source_candidate_id:candidate.source_candidate_id,
        source_candidate_segment_id:candidate.segment_id,source_provenance:candidate.provenance}};
    const existing=rubricDomain.entries.find(entry=>entry.authoring_question_key===target&&entry.material_role==="teacher_manual");
    const newEntry=existing?{...existing,criteria:[...existing.criteria,criterion]}:{id:`teacher-rubric-${localId()}`,
      authoring_question_key:target,question_id:snapshot.source_provenance.authoring_origins?.identities?.[target]?.formal_question_id||target,
      material_role:"teacher_manual",source_draft_id:null,material_id:null,source_sha256:null,
      source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]},criteria:[criterion],operation_history:[]};
    const entries=existing?rubricDomain.entries.map(entry=>entry.id===existing.id?newEntry:entry):[...rubricDomain.entries,newEntry];
    const recovery={...snapshot.domains?.recovery,rubric_candidates:snapshot.domains?.recovery?.rubric_candidates.map(item=>item.id===candidate.id?{...item,promoted:true}:item)||[]};
    const rubrics={...snapshot.rubrics,[target]:[...(snapshot.rubrics[target]||[]),criterion]};
    change({...snapshot,domains:{...snapshot.domains,rubric:{...rubricDomain,entries},recovery},rubrics},"rubric");
  }
  const viewed=materials.find(m=>m.id===materialId);
  const analysisDomain=viewed?.material_type==="question_sheet"?"question":
    viewed&&["model_answer_source","rubric_source"].includes(viewed.material_type)?"answer":undefined;
  const boundAnalyzed=analysisDomain==="question"?!!questionDomain&&viewed?.sha256===questionDomain.document.source_pdf_sha256:
    analysisDomain==="answer"&&materialId===snapshot.domains?.answer?.material_id;
  const analyzed=!!boundAnalyzed||snapshot.source_provenance.analysis_materials?.some(m=>m.id===materialId&&m.sha256===viewed?.sha256);
  const readiness=analysisReadiness(revision?.analysis_readiness?.[materialId],{editable:!readonly,dirty,busy,selected:!!materialId,supported:!!analysisDomain});
  const analysisReason=readiness.reason;
  const analysisMaterial=analysisRequest?materials.find(m=>m.id===analysisRequest.materialId):undefined;
  const sourceWarnings=revision?.source_warnings||[];
  const replaceMaterial=(mid:string)=>{setReplacement(mid);setRole(materials.find(m=>m.id===mid)?.material_type||"question_sheet");setSourceMode("add");};
  let mappedLocation:{id:string;page:number;bbox?:number[]}|undefined;
  if(node&&viewed?.sha256===questionDomain?.document.source_pdf_sha256){
    const selectedRegion=regions.find(r=>r.region_id===regionId&&activeRegions.includes(r));
    const source=selectedRegion||questionDomain?.document.source_regions[node.stable_key]?.[0];
    if(source)mappedLocation={id:`${selected}:${regionId}`,page:source.page_index+1,bbox:source.bbox};
  }else if(node&&materialId===snapshot.domains?.answer?.material_id){
    const sourceId=snapshot.source_provenance.authoring_origins?.identities[selected]?.formal_question_id||selected;
    const source=snapshot.domains.answer.question_regions.find(r=>r.question_id===sourceId);
    if(source)mappedLocation={id:`${selected}:${materialId}`,page:source.page_index+1,bbox:[source.left,source.top,source.right,source.bottom]};
  }
  return <><h1>{snapshot.metadata.name}</h1><p>問題・解答・採点基準を編集します。保存しても既存の正式内容は変更されません。</p>
    {externalChange&&<section role="alert" className="panel"><p>外部の保存済みレビューが更新されています。統合下書きは上書きされていません。</p>
      <button disabled={busy} onClick={()=>{setContinueExternal(true);notify("info","現在の編集内容を継続します","外部レビューの更新は取り込みません。");}}>現在の下書きを継続</button>
      <button disabled={busy} onClick={importSources}>最新レビューを取り込む</button></section>}
    {error&&!splitProposal&&<p role="alert" className="error">{error}</p>}
    {sourceWarnings.length>0&&<section aria-label="保存済み内容の出典確認" className="authoring-source-notice" role="status"><p>⚠ 元資料との対応に確認が必要な設問があります。編集内容は保存されています。</p>{sourceWarnings.map((w,i)=><div key={i}><span>{w.message}</span>{w.question_key&&<button onClick={()=>navigate({question_key:w.question_key,section:"question",field:"source",message:w.message})}>確認する</button>}</div>)}</section>}
    {(sourceProblems.length>0||questionStale||answerStale)&&<p role="alert">元PDFとの対応が無効になっています。資料と保存済みレビューを確認し、必要なら明示的に再解析してください。</p>}
    <ReviewWorkspaceLayout actions={<div className="review-toolbar" aria-busy={busy}>
      {readonly?<button className="button" disabled={busy} onClick={begin}>修正版を作成</button>:<button className={`button authoring-save-button${dirty?" is-dirty":" is-saved"}`} aria-describedby="authoring-save-state" disabled={busy} onClick={()=>void save()}>{saving?"保存中…":"保存"}</button>}
      {!readonly&&<span id="authoring-save-state" className="visually-hidden" role="status">{dirty?"保存状態: 未保存の変更があります":"保存状態: 保存済み"}</span>}
      {!readonly&&<button disabled={busy} onClick={importSources}>保存済みレビューを取り込む</button>}
      <button className="button secondary" disabled={busy} onClick={finalReview}>最終確認へ</button><Link className="button secondary" href={`/tests/${id}`} onClick={event=>{if(saving||dirty&&!window.confirm("未保存の変更があります。保存せずにテスト詳細へ戻りますか？"))event.preventDefault();}}>戻る</Link>
      {dirty&&<><span role="status">未保存の変更があります</span><span className="muted">{Object.entries(dirtyDomains).filter(([,v])=>v).map(([k])=>({question:"問題",answer:"解答",rubric:"採点基準",diagram:"図"}[k])).filter(Boolean).join("・")}</span></>}
      <div className="authoring-utility-controls">{notificationView}
        <div className="authoring-issues-control"><button type="button" aria-label={`要修正事項、未解決${issues.length}件`} aria-expanded={issuesOpen} onClick={()=>setIssuesOpen(value=>!value)}>⚠ 要修正{issues.length>0&&<span className="authoring-count-badge">{issues.length}</span>}</button>
          {issuesOpen&&<section className="authoring-issues-panel" aria-label="要修正事項"><header><strong>要修正事項 {issues.length}件</strong><button type="button" onClick={()=>setIssuesOpen(false)}>閉じる</button></header>{issues.length===0?<p>現在、確認が必要な項目はありません。</p>:<ul>{issues.map((issue,index)=><li key={`${issue.question_key||issue.section}-${issue.field||""}-${index}`}>{issue.question_key||issue.section==="answer"?<button type="button" onClick={()=>{navigate(issue);setIssuesOpen(false);}}>{issue.question_key?pathFor(issue.question_key):"設問未割当"} — {issue.message}</button>:<span>{issue.message}</span>}</li>)}</ul>}</section>}
        </div>
      </div>
    </div>} source={<>
      <div className="authoring-source-controls" role="group" aria-label="利用資料の操作">
        <select aria-label="利用資料" value={sourceMode==="pdf"?materialId:`action:${sourceMode}`} onChange={e=>{
          const value=e.target.value;if(value==="action:add"||value==="action:manage"){setReplacement(null);setSourceMode(value==="action:add"?"add":"manage");if(value==="action:add"){const order=["question_sheet","model_answer_source","rubric_source"],present=new Set(materials.map(m=>m.material_type));const missing=order.find(item=>!present.has(item));setRole(missing||order[(order.indexOf(role)+1)%order.length]);}}
          else {setMaterialId(value);setSourceMode("pdf");setReplacement(null);}
        }}><option value="">資料を選択・追加・編集</option><optgroup label="資料">{materials.map(m=><option key={m.id} value={m.id}>{roles[m.material_type]||"資料"} — {m.original_filename}{snapshot.materials.some(ref=>ref.replaces_material_id===m.id)?"（差し替え済み）":""}</option>)}</optgroup>
          <optgroup label="資料管理"><option value="action:add">資料の追加</option><option value="action:manage">資料の編集</option></optgroup>
        </select>
        {sourceMode==="pdf"&&materialId&&<div className="authoring-current-material-actions"><DisabledActionHint reason={readiness.state==="unsaved_changes"?"未保存の変更があります。この資料を解析する前に保存してください。":analysisReason||undefined}><button disabled={readiness.state!=="ready"} onClick={event=>{if(analysisDomain){analysisTrigger.current=event.currentTarget;setAnalysisRequest({domain:analysisDomain,materialId});}}}>{analyzing?"解析中…":analyzed?"再解析":"解析"}</button></DisabledActionHint>
          <button disabled={readonly||busy} onClick={()=>replaceMaterial(materialId)}>差換え</button>
        </div>}
      </div>
      {sourceMode!=="pdf"&&(<section className="authoring-material-management" aria-label="資料管理"><h3>{sourceMode==="manage"?"資料の編集":replacement?"資料の差換え":"資料の追加"}</h3><p>資料を追加してから編集できます。差し替えは元資料を保持し、出典の再確認が必要です。解析は明示操作のみです。</p>{sourceMode==="manage"&&<><button disabled={readonly||busy} onClick={()=>{setReplacement(null);setSourceMode("add");}}>資料の追加</button><ul>{materials.map(m=><li key={m.id}>{roles[m.material_type]||"資料"} — {m.original_filename}<details><summary>出典情報</summary>SHA: {m.sha256||"なし"}<p>{snapshot.materials.some(ref=>ref.replaces_material_id===m.id)?"差し替え済み・元資料を保持":"利用中"}{materialId===m.id?"・選択中の資料":""}</p></details><button onClick={()=>{setMaterialId(m.id);setSourceMode("pdf");}}>選択</button><button disabled={readonly||busy} onClick={()=>replaceMaterial(m.id)}>差換え</button><label>資料の種類<select aria-label={`${m.original_filename}の資料の種類`} disabled={readonly||busy} value={materialRoleChanges[m.id]||m.material_type} onChange={event=>setMaterialRoleChanges(current=>({...current,[m.id]:event.target.value}))}>{Object.entries(roles).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><button disabled={readonly||busy||!(materialRoleChanges[m.id]&&materialRoleChanges[m.id]!==m.material_type)} onClick={()=>void changeMaterialRole(m,materialRoleChanges[m.id])}>種類を変更</button><button disabled={readonly||busy} onClick={()=>setDeleteMaterial(m)}>資料を削除</button></li>)}</ul></>}{sourceMode==="add"&&<>{replacement&&<p role="alert">差し替え対象: {materials.find(m=>m.id===replacement)?.original_filename}。既存の出典確認は再確認が必要です。自動解析は行いません。</p>}
        <label>資料の種類<select aria-label="資料の種類" disabled={!!replacement} value={role} onChange={e=>setRole(e.target.value)}>{Object.entries(roles).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <input ref={fileInput} aria-label="資料を追加" type="file" accept="application/pdf,.pdf" multiple={!replacement} disabled={readonly||busy} onChange={e=>void upload(e.target.files)}/>
        {!replacement&&<><button disabled={readonly||busy} onClick={()=>setReuseFiles(value=>!value)}>既存ファイルを再利用</button>
          {reuseFiles&&<section aria-label="既存ファイルの再利用"><label>既存ファイル<select aria-label="既存ファイル" value={reuseMaterialId} onChange={e=>setReuseMaterialId(e.target.value)}><option value="">ファイルを選択</option>{materials.filter((m,i,all)=>m.sha256&&all.findIndex(other=>other.sha256===m.sha256)===i).map(m=><option key={m.id} value={m.id}>{m.original_filename} — {m.sha256?.slice(0,8)} — 使用中: {materials.filter(other=>other.sha256===m.sha256).map(other=>roles[other.material_type]||other.material_type).join("・")}</option>)}</select></label>
            <button disabled={readonly||busy||!reuseMaterialId||materials.some(m=>m.material_type===role&&m.sha256===materials.find(source=>source.id===reuseMaterialId)?.sha256)} onClick={()=>void reuseMaterial()}>{roles[role]}として追加</button>
            {reuseMaterialId&&materials.some(m=>m.material_type===role&&m.sha256===materials.find(source=>source.id===reuseMaterialId)?.sha256)&&<p>このファイルは選択した資料の種類で登録済みです。</p>}
          </section>}
        </>}
        <p>選択した資料の解析は左ペインの「解析」「再解析」から開始してください。未保存の変更がある場合は先に保存してください。</p>
        <p><Link href={`/tests/${id}?section=questions`}>既存の資料解析・出典付きレビューを開く</Link></p>
      </>}</section>)}
      {sourceMode==="pdf"&&materialId&&<SourcePdfPreview key={materialId} testId={id} material={materials.find(m=>m.id===materialId)} label="利用資料PDF" inline paneZoom diagramSelection={diagramSelection?.record.material_id===materialId?diagramSelection:undefined} targetLocation={diagramSelection?.record.material_id===materialId?{id:diagramSelection.record.id,page:diagramSelection.record.page_index+1,bbox:diagramSelection.record.final_bbox||diagramSelection.record.automatic_bbox}:mappedLocation}/>}
    </>} selector={<><div className="review-toolbar authoring-target-controls">
      <label>対象設問<select aria-label="対象設問" value={selected} onChange={e=>{if(e.target.value==="all")void finalReview();else {setSelected(e.target.value);setDiagramSelection(undefined);setRegionId("");}}}>
        {orderedNodes().map(n=><option key={n.stable_key} value={n.stable_key}>{pathFor(n.stable_key)}</option>)}{snapshot.domains?.answer?.entries.some(e=>!e.authoring_question_key)&&<option value="unassigned">設問未割当の候補</option>}<option value="all">テスト全体確認</option>
      </select></label><span>表示</span>{([['question','問題'],['answer','解答'],['rubric','採点基準']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={visible[key]} onChange={e=>{const next={...visible,[key]:e.target.checked};setVisible(next);localStorage.setItem("test-authoring-visible",JSON.stringify(next));}}/>{label}</label>)}
      <span className="authoring-add-question"><button disabled={readonly||saving||analyzing} onClick={()=>{const n=newNode(nodes.length);change({...snapshot,nodes:[...nodes,n]});setBuffers(current=>({...current,[n.stable_key]:""}));setSelected(n.stable_key);}}>設問を追加</button></span>
    </div>{analyzing&&<p className="authoring-analysis-progress" role="status" aria-live="polite"><span className="spinner" aria-hidden="true"/><strong>{analysisProgress}を解析しています…</strong><span className="muted">元資料を確認し、候補を更新しています。</span></p>}
      {rubricRecovery.length>0&&<details className="authoring-recovery-panel"><summary>未割当の採点基準候補を確認（{rubricRecovery.length}件）</summary><p>候補は採点基準へ自動登録されていません。内容と対応先を確認してください。</p>
        {rubricRecovery.map(candidate=><article className="panel" key={candidate.id}><MarkdownMathText source={candidate.text}/><p>{candidate.origin_role==="model_answer_source"?"模範解答資料内で見つかった採点基準候補":"採点基準資料からの候補"}</p>
          <label>対象設問<select aria-label="未割当候補の対象設問" value={recoveryTargets[candidate.id]||candidate.question_key||""} onChange={event=>setRecoveryTargets(current=>({...current,[candidate.id]:event.target.value}))}><option value="">設問を選択</option>{orderedNodes().filter(item=>!nodes.some(child=>child.included&&child.parent_key===item.stable_key)).map(item=><option key={item.stable_key} value={item.stable_key}>{pathFor(item.stable_key)}</option>)}</select></label>
          <button type="button" disabled={readonly||saving||analyzing||!(recoveryTargets[candidate.id]||candidate.question_key)} onClick={()=>promoteRecovery(candidate.id)}>採点基準として追加</button>
          <button type="button" disabled={readonly||saving||analyzing} onClick={()=>updateRecovery(candidate.id,{dismissed:true})}>無視</button>
        </article>)}
      </details>}
    </>}>
      {selected==="all"?<section aria-label="テスト全体確認"><h2>テスト全体確認</h2>
        <label>テスト名<input disabled={readonly||saving||analyzing} value={snapshot.metadata.name} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,name:e.target.value}})}/></label>
        <label>合計点<input type="number" disabled={readonly||saving||analyzing} value={snapshot.metadata.total_points} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,total_points:Number(e.target.value)}})}/></label>
        <ol>{nodes.filter(n=>n.included).map(n=><li key={n.stable_key}>{pathFor(n.stable_key)} — {effectiveQuestionScore(n.stable_key,nodes).points??"未設定"}点</li>)}</ol>
        <ul>{issues.map((issue,index)=><li key={index}>{issue.question_key||issue.section==="answer"?<button onClick={()=>navigate(issue)}>{issue.question_key?pathFor(issue.question_key):"設問未割当"} — {issue.message}</button>:issue.message}</li>)}</ul>
        {questionDomain&&questionDomain.document.warnings.length>0&&<WarningPanel targetLabel={w=>{const owner=warningQuestion(w);return owner?pathFor(owner.stable_key):"試験全体";}} warnings={questionDomain.document.warnings} states={questionDomain.snapshot.warning_states||{}} readonly={readonly||saving||analyzing}
            onChange={(key,resolution)=>change({...snapshot,domains:{...snapshot.domains,question:{...questionDomain,snapshot:{...questionDomain.snapshot,warning_states:{...questionDomain.snapshot.warning_states,[key]:resolution}}}}})}/>}
        <button disabled title="この画面からの試験内容確定は現在利用できません。">試験内容を確定</button>
      </section>:(node||selected==="unassigned")&&<>
        {visible.question&&node&&<section id="authoring-question" tabIndex={-1} aria-label="問題"><h2>問題</h2>

          <AuthoringPreviewEditor actions={<button aria-pressed={questionSettings} onClick={()=>{setQuestionSettings(v=>!v);setEditing(v=>({...v,question:false}));}}>{questionSettings?"プレビューに戻る":"設問設定の変更"}</button>} label="問題" editLabel="本文編集" editing={editing.question} auxiliaryEditing={questionSettings} onEditing={value=>{setQuestionSettings(false);setEditing(v=>({...v,question:value}));}} preview={<><p className="authoring-question-metadata">{node.parent_key?"小問":"大問"}：{pathFor(node.stable_key)} ／ 配点：{previewScore??"－"}点（{node.score_semantics==="sum_children"?"小問合計":node.score_semantics==="each_child"?"小問ごとの配点":previewScore===null?"未設定":"直接配点"}）</p><div className="authoring-question-preview-frame"><MarkdownMathText source={buffers[selected]??node.body_text}/><AcceptedDiagramPreview records={questionStale?[]:node.diagram_records} path={questionDomain?`/tests/${id}/authoring/nodes/${selected}/diagrams`:undefined}/></div></>}>
          <NodeEditor editorMode={questionSettings?"settings":"body"} inlinePreview={false} key={node.stable_key} node={node} nodes={nodes} regions={activeRegions} readonly={readonly||analyzing}
            content={buffers[selected]??node.body_text} contentChanged={(buffers[selected]??node.body_text)!==questionContent(node,regions).text}
            mathContext={questionDomain&&!questionStale&&revision?{reviewId:questionDomain.document.id,revision:revision.edit_version,savedNode:revision.snapshot.nodes.find(n=>n.stable_key===selected),authoringTestId:id}:undefined}
            activeRegionId={regionId} renderEvidence={questionDomain?(rid)=><EvidencePanel id={questionDomain.document.id} regionId={rid} ownerLabel={pathFor(selected)} readonly={readonly||saving||analyzing}
              decision={(regions.find(r=>r.region_id===rid)?.region_type==="formula"?node.formula_decisions:node.figure_decisions)[rid]||{decision:"unreviewed"}}
              onDecision={d=>{const field=regions.find(r=>r.region_id===rid)?.region_type==="formula"?"formula_decisions":"figure_decisions";updateNode({...node,[field]:{...node[field],[rid]:d}});}}/>:undefined}
            onCaret={offset=>{questionCaret.current=offset;}} onContentChange={(text,proposal)=>{setSplitProposal(null);markDirty();setDirtyDomains(d=>({...d,question:true}));setBuffers(current=>({...current,[selected]:text}));if(proposal?.apply_provenance)updateNode({...node,math_ocr_edits:[...(node.math_ocr_edits||[]),proposal.apply_provenance].slice(-16)});}}
            onConfirmContent={confirm=>{const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);if(next)updateNode(confirm(next));else setError("問題文と元資料の対応を確認してください。");}} onChange={updateNode}
            onParent={parent=>reparentNode(node,parent)} onMove={direction=>moveNode(node,direction)} onRegion={setRegionId}/>
          <div hidden={questionSettings}><button disabled={readonly||saving||analyzing} onClick={()=>{
            const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);
            if(!next){setError("元資料との対応を保った分割案を作成できません。");return;}
            updateNode(next);const proposal=suggestSubquestions(next,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key));
            setError("");setSplitProposal(proposal?reviewQuestionSplit(proposal,node):null);if(!proposal)notify("info","小問候補は見つかりませんでした","必要なら設問を追加してください。");
          }}>小問の分割案を作成</button>
          <button disabled={readonly||saving||busy||splitRunning} aria-busy={splitRunning} onClick={()=>void suggestQuestionSplit()}>{splitRunning?<><span className="spinner" aria-hidden="true"/>分割案を作成中…</>:"AIで小問の分割案を作成"}</button>
          <button disabled={readonly||saving||analyzing} onClick={()=>{
            const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);
            const proposal=next&&splitQuestionAtCaret(next,questionCaret.current,questionContent(next,regions).spans,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key)?.ordered_content);
            if(!proposal){setError("この位置は元資料の範囲を安全に分割できません。数式や図の境界を避け、分割位置を確認してください。");return;}
            setError("");updateNode(next!);setSplitProposal(reviewQuestionSplit(proposal,node));
          }}>問題文のカーソル位置で分割</button>

          </div><div hidden={questionSettings}>
          {questionDomain&&revision&&<DiagramReview path={`/tests/${id}/authoring/nodes/${selected}/diagrams`} revision={revision.edit_version}
            records={node.diagram_records} sourceStale={questionStale} disabled={readonly||saving||analyzing} label="図の確認" onSelect={setDiagramSelection}
            onChange={records=>{markDirty();setDirtyDomains(d=>({...d,diagram:true}));setSnapshot(current=>current?{...current,nodes:current.nodes.map(n=>{if(n.stable_key!==node.stable_key)return n;const decisions={...n.figure_decisions};for(const record of records)for(const rid of record.legacy_region_ids||(record.legacy_region_id?[record.legacy_region_id]:[]))decisions[rid]={decision:record.state==="accepted"?"accepted_as_evidence":record.state==="excluded"?"excluded":"unreviewed"};return {...n,diagram_records:records,figure_decisions:decisions};})}:current);}}/>}
          {questionDomain&&questionWarnings.length>0&&<WarningPanel warnings={questionWarnings} targetLabel={()=>pathFor(selected)} states={questionDomain.snapshot.warning_states||{}} readonly={readonly||saving||analyzing}
            onChange={(key,resolution)=>change({...snapshot,domains:{...snapshot.domains,question:{...questionDomain,snapshot:{...questionDomain.snapshot,warning_states:{...questionDomain.snapshot.warning_states,[key]:resolution}}}}})}/>}
          </div>
        </AuthoringPreviewEditor></section>}
        {visible.answer&&<section id="authoring-answer" tabIndex={-1} aria-label="模範解答"><h2>模範解答</h2>
          {snapshot.domains?.answer&&revision?<AuthoringCandidates key={`answer:${snapshot.domains.answer.draft_id}`} testId={id} draftId={snapshot.domains.answer.draft_id} revision={revision.edit_version} questionKey={selected}
            staleSourceDraftIds={staleAnswerSourceDraftIds} entries={snapshot.domains.answer.entries as AuthoringEntry[]} savedEntries={(revision.snapshot.domains?.answer?.entries||[]) as AuthoringEntry[]} disabled={readonly||saving||analyzing}
            answerEditing={editing.answer} rubricEditing={false} onAnswerEditing={value=>setEditing(v=>({...v,answer:value}))} onRubricEditing={()=>{}}
            showAnswer showRubric={false} questions={orderedNodes().map(n=>({key:n.stable_key,parentKey:n.parent_key,label:pathFor(n.stable_key),gradable:!nodes.some(c=>c.included&&c.parent_key===n.stable_key),sourceId:snapshot.source_provenance.authoring_origins?.identities[n.stable_key]?.formal_question_id||n.stable_key}))}
            onSelect={selection=>{if(selection.record.source_type==="manual_pdf_crop"&&selection.record.material_id){setMaterialId(String(selection.record.material_id));setSourceMode("pdf");}setDiagramSelection(selection);}} onChange={entries=>{
              const answerDomain=snapshot.domains?.answer;
              if(!answerDomain)return;
              const answers={...snapshot.answers};
              for(const key of new Set([...answerDomain.entries,...entries].map(e=>e.authoring_question_key).filter((value):value is string=>!!value))){
                const current=entries.filter(e=>e.authoring_question_key===key&&e.material_role!=="rubric_source"&&e.disposition!=="ignored"&&e.disposition!=="excluded"&&e.disposition!=="unassigned");
                const primary=current.find(e=>(e.answer_kind||"primary")==="primary"&&(e.answer_text.trim()||e.diagram_records?.some(record=>record.state==="accepted")))||current.find(e=>(e.answer_kind||"primary")==="primary");
                answers[key]={primary:primary?.answer_text||"",alternatives:current.flatMap(e=>[...(e.answer_kind==="alternative"?[e.answer_text]:[]),...(e.manual_alternative_answers||e.semantic_classification?.manual_alternative_answers||e.semantic_classification?.alternative_answers||[]).map(a=>a.text)]),diagram_records:primary?.diagram_records||[]};
              }
              change({...snapshot,domains:{...snapshot.domains,answer:{...answerDomain,entries}},answers},"answer");
            }}/>:<AuthoringPreviewEditor editLabel="本文編集" label="模範解答" editing={editing.answer} onEditing={value=>setEditing(v=>({...v,answer:value}))} preview={<div className="authoring-question-preview-frame authoring-answer-preview-frame"><MarkdownMathText source={answer.primary||"本文なし"}/>{answer.alternatives.map((text,index)=><div key={index}><h4>別解{index+1}</h4><MarkdownMathText source={text}/></div>)}<AcceptedDiagramPreview records={answer.diagram_records}/></div>}>
            <label>模範解答本文<textarea aria-label="模範解答本文" rows={4} disabled={readonly||saving||analyzing} value={answer.primary} onChange={event=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:event.target.value}}},"answer")}/></label>
            <LatexNormalizationControl text={answer.primary} contextType="model_answer" disabled={readonly||saving||analyzing} onApply={text=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:text}}},"answer")}/>
          </AuthoringPreviewEditor>}
        </section>}
        {visible.rubric&&<section id="authoring-rubric" tabIndex={-1} aria-label="採点基準"><h2>採点基準</h2>
          <AuthoringCandidates key={`rubric:${rubricDomain?.draft_id||"manual"}`} testId={id} draftId={rubricDomain?.draft_id||"manual-rubric"} revision={revision?.edit_version||1} questionKey={selected}
            entries={rubricEntries} savedEntries={rubricEntries} disabled={readonly||saving||analyzing} answerEditing={false} rubricEditing={editing.rubric}
            onAnswerEditing={()=>{}} onRubricEditing={value=>setEditing(v=>({...v,rubric:value}))} showAnswer={false} showRubric
            questions={orderedNodes().map(n=>({key:n.stable_key,parentKey:n.parent_key,label:pathFor(n.stable_key),gradable:!nodes.some(c=>c.included&&c.parent_key===n.stable_key)}))}
            onSelect={setDiagramSelection} onChange={updated=>{
              const oldById=new Map((rubricDomain?.entries||[]).map(entry=>[entry.id,entry]));
              const entries=updated.map(entry=>{
                const old=oldById.get(entry.id);
                return old?{...old,criteria:entry.rubric_edits||old.criteria,operation_history:entry.rubric_merge_history||old.operation_history,authoring_question_key:entry.authoring_question_key,question_id:entry.question_id,disposition:entry.disposition,semantic_classification:entry.semantic_classification}:
                  {id:entry.id,authoring_question_key:entry.authoring_question_key,question_id:entry.question_id,material_role:"teacher_manual",source_draft_id:null,material_id:null,source_sha256:null,source:entry.source,candidate_text:"",disposition:"include" as const,criteria:entry.rubric_edits||[],operation_history:entry.rubric_merge_history||[]};
              });
              const domain={...(rubricDomain||{entries:[],sources:{},analysis_result:null,analysis_results:{}}),entries};
              const rubrics={...snapshot.rubrics};
              for(const key of new Set([...rubricEntries,...updated].map(entry=>entry.authoring_question_key).filter((value):value is string=>!!value)))
                rubrics[key]=entries.filter(entry=>entry.authoring_question_key===key&&entry.disposition!=="excluded"&&entry.disposition!=="ignored").flatMap(entry=>entry.criteria.filter(criterion=>!criterion.excluded));
              change({...snapshot,domains:{...snapshot.domains,rubric:domain},rubrics},"rubric");
            }}/>
        </section>}
      </>}

    </ReviewWorkspaceLayout>
    {splitProposal&&(()=>{const target=nodes.find(candidate=>candidate.stable_key===splitProposal.targetKey);if(!target)return null;return <AuthoringDialog title={`${pathFor(target.stable_key)}の分割案`} onCancel={()=>setSplitProposal(null)} actions={<><button type="button" onClick={()=>setSplitProposal(null)}>取消</button><button type="button" disabled={splitProposal.children.some(child=>child.included&&(child.role||"child")==="child"&&(!["automatic","manual_mapped"].includes(child.mappingStatus)||!child.contentValid))} onClick={applyQuestionSplitProposal}>分割を適用</button></>}>
      <p>元の問題文</p><div className="authoring-question-preview-frame"><MarkdownMathText source={buffers[target.stable_key]??questionContent(target,regions).text}/></div>
      {error&&<p role="alert" className="error">{error}</p>}<h3>分割後の候補</h3>{splitProposal.children.map((child,index)=><Fragment key={`${target.stable_key}:${index}`}><div className="authoring-split-block">
        <label>小問名<input value={child.label} onChange={event=>setSplitProposal(current=>current?{...current,children:current.children.map((candidate,i)=>i===index?{...candidate,label:event.target.value}:candidate)}:current)}/></label>
        <label>分割部分 {index+1}の扱い<select aria-label={`分割部分 ${index+1}の扱い`} value={child.role||"child"} onChange={event=>setSplitProposal(current=>current?{...current,children:current.children.map((candidate,i)=>i===index?{...candidate,role:event.target.value as "parent"|"child"|"exclude"}:candidate)}:current)}><option value="parent">親本文に残す</option><option value="child">小問にする</option><option value="exclude">除外</option></select></label>
        <pre>{questionContent({...target,ordered_content:child.items},regions).text}</pre><p>{child.mappingStatus==="automatic"?"元資料との対応を確認済み":"元資料との対応を確認できません。対応する読み取り項目を指定してください。"}</p>
        {child.mappingStatus==="manual_required"&&<fieldset><legend>対応する読み取り項目</legend>{splitProposal.sourceOptions.map(option=><label key={option.id}><input type="checkbox" checked={child.selectedSourceIds.includes(option.id)} onChange={event=>setSplitProposal(current=>current?{...current,children:current.children.map((candidate,i)=>i===index?{...candidate,selectedSourceIds:event.target.checked?[...candidate.selectedSourceIds,option.id]:candidate.selectedSourceIds.filter(value=>value!==option.id)}:candidate)}:current)}/>{option.label} — {option.excerpt}</label>)}<button type="button" onClick={()=>{const items=mapCandidateToSources(child.items,child.selectedSourceIds,splitProposal.sourceOptions);if(items)setSplitProposal(current=>current?{...current,children:current.children.map((candidate,i)=>i===index?{...candidate,items,mappingStatus:"manual_mapped",included:true}:candidate)}:current);}}>この対応を使用</button></fieldset>}
      </div>{index<splitProposal.children.length-1&&<hr className="authoring-split-divider"/>}</Fragment>)}
    </AuthoringDialog>;})()}
    {registrationPrompt&&<AuthoringDialog title="保存して解析へ進みますか？" onCancel={()=>{if(!saving)setRegistrationPrompt(null);}} busy={saving} actions={<><button type="button" disabled={saving} onClick={()=>setRegistrationPrompt(null)}>いいえ</button><button type="button" disabled={saving} onClick={()=>void saveThenAnalyzeRegistered()}>{saving?"保存中…":"はい"}</button></>}>
      <p>ファイルを読み込みました。</p><p>解析には保存が必要です。保存と解析確認へ進みますか？</p>{registrationError&&<p role="alert" className="error">{registrationError}</p>}
    </AuthoringDialog>}
    {deleteMaterial&&<AuthoringDialog title="この資料を削除しますか？" onCancel={()=>{if(!busy)setDeleteMaterial(null);}} busy={busy} actions={<><button type="button" disabled={busy} onClick={()=>setDeleteMaterial(null)}>キャンセル</button><button type="button" disabled={busy} onClick={()=>void removeMaterial(deleteMaterial)}>資料を削除</button></>}>
      <p>削除するのはこの資料の種類の登録です。同じ元ファイルを使う別の資料や、保存済みの解答・採点基準本文は削除されません。</p><p>元資料との関連が解除される場合があります。</p>
    </AuthoringDialog>}
    {analysisRequest&&analysisMaterial&&<AuthoringDialog title={`${roles[analysisMaterial.material_type]||"資料"}を${analyzed?"再解析":"解析"}しますか？`} onCancel={closeAnalysis} actions={<><button type="button" onClick={closeAnalysis}>キャンセル</button><button type="button" disabled={busy} onClick={()=>{const request=analysisRequest;closeAnalysis();if(request)void analyzeSource(request.domain,request.materialId);}}>{analyzed?"再解析":"解析"}</button></>}>
      <div id="authoring-analysis-description">
        {analysisMaterial.material_type==="question_sheet"?<><p>問題用紙を{analyzed?"再解析":"解析"}すると、問題文・小問構成など問題用紙から作成した内容が、新しい解析結果をもとに更新される可能性があります。</p><p>模範解答・採点基準の編集内容は保持されます。</p></>:
          analysisMaterial.material_type==="model_answer_source"?<><p>模範解答の解析結果だけを更新します。</p><p>問題文・小問構成は変更しません。採点基準の編集内容も保持されます。</p></>:
          <><p>採点基準の解析結果だけを更新します。</p><p>問題文・小問構成・模範解答は変更しません。</p></>}
        <p>現在の保存状態は履歴として保持されます。</p><p>続行しますか？</p>
      </div>
    </AuthoringDialog>}
    </>;
}
