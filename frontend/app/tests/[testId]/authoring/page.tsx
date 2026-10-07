"use client";
import {useEffect, useRef, useState} from "react";
import {useParams} from "next/navigation";
import Link from "next/link";
import {ReviewWorkspaceLayout} from "@/components/reviews/ReviewWorkspaceLayout";
import {AuthoringPreviewEditor, AcceptedDiagramPreview} from "@/components/reviews/AuthoringPreviewEditor";
import {MarkdownMathText} from "@/components/MarkdownMathText";
import {NodeEditor} from "@/components/reviews/NodeEditor";
import {SourcePdfPreview} from "@/components/SourcePdfPreview";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import {LoadingState, ErrorState} from "@/components/ui";
import {testAuthoring, type AuthoringRevision, type AuthoringSnapshot, type AuthoringIssue} from "@/lib/api/testAuthoring";
import {testData} from "@/lib/api/domain";
import {apiFetch, json} from "@/lib/api/client";
import {canonicalQuestionPath} from "@/lib/canonicalQuestionPath";
import {localId} from "@/lib/localId";
import {editQuestionContent, questionContent} from "@/lib/questionContent";
import {DiagramReview, type DiagramSelection} from "@/components/reviews/DiagramReview";
import {suggestSubquestions, splitQuestionAtCaret, splitQuestionRanges, mapCandidateToSources, type SplitProposal} from "@/lib/questionSplit";
import {applyQuestionSplit} from "@/lib/questionSplitApply";
import {AuthoringCandidates, type AuthoringEntry} from "@/components/reviews/AuthoringCandidates";
import {rubricRows} from "@/lib/rubricEditing";
import {WarningPanel} from "@/components/reviews/WarningPanel";
import {EvidencePanel} from "@/components/reviews/EvidencePanel";
import type {ReviewNode} from "@/types/reviews";
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
  const [materialPanel,setMaterialPanel]=useState(false);
  const [replacement,setReplacement]=useState<string|null>(null);
  const [role,setRole]=useState("question_sheet");
  const [visible,setVisible]=useState({question:true,answer:true,rubric:true});
  const [issues,setIssues]=useState<AuthoringIssue[]>([]);
  const [saving,setSaving]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const questionCaret=useRef(0);
  const questionToolScope=useRef("");questionToolScope.current=`${selected}:${revision?.edit_version}:${buffers[selected]}`;
  const fileInput=useRef<HTMLInputElement>(null);
  const readonly=!revision || revision.state==="confirmed";
  useEffect(()=>{
    let active=true;
    void Promise.all([testAuthoring.get(id),testData.materials(id)]).then(([data,files])=>{
      if(!active)return;
      const value=data.revision?.snapshot||data.legacy;
      setRevision(data.revision);setSnapshot(value);setDirty(false);setDirtyDomains({});setExternalChange(data.external_source_change);setSourceProblems(data.source_problems||[]);
      setBuffers(Object.fromEntries(value.nodes.map(n=>[n.stable_key,questionContent(n,value.domains?.question?.document.regions||[]).text])));
      setSelected(value.nodes[0]?.stable_key||"all");
      setMaterials(files.filter(m=>m.material_type!=="student_answer_source"));
      const superseded=new Set(value.materials.map(m=>m.replaces_material_id));
      const activeFiles=files.filter(m=>m.material_type!=="student_answer_source"&&!superseded.has(m.id));
      setMaterialId(activeFiles.find(m=>m.material_type==="question_sheet")?.id||activeFiles[0]?.id||"");
    }).catch(e=>{if(active)setError(e.message);});
    try{const prefs=localStorage.getItem("test-authoring-visible");if(prefs)setVisible(JSON.parse(prefs));}catch{}
    return()=>{active=false;};
  },[id]);
  const nodes=snapshot?.nodes||[];
  const orderedNodes=(parent:string|null=null,depth=0):ReviewNode[]=>depth>nodes.length?[]:nodes
    .filter(n=>n.parent_key===parent).sort((a,b)=>a.sort_order-b.sort_order||a.stable_key.localeCompare(b.stable_key))
    .flatMap(n=>[n,...orderedNodes(n.stable_key,depth+1)]);
  const node=nodes.find(n=>n.stable_key===selected);
  const pathFor=(key:string)=>canonicalQuestionPath(key,nodes.map(n=>({key:n.stable_key,parentKey:n.parent_key,label:n.label.raw})));
  function change(value:AuthoringSnapshot,domain?:string){setSnapshot(value);setDirty(true);setDirtyDomains(d=>({...d,...(domain?{[domain]:true}:{question:value.nodes!==snapshot?.nodes||value.domains?.question!==snapshot?.domains?.question||d.question,answer:value.answers!==snapshot?.answers||d.answer,rubric:value.rubrics!==snapshot?.rubrics||d.rubric})}));}
  function updateNode(value:ReviewNode){setDirty(true);setDirtyDomains(d=>({...d,question:true}));setSnapshot(s=>s?{...s,nodes:s.nodes.map(n=>n.stable_key===value.stable_key?value:n)}:s);}
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
    setSelected(issue.question_key||"unassigned");setDiagramSelection(undefined);setRegionId("");setVisible(v=>({...v,[issue.section]:true}));setEditing(v=>({...v,[issue.section]:true}));
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      const marker=document.getElementById(`authoring-${issue.section}`);
      const container=marker?.tagName==="SPAN"?marker.parentElement:marker;
      const target=issue.section==="rubric"?container?.querySelector<HTMLElement>('[aria-label="採点基準候補"]')||container:container;
      target?.scrollIntoView({block:"center"});
      const control=target?.querySelector<HTMLElement>('textarea,input,select,button');
      (control||marker)?.focus({preventScroll:true});
    }));
  }
  async function suggestQuestionSplit(){
    if(!node||!snapshot||!revision)return;
    const scope=questionToolScope.current,text=buffers[selected]??questionContent(node,regions).text;
    const reconciled=editQuestionContent(node,regions,text);
    if(!reconciled){setError("元資料との対応を確認してください。");return;}
    setBusy(true);setError("");
    try{
      const result=await apiFetch<{split:boolean;parts:{start:number;end:number}[]}>(`/tests/${id}/authoring/nodes/${selected}/split-suggest`,json({expected_revision:revision.edit_version,candidate_id:selected,text}));
      if(questionToolScope.current!==scope)return;
      if(!result.split){setNotice("分割が必要ないという提案です。必要ならカーソル位置を指定してください。");return;}
      const codepoints=Array.from(text),toOffset=(n:number)=>codepoints.slice(0,n).join("").length;
      const boundaries=[0,...result.parts.map(p=>toOffset(p.end))];
      const proposal=splitQuestionRanges(reconciled,boundaries,questionContent(reconciled,regions).spans,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key)?.ordered_content);
      if(!proposal){setError("分割案は元資料の範囲を安全に分けられません。カーソル位置や対応する読み取り項目を確認してください。");return;}
      updateNode(reconciled);setSplitProposal(proposal);
    }catch(e){if(questionToolScope.current===scope)setError(e instanceof Error?e.message:"分割案を取得できませんでした。");}finally{setBusy(false);}
  }
  async function analyzeSource(domain:"question"|"answer"){
    if(!revision||!materialId||dirty){setError("資料を選び、現在の変更を保存してから解析してください。");return;}
    if(!window.confirm(`${analyzed?"再解析":"解析"}して新しい解析結果を取り込んだ下書きを作成します。現在の保存済み下書きは修正版の履歴として保持されます。問題資料の解析では最新の保存済みレビューから編集内容を構成します。続行しますか？`))return;
    setBusy(true);setAnalyzing(true);setError("");
    try{
      let row:AuthoringRevision;
      if(domain==="answer")row=await testAuthoring.analyzeAnswer(id,materialId,revision.edit_version,true);
      else{
        const response=await fetch(`/api/v1/tests/${id}/materials/${materialId}/file`,{credentials:"include"});
        if(!response.ok)throw new Error("元PDFを取得できませんでした。");
        const extraction=await apiFetch<{id:string}>(`/tests/${id}/question-materials`,{method:"POST",headers:{"Content-Type":"application/pdf","X-Filename":materials.find(m=>m.id===materialId)?.original_filename||"question.pdf"},body:await response.blob()});
        const draft=await apiFetch<{id:string}>(`/question-imports/${extraction.id}/draft`,json({}));
        await apiFetch(`/question-import-drafts/${draft.id}/reviews`,json({}));
        row=await testAuthoring.importSources(id,revision.edit_version,true,materialId);
      }
      setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});setExternalChange(false);setContinueExternal(false);
      setBuffers(Object.fromEntries(row.snapshot.nodes.map(n=>[n.stable_key,questionContent(n,row.snapshot.domains?.question?.document.regions||[]).text])));
      setSelected(current=>row.snapshot.nodes.some(n=>n.stable_key===current)?current:row.snapshot.nodes[0]?.stable_key||"all");
      setNotice("解析結果を新しい編集用下書きに取り込みました。解析前の保存済み下書きと正式内容は保持されています。");
    }catch(e){setError(`資料を解析できませんでした。保存済みの下書きは保持されています。資料を確認して再試行してください。${e instanceof Error?` (${e.message})`:""}`);}finally{setBusy(false);setAnalyzing(false);}
  }
  async function begin(){setBusy(true);setError("");try{
    const row=await testAuthoring.begin(id);setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});
    setSelected(current=>row.snapshot.nodes.some(n=>n.stable_key===current)?current:row.snapshot.nodes[0]?.stable_key||"all");
    setBuffers(Object.fromEntries(row.snapshot.nodes.map(n=>[n.stable_key,questionContent(n,row.snapshot.domains?.question?.document.regions||[]).text])));
    setNotice("下書きを開きました。保存しても正式な問題・解答・採点基準は変更されません。");
  }catch(e){setError(e instanceof Error?e.message:"下書きを開けませんでした。");}finally{setBusy(false);}}
  async function importSources(){if(!revision)return;
    if(!window.confirm("統合下書きを最新の保存済みレビューに置き換えます。現在の下書き編集は失われます。取り込みますか？"))return;
    setBusy(true);setError("");try{
      const row=await testAuthoring.importSources(id,revision.edit_version);setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});
      setBuffers(Object.fromEntries(row.snapshot.nodes.map(n=>[n.stable_key,questionContent(n,row.snapshot.domains?.question?.document.regions||[]).text])));
      setSelected(row.snapshot.nodes[0]?.stable_key||"all");setExternalChange(false);setContinueExternal(false);
    }catch(e){setError(e instanceof Error?e.message:"取り込めませんでした。");}finally{setBusy(false);}
  }
  async function save(){if(!snapshot||!revision)return;setBusy(true);setSaving(true);setError("");try{
    const value={...snapshot,nodes:snapshot.nodes.map(n=>{
      const text=buffers[n.stable_key]??n.body_text;
      const reconciled=editQuestionContent(n,snapshot.domains?.question?.document.regions||[],text);
      if(!reconciled)throw new Error("問題文と出典の対応を確認してください。");
      return {...reconciled,body_text:text};
    })};
    const row=await testAuthoring.save(id,value,revision.edit_version,continueExternal);
    setRevision(row);setSnapshot(row.snapshot);setDirty(false);setDirtyDomains({});setNotice("下書きを保存しました。");
  }catch(e){setError(e instanceof Error?e.message:"保存できませんでした。");}finally{setBusy(false);setSaving(false);}}
  async function finalReview(){
    setBusy(true);try{
      if(dirty&&snapshot&&revision){
        const value={...snapshot,nodes:snapshot.nodes.map(n=>{
          const text=buffers[n.stable_key]??questionContent(n,regions).text,next=editQuestionContent(n,regions,text);
          if(!next)throw new Error("問題文と元資料の対応を確認してください。");return {...next,body_text:text};
        })};setIssues((await testAuthoring.reviewLocal(id,value,revision.edit_version)).issues);
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
    setSnapshot(current=>current?{...current,materials:[...current.materials.filter(ref=>!uploaded.some(m=>m.id===ref.id)),...uploaded.map(m=>({id:m.id,sha256:m.sha256||null,role:m.material_type,...(old?{replaces_material_id:old.id}:{})}))]}:current);
    setDirty(true);setMaterialId(uploaded[0].id);setNotice(old?"資料を差し替えました。元資料と出典情報は保持されています。変更を保存してから明示的に再解析してください。":"資料を追加しました。既存の資料と解析結果は保持されています。");setReplacement(null);
  }catch(e){setError(e instanceof Error?e.message:"資料を追加できませんでした。");}finally{setBusy(false);if(fileInput.current)fileInput.current.value="";}}
  if(error&&!snapshot)return <ErrorState message={error}/>;
  if(!snapshot)return <LoadingState/>;
  const questionDomain=snapshot.domains?.question;
  const regions=questionDomain?.document.regions||[];
  const activeRegions=regions.filter(r=>node?.ordered_content.some(item=>"region_id" in item&&item.region_id===r.region_id)||!!node?.formula_decisions[r.region_id]||!!node?.figure_decisions[r.region_id]);
  const answer=snapshot.answers[selected]||{primary:"",alternatives:[],diagram_records:[]};
  const criteria=snapshot.rubrics[selected]||[];
  const hasRubricState=(entry:AuthoringEntry)=>entry.rubric_edits!==undefined||entry.semantic_classification?.segments.some(s=>s.category==="rubric");
  const formalRubricFallback=!!criteria.length&&!snapshot.domains?.answer?.entries.some(e=>e.authoring_question_key===selected&&hasRubricState(e));
  const superseded=snapshot.materials.filter(m=>m.replaces_material_id).map(m=>snapshot.materials.find(old=>old.id===m.replaces_material_id));
  const questionStale=!!questionDomain&&superseded.some(m=>m?.role==="question_sheet"&&m.sha256===questionDomain.document.source_pdf_sha256);
  const answerStale=!!snapshot.domains?.answer&&superseded.some(m=>m?.id===snapshot.domains?.answer?.material_id);
  const viewed=materials.find(m=>m.id===materialId);
  const analysisDomain=viewed?.material_type==="question_sheet"?"question":
    viewed&&["model_answer_source","rubric_source"].includes(viewed.material_type)?"answer":undefined;
  const boundAnalyzed=analysisDomain==="question"?!!questionDomain&&viewed?.sha256===questionDomain.document.source_pdf_sha256:
    analysisDomain==="answer"&&materialId===snapshot.domains?.answer?.material_id;
  const analyzed=!!boundAnalyzed||snapshot.source_provenance.analysis_materials?.some(m=>m.id===materialId&&m.sha256===viewed?.sha256);
  const analysisReason=readonly?"編集用の下書きを作成してください。":busy?"処理中です。完了までお待ちください。":
    !materialId?"資料を選択してください。":!analysisDomain?"この資料は解析対象ではありません。":dirty?"変更を保存してから解析してください。":"";
  const replaceMaterial=(mid:string)=>{setReplacement(mid);setRole(materials.find(m=>m.id===mid)?.material_type||"question_sheet");setMaterialPanel(true);};
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
  return <><h1>{snapshot.metadata.name}</h1><p>問題・解答・採点基準を下書きで編集します。既存の正式内容は保持されます。</p>
    {externalChange&&<section role="alert" className="panel"><p>外部の保存済みレビューが更新されています。統合下書きは上書きされていません。</p>
      <button disabled={busy} onClick={()=>{setContinueExternal(true);setNotice("現在の統合下書きを継続します。外部レビューの更新は取り込みません。");}}>現在の下書きを継続</button>
      <button disabled={busy} onClick={importSources}>最新レビューを取り込む</button></section>}
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {(sourceProblems.length>0||questionStale||answerStale)&&<p role="alert">元PDFとの対応が無効になっています。資料と保存済みレビューを確認し、必要なら明示的に再解析してください。</p>}
    {analysisReason&&<p id="authoring-analysis-reason" className="muted" role="status">選択資料の解析: {analysisReason}</p>}{analyzing&&<p role="status">選択資料を解析しています。完了までお待ちください。</p>}
    <ReviewWorkspaceLayout actions={<div className="review-toolbar" aria-busy={busy}>
      {readonly?<button className="button" disabled={busy} onClick={begin}>編集用の下書きを作成</button>:<button className="button" disabled={busy||!dirty} onClick={save}>保存</button>}
      {!readonly&&<button disabled={busy} onClick={importSources}>保存済みレビューを取り込む</button>}
      <button className="button secondary" disabled={busy} onClick={finalReview}>最終確認へ</button><Link className="button secondary" href={`/tests/${id}`}>戻る</Link>
      {dirty&&<><span role="status">未保存の変更があります</span><span className="muted">{Object.entries(dirtyDomains).filter(([,v])=>v).map(([k])=>({question:"問題",answer:"解答",rubric:"採点基準",diagram:"図"}[k])).filter(Boolean).join("・")}</span></>}
    </div>} source={<>
      <div className="authoring-source-controls" role="group" aria-label="利用資料の操作">
        <label><span>利用資料</span><select aria-label="利用資料" value={materialId} onChange={e=>setMaterialId(e.target.value)}>
          <option value="">資料を選択</option>{materials.map(m=><option key={m.id} value={m.id}>{roles[m.material_type]||"資料"} — {m.original_filename}{snapshot.materials.some(ref=>ref.replaces_material_id===m.id)?"（差し替え済み）":""}</option>)}
        </select></label>
        <div className="authoring-current-material-actions"><span title={analysisReason||undefined}><button aria-describedby={analysisReason?"authoring-analysis-reason":undefined} disabled={!!analysisReason} onClick={()=>analysisDomain&&void analyzeSource(analysisDomain)}>{analyzing?"解析中…":analyzed?"再解析":"解析"}</button></span>
          <button disabled={readonly||busy||!materialId} onClick={()=>replaceMaterial(materialId)}>差換え</button><span aria-hidden="true">|</span><button aria-expanded={materialPanel} onClick={()=>setMaterialPanel(v=>!v)}>一覧</button>
        </div>
      </div>
      {materialId&&<SourcePdfPreview key={materialId} testId={id} material={materials.find(m=>m.id===materialId)} label="利用資料PDF" inline paneZoom diagramSelection={diagramSelection?.record.material_id===materialId?diagramSelection:undefined} targetLocation={diagramSelection?.record.material_id===materialId?{id:diagramSelection.record.id,page:diagramSelection.record.page_index+1,bbox:diagramSelection.record.final_bbox||diagramSelection.record.automatic_bbox}:mappedLocation}/>}
    </>} selector={<div className="review-toolbar">
      <label>対象設問<select aria-label="対象設問" value={selected} onChange={e=>{if(e.target.value==="all")void finalReview();else {setSelected(e.target.value);setDiagramSelection(undefined);setRegionId("");}}}>
        {orderedNodes().map(n=><option key={n.stable_key} value={n.stable_key}>{pathFor(n.stable_key)}</option>)}{snapshot.domains?.answer?.entries.some(e=>!e.authoring_question_key)&&<option value="unassigned">設問未割当の候補</option>}<option value="all">テスト全体確認</option>
      </select></label><span>表示</span>{([['question','問題'],['answer','解答'],['rubric','採点基準']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={visible[key]} onChange={e=>{const next={...visible,[key]:e.target.checked};setVisible(next);localStorage.setItem("test-authoring-visible",JSON.stringify(next));}}/>{label}</label>)}
    </div>}>
      <details open={materialPanel} onToggle={e=>setMaterialPanel(e.currentTarget.open)}><summary>試験資料</summary><p>資料を追加してから編集できます。差し替えは元資料を保持し、出典の再確認が必要です。解析は明示操作のみです。</p><button disabled={readonly||busy} onClick={()=>{setReplacement(null);fileInput.current?.focus();}}>資料を追加</button><ul>{materials.map(m=><li key={m.id}>{roles[m.material_type]||"資料"} — {m.original_filename}<details><summary>出典情報</summary>SHA: {m.sha256||"なし"}<p>{snapshot.materials.some(ref=>ref.replaces_material_id===m.id)?"差し替え済み・元資料を保持":"利用中"}{materialId===m.id?"・選択中の資料":""}</p></details><button onClick={()=>setMaterialId(m.id)}>選択</button><button disabled={readonly||busy} onClick={()=>replaceMaterial(m.id)}>差換え</button></li>)}</ul>{replacement&&<p role="alert">差し替え対象: {materials.find(m=>m.id===replacement)?.original_filename}。既存の出典確認は再確認が必要です。自動解析は行いません。</p>}
        <label>資料の種類<select aria-label="資料の種類" disabled={!!replacement} value={role} onChange={e=>setRole(e.target.value)}>{Object.entries(roles).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <input ref={fileInput} aria-label="資料を追加" type="file" accept="application/pdf,.pdf" multiple={!replacement} disabled={readonly||busy} onChange={e=>void upload(e.target.files)}/>
        <p>選択した資料の解析は左ペインの「解析」「再解析」から開始してください。未保存の変更がある場合は先に保存してください。</p>
        <p><Link href={`/tests/${id}?section=questions`}>既存の資料解析・出典付きレビューを開く</Link></p>
      </details>
      {selected==="all"?<section aria-label="テスト全体確認"><h2>テスト全体確認</h2>
        <label>テスト名<input disabled={readonly||saving} value={snapshot.metadata.name} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,name:e.target.value}})}/></label>
        <label>合計点<input type="number" disabled={readonly||saving} value={snapshot.metadata.total_points} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,total_points:Number(e.target.value)}})}/></label>
        <ol>{nodes.filter(n=>n.included).map(n=><li key={n.stable_key}>{pathFor(n.stable_key)} — {n.score_points??"未設定"}点</li>)}</ol>
        <ul>{issues.map((issue,index)=><li key={index}>{issue.question_key||issue.section==="answer"?<button onClick={()=>navigate(issue)}>{issue.question_key?pathFor(issue.question_key):"設問未割当"} — {issue.message}</button>:issue.message}</li>)}</ul>
        <button disabled title="この画面からの試験内容確定は現在利用できません。">試験内容を確定</button>
      </section>:(node||selected==="unassigned")&&<>
        {visible.question&&node&&<section id="authoring-question" tabIndex={-1} aria-label="問題"><h2>問題</h2>
          <AuthoringPreviewEditor label="問題" editing={editing.question} onEditing={value=>setEditing(v=>({...v,question:value}))} preview={<><MarkdownMathText source={buffers[selected]??node.body_text}/><AcceptedDiagramPreview records={questionStale?[]:node.diagram_records} path={questionDomain?`/tests/${id}/authoring/nodes/${selected}/diagrams`:undefined}/></>}>
          <NodeEditor inlinePreview={false} key={node.stable_key} node={node} nodes={nodes} regions={activeRegions} readonly={readonly||saving}
            content={buffers[selected]??node.body_text} contentChanged={(buffers[selected]??node.body_text)!==questionContent(node,regions).text}
            mathContext={questionDomain&&!questionStale&&revision?{reviewId:questionDomain.document.id,revision:revision.edit_version,savedNode:revision.snapshot.nodes.find(n=>n.stable_key===selected),authoringTestId:id}:undefined}
            activeRegionId={regionId} renderEvidence={questionDomain?(rid)=><EvidencePanel id={questionDomain.document.id} regionId={rid} ownerLabel={pathFor(selected)} readonly={readonly||saving}
              decision={(regions.find(r=>r.region_id===rid)?.region_type==="formula"?node.formula_decisions:node.figure_decisions)[rid]||{decision:"unreviewed"}}
              onDecision={d=>{const field=regions.find(r=>r.region_id===rid)?.region_type==="formula"?"formula_decisions":"figure_decisions";updateNode({...node,[field]:{...node[field],[rid]:d}});}}/>:undefined}
            onCaret={offset=>{questionCaret.current=offset;}} onContentChange={(text,proposal)=>{setSplitProposal(null);setDirty(true);setDirtyDomains(d=>({...d,question:true}));setBuffers(current=>({...current,[selected]:text}));if(proposal?.apply_provenance)updateNode({...node,math_ocr_edits:[...(node.math_ocr_edits||[]),proposal.apply_provenance].slice(-16)});}}
            onConfirmContent={confirm=>{const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);if(next)updateNode(confirm(next));else setError("問題文と元資料の対応を確認してください。");}} onChange={updateNode}
            onParent={parent=>reparentNode(node,parent)} onMove={direction=>moveNode(node,direction)} onRegion={setRegionId}/>
          <button disabled={readonly||saving} onClick={()=>{
            const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);
            if(!next){setError("元資料との対応を保った分割案を作成できません。");return;}
            updateNode(next);const proposal=suggestSubquestions(next,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key));
            setSplitProposal(proposal);if(!proposal)setNotice("小問候補を検出できませんでした。必要なら設問を追加してください。");
          }}>小問の分割案を作成</button>
          <button disabled={readonly||saving||busy} onClick={()=>void suggestQuestionSplit()}>AIで小問の分割案を作成</button>
          <button disabled={readonly||saving} onClick={()=>{
            const next=editQuestionContent(node,regions,buffers[selected]??node.body_text);
            const proposal=next&&splitQuestionAtCaret(next,questionCaret.current,questionContent(next,regions).spans,questionDomain?.document.automatic_nodes.find(n=>n.stable_key===node.source_draft_stable_key)?.ordered_content);
            if(!proposal){setError("この位置は元資料の範囲を安全に分割できません。数式や図の境界を避け、分割位置を確認してください。");return;}
            updateNode(next!);setSplitProposal(proposal);
          }}>問題文のカーソル位置で分割</button>
          {splitProposal&&<section aria-label="小問の分割案"><h3>小問の分割案</h3>
            {splitProposal.children.map((child,index)=><div key={index}><strong>{child.label}</strong><pre>{questionContent({...node,ordered_content:child.items},regions).text}</pre><p>{child.mappingStatus==="automatic"?"元資料との対応を確認済み":"元資料との対応を確認できません。対応する読み取り項目を指定してください。"}</p>
              {child.mappingStatus==="manual_required"&&<fieldset><legend>対応する読み取り項目</legend>{splitProposal.sourceOptions.map(option=><label key={option.id}><input type="checkbox" checked={child.selectedSourceIds.includes(option.id)} onChange={e=>setSplitProposal({...splitProposal,children:splitProposal.children.map((c,i)=>i===index?{...c,selectedSourceIds:e.target.checked?[...c.selectedSourceIds,option.id]:c.selectedSourceIds.filter(id=>id!==option.id)}:c)})}/>{option.label} — {option.excerpt}</label>)}<button onClick={()=>{const items=mapCandidateToSources(child.items,child.selectedSourceIds,splitProposal.sourceOptions);if(items)setSplitProposal({...splitProposal,children:splitProposal.children.map((c,i)=>i===index?{...c,items,mappingStatus:"manual_mapped",included:true}:c)});}}>この対応を使用</button></fieldset>}
              <label>小問名<input value={child.label} onChange={e=>setSplitProposal({...splitProposal,children:splitProposal.children.map((c,i)=>i===index?{...c,label:e.target.value}:c)})}/></label>
            </div>)}
            <button disabled={splitProposal.children.some(c=>c.included&&(!["automatic","manual_mapped"].includes(c.mappingStatus)||!c.contentValid))} onClick={()=>{
              const result=applyQuestionSplit(node,splitProposal,()=>`teacher-${localId()}`);if(!result)return;
              const orderOffset=Math.max(-1,...snapshot.nodes.filter(n=>n.parent_key===node.stable_key).map(n=>n.sort_order))+1;
              result.children.forEach(n=>{n.sort_order+=orderOffset;});
              change({...snapshot,nodes:[...snapshot.nodes.map(n=>n.stable_key===node.stable_key?result.updated:n),...result.children]});
              setBuffers(current=>({...current,[node.stable_key]:questionContent(result.updated,regions).text,...Object.fromEntries(result.children.map(n=>[n.stable_key,questionContent(n,regions).text]))}));
              setSelected(result.children[0].stable_key);setSplitProposal(null);
            }}>この内容で分割</button><button onClick={()=>setSplitProposal(null)}>キャンセル</button>
          </section>}
          {questionDomain&&revision&&<DiagramReview path={`/tests/${id}/authoring/nodes/${selected}/diagrams`} revision={revision.edit_version}
            records={node.diagram_records} sourceStale={questionStale} disabled={readonly||saving} label="図の確認" onSelect={setDiagramSelection}
            onChange={records=>{setDirty(true);setDirtyDomains(d=>({...d,diagram:true}));setSnapshot(current=>current?{...current,nodes:current.nodes.map(n=>{if(n.stable_key!==node.stable_key)return n;const decisions={...n.figure_decisions};for(const record of records)for(const rid of record.legacy_region_ids||(record.legacy_region_id?[record.legacy_region_id]:[]))decisions[rid]={decision:record.state==="accepted"?"accepted_as_evidence":record.state==="excluded"?"excluded":"unreviewed"};return {...n,diagram_records:records,figure_decisions:decisions};})}:current);}}/>}
          {questionDomain&&<WarningPanel warnings={questionDomain.document.warnings} states={questionDomain.snapshot.warning_states||{}} readonly={readonly||saving}
            onChange={(key,resolution)=>change({...snapshot,domains:{...snapshot.domains,question:{...questionDomain,snapshot:{...questionDomain.snapshot,warning_states:{...questionDomain.snapshot.warning_states,[key]:resolution}}}}})}/>}
        </AuthoringPreviewEditor></section>}
        {snapshot.domains?.answer&&(visible.answer||visible.rubric)&&revision&&<section id="authoring-answer" tabIndex={-1} aria-label="解答・採点基準"><span id="authoring-rubric" tabIndex={-1}/><h2>解答・採点基準</h2>
          <AuthoringCandidates key={snapshot.domains.answer.draft_id} testId={id} draftId={snapshot.domains.answer.draft_id} revision={revision.edit_version} questionKey={selected}
            sourceStale={answerStale} entries={snapshot.domains.answer.entries} savedEntries={revision.snapshot.domains?.answer?.entries||[]} disabled={readonly||saving}
            answerEditing={editing.answer} rubricEditing={editing.rubric} onAnswerEditing={value=>setEditing(v=>({...v,answer:value}))} onRubricEditing={value=>setEditing(v=>({...v,rubric:value}))}
            showAnswer={visible.answer} showRubric={visible.rubric&&!formalRubricFallback} questions={orderedNodes().map(n=>({key:n.stable_key,label:pathFor(n.stable_key),gradable:n.score_semantics==="direct",sourceId:snapshot.source_provenance.authoring_origins?.identities[n.stable_key]?.formal_question_id||n.stable_key}))}
            onSelect={setDiagramSelection} onChange={(rawEntries,domain)=>{
              const entries=rawEntries.map(e=>hasRubricState(e)?{...e,rubric_edits:e.rubric_edits??rubricRows(e)}:e);
              const answers={...snapshot.answers},rubrics={...snapshot.rubrics};
              for(const key of new Set([...snapshot.domains!.answer!.entries,...entries].map(e=>e.authoring_question_key).filter(Boolean))){
                const current=entries.filter(e=>e.authoring_question_key===key&&e.disposition!=="ignored"&&e.disposition!=="excluded"&&e.disposition!=="unassigned");
                const primary=current.find(e=>(e.answer_kind||"primary")==="primary");
                answers[key!]={primary:primary?.answer_text||"",alternatives:current.flatMap(e=>[...(e.answer_kind==="alternative"?[e.answer_text]:[]),...(e.manual_alternative_answers||e.semantic_classification?.manual_alternative_answers||e.semantic_classification?.alternative_answers||[]).map(a=>a.text)]),diagram_records:primary?.diagram_records||[]};
                if(current.some(hasRubricState)||snapshot.domains!.answer!.entries.some(e=>e.authoring_question_key===key&&hasRubricState(e)))rubrics[key!]=current.flatMap(e=>rubricRows(e).filter(c=>!c.excluded));
              }
              change({...snapshot,domains:{...snapshot.domains,answer:{...snapshot.domains!.answer!,entries}},answers,rubrics},domain||"answer");
            }}/></section>}
        {!snapshot.domains?.answer&&visible.answer&&<section id="authoring-answer" tabIndex={-1} aria-label="解答"><h2>解答</h2>
          <AuthoringPreviewEditor label="解答" editing={editing.answer} onEditing={value=>setEditing(v=>({...v,answer:value}))} preview={<><MarkdownMathText source={answer.primary||"本文なし"}/>{answer.alternatives.map((text,i)=><div key={i}><h4>別解{i+1}</h4><MarkdownMathText source={text}/></div>)}<AcceptedDiagramPreview records={answer.diagram_records}/></>}>
          <label>模範解答本文<textarea aria-label="模範解答本文" rows={8} disabled={readonly||saving} value={answer.primary} onChange={e=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:e.target.value}}})}/></label>
          <LatexNormalizationControl text={answer.primary} contextType="model_answer" disabled={readonly||saving} onApply={text=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:text}}})}/>
          {!!answer.diagram_records.length&&<p>保存済みの模範解答図: {answer.diagram_records.length}件（元の出典情報を保持）</p>}
        </AuthoringPreviewEditor></section>}
        {(!snapshot.domains?.answer||formalRubricFallback)&&visible.rubric&&<section id="authoring-rubric" tabIndex={-1} aria-label="採点基準"><h2>採点基準</h2>
          <AuthoringCandidates answerEditing={editing.answer} rubricEditing={editing.rubric} onAnswerEditing={value=>setEditing(v=>({...v,answer:value}))} onRubricEditing={value=>setEditing(v=>({...v,rubric:value}))} testId={id} draftId="" revision={revision?.edit_version||1} questionKey={selected} showAnswer={false} showRubric
            disabled={readonly||saving} questions={orderedNodes().map(n=>({key:n.stable_key,label:pathFor(n.stable_key),gradable:n.score_semantics==="direct"}))}
            savedEntries={[]} entries={[{id:`formal-entry:${selected}`,mapping_state:"manual_mapped",question_id:null,authoring_question_key:selected,answer_text:"",source:{kind:"teacher_manual",material_id:null,source_sha256:null,segments:[]},
              rubric_edits:criteria,rubric_merge_history:snapshot.rubric_histories?.[selected]||[]}]}
            onSelect={setDiagramSelection} onChange={entries=>change({...snapshot,rubrics:{...snapshot.rubrics,[selected]:entries[0].rubric_edits||[]},
              ...(snapshot.rubric_histories?{rubric_histories:{...snapshot.rubric_histories,[selected]:entries[0].rubric_merge_history||[]}}:{})})}/>

        </section>}
      </>}
      <button disabled={readonly||saving} onClick={()=>{const n=newNode(nodes.length);change({...snapshot,nodes:[...nodes,n]});setBuffers(current=>({...current,[n.stable_key]:""}));setSelected(n.stable_key);}}>設問を追加</button>
    </ReviewWorkspaceLayout></>;
}
