import type {ModelAnswerDraftEntry} from "./api/modelAnswerImports";
import type {DiagramRecord} from "../types/diagrams";

/** A new explicit diagram acceptance outranks automatic non-answer exclusion. */
export function acceptedAnswerDiagramPatch(entry:ModelAnswerDraftEntry, records:DiagramRecord[], targetValid:boolean):Partial<ModelAnswerDraftEntry> {
  const priorAccepted=new Set(entry.diagram_records?.filter(record=>record.state==="accepted").map(record=>record.id));
  const teacherDisposition=entry.teacher_correction?.disposition;
  const automaticExclusion=targetValid && entry.disposition==="excluded" && entry.mapping_state==="automatic" &&
    entry.ignore_reason==="classified_as_non_answer" && entry.semantic_classification?.status==="classified" &&
    !["ignored","excluded","unassigned"].includes(String(teacherDisposition));
  const acceptance=records.some(record=>record.state==="accepted" && !priorAccepted.has(record.id) && record.trust_state!=="hard_invalid");
  return automaticExclusion && acceptance ? {diagram_records:records,disposition:"include",
    teacher_correction:{...entry.teacher_correction,disposition:"include",teacher_confirmed:true}} : {diagram_records:records};
}
