import katex from "katex";
import { parseMathText } from "@/lib/mathText";

export const mathInputHelp = "数式はLaTeXで入力できます。文章中は $...$、独立した式は $$...$$ で囲んでください。式だけの場合は \\frac{1}{3} のように入力できます。";

export function MathText({ source, className = "", allowBareMath = true, mathOnly = false }: { source: string | null | undefined; className?: string; allowBareMath?: boolean; mathOnly?: boolean }) {
  const parts = mathOnly && source?.trim() && !source.trim().startsWith("$")
    ? [{ kind: "display" as const, value: source.trim() }] : parseMathText(source || "", allowBareMath);
  return <span className={`math-text ${className}`.trim()}>{parts.map((part, index) => {
    if (part.kind === "text") return <span key={index}>{part.value}</span>;
    try {
      const html = katex.renderToString(part.value, { displayMode: part.kind === "display", throwOnError: true, trust: false, output: "htmlAndMathml" });
      return <span key={index} className={part.kind === "display" ? "math-display" : "math-inline"} dangerouslySetInnerHTML={{ __html: html }} />;
    } catch {
      return <span key={index} className="math-error" title="数式を表示できません">{part.kind === "display" ? `$$${part.value}$$` : `$${part.value}$`}</span>;
    }
  })}</span>;
}

export function MathPreview({ source, mathOnly = false }: { source: string; mathOnly?: boolean }) {
  return <div className="math-preview" aria-label="数式プレビュー"><strong className="math-preview-label">プレビュー</strong><div className="math-preview-body">{source.trim() ? <MathText source={source} mathOnly={mathOnly} /> : <span className="muted">入力するとここにプレビューが表示されます。</span>}</div></div>;
}
