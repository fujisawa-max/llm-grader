"use client";
import { latexErrorMessage } from "@/lib/latexErrors";
import { useState } from "react";
import katex from "katex";
import { MarkdownMathText } from "./MarkdownMathText";
import { normalizeLatex, type LatexProposal, type TextContext } from "@/lib/api/textTools";
import { parseMathText } from "@/lib/mathText";

export function LatexNormalizationControl({text, contextType, contextLabel = "", disabled = false, onApply}: {
  text: string; contextType: TextContext; contextLabel?: string; disabled?: boolean;
  onApply: (text: string, proposal: LatexProposal) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<LatexProposal | null>(null);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  async function suggest() {
    if (text.length > 12000) {setError("LaTeX変換の本文は12,000文字以内にしてください。元の本文は保持されています。"); return;}
    setBusy(true); setProposal(null); setError(""); setConfirmed(false);
    try { setProposal(await normalizeLatex(text, contextType, contextLabel)); }
    catch (cause) { setError(latexErrorMessage(cause)); }
    finally { setBusy(false); }
  }
  let mathError = !!proposal && (proposal.normalized_text.replace(/\\\$/g, "").match(/\$/g)?.length || 0) % 2 !== 0;
  if (proposal) {
    try { for (const part of parseMathText(proposal.normalized_text, false)) {
      if (part.kind !== "text") katex.renderToString(part.value, {throwOnError: true, trust: false});
    } } catch { mathError = true; }
  }
  const stale = proposal && proposal.original_text !== text;
  return <section className="latex-normalization" aria-label="LaTeX変換" aria-busy={busy}>
    <button type="button" className="button secondary" disabled={disabled || busy || !text.trim()} onClick={suggest}>LLMでLaTeX化</button>
    {busy && <p role="status">LaTeX変換案を作成しています… 必要に応じてLLMを起動します。初回は時間がかかる場合があります。</p>}
    {error && <p role="alert">{error}</p>}
    {proposal && <section aria-label="LLMによるLaTeX変換案">
      <h4>LLMによるLaTeX変換案</h4>
      <h5>元の文章</h5><pre style={{whiteSpace: "pre-wrap"}}>{proposal.original_text}</pre>
      <h5>変換案</h5><pre style={{whiteSpace: "pre-wrap"}}>{proposal.normalized_text}</pre>
      <MarkdownMathText source={proposal.normalized_text} />
      {proposal.status === "no_change" && <p role="status">LaTeX化できる数式表現は見つかりませんでした。</p>}
      {proposal.warnings.map((warning, i) => <p role="alert" key={i}>{warning}</p>)}
      {proposal.status === "ambiguous" && <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />数式構造に曖昧さがあります。変換案を確認しました。</label>}
      {mathError && <p role="alert">数式を表示できません。構文を確認してください。</p>}
      {stale && <p role="alert">本文が変更されています。変換案を作り直してください。</p>}
      <div className="actions"><button type="button" className="button" disabled={disabled || !!stale || mathError || proposal.status === "rejected" || proposal.status === "no_change" || (proposal.status === "ambiguous" && !confirmed)} onClick={() => {onApply(proposal.normalized_text, proposal); setProposal(null);}}>この変換を適用</button>
        <button type="button" className="button secondary" onClick={() => setProposal(null)}>キャンセル</button></div>
    </section>}
  </section>;
}
