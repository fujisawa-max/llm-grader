"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {testAuthoring} from "@/lib/api/testAuthoring";
export function RecentCourseTests({courseId}:{courseId:string}) {
  const [items,setItems]=useState<{id:string;name:string;authoring_state:string;status:string}[]>([]);
  const [error,setError]=useState(false);
  useEffect(()=>{let active=true;testAuthoring.recent(courseId).then(data=>{if(active)setItems(data.tests);}).catch(()=>{if(active)setError(true);});return()=>{active=false;};},[courseId]);
  if(error)return <p className="muted">最近のテストを取得できませんでした。</p>;
  const test=items[0];
  if(!test)return null;
  const editing=["draft","final_review"].includes(test.authoring_state)||
    (test.authoring_state==="legacy"&&["draft","setup","rubric_review"].includes(test.status));
  return <div className="recent-course-test" aria-label="最近のテスト"><p>{test.name}</p>
    <p className="muted">{editing?"下書き":test.authoring_state==="confirmed"?"確定済み":"登録済み"}</p>
    <Link href={editing?`/tests/${test.id}/authoring`:`/tests/${test.id}`}>
      {editing?"編集を続ける":"テストを見る"}
    </Link></div>;
}
