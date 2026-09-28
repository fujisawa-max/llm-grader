import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkBreaks from "remark-breaks";
import rehypeKatex from "rehype-katex";

function safeUrl(url: string): string {
  if (/^(https?:|mailto:)/i.test(url)) return url;
  if (url.startsWith("//") || /^[a-z][\w+.-]*:/i.test(url)) return "";
  return url;
}

/** Markdown source remains plain text in storage; only this view renders it. */
export function MarkdownMathText({ source, className = "" }: { source: string | null | undefined; className?: string }) {
  return <div className={`markdown-math ${className}`.trim()}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath, remarkBreaks]}
      rehypePlugins={[[rehypeKatex, { trust: false, throwOnError: false }]]}
      urlTransform={safeUrl}
      skipHtml
    >{source || ""}</ReactMarkdown>
  </div>;
}

export function MarkdownMathPreview({ source }: { source: string }) {
  return <div className="math-preview" aria-label="問題文プレビュー">
    <strong className="math-preview-label">プレビュー</strong>
    <div className="math-preview-body">
      {source.trim() ? <MarkdownMathText source={source} /> : <span className="muted">入力するとここにプレビューが表示されます。</span>}
    </div>
  </div>;
}

export const markdownMathHelp = "MarkdownとLaTeXを使用できます。箇条書きは「- 項目」、番号付きは「1. 項目」、数式は $...$ または $$...$$ で入力します。";
