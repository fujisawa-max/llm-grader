import type { ContentItem } from "@/types/reviews";

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
