"use client";
import type {RubricCandidateEdit} from "@/lib/api/modelAnswerImports";

/** Explicit teacher policy; adding a row never invents a score or condition. */
export function ExecutableRubricLevels({criterion,onChange,disabled=false}:{criterion:RubricCandidateEdit;onChange:(value:RubricCandidateEdit)=>void;disabled?:boolean}){
  const levels=criterion.levels||[];
  const update=(next:typeof levels)=>onChange({...criterion,levels:next});
  return <section aria-label="得点段階と部分点の条件">
    <h4>得点段階と部分点の条件</h4>
    <p>使用する得点と、その得点になる条件を設定してください。集計は基準ごとの得点の合計です。</p>
    {!levels.length&&<p>未設定です。下書きは保存できますが、テストの確定には設定が必要です。</p>}
    {levels.map((level,index)=><div key={index}>
      <label>得点<input aria-label={`得点段階${index+1}の得点`} type="number" min="0" max={criterion.points} step="1" disabled={disabled} value={level.score??""} onChange={event=>update(levels.map((v,i)=>i===index?{...v,score:event.target.value===""?null:Number(event.target.value)}:v))}/></label>
      <label>条件<textarea aria-label={`得点段階${index+1}の条件`} rows={2} disabled={disabled} value={level.condition} onChange={event=>update(levels.map((v,i)=>i===index?{...v,condition:event.target.value}:v))}/></label>
      <button type="button" disabled={disabled} onClick={()=>update(levels.filter((_,i)=>i!==index))}>この得点段階を削除</button>
    </div>)}
    <button type="button" disabled={disabled} onClick={()=>update([...levels,{score:null,condition:""}])}>得点段階を追加</button>
  </section>;
}
