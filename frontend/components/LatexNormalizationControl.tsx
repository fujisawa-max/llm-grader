"use client";
import { latexErrorMessage, mathOcrReasonMessage } from "@/lib/latexErrors";
import { useState } from "react";
import katex from "katex";
import { MarkdownMathText } from "./MarkdownMathText";
import { mathOCR, normalizeLatex, type LatexProposal, type TextContext } from "@/lib/api/textTools";
import { parseMathText } from "@/lib/mathText";

export function LatexNormalizationControl({text, contextType, contextLabel = "", disabled = false, source, onApply}: {
  source?: {draftId: string; entryId: string; revision: number};
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
    try { setProposal(source ? await mathOCR(source, text) : await normalizeLatex(text, contextType, contextLabel)); }
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
    <button type="button" className="button secondary" disabled={disabled || busy || !text.trim()} onClick={suggest}>数式をLaTeX化</button>
    {busy && <p role="status"><span className="processing-spinner" aria-hidden="true" />数式を解析中… 必要に応じてLLMを起動します。初回は時間がかかる場合があります。</p>}
    {error && <p role="alert">{error}</p>}
    {proposal && <section aria-label="LLMによるLaTeX変換案">
      <h4>LaTeX変換案</h4>
      <h5>元の文章</h5><pre style={{whiteSpace: "pre-wrap"}}>{proposal.original_text}</pre>
      <h5>変換案</h5><pre style={{whiteSpace: "pre-wrap"}}>{proposal.normalized_text}</pre>
      <MarkdownMathText source={proposal.normalized_text} />
      {proposal.status === "no_change" && <p role="status">{source ? "LaTeX化できる数式領域は見つかりませんでした。" : "LaTeX化できる数式表現は見つかりませんでした。"}</p>}
      {proposal.grouping_summary && <details><summary>領域診断</summary><pre>{JSON.stringify(proposal.grouping_summary, null, 2)}</pre></details>}
      {proposal.reason_code && proposal.status === "rejected" && <p role="alert">{mathOcrReasonMessage(proposal.reason_code)}</p>}
      {proposal.math_regions?.map((region, i) => <details key={i} open={proposal.status === "rejected"}><summary>数式の原文: ページ {region.page_index + 1}</summary>
        {region.crop_image && <img src={region.crop_image} alt={`数式OCR対象 ${i + 1}`} style={{maxWidth: "100%"}} />}
        <p>領域判定: {region.grouping_method === "geometry" ? "位置情報" : "位置情報 + 画像確認"} / {region.crop_width} × {region.crop_height} px</p>
        {region.normalization_method && <p>数式整形: {region.ornith_used ? "決定論的 + Ornith書式補助" : "決定論的"}</p>}
        {region.rejection_code && <p role="alert">{mathOcrReasonMessage(region.rejection_code)}</p>}
        <details><summary>OCR診断</summary><p>bbox: {region.bbox?.join(", ")} / crop: {region.crop_bbox?.join(", ")}</p><p>画像確認: {region.ricoh_used ? "実行" : "不要"}</p>{region.ricoh_result !== undefined && <pre>{JSON.stringify(region.ricoh_result, null, 2)}</pre>}<p>画像確認終了: {region.ricoh_finish_reason || "未取得"} / tokens: {region.ricoh_completion_tokens ?? "未取得"}</p>{region.ricoh_rejection_code && <p>{mathOcrReasonMessage(region.ricoh_rejection_code)}</p>}<p>応答field: {region.source_field || "未取得"}</p><p>source segments: {region.segment_ids?.join(", ")}</p><pre>{region.raw_latex || "応答本文なし"}</pre><p>候補数: {region.candidate_count ?? "未取得"} / 重複: {region.duplicate_count ?? 0} / 選択候補: {region.selected_candidate_index ?? "なし"}</p><pre>{region.selected_candidate || region.normalized_candidate}</pre>
          <details><summary>最終検証と書式補助</summary><p>検証対象の原文</p><pre>{region.original_text}</pre><p>source識別子: {region.validation_source_identifiers?.join(", ")}</p><p>source数値: {region.validation_source_numbers?.join(", ")}</p><p>決定論的候補 ({region.deterministic_status})</p><pre>{region.deterministic_candidate}</pre>{region.deterministic_rejection_reason && <p>{mathOcrReasonMessage(region.deterministic_rejection_reason)}</p>}<p>Ornith書式補助: {region.ornith_used ? "実行" : "不要"}</p>{region.ornith_used && <><p>profile: {region.ornith_profile}</p><pre>{region.ornith_raw_output}</pre><pre>{region.ornith_normalized_output}</pre></>}<pre>{JSON.stringify(region.formatting_validation, null, 2)}</pre><p>最終候補</p><pre>{region.final_candidate}</pre><pre>{JSON.stringify(region.final_validation, null, 2)}</pre></details>
          {region.normalization_steps && <details><summary>整形内容</summary><pre>{JSON.stringify(region.normalization_steps, null, 2)}</pre></details>}
          {region.candidate_scores && <details><summary>候補ごとの検証</summary>{region.candidate_scores.map(candidate => <section key={candidate.index} aria-label={`OCR候補 ${candidate.index + 1}`}><p>候補 {candidate.index + 1}: {candidate.accepted ? "検証済み" : "不採用"} / score: {candidate.score}{candidate.duplicate_of !== undefined && ` / 候補 ${candidate.duplicate_of + 1} と重複`}</p><pre>{candidate.raw_candidate}</pre><pre>{candidate.normalized_candidate}</pre>{candidate.rejection_reason && <p>{mathOcrReasonMessage(candidate.rejection_reason)}</p>}</section>)}</details>}
        </details>
      </details>)}
      {proposal.warnings.map((warning, i) => <p role="alert" key={i}>{warning}</p>)}
      {proposal.status === "ambiguous" && <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />数式構造に曖昧さがあります。変換案を確認しました。</label>}
      {mathError && <p role="alert">数式を表示できません。構文を確認してください。</p>}
      {stale && <p role="alert">本文が変更されています。変換案を作り直してください。</p>}
      <div className="actions"><button type="button" className="button" disabled={disabled || !!stale || mathError || proposal.status === "rejected" || proposal.status === "no_change" || (proposal.status === "ambiguous" && !confirmed)} onClick={() => {onApply(proposal.normalized_text, {...proposal, math_regions: proposal.math_regions?.map(({crop_image: _image, raw_response: _raw, ricoh_raw_response: _ricoh, ornith_raw_response: _ornith, ...region}) => region)}); setProposal(null);}}>この変換を適用</button>
        <button type="button" className="button secondary" onClick={() => setProposal(null)}>キャンセル</button></div>
    </section>}
  </section>;
}
