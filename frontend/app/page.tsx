"use client";
import {RecentCourseTests} from "@/components/RecentCourseTests";
import { useEffect, useState } from "react";
import Link from "next/link";
import { courses } from "@/lib/api/domain";
import type { Course } from "@/types/domain";
import { PageHeader, LoadingState, ErrorState, EmptyState } from "@/components/ui";
export default function Home() { const [items,setItems]=useState<Course[]|null>(null); const [error,setError]=useState(""); useEffect(()=>{courses.list().then(setItems).catch(e=>setError(e.message));},[]); if(error)return <ErrorState message={error}/>; if(!items)return <LoadingState/>; return <><PageHeader title="ホーム"/><div className="cards"><div className="card"><h2>科目</h2><div className="stat">{items.length}</div><Link href="/courses">科目を管理する</Link></div><div className="card"><h2>採点中</h2><div className="stat">—</div><p className="muted">採点状況は採点画面で確認できます。</p></div><div className="card"><h2>要確認</h2><div className="stat">—</div><p className="muted">要確認答案は後続機能で表示します。</p></div></div><section className="section"><h2>最近の科目</h2>{items.length===0?<EmptyState message="まだ科目が登録されていません" action={<Link className="button" href="/courses">科目を作成</Link>}/>:<div className="cards recent-course-cards">{items.slice(0,6).map(c=><div className="card recent-course-card" key={c.id}><div className="recent-course-details"><h3>{c.code ? `${c.code} ` : ""}{c.name}</h3><p className="muted">更新日: {new Date(c.updated_at).toLocaleDateString("ja-JP")}</p><Link href={`/courses/${c.id}`}>開く</Link></div><RecentCourseTests courseId={c.id}/></div>)}</div>}</section></>; }
