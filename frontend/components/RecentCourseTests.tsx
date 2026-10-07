"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {testAuthoring} from "@/lib/api/testAuthoring";
export function RecentCourseTests({courseId}:{courseId:string}) {
  const [items,setItems]=useState<{id:string;name:string;authoring_state:string;status:string}[]>([]);
  const [error,setError]=useState(false);
  useEffect(()=>{let active=true;testAuthoring.recent(courseId).then(data=>{if(active)setItems(data.tests);}).catch(()=>{if(active)setError(true);});return()=>{active=false;};},[courseId]);
  if(error)return <p className="muted">最近のテストを取得できませんでした。</p>;
  return <div aria-label="最近のテスト">{items.map(test=><div key={test.id}><p>{test.name}</p>
    <Link href={test.authoring_state==="draft"||test.authoring_state==="final_review"?`/tests/${test.id}/authoring`:`/tests/${test.id}`}>
      {test.authoring_state==="draft"||test.authoring_state==="final_review"?"編集を続ける":"テストを見る"}
    </Link></div>)}</div>;
}
