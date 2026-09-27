"use client";
import {useState, type FormEvent} from "react";
import {courses} from "@/lib/api/domain";
import type {Course, Offering} from "@/types/domain";
import {semesters} from "@/lib/semester";
export function CourseForm({course, offering, onSaved, onCancel}: {course?:Course; offering?:Offering; onSaved:()=>void; onCancel:()=>void}) {
 const [name,setName]=useState(course?.name||""); const [year,setYear]=useState(offering?.academic_year||new Date().getFullYear()); const [term,setTerm]=useState(offering?.term||"first_semester");
 const [code,setCode]=useState(course?.code||""); const [description,setDescription]=useState(course?.description||""); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
 async function save(e:FormEvent){e.preventDefault();setBusy(true);setError("");try{const value={name:name.trim(),code:code||null,description:description||null,offering:{academic_year:year,term,offering_id:offering?.id}};if(course)await courses.update(course.id,value);else await courses.create(value);onSaved();}catch(e){setError(e instanceof Error?e.message:"保存できませんでした");}finally{setBusy(false);}}
 return <form className="panel form" onSubmit={save}><h2>{course?"科目を編集":"新しい科目を作成"}</h2>
 <div className="field"><label htmlFor="course-name">科目名</label><input id="course-name" required maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></div>
 <div className="field"><label htmlFor="course-year">年度</label><input id="course-year" type="number" min={1900} max={2200} required value={year} onChange={e=>setYear(Number(e.target.value))}/></div>
 <div className="field"><label htmlFor="course-term">開講時期</label><select id="course-term" value={term} onChange={e=>setTerm(e.target.value)}>{Object.entries(semesters).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></div>
 <div className="field"><label htmlFor="course-code">科目コード（任意）</label><input id="course-code" value={code} onChange={e=>setCode(e.target.value)}/></div>
 <div className="field"><label htmlFor="course-description">説明（任意）</label><textarea id="course-description" value={description} onChange={e=>setDescription(e.target.value)}/></div>
 {error&&<p role="alert">{error}</p>}<div className="actions"><button className="button" disabled={busy}>{busy?"保存中…":"保存"}</button><button className="button secondary" type="button" onClick={onCancel}>キャンセル</button></div></form>;
}

