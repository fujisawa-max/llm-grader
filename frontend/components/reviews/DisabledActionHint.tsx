"use client";
import {useEffect,useId,useRef,useState,type ReactNode} from "react";
import {createPortal} from "react-dom";

/** Keep disabled-action reasons above pane overflow and inside the viewport. */
export function DisabledActionHint({reason,children}:{reason?:string;children:ReactNode}){
  const id=useId(),anchor=useRef<HTMLSpanElement>(null),tooltip=useRef<HTMLSpanElement>(null);
  const [open,setOpen]=useState(false),[position,setPosition]=useState({left:8,top:8});
  useEffect(()=>{
    if(!open||!reason)return;
    const place=()=>{
      const box=anchor.current?.getBoundingClientRect(),hint=tooltip.current?.getBoundingClientRect();
      if(!box||!hint)return;
      const left=Math.max(8,Math.min(box.left,window.innerWidth-hint.width-8));
      const top=box.bottom+8+hint.height<=window.innerHeight-8?box.bottom+8:Math.max(8,box.top-hint.height-8);
      setPosition({left,top});
    };
    place();window.addEventListener("resize",place);window.addEventListener("scroll",place,true);
    return()=>{window.removeEventListener("resize",place);window.removeEventListener("scroll",place,true);};
  },[open,reason]);
  return <span ref={anchor} className="disabled-action-hint" tabIndex={reason?0:undefined} role={reason?"group":undefined} aria-label={reason?"解析できない理由":undefined} aria-describedby={reason&&open?id:undefined}
    onMouseEnter={()=>setOpen(true)} onMouseLeave={()=>setOpen(false)} onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onKeyDown={e=>{if(e.key==="Escape")setOpen(false);}}>
    {children}
    {reason&&open&&createPortal(<span ref={tooltip} id={id} role="tooltip" className="disabled-action-tooltip" style={position}>{reason}</span>,document.body)}
  </span>;
}
