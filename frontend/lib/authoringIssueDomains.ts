import type {AuthoringIssue} from "./api/testAuthoring";

export const authoringIssueDomains = [
  ["question", "問題"], ["answer", "解答"], ["rubric", "採点基準"],
] as const;
export type AuthoringIssueDomain = typeof authoringIssueDomains[number][0];
export type AuthoringIssueVisibility = Record<AuthoringIssueDomain, boolean>;
export const allAuthoringIssueDomains: AuthoringIssueVisibility = {question:true,answer:true,rubric:true};

/** Structured ownership only. Test-wide source/save/publication/metadata issues
 * and future unrecognized sections remain visible as common requirements. */
export function authoringIssueDomain(issue:AuthoringIssue): AuthoringIssueDomain | "common" {
  for (const value of [issue.domain, issue.section]) {
    if (value === "question" || value === "answer" || value === "rubric") return value;
    if (value === "model_answer") return "answer";
  }
  return "common";
}

export function countAuthoringIssueDomains(issues:AuthoringIssue[]) {
  const counts = {question:0,answer:0,rubric:0,common:0};
  for (const issue of issues) counts[authoringIssueDomain(issue)]++;
  return counts;
}

export function visibleAuthoringIssues(issues:AuthoringIssue[], visible:AuthoringIssueVisibility) {
  return issues.filter(issue => {
    const domain = authoringIssueDomain(issue);
    return domain === "common" || visible[domain];
  });
}
