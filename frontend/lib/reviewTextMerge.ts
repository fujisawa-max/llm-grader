import type { ContentItem } from "@/types/reviews";
import { inlineFormulaSource } from "@/lib/formulaMerge";

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(stableJson).join(",") + "]";
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return "{" + Object.keys(object).sort().map(key => JSON.stringify(key) + ":" + stableJson(object[key])).join(",") + "}";
  }
  return JSON.stringify(value) ?? String(value);
}

function evidence(item: ContentItem): Record<string, unknown> {
  return Object.fromEntries(Object.entries(item).filter(([key]) =>
    !["type", "order", "text", "merged_source_segments"].includes(key)));
}

/** Merge an adjacent run of text items, preserving each source anchor as evidence. */
export function mergeContiguousText(items: ContentItem[], selectedIndices: number[], maxLength = 20000): ContentItem[] | null {
  const indices = [...new Set(selectedIndices)].sort((a, b) => a - b);
  if (indices.length < 2 || indices.some((index, at) =>
    !Number.isInteger(index) || index < 0 || index >= items.length ||
    (at > 0 && index !== indices[at - 1] + 1))) return null;
  const selected = indices.map(index => items[index]);
  if (selected.some(item => item.type !== "text" || typeof item.text !== "string")) return null;
  if (selected.reduce((total, item) => total + (item.type === "text" ? (item.text?.length ?? 0) : 0), 0) > maxLength) return null;

  const first = selected[0];
  if (first.type !== "text") return null;
  const sourceSegments = selected.flatMap((item, at) => [
    ...(at === 0 ? [] : (Object.keys(evidence(item)).length ? [evidence(item)] : [])),
    ...((item.type === "text" && Array.isArray(item.merged_source_segments)
      ? item.merged_source_segments : []) as Record<string, unknown>[]),
  ]);
  const deduplicatedSegments = [...new Map(sourceSegments.map(segment => [stableJson(segment), segment])).values()];
  const merged = { ...first, text: selected.map(item => item.type === "text" ? (item.text ?? "") : "").join("") } as ContentItem & {
    merged_source_segments?: Record<string, unknown>[];
  };
  if (deduplicatedSegments.length) merged.merged_source_segments = deduplicatedSegments;
  else delete merged.merged_source_segments;
  const firstIndex = indices[0], selectedSet = new Set(indices);
  return items.flatMap((item, index) => index === firstIndex ? [merged] : selectedSet.has(index) ? [] : [item])
    .map((item, order) => ({ ...item, order }));
}

/** Merge one contiguous Text/Formula run into its first Text item, retaining source anchors. */
export function mergeContiguousContent(
  items: ContentItem[], selectedIndices: number[], formulaSources: Record<string, string>, maxLength = 20000,
): ContentItem[] | null {
  const indices = [...new Set(selectedIndices)].sort((a, b) => a - b);
  if (indices.length < 2 || indices.some((index, at) =>
    !Number.isInteger(index) || index < 0 || index >= items.length ||
    (at > 0 && index !== indices[at - 1] + 1))) return null;
  const selected = indices.map(index => items[index]);
  if (selected[0]?.type !== "text" || selected.some(item => item.type !== "text" && item.type !== "formula_region")) return null;

  const pieces: string[] = [];
  let total = 0;
  for (const item of selected) {
    if (item.type === "text") {
      if (typeof item.text !== "string") return null;
      pieces.push(item.text);
      total += item.text.length;
    } else if (item.type === "formula_region" && typeof item.region_id === "string") {
      const raw = formulaSources[item.region_id];
      const latex = typeof raw === "string" ? inlineFormulaSource(raw) : "";
      if (!latex) return null;
      pieces.push(`$${latex}$`);
      total += latex.length + 2;
    }
    if (total > maxLength) return null;
  }

  const firstIndex = indices[0], first = selected[0];
  if (firstIndex === undefined || !first) return null;
  if (first.type !== "text") return null;
  const firstMergedSegments = "merged_source_segments" in first ? first.merged_source_segments : undefined;
  const sourceSegments: Record<string, unknown>[] = [
    ...(Array.isArray(firstMergedSegments) ? firstMergedSegments : []),
  ];
  selected.slice(1).forEach(item => {
    if (item.type === "formula_region") {
      sourceSegments.push(Object.fromEntries(Object.entries(item).filter(([key]) => key !== "order")));
      return;
    }
    if (Object.keys(evidence(item)).length) sourceSegments.push(evidence(item));
    if ("merged_source_segments" in item && Array.isArray(item.merged_source_segments)) sourceSegments.push(...item.merged_source_segments);
  });
  const deduplicated = [...new Map(sourceSegments.map(segment => [stableJson(segment), segment])).values()];
  const merged = { ...first, text: pieces.join("") } as ContentItem & { merged_source_segments?: Record<string, unknown>[] };
  if (deduplicated.length) merged.merged_source_segments = deduplicated;
  else delete merged.merged_source_segments;
  const selectedSet = new Set(indices);
  return items.flatMap((item, index) => index === firstIndex ? [merged] : selectedSet.has(index) ? [] : [item])
    .map((item, order) => ({ ...item, order }));
}
