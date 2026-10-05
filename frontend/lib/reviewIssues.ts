export interface ReviewIssueTarget {
  id: string;
  domain: "question" | "model_answer" | "rubric";
  questionKey?: string;
  path: string;
  issueType: string;
  message: string;
  itemId?: string;
  targetId: string;
  controlSelector?: string;
  reviewTargetId?: string;
}
/** Called only after explicit navigation; never reconciles or persists editor text. */
export function focusReviewIssue(issue: ReviewIssueTarget) {
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    const target = document.getElementById(issue.targetId);
    if (!target) return;
    // Rubric controls may live inside a closed details element.
    for (let parent = target.parentElement; parent; parent = parent.parentElement)
      if (parent instanceof HTMLDetailsElement) parent.open = true;
    target.scrollIntoView({block: "center", behavior: "smooth"});
    const control = issue.controlSelector ? target.querySelector<HTMLElement>(issue.controlSelector) :
      target.matches("input,textarea,select,button") ? target : target.querySelector<HTMLElement>("textarea,select,input,button");
    (control || target).focus({preventScroll: true});
  }));
}
export function reviewWarningId(id: string) { return `review-warning-${encodeURIComponent(id)}`; }
