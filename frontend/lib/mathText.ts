export type MathPart = { kind: "text" | "inline" | "display"; value: string };

const bareExpression = /^\s*\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|lim|sin|cos|tan|log|ln|alpha|beta|gamma|theta|pi|vec|begin)\b[\s\S]*$/;

function escaped(source: string, index: number): boolean {
  let slashes = 0;
  for (let i = index - 1; i >= 0 && source[i] === "\\"; i--) slashes++;
  return slashes % 2 === 1;
}

/** Parse math delimiters without modifying the source kept by the editor/API. */
export function parseMathText(source: string, allowBareMath = true): MathPart[] {
  if (allowBareMath && bareExpression.test(source) && !source.includes("$")) {
    return [{ kind: "display", value: source.trim() }];
  }
  const parts: MathPart[] = [];
  let plain = "";
  let i = 0;
  while (i < source.length) {
    if (source[i] !== "$" || escaped(source, i)) {
      // A backslash before a dollar sign is display escaping, not TeX source.
      if (source[i] === "$" && plain.endsWith("\\")) plain = plain.slice(0, -1);
      plain += source[i++];
      continue;
    }
    const width = source[i + 1] === "$" ? 2 : 1;
    let end = i + width;
    while (end < source.length) {
      if (source[end] === "$" && !escaped(source, end) && (width === 1 || source[end + 1] === "$")) break;
      end++;
    }
    if (end >= source.length || !source.slice(i + width, end).trim()) {
      plain += source.slice(i, i + width);
      i += width;
      continue;
    }
    if (plain) parts.push({ kind: "text", value: plain });
    plain = "";
    parts.push({ kind: width === 2 ? "display" : "inline", value: source.slice(i + width, end) });
    i = end + width;
  }
  if (plain || !parts.length) parts.push({ kind: "text", value: plain });
  return parts;
}
