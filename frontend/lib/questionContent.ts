import type {ContentItem, Region, ReviewNode} from "@/types/reviews";
import {questionFormulaText} from "./questionMathSource";
import {mergeContiguousContent} from "./reviewTextMerge";
import {parseMathText} from "./mathText";
import {setFormulaConfirmation} from "./formulaConfirmation";

export function questionContent(node: ReviewNode, regions: Region[]) {
  let text = "";
  const spans: {index: number; start: number; end: number; text: string}[] = [];
  node.ordered_content.forEach((item, index) => {
    let value = "";
    if (item.type === "text") value = String("text" in item ? item.text ?? "" : "");
    if (item.type === "formula_region") {
      const id = String(item.region_id);
      const raw = node.formula_decisions[id]?.teacher_transcription ?? regions.find(r => r.region_id === id)?.text_fragments?.map(f => f.native_text).join("\n") ?? "";
      value = raw;
    }
    if (item.type !== "text" && item.type !== "formula_region") return;
    if (text && !text.endsWith("\n")) text += "\n";
    const start = text.length;
    text += value;
    spans.push({index, start, end: text.length, text: value});
  });
  return {text, spans};
}

/** Edit a coherent view without changing immutable source anchors. A local
 * change stays in its original item; an edit across anchors uses the existing
 * provenance-preserving merge contract. Figures never move across text. */
