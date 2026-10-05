import type {ContentItem, ReviewNode} from "@/types/reviews";
import type {MathSource} from "@/lib/api/textTools";
import {parseMathText} from "@/lib/mathText";
import katex from "katex";

/** A formula field stores raw LaTeX, whereas a text field stores Markdown.
 * Keep independent equations in source order without flattening their meaning.
 */
export function questionFormulaText(text: string): string | null {
  const parts = parseMathText(text, false);
  if (parts.some(part => part.kind === "text" && part.value.trim())) return null;
  const formulas = parts.filter(part => part.kind !== "text").map(part => part.value.trim());
  if (!formulas.length) return null;
  const result = formulas.length === 1 ? formulas[0] : `\\begin{gathered}${formulas.join("\\\\")}\\end{gathered}`;
  try {katex.renderToString(result, {throwOnError: true, trust: false}); return result;}
  catch {return null;}
}

export function questionMathReference(item: ContentItem): Record<string, unknown> {
  return Object.fromEntries(Object.entries(item).filter(([key]) => key !== "text" && key !== "order"));
}
export function questionMathSource(reviewId: string, revision: number, node: ReviewNode, saved: ReviewNode | undefined, itemIndex: number): MathSource | undefined {
  const item = node.ordered_content[itemIndex], previous = saved?.ordered_content[itemIndex];
  if (!item || !previous || !["text", "formula_region"].includes(item.type)) return;
  const reference = questionMathReference(item), expected = questionMathReference(previous);
  if (JSON.stringify(reference) !== JSON.stringify(expected)) return; // Save structure first.
  const merged = "merged_source_segments" in item && Array.isArray(item.merged_source_segments) ? item.merged_source_segments : [];
  const evidence = [item, ...merged];
  if (!evidence.some(value => (Array.isArray(value.source_element_ids) && value.source_element_ids.length) || value.type === "formula_region")) return;
  if (evidence.some(value => value.source_slice)) return; // A partial bbox may cross a sibling.
  return {kind: "question_review", reviewId, nodeKey: node.stable_key, itemIndex, revision, expectedSource: expected};
}
