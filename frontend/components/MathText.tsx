import katex from "katex";
import { parseMathText } from "@/lib/mathText";

export const mathInputHelp = "数式はLaTeXで入力できます。文章中は $...$、独立した式は $$...$$ で囲んでください。式だけの場合は \\frac{1}{3} のように入力できます。";

export function MathText({ source, className = "", allowBareMath = true }: { source: string | null | undefined; className?: string; allowBareMath?: boolean }) {
  return <span className={`math-text ${className}`.trim()}>{parseMathText(source || "", allowBareMath).map((part, index) => {
    if (part.kind === "text") return <span key={index}>{part.value}</span>;
    try {
      const html = katex.renderToString(part.value, { displayMode: part.kind === "display", throwOnError: true, trust: false, output: "htmlAndMathml" });
      return <span key={index} className={part.kind === "display" ? "math-display" : "math-inline"} dangerouslySetInnerHTML={{ __html: html }} />;
    } catch {
      return <span key={index} className="math-error" title="数式を表示できません">{part.kind === "display" ? `$$${part.value}$$` : `$${part.value}$`}</span>;
    }
  })}</span>;
}

export function MathPreview({ source }: { source: string }) {
  return <div className="math-preview" aria-label="数式プレビュー"><small className="muted">プレビュー</small><MathText source={source} /></div>;
}
