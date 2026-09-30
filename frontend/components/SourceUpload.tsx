"use client";
import {useRef,useState} from "react";
import {apiFetch} from "@/lib/api/client";
import {reviews} from "@/lib/api/reviews";
import {useRouter} from "next/navigation";
import {testData} from "@/lib/api/domain";
import type {Material,Student,Submission} from "@/types/domain";
import {SourcePdfPreview} from "@/components/SourcePdfPreview";
type Role="question_sheet"|"model_answer_source"|"student_answer_source";
type Item={id:string;file:File;number:string;name:string;studentId:string;material?:Material;state:string;error?:string};
const captions:Record<Role,string>={question_sheet:"問題用紙",model_answer_source:"模範解答",student_answer_source:"学生答案"};
function sourceMime(file:File){
 if(/\.pdf$/i.test(file.name))return "application/pdf";
 if(/\.png$/i.test(file.name))return "image/png";
 if(/\.jpe?g$/i.test(file.name))return "image/jpeg";
 return "";
}
function sourceError(file:File){
 if(!file.size)return "空のファイルです";
 if(file.size>25*1024*1024)return "25MBを超えています";
 if(!sourceMime(file))return "PNG・JPEG・PDFを選択してください";
 return undefined;
}
function registrationError(error:unknown){
 if(error instanceof TypeError)return "サーバーに接続できませんでした。接続を確認して再試行してください。";
 return error instanceof Error?error.message:"登録できませんでした。再試行してください。";
}
export function SourceUpload({testId,role,materials,students=[],submissions=[],refresh}:{
 testId:string;role:Role;materials:Material[];students?:Student[];submissions?:Submission[];refresh:()=>Promise<void>}) {
 const [items,setItems]=useState<Item[]>([]);const [busy,setBusy]=useState(false);const [progress,setProgress]=useState("");const [notice,setNotice]=useState("");const [preview,setPreview]=useState<Material>(); const studentMode=role==="student_answer_source";
 const inputRef=useRef<HTMLInputElement>(null);
 const rowSequence=useRef(0);
 const pending=items.filter(item=>item.state!=="登録済み");
 const mappingIncomplete=studentMode&&pending.some(item=>!item.studentId&&(!item.number.trim()||!item.name.trim()));
 const hasUploadable=pending.some(item=>Boolean(item.material)||!sourceError(item.file));
 const canRegister=!busy&&hasUploadable&&!mappingIncomplete;
 const router=useRouter();
 async function reviewPdf(material:Material){
   setBusy(true);setNotice("PDFの問題構造を解析しています…");
   try {
     const response=await fetch(testData.materialFileUrl(testId,material.id),{credentials:"include"});
     if(!response.ok)throw new Error("問題用紙を取得できませんでした");
     const extraction=await apiFetch<{id:string}>(`/tests/${testId}/question-materials`,{method:"POST",body:await response.blob(),headers:{"Content-Type":"application/pdf","X-Filename":"question.pdf"}});
     const draft=await apiFetch<{id:string}>(`/question-imports/${extraction.id}/draft`,{method:"POST"});
     const review=await reviews.create(draft.id);
     router.push(`/question-import-reviews/${review.id}`);
   }catch(e){setNotice(e instanceof Error?e.message:"問題用紙の確認を開始できませんでした");}finally{setBusy(false);}
 }
 const patch=(id:string,values:Partial<Item>)=>setItems(rows=>rows.map(row=>row.id===id?{...row,...values}:row));
 function choose(files:File[]){
 setNotice("");
 setItems(files.map(file=>({id:`source-row-${++rowSequence.current}`,file,number:"",name:"",studentId:"",state:"未登録",error:sourceError(file)})));
 }
 function removeItem(id:string){
 const remaining=items.filter(row=>row.id!==id);
 const next=remaining.some(row=>row.state!=="登録済み")?remaining:[];
 setItems(next);
 if(inputRef.current){
   const selected=new DataTransfer();
   next.forEach(row=>selected.items.add(row.file));
   inputRef.current.files=selected.files;
 }
 }
 function move(index:number,delta:number){setItems(old=>{const next=[...old];[next[index],next[index+delta]]=[next[index+delta],next[index]];return next;});}
 async function upload(){
 if(!canRegister)return;
 setBusy(true);setNotice("");const work=pending.map(x=>({...x}));
 const completedIds=new Set<string>();let failedCount=0;let processed=0;
 try {
 for(const row of work){
 setProgress(`${captions[role]}を登録中… ${processed} / ${work.length}（失敗 ${failedCount}）`);
 if(sourceError(row.file)&&!row.material){failedCount++;processed++;continue;}
 try {if(!row.material){row.material=await apiFetch<Material>(`/tests/${testId}/materials/upload`,{method:"POST",body:row.file,headers:{"Content-Type":sourceMime(row.file),"X-Filename":encodeURIComponent(row.file.name),"X-Source-Role":role}});patch(row.id,{material:row.material,error:undefined,state:studentMode?"資料保存済み":"登録済み"});}
 if(!studentMode)completedIds.add(row.id);
 }catch(e){failedCount++;patch(row.id,{state:"登録失敗",error:registrationError(e)});}
 processed++;setProgress(`${captions[role]}を登録中… ${processed} / ${work.length}（失敗 ${failedCount}）`);
 }
 if(studentMode){
 const groups=new Map<string,Item[]>();
 for(const row of work){const key=row.studentId||row.number.trim();groups.set(key,[...(groups.get(key)||[]),row]);}
 for(const group of groups.values()){
 if(group.some(x=>!x.material))continue;
 try {
 if(new Set(group.map(x=>x.name)).size>1)throw new Error("同じ学生の氏名を揃えてください");
 setProgress(`学生答案を紐付け中… ${completedIds.size} / ${work.length}（失敗 ${failedCount}）`);
 await testData.createSubmission(testId,{student_id:group[0].studentId||undefined,student_identifier:group[0].number.trim(),display_name:group[0].name||undefined,material_ids:group.map(x=>x.material!.id)});
 for(const row of group){completedIds.add(row.id);patch(row.id,{state:"登録済み",error:undefined});}
 }catch(e){failedCount+=group.length;for(const row of group)patch(row.id,{error:registrationError(e),state:"紐付け失敗"});}
 }}
 failedCount=work.length-completedIds.size;
 await refresh();
 if(failedCount===0){setItems([]);if(inputRef.current)inputRef.current.value="";}
 setNotice(failedCount?`${completedIds.size}件成功・${failedCount}件失敗。失敗したファイルを確認し、再度「${captions[role]}を登録」を押してください。`:`${captions[role]}を${completedIds.size}件登録しました。AI処理は実行していません。`);
 }catch(e){setNotice(e instanceof Error?e.message:"登録状態を取得できませんでした");}finally{setBusy(false);setProgress("");}
 }
 const registered=materials.filter(m=>m.material_type===role);
 return <section className="panel section" aria-label={captions[role]+"登録"}>
 <h2>{captions[role]}を登録</h2><p>PNG・JPEG・PDF（1ファイル25MB、最大100ページ）。登録だけでは読み取り・採点を開始しません。</p>
 {studentMode&&<p>学籍番号・氏名は教師が確認して入力してください。ファイル名からは推定しません。同じ学生を複数行で指定すると、上から順に1答案のページとして登録します。別の資料で再登録すると、新しい答案回として保存します。</p>}
 <label htmlFor={"source-"+role}>{captions[role]}{studentMode?"を追加":"ファイルを選択"}</label>
 <input ref={inputRef} id={"source-"+role} type="file" multiple accept=".png,.jpg,.jpeg,.pdf" disabled={busy} onChange={e=>choose(Array.from(e.currentTarget.files??[]))}/>
 <div className="source-register-actions"><button type="button" className="button" disabled={!canRegister} onClick={()=>void upload()}>{captions[role]}を登録</button><span aria-live="polite">{items.length===0?"ファイル未選択":items.length===1?`選択済み: ${items[0].file.name}`:`選択済み: ${items.length}ファイル（${items.slice(0,2).map(item=>item.file.name).join("、")}${items.length>2?" ほか":""}）`}</span></div>
 {mappingIncomplete&&<p className="muted">登録する学生の学籍番号と氏名を入力するか、登録済み学生を選択してください。</p>}
 {items.length>0&&!hasUploadable&&<p className="muted">選択したファイルの形式またはサイズを確認してください。</p>}
 <div className="source-table-scroll">{items.length>0&&<table className="table"><thead><tr><th>順序 / ファイル</th>{studentMode&&<><th>学生の対応</th><th>学籍番号 / 氏名</th></>}<th>登録状態</th><th>操作</th></tr></thead><tbody>{items.map((x,i)=><tr key={x.id}><td>{i+1}. {x.file.name}</td>{studentMode&&<><td><select aria-label={`学生 ${i+1}`} disabled={busy||x.state==="登録済み"} value={x.studentId} onChange={e=>{const s=students.find(s=>s.id===e.target.value);patch(x.id,{studentId:e.target.value,number:s?.student_identifier||"",name:s?.display_name||""});}}><option value="">学籍番号を入力</option>{students.map(s=><option key={s.id} value={s.id}>{s.student_identifier} {s.display_name}</option>)}</select></td><td><input aria-label={`学籍番号 ${i+1}`} disabled={busy||!!x.studentId||x.state==="登録済み"} value={x.number} onChange={e=>patch(x.id,{number:e.target.value})}/><input aria-label={`氏名 ${i+1}`} disabled={busy||!!x.studentId||x.state==="登録済み"} value={x.name} onChange={e=>patch(x.id,{name:e.target.value})}/></td></>}<td>{x.state}{x.error&&<p role="alert">{x.error}</p>}</td><td><div className="actions"><button type="button" disabled={busy||i===0||x.state==="登録済み"} onClick={()=>move(i,-1)} aria-label={`上へ ${i+1}`}>↑</button><button type="button" disabled={busy||i===items.length-1||x.state==="登録済み"} onClick={()=>move(i,1)} aria-label={`下へ ${i+1}`}>↓</button><button type="button" disabled={busy||x.state==="登録済み"} onClick={()=>removeItem(x.id)}>取り消し</button></div></td></tr>)}</tbody></table>}</div>
 <p role="status">{progress||notice}</p><p>{captions[role]}: {registered.length}ファイル登録済み{studentMode?` / 学生答案 ${submissions.length}件`:""}</p>
 <div className="actions">{registered.map((m,i)=><button className="button secondary" key={m.id} onClick={()=>setPreview(m)}>{i+1}. {m.original_filename||"登録資料"}を確認</button>)}</div>
 {role==="question_sheet"&&registered.filter(m=>m.mime_type==="application/pdf").map(m=><button className="button secondary" disabled={busy} key={m.id} onClick={()=>void reviewPdf(m)}>{m.original_filename}を解析して設問を確認</button>)}
 {preview&&<><button type="button" onClick={()=>setPreview(undefined)}>資料を閉じる</button>{preview.mime_type==="application/pdf"?<SourcePdfPreview testId={testId} material={preview} label={captions[role]} inline/>:<img className="registered-source-preview" src={testData.materialFileUrl(testId,preview.id)} alt={captions[role]+"原資料"}/>}</>}
 <p>{role==="question_sheet"?"次の作業: 問題の内容とページ順を確認し、下の「問題を追加」から設問を登録してください。PDFの解析・レビューは既存の問題取り込み経路で行います。":role==="model_answer_source"?"次の作業: 下の設問別編集欄で模範解答を確認・登録し、採点基準を設定してください。":"次の作業: 原答案と学生の対応を確認してください。読み取り処理・設問対応の確認は別の明示的な処理です。"}</p>
 </section>;
}
