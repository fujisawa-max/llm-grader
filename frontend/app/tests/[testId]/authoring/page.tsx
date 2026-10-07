"use client";
import {useEffect, useRef, useState} from "react";
import {useParams} from "next/navigation";
import Link from "next/link";
import {ReviewWorkspaceLayout} from "@/components/reviews/ReviewWorkspaceLayout";
import {NodeEditor} from "@/components/reviews/NodeEditor";
import {SourcePdfPreview} from "@/components/SourcePdfPreview";
import {LatexNormalizationControl} from "@/components/LatexNormalizationControl";
import {LoadingState, ErrorState} from "@/components/ui";
import {testAuthoring, type AuthoringRevision, type AuthoringSnapshot, type AuthoringIssue} from "@/lib/api/testAuthoring";
import {testData} from "@/lib/api/domain";
import {apiFetch} from "@/lib/api/client";
import {canonicalQuestionPath} from "@/lib/canonicalQuestionPath";
import {localId} from "@/lib/localId";
import {editQuestionContent} from "@/lib/questionContent";
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
  const [revision,setRevision]=useState<AuthoringRevision|null>(null);
  const [snapshot,setSnapshot]=useState<AuthoringSnapshot>();
  const [dirty,setDirty]=useState(false);
  const [buffers,setBuffers]=useState<Record<string,string>>({});
  const [selected,setSelected]=useState("");
  const [materials,setMaterials]=useState<Material[]>([]),[materialId,setMaterialId]=useState("");
  const [role,setRole]=useState("question_sheet");
  const [visible,setVisible]=useState({question:true,answer:true,rubric:true});
  const [issues,setIssues]=useState<AuthoringIssue[]>([]);
  const [saving,setSaving]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const fileInput=useRef<HTMLInputElement>(null);
  const readonly=!revision || revision.state==="confirmed";
  useEffect(()=>{
    let active=true;
    void Promise.all([testAuthoring.get(id),testData.materials(id)]).then(([data,files])=>{
      if(!active)return;
      const value=data.revision?.snapshot||data.legacy;
      setRevision(data.revision);setSnapshot(value);setDirty(false);
      setBuffers(Object.fromEntries(value.nodes.map(n=>[n.stable_key,n.body_text])));
      setSelected(value.nodes[0]?.stable_key||"all");
      setMaterials(files.filter(m=>m.material_type!=="student_answer_source"));
      setMaterialId(files.find(m=>m.material_type==="question_sheet")?.id||files[0]?.id||"");
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
  function change(value:AuthoringSnapshot){setSnapshot(value);setDirty(true);}
  function updateNode(value:ReviewNode){setDirty(true);setSnapshot(s=>s?{...s,nodes:s.nodes.map(n=>n.stable_key===value.stable_key?value:n)}:s);}
  function navigate(issue:AuthoringIssue){
    if(!issue.question_key)return;
    setSelected(issue.question_key);setVisible(v=>({...v,[issue.section]:true}));
    requestAnimationFrame(()=>requestAnimationFrame(()=>{
      const target=document.getElementById(`authoring-${issue.section}`);
      target?.scrollIntoView({block:"center"});target?.focus({preventScroll:true});
    }));
  }
  async function begin(){setBusy(true);setError("");try{
    const row=await testAuthoring.begin(id);setRevision(row);setSnapshot(row.snapshot);setDirty(false);
    setBuffers(Object.fromEntries(row.snapshot.nodes.map(n=>[n.stable_key,n.body_text])));
    setNotice("下書きを開きました。保存しても正式な問題・解答・採点基準は変更されません。");
  }catch(e){setError(e instanceof Error?e.message:"下書きを開けませんでした。");}finally{setBusy(false);}}
  async function save(){if(!snapshot||!revision)return;setBusy(true);setSaving(true);setError("");try{
    const value={...snapshot,nodes:snapshot.nodes.map(n=>{
      const text=buffers[n.stable_key]??n.body_text;
      const reconciled=editQuestionContent(n,[],text);
      if(!reconciled)throw new Error("問題文と出典の対応を確認してください。");
      return {...reconciled,body_text:text};
    })};
    const row=await testAuthoring.save(id,value,revision.edit_version);
    setRevision(row);setSnapshot(row.snapshot);setDirty(false);setNotice("下書きを保存しました。");
  }catch(e){setError(e instanceof Error?e.message:"保存できませんでした。");}finally{setBusy(false);setSaving(false);}}
  async function finalReview(){if(dirty){setNotice("変更を保存してからテスト全体を確認してください。");return;}
    setBusy(true);try{setIssues((await testAuthoring.review(id)).issues);setSelected("all");}
    catch(e){setError(e instanceof Error?e.message:"確認できませんでした。");}finally{setBusy(false);}}
  async function upload(files:FileList|null){if(!files||!snapshot)return;setBusy(true);setError("");try{
    const uploaded:Material[]=[];
    for(const file of Array.from(files)){
      if(!/\.pdf$/i.test(file.name)||file.size>25*1024*1024)throw new Error("25MB以内のPDFを選択してください。");
      uploaded.push(await apiFetch<Material>(`/tests/${id}/materials/upload`,{method:"POST",body:file,
        headers:{"Content-Type":"application/pdf","X-Source-Role":role,"X-Filename":encodeURIComponent(file.name)}}));
    }
    setMaterials(current=>[...current,...uploaded.filter(m=>!current.some(old=>old.id===m.id))]);
    setSnapshot(current=>current?{...current,materials:[...current.materials,...uploaded.filter(m=>!current.materials.some(old=>old.id===m.id)).map(m=>({id:m.id,sha256:m.sha256||null,role:m.material_type}))]}:current);
    setDirty(true);setMaterialId(uploaded[0].id);setNotice("資料を追加しました。既存の資料と解析結果は保持されています。");
  }catch(e){setError(e instanceof Error?e.message:"資料を追加できませんでした。");}finally{setBusy(false);if(fileInput.current)fileInput.current.value="";}}
  if(error&&!snapshot)return <ErrorState message={error}/>;
  if(!snapshot)return <LoadingState/>;
  const answer=snapshot.answers[selected]||{primary:"",alternatives:[],diagram_records:[]};
  const criteria=snapshot.rubrics[selected]||[];
  return <><h1>{snapshot.metadata.name}</h1><p>問題・解答・採点基準を下書きで編集します。既存の正式内容は保持されます。</p>
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <ReviewWorkspaceLayout actions={<div className="review-toolbar" aria-busy={busy}>
      {readonly?<button className="button" disabled={busy} onClick={begin}>編集用の下書きを作成</button>:<button className="button" disabled={busy||!dirty} onClick={save}>保存</button>}
      <button className="button secondary" disabled={busy} onClick={finalReview}>最終確認へ</button><Link className="button secondary" href={`/tests/${id}`}>戻る</Link>
      {dirty&&<span role="status">未保存の変更があります</span>}
    </div>} source={<>
      <label>利用資料<select aria-label="利用資料" value={materialId} onChange={e=>setMaterialId(e.target.value)}>
        <option value="">資料を選択</option>{materials.map(m=><option key={m.id} value={m.id}>{roles[m.material_type]||"資料"} — {m.original_filename}</option>)}
      </select></label>
      {materialId&&<SourcePdfPreview key={materialId} testId={id} material={materials.find(m=>m.id===materialId)} label="利用資料PDF" inline paneZoom/>}
    </>} selector={<div className="review-toolbar">
      <label>対象設問<select aria-label="対象設問" value={selected} onChange={e=>{if(e.target.value==="all")void finalReview();else setSelected(e.target.value);}}>
        {orderedNodes().map(n=><option key={n.stable_key} value={n.stable_key}>{pathFor(n.stable_key)}</option>)}<option value="all">テスト全体確認</option>
      </select></label><span>表示</span>{([['question','問題'],['answer','解答'],['rubric','採点基準']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={visible[key]} onChange={e=>{const next={...visible,[key]:e.target.checked};setVisible(next);localStorage.setItem("test-authoring-visible",JSON.stringify(next));}}/>{label}</label>)}
    </div>}>
      <details><summary>試験資料</summary><p>資料を追加してから編集できます。差し替え用資料も追加として保持します。</p>
        <label>資料の種類<select aria-label="資料の種類" value={role} onChange={e=>setRole(e.target.value)}>{Object.entries(roles).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <input ref={fileInput} aria-label="資料を追加" type="file" accept="application/pdf,.pdf" multiple disabled={readonly||busy} onChange={e=>void upload(e.target.files)}/>
        <p><Link href={`/tests/${id}?section=questions`}>既存の資料解析・出典付きレビューを開く</Link></p>
      </details>
      {selected==="all"?<section aria-label="テスト全体確認"><h2>テスト全体確認</h2>
        <label>テスト名<input disabled={readonly||saving} value={snapshot.metadata.name} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,name:e.target.value}})}/></label>
        <label>合計点<input type="number" disabled={readonly||saving} value={snapshot.metadata.total_points} onChange={e=>change({...snapshot,metadata:{...snapshot.metadata,total_points:Number(e.target.value)}})}/></label>
        <ol>{nodes.filter(n=>n.included).map(n=><li key={n.stable_key}>{pathFor(n.stable_key)} — {n.score_points??"未設定"}点</li>)}</ol>
        <ul>{issues.map((issue,index)=><li key={index}>{issue.question_key?<button onClick={()=>navigate(issue)}>{pathFor(issue.question_key)} — {issue.message}</button>:issue.message}</li>)}</ul>
        <button disabled title="この画面からの試験内容確定は現在利用できません。">試験内容を確定</button>
      </section>:node&&<>
        {visible.question&&<section id="authoring-question" tabIndex={-1} aria-label="問題"><h2>問題</h2>
          <NodeEditor key={node.stable_key} node={node} nodes={nodes} regions={[]} readonly={readonly||saving}
            content={buffers[selected]??node.body_text} contentChanged={(buffers[selected]??node.body_text)!==node.body_text}
            onContentChange={text=>{setDirty(true);setBuffers(current=>({...current,[selected]:text}));}}
            onConfirmContent={confirm=>updateNode(confirm(node))} onChange={updateNode}
            onParent={parent=>updateNode({...node,parent_key:parent})} onMove={direction=>updateNode({...node,sort_order:node.sort_order+direction})} onRegion={()=>{}}/>
        </section>}
        {visible.answer&&<section id="authoring-answer" tabIndex={-1} aria-label="解答"><h2>解答</h2>
          <label>模範解答本文<textarea aria-label="模範解答本文" rows={8} disabled={readonly||saving} value={answer.primary} onChange={e=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:e.target.value}}})}/></label>
          <LatexNormalizationControl text={answer.primary} contextType="model_answer" disabled={readonly||saving} onApply={text=>change({...snapshot,answers:{...snapshot.answers,[selected]:{...answer,primary:text}}})}/>
          {!!answer.diagram_records.length&&<p>保存済みの模範解答図: {answer.diagram_records.length}件（元の出典情報を保持）</p>}
        </section>}
        {visible.rubric&&<section id="authoring-rubric" tabIndex={-1} aria-label="採点基準"><h2>採点基準</h2>
          {criteria.map((criterion,index)=><fieldset key={criterion.id} disabled={readonly||saving}><label>観点<textarea aria-label="観点" value={criterion.description} onChange={e=>change({...snapshot,rubrics:{...snapshot.rubrics,[selected]:criteria.map((c,i)=>i===index?{...c,description:e.target.value}:c)}})}/></label>
            <label>点数<input type="number" min="0" value={criterion.points} onChange={e=>change({...snapshot,rubrics:{...snapshot.rubrics,[selected]:criteria.map((c,i)=>i===index?{...c,points:Number(e.target.value)}:c)}})}/></label></fieldset>)}
          <button disabled={readonly||saving} onClick={()=>change({...snapshot,rubrics:{...snapshot.rubrics,[selected]:[...criteria,{id:localId(),description:"",points:0}]}})}>観点を追加</button>
        </section>}
      </>}
      <button disabled={readonly||saving} onClick={()=>{const n=newNode(nodes.length);change({...snapshot,nodes:[...nodes,n]});setBuffers(current=>({...current,[n.stable_key]:""}));setSelected(n.stable_key);}}>設問を追加</button>
    </ReviewWorkspaceLayout></>;
}
