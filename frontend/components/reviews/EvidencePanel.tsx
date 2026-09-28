"use client";
import { useEffect, useState } from "react";
import { reviews } from "@/lib/api/reviews";
import type { Decision, Json, RegionEvidence } from "@/types/reviews";
import { reviewDecisionLabel, reviewIssueLabel } from "@/lib/reviewLabels";
import { MathPreview } from "@/components/MathText";

export function EvidencePanel({ id, regionId, ownerLabel, decision, readonly, onDecision }: {
  id: string; regionId: string; ownerLabel: string; decision: Decision; readonly: boolean; onDecision: (d: Decision) => void;
}) {
  const [data, setData] = useState<RegionEvidence>();
  const [raw, setRaw] = useState<Json>();
  const [error, setError] = useState("");
  const [rawError, setRawError] = useState("");
  const [rawLoading, setRawLoading] = useState(false);
  const [cropError, setCropError] = useState(false);
  useEffect(() => {
    let active = true;
    setData(undefined); setRaw(undefined); setError(""); setRawError(""); setCropError(false);
    reviews.evidence(id, regionId).then(d => { if (active) setData(d); })
      .catch(() => { if (active) setError("読み取り内容を取得できませんでした。再試行してください。"); });
    return () => { active = false; };
  }, [id, regionId]);
  async function loadRaw() {
    setRawLoading(true); setRawError("");
    try { setRaw((await reviews.raw(id, regionId)).raw); }
    catch { setRawError("元データの取得に失敗しました。"); }
    finally { setRawLoading(false); }
  }
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p>読み取り内容を読み込み中…</p>;
  const { region, parsed_view: parsed, pin } = data;
  const formula = region.region_type === "formula";
  const flags = [...new Set([...region.review_flags, ...(parsed?.review_flags || []), ...(parsed?.parser_warnings || [])])];
  const candidate = parsed?.transcription_normalized || parsed?.output.recognized_expression;
  return <article className="panel review-evidence" data-testid="evidence-panel">
    <h3>{formula ? "数式" : "図"}の確認</h3>
    <p>割当: {ownerLabel} · {region.page_index + 1}ページ</p>
    {data.crop_source === "review_preview" && <p className="notice">元の問題用紙から切り出した範囲です。画像解析の候補はありません。</p>}
    {data.crop_available ? <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="review-crop" alt={`${formula ? "数式" : "図"}の原文範囲`} src={reviews.cropUrl(id, regionId)} onError={() => setCropError(true)} />
      {cropError && <p className="error">原文画像の取得に失敗しました。</p>}
    </> : <p className="notice">切り出し画像はありません。左の原PDFで確認してください。</p>}
    <div className="evidence-comparison">
      <section><h4>PDFから読み取った内容</h4>
        {formula ? <pre>{region.text_fragments?.map(t => t.native_text).join("\n") || "読み取り内容はありません"}</pre>
          : <p>画像資料 {region.image_evidence?.length || 0}件</p>}
        <details><summary>PDF解析の技術情報</summary><pre>{JSON.stringify({ routing: region.routing_evidence, elements: data.native_elements }, null, 2)}</pre></details>
      </section>
      <section><h4>画像解析による候補</h4>
        {!parsed ? <p>画像解析による候補はありません</p> : <>
          {!formula && <p className="notice"><strong>{parsed.parse_status === "partial" ? "一部のみ読み取り済み・要確認" : parsed.parse_status === "complete" ? "読み取り済み" : "確認が必要"}</strong></p>}
          {formula ? <pre>{typeof candidate === "string" ? candidate : "候補なし"}</pre> :
            [["visible_text", "見える文字"], ["labels", "ラベル"], ["visual_elements", "図の要素"], ["spatial_relations", "位置関係"]].map(([key, label]) => <div key={key}><strong>{label}</strong><pre>{JSON.stringify(parsed.output[key] || [], null, 2)}</pre></div>)}
          <details><summary>画像解析の技術情報</summary><p>解析元: {parsed.source_field || "不明"}<br />解析器: {parsed.parser_name || "旧形式"} / {parsed.parser_version || "旧形式"}</p>{parsed.unstructured_observation && <pre>{parsed.unstructured_observation}</pre>}</details>
        </>}
      </section>
    </div>
    {flags.length > 0 && <div className="notice" aria-label="読み取りに関する確認事項">{flags.map(f => <p key={f}>{reviewIssueLabel(f)}</p>)}<details><summary>技術情報</summary>{flags.map(f => <div key={f}>{f}</div>)}</details></div>}
    {data.raw_available && <details key={regionId} onToggle={event => { if (event.currentTarget.open && raw === undefined && !rawLoading) void loadRaw(); }}>
      <summary>画像解析の元データ（技術情報）</summary>
      {rawLoading && <p>元データを読み込み中…</p>}{rawError && <p role="alert">{rawError}<button onClick={loadRaw}>再試行</button></p>}
      {raw !== undefined && <pre data-testid="raw-vision-output">{JSON.stringify(raw, null, 2)}</pre>}
    </details>}
    <fieldset disabled={readonly} className="review-fields"><legend>教師の判断</legend>
      <label>確認結果<select aria-label="確認結果" value={decision.decision} onChange={e => onDecision({ ...decision, decision: e.target.value })}>
        <option value="unreviewed">{reviewDecisionLabel("unreviewed")}</option>
        {formula ? <><option value="use_native" disabled={!region.text_fragments?.length}>{reviewDecisionLabel("use_native")}</option>
          <option value="use_vision" disabled={!pin?.has_candidate}>{reviewDecisionLabel("use_vision")}</option><option value="teacher_edit">{reviewDecisionLabel("teacher_edit")}</option></>
          : <><option value="accepted_as_evidence">{reviewDecisionLabel("accepted_as_evidence")}</option><option value="needs_correction">{reviewDecisionLabel("needs_correction")}</option></>}
      </select></label>
      {formula && decision.decision === "teacher_edit" && <label>教師が確認した数式<textarea aria-label="教師が確認した数式" maxLength={20000} value={decision.teacher_transcription || ""}
        onChange={e => onDecision({ ...decision, teacher_transcription: e.target.value })} /><small>入力内容を修正版に保存します。</small><MathPreview source={decision.teacher_transcription || ""} mathOnly /></label>}
      <label>教師メモ<textarea aria-label="教師メモ" maxLength={2000} value={decision.note || ""} onChange={e => onDecision({ ...decision, note: e.target.value })} /></label>
    </fieldset>
    <details><summary>技術情報</summary><pre>{JSON.stringify({ region_id: regionId, bbox: region.bbox, source_elements: region.source_element_ids, pin }, null, 2)}</pre></details>
  </article>;
}
