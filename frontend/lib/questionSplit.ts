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
  canApply: boolean;
}

const circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
const marker = /^\s*(?:([1-9]\d?)[.)]|[（(]([1-9]\d?)[)）]|([①-⑳]))(?=\s|[^\d\s])\s*/u;

function labelFor(match: RegExpMatchArray): string {
  const number = match[1] || match[2] || String(circled.indexOf(match[3] || "") + 1);
  return `(${number})`;
}

const mappingKeys = new Set(["type", "order", "text", "merged_source_segments", "source_slice"]);
const evidenceOf = (item: Record<string, unknown>) => Object.fromEntries(
  Object.entries(item).filter(([key]) => !mappingKeys.has(key))
);
const stableJson = (value: Record<string, unknown>) => JSON.stringify(
  Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
);
const points = (value: string) => Array.from(value);

interface SourceOrigin {
  evidence: Record<string, unknown>;
  canonicalText: string;
  sourceStart: number;
  sourceEnd: number;
  sourceTotal: number;
  contentStart: number;
  contentEnd: number;
  segment?: Record<string, unknown>;
}
type UnlocatedOrigin = Omit<SourceOrigin, "contentStart" | "contentEnd">;

// Offsets are measured against the canonical immutable OCR text, never against
// a teacher-edited Markdown value or the rendered preview.
function sourceText(item: Record<string, unknown>, canonical: ContentItem): Omit<SourceOrigin, "contentStart" | "contentEnd" | "segment"> | null {
  if (!("text" in canonical) || typeof canonical.text !== "string") return null;
  const total = points(canonical.text).length;
  const slice = item.source_slice;
  if (slice === undefined) return {
    evidence: evidenceOf(item), canonicalText: canonical.text, sourceStart: 0, sourceEnd: total, sourceTotal: total,
  };
  if (!Array.isArray(slice) || slice.length !== 3 || slice.some(value => !Number.isInteger(value))) return null;
  const [start, end, length] = slice as number[];
  if (start < 0 || end <= start || end > length || length !== total) return null;
  return {
    evidence: evidenceOf(item), canonicalText: points(canonical.text).slice(start, end).join(""),
    sourceStart: start, sourceEnd: end, sourceTotal: total,
  };
}

function allMatches(haystack: string[], needle: string[], from: number): number[] {
  const found: number[] = [];
  if (!needle.length) return found;
  for (let index = from; index <= haystack.length - needle.length; index++) {
    if (needle.every((part, offset) => haystack[index + offset] === part)) found.push(index);
  }
  return found;
}

function locateOrigins(item: ContentItem, decisions: ReviewNode["formula_decisions"], canonicalItems: ContentItem[]): SourceOrigin[] | null {
  const value = "text" in item && typeof item.text === "string" ? item.text : "";
  const evidence = evidenceOf(item as unknown as Record<string, unknown>);
  if (!Object.keys(evidence).length && "source_slice" in item && item.source_slice !== undefined) return null;
  const candidates = canonicalItems.filter(candidate => candidate.type === "text" && stableJson(evidenceOf(candidate as unknown as Record<string, unknown>)) === stableJson(evidence));
  const origins: UnlocatedOrigin[] = [];
  if (Object.keys(evidence).length) {
    if (candidates.length !== 1) return null;
    const origin = sourceText(item as unknown as Record<string, unknown>, candidates[0]);
    if (!origin) return null;
    origins.push(origin);
  }
  const mergedSegments = (item as ContentItem & { merged_source_segments?: Record<string, unknown>[] }).merged_source_segments || [];
  for (const rawSegment of mergedSegments) {
    const segment = rawSegment as Record<string, unknown>;
    if (segment.type === "formula_region") {
      const regionId = String(segment.region_id || "");
      const transcription = decisions[regionId]?.teacher_transcription;
      if (!transcription) return null;
      origins.push({
        evidence: segment, canonicalText: `$${transcription}$`, sourceStart: 0,
        sourceEnd: 0, sourceTotal: 0, segment,
      });
      continue;
    }
    const segmentEvidence = evidenceOf(segment);
    if (!Object.keys(segmentEvidence).length) return null;
    const matches = canonicalItems.filter(candidate => candidate.type === "text" &&
      stableJson(evidenceOf(candidate as unknown as Record<string, unknown>)) === stableJson(segmentEvidence));
    if (matches.length !== 1) return null;
    const origin = sourceText(segment, matches[0]);
    if (!origin) return null;
    origins.push({ ...origin, segment });
  }
  const current = points(value);
  let cursor = 0;
  const resolved: SourceOrigin[] = [];
  for (const origin of origins) {
    const fragment = points(origin.canonicalText);
    const positions = allMatches(current, fragment, cursor);
    if (positions.length !== 1) return null;
    const contentStart = positions[0], contentEnd = contentStart + fragment.length;
    resolved.push({ ...origin, contentStart, contentEnd });
    cursor = contentEnd;
  }
  return resolved;
}

