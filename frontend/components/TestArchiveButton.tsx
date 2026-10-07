"use client";
import {useEffect,useRef,useState} from "react";
import {testAuthoring,type ArchiveImpact} from "@/lib/api/testAuthoring";
export function TestArchiveButton({testId,onArchived}:{testId:string;onArchived:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [impact,setImpact]=useState<ArchiveImpact>(),[name,setName]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>{if(impact)dialog.current?.showModal();},[impact]);
  async function open(){setBusy(true);setError("");try{setImpact(await testAuthoring.impact(testId));setName("");}catch(e){setError(e instanceof Error?e.message:"影響を確認できませんでした。");}finally{setBusy(false);}}
  async function archive(){if(!impact)return;setBusy(true);setError("");try{await testAuthoring.archive(testId,name,impact.impact_sha256);dialog.current?.close();onArchived();}catch(e){setError(e instanceof Error?e.message:"アーカイブできませんでした。");}finally{setBusy(false);}}
  return <><button type="button" disabled={busy} onClick={open}>削除</button>{error&&!impact&&<p role="alert">{error}</p>}
    <dialog ref={dialog} onCancel={()=>setImpact(undefined)} aria-labelledby={`archive-title-${testId}`}>
      {impact&&<><h2 id={`archive-title-${testId}`}>「{impact.name}」を一覧から非表示にしますか？</h2>
        <p>データは削除せずアーカイブします。問題・資料・答案・採点結果は保持されます。</p>
        <dl><dt>問題</dt><dd>{impact.questions}件</dd><dt>模範解答</dt><dd>{impact.model_answers}件</dd>
          <dt>採点基準</dt><dd>{impact.rubrics}件</dd><dt>学生答案</dt><dd>{impact.submissions}件</dd>
          <dt>採点ジョブ</dt><dd>{impact.grading_jobs}件</dd><dt>採点結果</dt><dd>{impact.results}件</dd></dl>
        {(impact.submissions>0||impact.grading_jobs>0)&&<p className="notice">学生答案または採点データがあります。アーカイブ後は通常のテスト画面から開けなくなります。</p>}
        <label>確認のためテスト名を入力<input aria-label="確認用テスト名" value={name} onChange={e=>setName(e.target.value)}/></label>
        {error&&<p role="alert">{error}</p>}
        <div className="actions"><button type="button" disabled={busy||name!==impact.name} onClick={archive}>アーカイブする</button>
          <button type="button" disabled={busy} onClick={()=>{dialog.current?.close();setImpact(undefined);}}>キャンセル</button></div>
      </>}
    </dialog></>;
}
