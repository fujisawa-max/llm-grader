"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";
import {courses,offerings,tests} from "@/lib/api/domain";
import type {Course,Offering} from "@/types/domain";
import {CourseForm} from "@/components/CourseForm";
import {semesterLabel,semesterOrder} from "@/lib/semester";
import {PageHeader,LoadingState} from "@/components/ui";
type Row={course:Course;offering?:Offering;count:number};
export default function CoursesPage(){
 const [rows,setRows]=useState<Row[]|null>(null); const [show,setShow]=useState(false); const [error,setError]=useState(""); const [sort,setSort]=useState("year-desc");
 const load=useCallback(async()=>{try{const cs=await courses.list();const groups=await Promise.all(cs.map(async course=>{const os=await offerings.list(course.id);return os.length?await Promise.all(os.map(async offering=>({course,offering,count:(await tests.list(offering.id)).length}))):[{course,count:0}];}));setRows(groups.flat());}catch(e){setError(e instanceof Error?e.message:"読み込めませんでした");}},[]);
 useEffect(()=>{void load();},[load]);
 const ordered=[...(rows||[])].sort((a,b)=>{const [key,direction]=sort.split("-");const sign=direction==="desc"?-1:1;const value=key==="year"?(a.offering?.academic_year||0)-(b.offering?.academic_year||0):key==="term"?semesterOrder(a.offering?.term||"")-semesterOrder(b.offering?.term||""):key==="name"?a.course.name.localeCompare(b.course.name,"ja"):new Date(key==="created"?a.course.created_at:a.course.updated_at).getTime()-new Date(key==="created"?b.course.created_at:b.course.updated_at).getTime();return sign*value;});
 return <><PageHeader title="科目"><button className="button" onClick={()=>setShow(!show)}>科目を作成</button></PageHeader>{error&&<p role="alert">{error}</p>}{show&&<CourseForm onSaved={()=>{setShow(false);void load();}} onCancel={()=>setShow(false)}/>}
 <label htmlFor="course-sort">並べ替え</label> <select id="course-sort" value={sort} onChange={e=>setSort(e.target.value)}>{[["year","年度"],["name","科目名"],["term","開講時期"],["created","登録日時"],["updated","更新日時"]].flatMap(([key,label])=>["asc","desc"].map(dir=><option key={key+dir} value={key+"-"+dir}>{label}（{dir==="asc"?"昇順":"降順"}）</option>))}</select>
 {!rows?<LoadingState/>:<div className="source-table-scroll"><table className="table"><thead><tr><th>科目名</th><th>年度</th><th>開講時期</th><th>試験数</th><th>更新日時</th></tr></thead><tbody>{ordered.map(({course:c,offering:o,count})=><tr key={o?.id||c.id}><td><Link href={o?`/offerings/${o.id}`:`/courses/${c.id}`}>{c.name}</Link></td><td>{o?.academic_year||"未設定"}</td><td>{o?semesterLabel(o.term,o.term_label):"未設定"}</td><td>{count}</td><td>{new Date(c.updated_at).toLocaleDateString("ja-JP")}</td></tr>)}</tbody></table>{!rows.length&&<p>まだ科目が登録されていません。</p>}</div>}</>;
}
