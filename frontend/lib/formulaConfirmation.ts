import type { Decision } from "@/types/reviews";
import katex from "katex";

/** Formula inclusion/merge state and teacher confirmation are separate facts. */
export function formulaIsConfirmed(decision: Decision | undefined): boolean {
  if (!decision) return false;
  if (decision.decision === "excluded") return true;
  if (decision.confirmation_status !== undefined) return decision.confirmation_status === "confirmed";
  // Backward compatibility for revisions created before confirmation_status existed.
  return decision.decision !== "unreviewed";
}

export function setFormulaConfirmation(
  decision: Decision | undefined,
  status: "unreviewed" | "confirmed",
  method: "individual" | "bulk" = "individual",
): Decision {
  const next: Decision = { ...(decision || { decision: "unreviewed" }), confirmation_status: status };
  if (status === "confirmed") next.confirmation_method = method;
  else delete next.confirmation_method;
  return next;
}

export function formulaHasRenderError(source: string): boolean {
  if (!source.trim()) return true;
  try {
    katex.renderToString(source.trim(), { throwOnError: true, trust: false });
    return false;
  } catch {
    return true;
  }
}