function splitRange(origin: SourceOrigin, start: number, end: number): [number, number, number] | null {
  const contentStart = Math.max(origin.contentStart, start);
  const contentEnd = Math.min(origin.contentEnd, end);
  if (contentStart >= contentEnd) return null;
  const sourceWidth = origin.sourceEnd - origin.sourceStart;
  const contentWidth = origin.contentEnd - origin.contentStart;
  if (sourceWidth !== contentWidth) return null;
  return [origin.sourceStart + contentStart - origin.contentStart,
    origin.sourceStart + contentEnd - origin.contentStart, origin.sourceTotal];
}

function textPiece(item: ContentItem, start: number, end: number, value: string, origins: SourceOrigin[]): ContentItem | null {
  const piece: ContentItem = { ...item, text: value };
  const primary = origins.find(origin => !origin.segment);
  const primaryRange = primary ? splitRange(primary, start, end) : null;
  if (primary && Math.max(primary.contentStart, start) < Math.min(primary.contentEnd, end) && !primaryRange) return null;
  if (primary && !primaryRange) {
    for (const key of Object.keys(primary.evidence)) delete (piece as unknown as Record<string, unknown>)[key];
    delete piece.source_slice;
  } else if (primaryRange) piece.source_slice = primaryRange;
  else if (piece.source_slice) delete piece.source_slice;

  const segments: Record<string, unknown>[] = [];
  for (const origin of origins.filter(value => value.segment)) {
    if (origin.segment?.type === "formula_region") {
      if (Math.max(origin.contentStart, start) < Math.min(origin.contentEnd, end)) segments.push(origin.segment);
      continue;
    }
    const range = splitRange(origin, start, end);
    if (Math.max(origin.contentStart, start) < Math.min(origin.contentEnd, end) && !range) return null;
    if (!range) continue;
    segments.push({ ...origin.evidence, source_slice: range });
  }
  const mutablePiece = piece as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
  if (segments.length) mutablePiece.merged_source_segments = segments;
  else delete mutablePiece.merged_source_segments;
  return piece;
}

/** Suggest a split from already reviewed content; this never mutates the source node. */
export function suggestSubquestions(node: ReviewNode, canonicalNode?: Pick<ReviewNode, "ordered_content">): SplitProposal | null {
  if (node.node_type !== "major_question") return null;
  const parentItems: ContentItem[] = [];
  const children: SplitCandidate[] = [];
  const notes: string[] = [];
  const placements: SplitProposal["placements"] = [];
  let canApply = true;
  const canonicalItems = canonicalNode?.ordered_content || node.ordered_content;
  let current: SplitCandidate | null = null;
  const append = (item: ContentItem, owner: number | null) => {
    if (owner === null) parentItems.push(item);
    else children[owner].items.push(item);
    placements.push({ owner, item });
  };
  for (const item of node.ordered_content) {
    if (item.type === "text" && typeof item.text === "string") {
      const source = item.text;
      const sourcePoints = points(source);
      const lines: { start: number; end: number; value: string; match: RegExpMatchArray | null }[] = [];
      let start = 0;
      while (start < sourcePoints.length) {
        const newline = sourcePoints.indexOf("\n", start);
        const end = newline < 0 ? sourcePoints.length : newline + 1;
        const value = sourcePoints.slice(start, end).join("");
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
      const origins = locateOrigins(item, node.formula_decisions, canonicalItems);
      if (!origins) {
        canApply = false;
        notes.push("編集済みの問題文と元の読み取り範囲を一意に照合できません。内容は保持されています。分割前に問題文を元の読み取り状態へ戻すか、小問を手動で追加してください。");
      }
      lines.forEach((line, lineIndex) => {
        if (line.match) {
          current = { label: labelFor(line.match), items: [], included: true };
          children.push(current);
        }
        const text = line.match ? line.value.slice(line.match[0].length) : line.value;
        const piece = origins ? textPiece(item, line.start, line.end, text, origins) : { ...item, text };
        if (!piece) {
          canApply = false;
          notes.push("問題文の出典範囲を安全に分けられません。分割案は確認用で、適用できません。");
          append({ ...item, text }, current ? children.length - 1 : null);
        } else append(piece, current ? children.length - 1 : null);
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
  return { parentItems, children, notes: [...new Set(notes)], placements, canApply };
}