export function editQuestionContent(node: ReviewNode, regions: Region[], value: string): ReviewNode | null {
  const view = questionContent(node, regions);
  if (!view.spans.length) return {...node, ordered_content: [{type: "text", text: value, order: 0}, ...node.ordered_content].map((item, order) => ({...item, order}))};
  let start = 0;
  while (start < view.text.length && start < value.length && view.text[start] === value[start]) start++;
  if (start === view.text.length && start === value.length) return node;
  let end = view.text.length, newEnd = value.length;
  while (end > start && newEnd > start && view.text[end-1] === value[newEnd-1]) {end--; newEnd--;}
  const span = view.spans.find(s => s.start <= start && end <= s.end);
  const decisions = {...node.formula_decisions};
  const excluded = new Set<string>();
  const resetEmbedded = (item: ContentItem, text: string): boolean => {
    const ids = ("merged_source_segments" in item ? item.merged_source_segments || [] : []).filter(s => s.type === "formula_region").map(s => String(s.region_id));
    if (!ids.length) return true;
    const oldParts = parseMathText(String("text" in item ? item.text ?? "" : ""), false).filter(p => p.kind !== "text");
    const parts = parseMathText(text, false).filter(p => p.kind !== "text");
    // Temporary invalid delimiters must remain editable. Keep the last
    // known source transcription unconfirmed; strict save/review validation
    // still rejects a source formula that is absent from the edited text.
    if (oldParts.length !== parts.length) {
      for (const id of ids) {
        const old = decisions[id], transcription = old?.teacher_transcription?.trim();
        if (parts.length < oldParts.length && transcription && !text.includes(transcription) &&
            oldParts.some(part => part.value.trim() === transcription)) {
          // Explicit deletion of an entire source formula. Its native region
          // remains in the immutable draft and excluded decision history.
          excluded.add(id);
          decisions[id] = setFormulaConfirmation({...old, decision: "excluded"}, "confirmed", "individual");
        } else decisions[id] = setFormulaConfirmation(old, "unreviewed");
      }
      return true;
    }
    const used = new Set<number>();
    for (const id of ids) {
      const old = decisions[id];
      const at = oldParts.findIndex((p, index) => !used.has(index) && p.value.trim() === old?.teacher_transcription?.trim());
      if (at < 0) {decisions[id] = setFormulaConfirmation(old, "unreviewed"); continue;}
      used.add(at);
      decisions[id] = setFormulaConfirmation({...old, teacher_transcription: parts[at].value.trim()}, "unreviewed");
    }
    return true;
  };
  if (span) {
    const text = span.text.slice(0, start-span.start) + value.slice(start, newEnd) + span.text.slice(end-span.start);
    const item = node.ordered_content[span.index];
    if (item.type === "formula_region") {
      const id = String(item.region_id);
      if (!text.trim()) return {...node, formula_decisions: {...decisions,
        [id]: setFormulaConfirmation({...decisions[id], decision: "excluded"}, "confirmed", "individual")},
        ordered_content: node.ordered_content.filter((_, index) => index !== span.index).map((it, order) => ({...it, order}))};
      const raw = questionFormulaText(text) ?? text;
      const markdown = questionFormulaText(text) !== null ? text : `$${text}$`;
      const anchor = Object.fromEntries(Object.entries(item).filter(([key]) => key !== "order"));
      decisions[id] = setFormulaConfirmation({...decisions[id], decision: "merged_into_text", teacher_transcription: raw}, "unreviewed");
      return {...node, formula_decisions: decisions, ordered_content: node.ordered_content.map((it, index) => index === span.index
        ? {type: "text", order: it.order, text: markdown, merged_source_segments: [anchor]} : it)};
    }
    if (!resetEmbedded(item, text)) return null;
    return {...node, formula_decisions: decisions, ordered_content: node.ordered_content.map((it, index) => index === span.index
      ? {...it, text, ...("merged_source_segments" in it ? {merged_source_segments: it.merged_source_segments?.filter(s => !excluded.has(String(s.region_id)))} : {})} : it)};
  }
  // Preserve unchanged formula anchors when several prose spans are edited
  // together (for example numbering before a split). Match the whole formula,
  // never individual repeated values, and require an unambiguous occurrence.
  const protectedSpans = view.spans.filter(s => node.ordered_content[s.index].type === "formula_region" && s.start >= start && s.end <= end);
  if (protectedSpans.length) {
    let cursor = start;
    const anchors = protectedSpans.map(span => {
      const at = value.indexOf(span.text, cursor);
      if (at < 0 || value.indexOf(span.text, at+span.text.length) >= 0) return null;
      cursor = at + span.text.length;
      return {...span, at};
    });
    if (anchors.every(anchor => anchor !== null)) {
      const patches: {start: number; end: number; text: string}[] = [];
      let oldAt = start, newAt = start;
      for (const anchor of anchors) {
        if (!anchor) return null;
        patches.push({start: oldAt, end: anchor.start, text: value.slice(newAt, anchor.at)});
        oldAt = anchor.end; newAt = anchor.at + anchor.text.length;
      }
      patches.push({start: oldAt, end, text: value.slice(newAt, newEnd)});
      let updated: ReviewNode | null = node;
      for (const patch of patches.reverse()) {
        const current = questionContent(updated, regions).text;
        updated = editQuestionContent(updated, regions, current.slice(0, patch.start)+patch.text+current.slice(patch.end));
        if (!updated) return null;
      }
      return updated;
    }
  }
  // Cross-item replacement is bounded to a contiguous textual run. Retain
  // figures/score evidence and refuse a rewrite that crosses their positions.
  const affected = view.spans.filter(s => s.end > start && s.start < end);
  if (!affected.length) return null;
  const first = affected[0].index, last = affected[affected.length-1].index;
  if (node.ordered_content.slice(first, last+1).some(it => !["text", "formula_region"].includes(it.type))) return null;
  const items = [...node.ordered_content];
  const from = first;
  let to = last;
  if (items[first].type !== "text") {items.splice(first, 0, {type: "text", order: first, text: ""}); to++;}
  const sources = Object.fromEntries(regions.map(r => [r.region_id, decisions[r.region_id]?.teacher_transcription ?? r.text_fragments?.map(f => f.native_text).join("\n") ?? ""]));
  const merged = mergeContiguousContent(items, Array.from({length: to-from+1}, (_, i) => from+i), sources);
  if (!merged) return null;
  const replacement = view.text.slice(affected[0].start, start) + value.slice(start, newEnd) + view.text.slice(end, affected[affected.length-1].end);
  const oldItem = merged[from];
  for (const s of ("merged_source_segments" in oldItem ? oldItem.merged_source_segments || [] : [])) if (s.type === "formula_region") {
    const id = String(s.region_id);
    decisions[id] = setFormulaConfirmation({...decisions[id], decision: "merged_into_text", teacher_transcription: sources[id]}, "unreviewed");
  }
  if (!resetEmbedded(oldItem, replacement)) return null;
  merged[from] = {...oldItem, text: replacement, ...("merged_source_segments" in oldItem ? {merged_source_segments: oldItem.merged_source_segments?.filter(s => !excluded.has(String(s.region_id)))} : {})};
  return {...node, ordered_content: merged, formula_decisions: decisions};
}
