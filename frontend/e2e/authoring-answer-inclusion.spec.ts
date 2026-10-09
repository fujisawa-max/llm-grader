import {test,expect} from "@playwright/test";
import {acceptedAnswerDiagramPatch} from "../lib/authoringAnswerInclusion";
import type {ModelAnswerDraftEntry} from "../lib/api/modelAnswerImports";
import type {DiagramRecord} from "../types/diagrams";
const entry=():ModelAnswerDraftEntry=>({id:"a",question_id:"child",mapping_state:"automatic",disposition:"excluded",ignore_reason:"classified_as_non_answer",answer_text:"",source:{material_id:"m",source_sha256:"sha",segments:[]},semantic_classification:{status:"classified"} as ModelAnswerDraftEntry["semantic_classification"]});
for(const source_type of [undefined,"manual_pdf_crop"])test(`explicit ${source_type||"automatic"} diagram acceptance includes auto-excluded entry`,()=>{
 const before=entry(),records=[{id:"crop",state:"accepted",trust_state:"trusted",source_type}] as unknown as DiagramRecord[];
 const patch=acceptedAnswerDiagramPatch(before,records,true);
 expect(patch.disposition).toBe("include");expect(patch.teacher_correction).toEqual({disposition:"include",teacher_confirmed:true});expect(before.disposition).toBe("excluded");expect(before.ignore_reason).toBe("classified_as_non_answer");
});
for(const changes of [{disposition:"ignored"},{disposition:"unassigned"},{mapping_state:"needs_review"},{teacher_correction:{disposition:"excluded",teacher_confirmed:true}},{teacher_correction:{disposition:"ignored",teacher_confirmed:true}}])test(`preserve non-automatic/teacher decision ${JSON.stringify(changes)}`,()=>{
 const records=[{id:"crop",state:"accepted"}] as unknown as DiagramRecord[];
 expect(acceptedAnswerDiagramPatch({...entry(),...changes} as ModelAnswerDraftEntry,records,true)).toEqual({diagram_records:records});
});
test("displaying saved acceptance or an invalid target does not promote",()=>{
 const records=[{id:"crop",state:"accepted"}] as unknown as DiagramRecord[];
 expect(acceptedAnswerDiagramPatch({...entry(),diagram_records:records},records,true)).toEqual({diagram_records:records});expect(acceptedAnswerDiagramPatch(entry(),records,false)).toEqual({diagram_records:records});
});
