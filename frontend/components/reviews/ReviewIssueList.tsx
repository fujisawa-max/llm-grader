import type { ReviewIssueTarget } from "@/lib/reviewIssues";
export function ReviewIssueList({issues, onNavigate, label = "未確認の項目"}: {
  issues: ReviewIssueTarget[]; onNavigate: (issue: ReviewIssueTarget) => void; label?: string;
}) {
  return <ul aria-label={label}>{issues.map(issue => <li key={issue.id}>
    <button type="button" className="registration-validation-jump" onClick={() => onNavigate(issue)}
      aria-label={`${issue.path} — ${issue.message}。該当候補を表示`}>{issue.path} — {issue.message}</button>
  </li>)}</ul>;
}
