/** Return the body of a formula field for use inside one inline-math pair. */
export function inlineFormulaSource(source: string): string {
  const value = source.trim();
  if (value.startsWith("$$") && value.endsWith("$$") && value.length > 4) {
    return value.slice(2, -2).trim();
  }
  if (value.startsWith("$") && value.endsWith("$") && value.length > 2) {
    return value.slice(1, -1).trim();
  }
  return value;
}
