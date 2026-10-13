import type {RubricCandidateEdit} from "@/lib/api/modelAnswerImports";

export const DEFAULT_ZERO_CONDITION="基準を満たしていない。";

/** Build only the default zero level and one editable full-credit level. */
export function initialRubricLevels(points:number,description:string,ambiguous=false){
  return [
    {score:0,condition:DEFAULT_ZERO_CONDITION},
    points>0
      ? {score:points,condition:ambiguous?"":description.trim()}
      : {score:null,condition:""},
  ];
}

export function derivedRubricMaximum(criterion:Pick<RubricCandidateEdit,"levels">):number{
  const scores=(criterion.levels||[]).map(level=>level.score).filter((score):score is number=>
    typeof score==="number"&&Number.isFinite(score)&&score>=0);
  return scores.length?Math.max(...scores):0;
}

export function prepareRubricCriteria(criteria:RubricCandidateEdit[]):RubricCandidateEdit[]{
  return criteria.map(criterion=>{
    const levels=criterion.levels;
    if(levels?.length)return {...criterion,points:derivedRubricMaximum(criterion)};
    return {...criterion,levels:initialRubricLevels(criterion.points,criterion.description,
      !!criterion.points_conflict&&!criterion.points_confirmed)};
  });
}

export function withCanonicalRubricMaximum(criterion:RubricCandidateEdit):RubricCandidateEdit{
  return {...criterion,points:derivedRubricMaximum(criterion)};
}
