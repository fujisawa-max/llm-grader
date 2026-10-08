"use client";
import {useCallback,useEffect,useState} from "react";

export type AuthoringNotificationSeverity="success"|"info"|"warning"|"error";
export interface AuthoringNotification {id:number;severity:AuthoringNotificationSeverity;title:string;detail?:string;createdAt:number;read:boolean;toast:boolean}

export function useAuthoringNotifications(){
  const [items,setItems]=useState<AuthoringNotification[]>([]);
  const [open,setOpen]=useState(false);
  const notify=useCallback((severity:AuthoringNotificationSeverity,title:string,detail?:string)=>{
    const id=Date.now()+Math.random();
    setItems(current=>[{id,severity,title,detail,createdAt:Date.now(),read:false,toast:true},...current].slice(0,50));
    const duration=severity==="error"?15000:severity==="warning"?9000:5000;
    window.setTimeout(()=>setItems(current=>current.map(item=>item.id===id?{...item,toast:false}:item)),duration);
  },[]);
  useEffect(()=>{if(open)setItems(current=>current.map(item=>({...item,read:true})));},[open]);
  const unread=items.filter(item=>!item.read).length;
  const view=<div className="authoring-notifications">
    <button type="button" aria-label={`通知履歴、未読${unread}件`} aria-expanded={open} onClick={()=>setOpen(value=>!value)}>♢ 通知{unread>0&&<span className="authoring-count-badge">{unread}</span>}</button>
    {open&&<section className="authoring-notification-history" aria-label="通知履歴" role="region"><header><strong>通知履歴</strong><button type="button" onClick={()=>setItems(current=>current.map(item=>({...item,read:true})))}>すべて既読</button><button type="button" aria-label="通知履歴を閉じる" onClick={()=>setOpen(false)}>閉じる</button></header>
      {items.length===0?<p>通知はありません。</p>:<ol>{items.map(item=><li key={item.id} className={`notification-${item.severity}`}><strong>{item.title}</strong>{item.detail&&<p>{item.detail}</p>}<time dateTime={new Date(item.createdAt).toISOString()}>{new Date(item.createdAt).toLocaleTimeString("ja-JP",{hour:"2-digit",minute:"2-digit"})}</time></li>)}</ol>}
    </section>}
    <div className="authoring-toast-stack" aria-label="新しい通知">{items.filter(item=>item.toast).slice(0,4).map(item=><article key={item.id} className={`authoring-toast notification-${item.severity}`}><button type="button" className="authoring-toast-open" aria-label={`${item.title}。通知履歴を開く`} onClick={()=>setOpen(true)}><span role={item.severity==="error"?"alert":"status"}>{item.title}{item.detail&&<small>{item.detail}</small>}</span></button><button type="button" aria-label={`${item.title}を閉じる`} onClick={()=>setItems(current=>current.map(entry=>entry.id===item.id?{...entry,toast:false}:entry))}>×</button></article>)}</div>
  </div>;
  return {notify,view};
}
