import type { ContentItem, ReviewNode } from "@/types/reviews";

export interface SplitCandidate {
  label: string;
  items: ContentItem[];
  included: boolean;
  mappingStatus: "automatic" | "manual_required" | "manual_mapped" | "unmapped_override";
  mappingMessage?: string;
  contentValid: boolean;
  selectedSourceIds: string[];
}
export interface SplitSourceOption {
  id: string;
  label: string;
  excerpt: string;
  evidence: Record<string, unknown>;
}
export interface SplitProposal {
  parentItems: ContentItem[];
  children: SplitCandidate[];
  sourceOptions: SplitSourceOption[];
  notes: string[];
  placements: { owner: number | null; item: ContentItem }[];
  canApply: boolean;
}

const circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
const marker = /^\s*(?:([1-9]\d?)[.)]|[（(]([1-9]\d?)[)）]|([①-⑳])|問\s*([1-9]\d?)(?=\s|[.:：、)]|$))(?=\s|[^\d\s]|$)\s*/u;

function labelFor(match: RegExpMatchArray): string {
  const number = match[1] || match[2] || match[4] || String(circled.indexOf(match[3] || "") + 1);
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

function sourceOptions(items: ContentItem[]): SplitSourceOption[] {
  const seen = new Set<string>();
  const result: SplitSourceOption[] = [];
  for (const [index, item] of items.entries()) {
    if (item.type !== "text" || typeof item.text !== "string") continue;
    const evidence = evidenceOf(item as unknown as Record<string, unknown>);
    if (!Object.keys(evidence).length) continue;
    const id = stableJson(evidence);
    if (seen.has(id)) continue;
    seen.add(id);
    const ids = Array.isArray(evidence.source_element_ids)
      ? evidence.source_element_ids.filter((value): value is string => typeof value === "string") : [];
    const page = typeof evidence.page_index === "number" ? ` ${evidence.page_index + 1}ページ` : "";
    result.push({
      id,
      label: ids.length ? `${ids.join(", ")}${page}` : `読み取り項目 ${result.length + 1}${page}`,
      excerpt: item.text.trim().replace(/\s+/gu, " ").slice(0, 180) || `読み取り項目 ${index + 1}`,
      evidence,
    });
  }
  return result;
}

export function mapCandidateToSources(items: ContentItem[], sourceIds: string[], options: SplitSourceOption[]): ContentItem[] | null {
  const selected = options.filter(option => sourceIds.includes(option.id));
  if (!selected.length || selected.length !== new Set(sourceIds).size) return null;
  const textIndex = items.findIndex(item => item.type === "text");
  if (textIndex < 0) return null;
  const mapped = items.map(item => {
    if (item.type !== "text") return { ...item };
    const textItem = { ...item } as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
    delete textItem.source_slice;
    delete textItem.page_index;
    delete textItem.bbox;
    delete textItem.source_element_ids;
    // Keep only independently verified formula provenance. Text source refs
    // are replaced by the teacher's explicit source-element selection below.
    const formulaSegments = (textItem.merged_source_segments || []).filter(segment => segment.type === "formula_region");
    if (formulaSegments.length) textItem.merged_source_segments = formulaSegments;
    else delete textItem.merged_source_segments;
    return textItem;
  });
  const anchor = mapped[textIndex] as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
  anchor.merged_source_segments = [
    ...(anchor.merged_source_segments || []),
    ...selected.map(option => ({ ...option.evidence })),
  ];
  return mapped;
}

export function clearTextSourceMapping(items: ContentItem[]): ContentItem[] {
  return items.map(item => {
    if (item.type !== "text") return { ...item };
    const cleared = { type: "text", order: item.order, text: item.text } as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
    const formulaSegments = (item.merged_source_segments || []).filter(segment => segment.type === "formula_region");
    if (formulaSegments.length) cleared.merged_source_segments = formulaSegments;
    return cleared;
  });
}

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

function sourceOrigins(item: ContentItem, decisions: ReviewNode["formula_decisions"], canonicalItems: ContentItem[]): UnlocatedOrigin[] | null {
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
  return origins;
}

function locateOrigins(item: ContentItem, decisions: ReviewNode["formula_decisions"], canonicalItems: ContentItem[]): SourceOrigin[] | null {
  const value = "text" in item && typeof item.text === "string" ? item.text : "";
  const origins = sourceOrigins(item, decisions, canonicalItems);
  if (!origins) return null;
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

function normalizedWithOffsets(value: string): { value: string[]; ranges: [number, number][] } {
  const input = points(value);
  const output: string[] = [];
  const ranges: [number, number][] = [];
  for (let index = 0; index < input.length;) {
    if (/\s|\u3000/u.test(input[index])) {
      const start = index;
      while (index < input.length && (/\s|\u3000/u.test(input[index]))) index++;
      if (output.length && index < input.length) {
        output.push(" ");
        ranges.push([start, index]);
      }
      continue;
    }
    output.push(input[index]);
    ranges.push([index, index + 1]);
    index++;
  }
  return { value: output, ranges };
}

function normalizedMatches(haystack: string, needle: string): [number, number][] {
  const source = normalizedWithOffsets(haystack);
  const target = normalizedWithOffsets(needle);
  const sourcePoints = points(haystack);
  const targetPoints = points(needle);
  if (!target.value.length) return [];
  return allMatches(source.value, target.value, 0).map(index => {
    let start = source.ranges[index][0];
    let end = source.ranges[index + target.value.length - 1][1];
    if (targetPoints[0] && /\s|\u3000/u.test(targetPoints[0])) {
      while (start > 0 && /\s|\u3000/u.test(sourcePoints[start - 1])) start--;
    }
    if (targetPoints.at(-1) && /\s|\u3000/u.test(targetPoints.at(-1)!)) {
      while (end < sourcePoints.length && /\s|\u3000/u.test(sourcePoints[end])) end++;
    }
    return [start, end];
  });
}

function uniqueOriginMatch(rawLine: string, origins: UnlocatedOrigin[] | null): boolean {
  if (!origins?.length) return false;
  return normalizedMatches(origins.map(origin => origin.canonicalText).join(""), rawLine).length === 1;
}

interface TextRangeMapping { origin: UnlocatedOrigin; range: [number, number, number] }

function mappedLinePiece(item: ContentItem, rawLine: string, displayText: string,
  origins: UnlocatedOrigin[] | null): { item: ContentItem; valid: boolean } {
  const blank: Record<string, unknown> = { type: "text", order: item.order, text: displayText };
  const sourceBacked = !!origins?.length;
  if (!origins) return { item: blank as ContentItem, valid: false };
  if (!sourceBacked) return { item: blank as ContentItem, valid: false };

  const formulaOrigins = origins.filter(origin => origin.segment?.type === "formula_region");
  const textOrigins = origins.filter(origin => origin.segment?.type !== "formula_region");
  const rawPoints = points(rawLine);
  const formulaRanges: { origin: UnlocatedOrigin; start: number; end: number }[] = [];
  let ambiguous = false;
  for (const origin of formulaOrigins) {
    const positions = allMatches(rawPoints, points(origin.canonicalText), 0);
    if (positions.length > 1) ambiguous = true;
    if (positions.length === 1) formulaRanges.push({ origin, start: positions[0], end: positions[0] + points(origin.canonicalText).length });
  }
  formulaRanges.sort((a, b) => a.start - b.start);
  if (formulaRanges.some((range, index) => index > 0 && range.start < formulaRanges[index - 1].end)) ambiguous = true;

  const textMappings: TextRangeMapping[] = [];
  let spanStart = 0;
  const spans = [...formulaRanges.map(range => [range.start, range.end] as [number, number]), [rawPoints.length, rawPoints.length] as [number, number]];
  for (const [formulaStart, formulaEnd] of spans) {
    const span = rawPoints.slice(spanStart, formulaStart).join("");
    if (span.trim()) {
      const matches = textOrigins.flatMap(origin => normalizedMatches(origin.canonicalText, span).map(([start, end]) => ({ origin, start, end })));
      if (matches.length !== 1) ambiguous = true;
      else {
        const match = matches[0];
        textMappings.push({ origin: match.origin, range: [match.origin.sourceStart + match.start, match.origin.sourceStart + match.end, match.origin.sourceTotal] });
      }
    }
    if (formulaStart < rawPoints.length) spanStart = formulaEnd;
  }

  // If no formula divided the line, the full numbered line (including its marker)
  // must map uniquely to one immutable OCR text anchor.
  if (!formulaRanges.length && rawLine.trim()) {
    const matches = textOrigins.flatMap(origin => normalizedMatches(origin.canonicalText, rawLine).map(([start, end]) => ({ origin, start, end })));
    textMappings.length = 0;
    if (matches.length === 1) {
      const match = matches[0];
      textMappings.push({ origin: match.origin, range: [match.origin.sourceStart + match.start, match.origin.sourceStart + match.end, match.origin.sourceTotal] });
      ambiguous = false;
    } else ambiguous = true;
  }

  const mapped: Record<string, unknown> = { ...blank };
  const merged: Record<string, unknown>[] = [];
  let primaryUsed = false;
  for (const mapping of textMappings) {
    if (!mapping.origin.segment && !primaryUsed) {
      Object.assign(mapped, mapping.origin.evidence);
      mapped.source_slice = mapping.range;
      primaryUsed = true;
    } else {
      merged.push({ ...mapping.origin.evidence, source_slice: mapping.range });
    }
  }
  for (const formula of formulaRanges) merged.push(formula.origin.segment!);
  if (merged.length) mapped.merged_source_segments = merged;
  return { item: mapped as ContentItem, valid: !ambiguous };
}

function retainedAmbiguousLine(item: ContentItem, mapped: ContentItem, rawLine: string): ContentItem {
  const source = mapped as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
  const segments = [...(source.merged_source_segments || [])];
  if (Array.isArray(source.source_slice)) {
    const evidence = evidenceOf(source as unknown as Record<string, unknown>);
    segments.unshift({ ...evidence, source_slice: source.source_slice });
  }
  const retained: ContentItem & { merged_source_segments?: Record<string, unknown>[] } = {
    type: "text", order: item.order, text: rawLine,
  };
  if (segments.length) retained.merged_source_segments = segments;
  return retained;
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
  const canonicalItems = canonicalNode?.ordered_content || node.ordered_content;
  const options = sourceOptions(canonicalItems);
  let current: SplitCandidate | null = null;
  const append = (item: ContentItem, owner: number | null, retainedItem: ContentItem = item) => {
    if (owner === null) parentItems.push(item);
    else children[owner].items.push(item);
    placements.push({ owner, item: retainedItem });
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
      const origins = sourceOrigins(item, node.formula_decisions, canonicalItems);
      // Explicit, previously verified slices are authoritative. For content
      // without a slice, resolve each candidate independently so repeated OCR
      // text cannot inherit an occurrence merely from its surrounding block.
      const hasExplicitSlice = "source_slice" in item && item.source_slice !== undefined;
      const located = origins && hasExplicitSlice ? locateOrigins(item, node.formula_decisions, canonicalItems) : null;
      lines.forEach(line => {
        if (line.match) {
          current = { label: labelFor(line.match), items: [], included: true, mappingStatus: "automatic", contentValid: true, selectedSourceIds: [] };
          children.push(current);
        }
        const text = line.match ? line.value.slice(line.match[0].length) : line.value;
        const owner = current ? children.length - 1 : null;
        const exactPiece = located ? textPiece(item, line.start, line.end, text, located) : null;
        const mapped = exactPiece && uniqueOriginMatch(line.value, origins)
          ? { item: exactPiece, valid: true }
          : mappedLinePiece(item, line.value, text, origins);
        if (!mapped.valid) {
          if (owner !== null) {
            const candidate = children[owner];
            candidate.mappingStatus = "manual_required";
            candidate.mappingMessage = "元資料との対応を一意に決められません。対応する読み取り項目を指定するか、対応情報なしで分割してください。";
            candidate.included = false;
          } else {
            notes.push("導入文の一部は元資料の範囲を特定できないため、分割後も大問に残します。問題用紙との設問単位の対応情報は引き継げません。");
          }
        }
        // Keep the original numbered line intact if an ambiguous candidate is
        // returned to the parent. The child preview may omit its marker, but
        // that marker is part of the teacher-visible source text and must not
        // disappear when the safe subset is applied.
        const retainedItem = mapped.valid
          ? { ...mapped.item, text: line.value } as ContentItem
          : retainedAmbiguousLine(item, mapped.item, line.value);
        // A marker on its own (for example a standalone "（1）" OCR item)
        // labels the child but is not child body content. Keeping the empty
        // post-marker text as an ordered item makes the backend reject the
        // otherwise valid split as an empty question-text field. Retain the
        // original marker only as the unselected-candidate fallback; the
        // canonical source draft remains unchanged either way.
        if (owner !== null && line.match && !text.trim()) {
          placements.push({ owner, item: retainedItem });
        } else {
          append(mapped.item, owner, retainedItem);
        }
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
  for (const child of children) {
    child.contentValid = child.items.some(item => item.type !== "text" ||
      ("text" in item && typeof item.text === "string" && !!item.text.trim()));
    if (!child.contentValid && child.mappingStatus === "automatic") child.mappingMessage = "小問本文が空です。本文を確認してから分割してください。";
  }
  const canApply = children.some(child => child.mappingStatus === "automatic" && child.contentValid);
  const ambiguousCount = children.filter(child => child.mappingStatus === "manual_required").length;
  const automaticCount = children.filter(child => child.mappingStatus === "automatic" && child.contentValid).length;
  if (ambiguousCount && automaticCount) notes.push(`${children.length}件中${automaticCount}件は自動で対応を確認できました。残り${ambiguousCount}件は対応方法を選択してください。`);
  if (ambiguousCount && !automaticCount) notes.push("自動で対応を確認できない候補があります。元資料の読み取り項目を指定するか、対応情報なしで分割してください。");
  return { parentItems, children, sourceOptions: options, notes: [...new Set(notes)], placements, canApply };
}
