import type { ContentItem, ReviewNode } from "@/types/reviews";

export interface SplitCandidate {
  label: string;
  items: ContentItem[];
  included: boolean;
}
export interface SplitProposal {
  parentItems: ContentItem[];
  children: SplitCandidate[];
  notes: string[];
  placements: { owner: number | null; item: ContentItem }[];
}

const circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
const marker = /^\s*(?:([1-9]\d?)[.)]|[（(]([1-9]\d?)[)）]|([①-⑳]))(?=\s|[^\d\s])\s*/u;

function labelFor(match: RegExpMatchArray): string {
  const number = match[1] || match[2] || String(circled.indexOf(match[3] || "") + 1);
  return `(${number})`;
}

function textPiece(item: ContentItem, start: number, end: number, value: string, keepSegments: boolean): ContentItem {
  const original = String("text" in item ? item.text || "" : "");
  const piece: ContentItem = { ...item, text: value };
  const existing = item.source_slice;
  const hasSource = Object.keys(item).some(key =>
    !["type", "order", "text", "merged_source_segments", "source_slice"].includes(key));
  if (hasSource && (start !== 0 || end !== original.length || existing)) {
    const base = Array.isArray(existing) && existing.length === 3 ? existing as number[] : [0, 0, Array.from(original).length];
    piece.source_slice = [
      base[0] + Array.from(original.slice(0, start)).length,
      base[0] + Array.from(original.slice(0, end)).length,
      base[2],
    ];
  }
  if (!keepSegments && "merged_source_segments" in piece) delete piece.merged_source_segments;
  return piece;
}

/** Suggest a split from already reviewed content; this never mutates the source node. */
export function suggestSubquestions(node: ReviewNode): SplitProposal | null {
  if (node.node_type !== "major_question") return null;
  const parentItems: ContentItem[] = [];
  const children: SplitCandidate[] = [];
  const notes: string[] = [];
  const placements: SplitProposal["placements"] = [];
  let current: SplitCandidate | null = null;
  const append = (item: ContentItem, owner: number | null) => {
    if (owner === null) parentItems.push(item);
    else children[owner].items.push(item);
    placements.push({ owner, item });
  };
  for (const item of node.ordered_content) {
    if (item.type === "text" && typeof item.text === "string") {
      const source = item.text;
      const lines: { start: number; end: number; value: string; match: RegExpMatchArray | null }[] = [];
      let start = 0;
      while (start < source.length) {
        const newline = source.indexOf("\n", start);
        const end = newline < 0 ? source.length : newline + 1;
        const value = source.slice(start, end);
        if (!value.trim() && lines.length) {
          const previous = lines[lines.length - 1];
          previous.end = end;
          previous.value += value;
        } else if (value.trim()) {
          lines.push({ start, end, value, match: value.match(marker) });
        }
        start = end;
      }
      if (!lines.length) {
        append(item, current ? children.length - 1 : null);
        continue;
      }
      const segmentOwner = lines.findIndex(line => {
        const segments = item.merged_source_segments;
        return Array.isArray(segments) && segments.some(segment => {
          const decision = node.formula_decisions[String(segment.region_id)];
          return segment.type === "formula_region" &&
            !!decision?.teacher_transcription && line.value.includes(`$${decision.teacher_transcription}$`);
        });
      });
      lines.forEach((line, lineIndex) => {
        if (line.match) {
          current = { label: labelFor(line.match), items: [], included: true };
          children.push(current);
        }
        const text = line.match ? line.value.slice(line.match[0].length) : line.value;
        append(textPiece(item, line.start, line.end, text,
          lineIndex === (segmentOwner >= 0 ? segmentOwner : 0)), current ? children.length - 1 : null);
      });
      continue;
    }
    if (item.type === "figure_region") {
      append(item, null);
      if (current) notes.push("図は共通資料として大問に残します。必要なら分割後に所属を確認してください。");
    } else {
      append(item, current ? children.length - 1 : null);
    }
  }
  if (children.length < 2) return null;
  return { parentItems, children, notes: [...new Set(notes)], placements };
}
