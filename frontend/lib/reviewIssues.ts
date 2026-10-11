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
/** Keep review content below the sticky chrome; focus the control separately. */
export function scrollReviewContent(content:HTMLElement) {
  const selector=document.querySelector<HTMLElement>(".review-workspace-selector");
  const header=document.querySelector<HTMLElement>(".header");
  const selectorTop=selector?parseFloat(getComputedStyle(selector).top):NaN;
  const top=Number.isFinite(selectorTop)?selectorTop+selector!.getBoundingClientRect().height:
    header?.getBoundingClientRect().height||0;
  const clearance=Math.min(top,window.innerHeight*.65)+Math.min(48,Math.max(16,(window.innerHeight-top)*.15));
  // scrollIntoView also reveals targets in an internally scrolling recovery list.
  content.scrollIntoView({block:"start",inline:"nearest"});
  window.scrollBy({top:content.getBoundingClientRect().top-clearance,behavior:"auto"});
}
/** Called only after explicit navigation; never reconciles or persists editor text. */
export function focusReviewIssue(issue: ReviewIssueTarget) {
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    const target = document.getElementById(issue.targetId);
    if (!target) return;
    // Rubric controls may live inside a closed details element.
    for (let parent = target.parentElement; parent; parent = parent.parentElement)
      if (parent instanceof HTMLDetailsElement) parent.open = true;
    scrollReviewContent(target.closest<HTMLElement>('[id^="authoring-rubric-"],.model-answer-import-entry')||target);
    const control = issue.controlSelector ? target.querySelector<HTMLElement>(issue.controlSelector) :
      target.matches("input,textarea,select,button") ? target : target.querySelector<HTMLElement>("textarea,select,input,button");
    (control || target).focus({preventScroll: true});
  }));
}
export function reviewWarningId(id: string) { return `review-warning-${encodeURIComponent(id)}`; }
