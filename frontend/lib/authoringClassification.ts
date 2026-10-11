import type {ModelAnswerDraftEntry} from "./api/modelAnswerImports";

/** Routing/category decisions are confirmation; prose and score edits are not. */
export function manualClassificationPatch(entry:ModelAnswerDraftEntry & {authoring_question_key?:string|null}, patch:Partial<ModelAnswerDraftEntry> & {authoring_question_key?:string|null}) {
  const fields:string[]=[];
  if(patch.disposition!==undefined&&patch.disposition!==(entry.disposition||"include"))fields.push("disposition");
  if(patch.answer_kind!==undefined&&patch.answer_kind!==(entry.answer_kind||"primary"))fields.push("answer_kind");
  if("authoring_question_key" in patch&&patch.authoring_question_key!==(entry.authoring_question_key||null))fields.push("target_question");
  if(patch.semantic_classification&&JSON.stringify(patch.semantic_classification.segments.map(s=>[s.id,s.category]))!==
    JSON.stringify(entry.semantic_classification?.segments.map(s=>[s.id,s.category])))fields.push("segment_category");
  if(!fields.length)return patch;
  const classification=patch.semantic_classification||entry.semantic_classification;
  return {...patch,...(classification?{semantic_classification:{...classification,status:"teacher_reviewed"}}:{}),
    teacher_correction:{...entry.teacher_correction,...patch.teacher_correction,teacher_confirmed:true,
      ...(patch.disposition!==undefined?{disposition:patch.disposition}:{}),confirmation_origin:"manual_edit",
      // Retain the first automatic result, including source spans/confidence.
      classification_original:entry.teacher_correction?.classification_original??entry.semantic_classification,
      classification_routing_original:entry.teacher_correction?.classification_routing_original??{
        disposition:entry.disposition||"include",mapping_state:entry.mapping_state,
        authoring_question_key:entry.authoring_question_key||null,answer_kind:entry.answer_kind||"primary"},
      classification_reviewed_fields:[...new Set([
        ...(Array.isArray(entry.teacher_correction?.classification_reviewed_fields)?entry.teacher_correction.classification_reviewed_fields.filter(field=>typeof field==="string"):[]),...fields])]}};
}
