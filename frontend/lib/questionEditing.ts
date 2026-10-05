import type {Region, ReviewNode} from "@/types/reviews";
import {editQuestionContent, questionContent} from "./questionContent";

/** The browser buffer is independent of source item boundaries. Only explicit
 * save/review/structural transitions reconcile it with immutable evidence. */
export interface QuestionTextBuffer {
  text: string;
  baseline: string;
  ocrEdits: Record<string, unknown>[];
}
export function questionTextBuffer(node: ReviewNode, regions: Region[]): QuestionTextBuffer {
  const text = questionContent(node, regions).text;
  return {text, baseline: text, ocrEdits: []};
}
export function bufferChanged(buffer: QuestionTextBuffer): boolean {
  return buffer.text !== buffer.baseline || buffer.ocrEdits.length > 0;
}
export function reconcileQuestionText(node: ReviewNode, regions: Region[], buffer?: QuestionTextBuffer): ReviewNode | null {
  if (!buffer || !bufferChanged(buffer)) return node;
  const next = editQuestionContent(node, regions, buffer.text);
  // Never replace the user's string with a lossy source projection. An unsafe
  // figure/source boundary fails closed at the explicit transition instead.
  if (!next || questionContent(next, regions).text !== buffer.text) return null;
  return buffer.ocrEdits.length ? {...next, math_ocr_edits: [...(next.math_ocr_edits || []), ...buffer.ocrEdits].slice(-16)} : next;
}
