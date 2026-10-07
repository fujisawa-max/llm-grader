"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {testAuthoring} from "@/lib/api/testAuthoring";
import {testWorkflowHref} from "@/lib/testWorkflowNavigation";
export function TestAuthoringEntry({testId}:{testId:string}){
  const [state,setState]=useState<string|null>(null);
  useEffect(()=>{let active=true;void testAuthoring.status(testId).then(value=>{if(active)setState(value.state);}).catch(()=>{});return()=>{active=false;};},[testId]);
  return <Link className="button secondary" href={testWorkflowHref(testId,"authoring")}>{state==="confirmed"?"表示":"編集"}</Link>;
}
