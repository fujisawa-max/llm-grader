import type {Region, ReviewNode} from "@/types/reviews";
import {questionContent} from "./questionContent";

/** Match fix4's Python str.split() whitespace-only comparison, without
 * normalizing the actual text or manufacturing a persisted receipt. */
export function meaningfulTextEdit(before:string,after:string) {
  const semantic=(value:string)=>value.replace(/[\p{White_Space}\u001c-\u001f]/gu,"");
  return semantic(before)!==semantic(after);
}

/** Last explicit input belongs to the unsaved session, not to source refreshes.
 * After Save, only the server's scoped text receipt supplies durable review. */
export function questionTextReviewed(node:ReviewNode,savedNode:ReviewNode|undefined,regions:Region[],content:string,lastManualInput:string|undefined) {
  const savedText=questionContent(savedNode||node,regions).text;
  const changed=meaningfulTextEdit(savedText,content);
  if(lastManualInput===content&&changed)return true;
  const receipt=savedNode?.teacher_correction?.text_review;
  return !changed&&!!receipt&&typeof receipt==="object"&&
    "teacher_confirmed" in receipt&&receipt.teacher_confirmed===true&&
    "confirmation_origin" in receipt&&receipt.confirmation_origin==="manual_edit";
}
