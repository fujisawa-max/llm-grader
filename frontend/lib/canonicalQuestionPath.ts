/** The same hierarchy labels are used by review issues and target selectors. */
export interface CanonicalQuestionNode { key: string; parentKey?: string | null; label: string; fallbackPath?: string; }
export function canonicalQuestionPath(key: string, nodes: CanonicalQuestionNode[], fallback = "選択中の設問"): string {
  const byKey = new Map(nodes.map(node => [node.key, node]));
  const labels: string[] = [], seen = new Set<string>();
  let current = byKey.get(key);
  while (current && !seen.has(current.key)) {
    seen.add(current.key);
    if (current.parentKey && !byKey.has(current.parentKey) && current.fallbackPath) return current.fallbackPath;
    labels.unshift(current.label);
    current = current.parentKey ? byKey.get(current.parentKey) : undefined;
  }
  return labels.join(" > ") || fallback;
}

/** Same top-parent scope as saved diagram sibling reuse; invalid chains fail closed. */
export function canonicalQuestionRoot(key: string, nodes: CanonicalQuestionNode[]): string | undefined {
  const byKey = new Map(nodes.map(node => [node.key, node]));
  const seen = new Set<string>();
  let current = byKey.get(key);
  while (current && !seen.has(current.key)) {
    seen.add(current.key);
    if (!current.parentKey) return current.key;
    current = byKey.get(current.parentKey);
  }
  return undefined;
}
