type TestWorkflowDestination = "overview" | "questions" | "answers" | "policy" | "samples" |
  "rubric" | "students" | "grading" | "results" | "review";

export function testWorkflowHref(testId: string, destination: TestWorkflowDestination): string {
  const base = `/tests/${encodeURIComponent(testId)}`;
  return destination === "review" ? `${base}/grading/review`
    : `${base}?section=${destination === "rubric" ? "answers" : destination}`;
}
