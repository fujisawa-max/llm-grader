"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {useParams,useRouter} from "next/navigation";
import {courses,offerings} from "@/lib/api/domain";
import type {Course,Offering} from "@/types/domain";
import {CourseForm} from "@/components/CourseForm";
import {semesterLabel} from "@/lib/semester";
export default function CourseDetail(){
 const id=String(useParams().courseId);const router=useRouter();const [course,setCourse]=useState<Course>();const [items,setItems]=useState<Offering[]>([]);const [error,setError]=useState("");
 useEffect(()=>{Promise.all([courses.get(id),offerings.list(id)]).then(([c,o])=>{setCourse(c);setItems(o);if(o.length===1)router.replace(`/offerings/${o[0].id}`);}).catch(e=>setError(e.message));},[id,router]);
 if(error)return <p role="alert">{error}</p>;if(!course)return <p>読み込み中…</p>;
 return <><h1>{course.name}</h1>{items.length?items.map(o=><p key={o.id}><Link href={`/offerings/${o.id}`}>{course.name} / {o.academic_year}年度 {semesterLabel(o.term,o.term_label)}</Link></p>):<><p>この科目の年度と開講時期を設定してください。</p><CourseForm course={course} onSaved={()=>window.location.reload()} onCancel={()=>router.push("/courses")}/></>}</>;
}
