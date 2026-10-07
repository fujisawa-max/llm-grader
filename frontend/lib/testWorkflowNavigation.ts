type TestWorkflowDestination = "overview" | "questions" | "answers" | "policy" | "samples" |
  "authoring" | "rubric" | "students" | "grading" | "results" | "review";

export function testWorkflowHref(testId: string, destination: TestWorkflowDestination): string {
  const base = `/tests/${encodeURIComponent(testId)}`;
  return destination === "authoring" ? `${base}/authoring` : destination === "review" ? `${base}/grading/review`
    : `${base}?section=${destination === "rubric" ? "answers" : destination}`;
}
